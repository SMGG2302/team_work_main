import threading
import queue
import time
import can
from logger_setup import get_logger # 保留导入
from protocol_processor import ProtocolDataProcessor
import random

class ControlProcessor(threading.Thread):
    """
    处理 MQTT 控制指令(更新内部状态)并周期性地将状态发送到 CAN 总线。
    """
    def __init__(self, control_queue, translator, can_handler, config_manager, shutdown_event, mqtt_handler):
        super().__init__(name="ControlProcessorThread")
        # 在 __init__ 中获取 logger 实例
        self.logger = get_logger()
        self.control_queue = control_queue
        self.translator = translator
        self.can_handler = can_handler
        self.mqtt_handler = mqtt_handler  # 新增：接收 MqttHandler 实例
        self.shutdown_event = shutdown_event
        self.daemon = True
        self.latest_updates_ctrl_dict = {} # 新增：存储最新的控制指令

        can_config = config_manager.get_can_config()
        
        self.send_interval_sec = can_config.get('send_interval_ms', 100) / 1000.0
        if self.send_interval_sec <= 0:
            self.logger.warning("CAN 发送间隔配置无效或为0，将使用默认值 0.1 秒。")
            self.send_interval_sec = 0.1
        
        # 获取性能警告阈值
        monitoring_config = config_manager.get_monitoring_config()
        self.performance_threshold = monitoring_config.get('performance_warning_threshold_sec', 0.02)

        self.target_can_ids = self.translator.get_target_can_ids_for_sending()
        if not self.target_can_ids:
             self.logger.warning("在 protocol.json 的 mqtt_to_can 中未找到任何有效的 CAN ID 定义，将不发送控制帧。")

        # 注意: [hex(id) for id in self.target_can_ids] 会产生 ['0x...', '0x...'] 的列表，这是预期的
        self.logger.info(f"控制处理器初始化完成。CAN 发送周期: {self.send_interval_sec:.3f} 秒。目标 CAN ID: {[hex(id) for id in self.target_can_ids]}")


    def run(self):
        self.logger.info("控制指令处理器线程已启动。")
        last_send_time = time.time()

        while not self.shutdown_event.is_set():
            # *** 优化消息处理逻辑 ***
            # 快速消耗队列中所有当前可用的消息，只保留每个 topic 的最新值
            # self.latest_updates_ctrl_dict = {}
            messages_processed_count = 0
            start_time_traverse_queue = time.time()  # 在try块外初始化
            try:
                while True: # 不断尝试获取，直到队列为空
                    topic, payload_str = self.control_queue.get_nowait()
                    # 使用 topic 作为 key，直接覆盖旧值，只保留最新的 payload
                    self.latest_updates_ctrl_dict[topic] = payload_str
                    self.control_queue.task_done() # 标记已取出
                    messages_processed_count += 1                
            except queue.Empty:
                # 队列已空，正常情况
                elapsed_time_traverse_queue = time.time()-start_time_traverse_queue # 耗时计算 
                if messages_processed_count > 0:
                     self.logger.debug(f"本轮耗时 {elapsed_time_traverse_queue*1000} 毫秒，处理了 {messages_processed_count} 条 MQTT 控制消息，保留了 {len(self.latest_updates_ctrl_dict)} 条最新指令。")
                pass # 继续执行后续逻辑
            except Exception as e:
                 # 处理 get_nowait 可能出现的其他异常 (虽然不太可能)
                 self.logger.error(f"从控制队列快速获取消息时出错: {e}", exc_info=True)

            # 使用收集到的最新值更新 Translator 状态
            if self.latest_updates_ctrl_dict:
                self.logger.debug(f"开始应用本轮最新指令: {self.latest_updates_ctrl_dict.keys()}")
                for topic, payload_str in self.latest_updates_ctrl_dict.items():
                    try:
                        self.translator.update_signal_state_from_mqtt(topic, payload_str)
                    except Exception as e:
                         # 单个消息更新失败不应阻止其他消息更新或发送
                         self.logger.error(f"应用最新指令 (Topic: {topic}) 更新状态时出错: {e}", exc_info=True)
                self.logger.debug("本轮最新指令应用完成。")
            
            if not self.mqtt_handler.is_heartbeating:
                if self.latest_updates_ctrl_dict:
                    self.logger.warning("检测到上游心跳停止，清空历史控制指令并重置Translator状态")
                    self.latest_updates_ctrl_dict.clear()
                    self.translator.reset_state()  # 重置Translator状态为初始值


            # 2. 检查是否到达发送时间 (保持不变)
            current_time = time.time() # 当清空队列代码块在前，此时 current_time 为设定周期+清空队列时间2-3ms（以last_send_time为基准）
            # 确保即使处理消息耗时很长，也能在处理后立即检查是否需要发送
            if current_time - last_send_time >= self.send_interval_sec and self.mqtt_handler.get_is_connected() and self.mqtt_handler.is_heartbeating:
            # if current_time - last_send_time >= self.send_interval_sec :
                # 到达发送周期，为每个目标 CAN ID 构建并发送帧
                self.logger.debug(f"到达 CAN 发送时间点 (实际间隔{current_time - last_send_time:.3f}s —— 理论间隔 {self.send_interval_sec:.3f}s)")
                # 如果间隔比设定周期大于配置的阈值 打印warning级别日志
                if current_time - last_send_time > self.send_interval_sec + self.performance_threshold:
                    self.logger.warning(f"当前时间间隔 {current_time - last_send_time:.3f}s 超过了设定的发送间隔 {self.send_interval_sec:.3f}s，可能是由于处理延迟或系统负载。")
                send_success_count = 0
                send_fail_count = 0
                for can_id in self.target_can_ids:
                    can_data = self.translator.build_can_frame(can_id)
                    if can_data is not None and len(can_data) == 8:
                        # 创建 CAN 消息，可以考虑添加时间戳
                        can_msg = can.Message(
                            arbitration_id=can_id,
                            data=can_data,
                            is_extended_id=False
                            # timestamp=time.time() # 取消注释以添加发送时间戳
                        )
                        if self.can_handler.send_message(can_msg):
                             send_success_count += 1
                        else:
                             send_fail_count += 1
                    elif can_data is None:
                         self.logger.error(f"构建 CAN ID {hex(can_id)} 的数据失败，本次不发送。")
                         send_fail_count += 1
                    else:
                         self.logger.error(f"构建 CAN ID {hex(can_id)} 的数据长度无效 ({len(can_data)} bytes)，期望 8 bytes。本次不发送。")
                         send_fail_count += 1

                if send_fail_count > 0:
                    self.logger.warning(f"本轮 CAN 发送完成: 成功 {send_success_count} 帧, 失败 {send_fail_count} 帧。")
                else:
                    self.logger.debug(f"本轮 CAN 发送完成: 成功 {send_success_count} 帧。")

                last_send_time = current_time # 更新上次发送时间


            # 3. 休眠直到下一个可能的事件点 (保持不变，但休眠时间基于处理后的时间)
            # 稍微调整休眠逻辑，确保至少有短暂的休息，避免100% CPU
            # 计算下一次理想的发送时间点
            next_ideal_send_time = last_send_time + self.send_interval_sec # 没有考虑清空队列的时间(实际周期100±3ms)，似乎应该，清空队列代码块位于发送can帧代码块后
            # 计算距离下次发送还有多久，但至少休眠一小段时间（比如1ms）
            time_to_next_send = max(0.001, next_ideal_send_time - time.time())
            # 在 shutdown_event 上等待这么久
            if self.shutdown_event.wait(time_to_next_send):
                 break # 如果在休眠期间收到关闭信号，退出循环

        self.logger.info("控制指令处理器线程已停止。")


class StatusProcessor(threading.Thread):
    """处理 CAN 状态帧并发布到 MQTT (消费者)"""
    def __init__(self, status_queue, translator, mqtt_handler, shutdown_event, control_processor, config_manager):
        super().__init__(name="StatusProcessorThread")
        self.logger = get_logger()
        self.status_queue = status_queue
        self.translator = translator
        self.mqtt_handler = mqtt_handler
        self.control_processor = control_processor
        self.config_manager = config_manager
        self.shutdown_event = shutdown_event
        self.daemon = True
        
        # 获取模拟数据配置
        self.simulation_config = config_manager.get_protocol_config().get('simulation_config', {})
        
        # 数据收集器初始化
        self.data_collector = DataCollector(config_manager, control_processor)
        self.data_merger = DataMerger(config_manager)
        
        # 协议数据处理器初始化
        self.protocol_processor = ProtocolDataProcessor(config_manager)

    def run(self):
        self.logger.info("状态消息处理器线程已启动。")
        alarm_dict = {} # 预定义：存储报警信息
        
        while not self.shutdown_event.is_set():
            try:
                # 1. 从队列获取CAN消息
                timeout_config = self.config_manager.get_timeout_config()
                queue_timeout = timeout_config.get('status_queue_get_timeout_sec', 1.0)
                #can_msg = self.status_queue.get(timeout=queue_timeout)
                
                try:
                    can_msg = self.status_queue.get(timeout=queue_timeout) 
                    # 标记消息完成
                    #self.status_queue.task_done()
                    can_message_received = True
                    self.logger.debug(f"接收到CAN消息: {can_msg}")
                except queue.Empty:
                    # 队列为空时，使用None表示没有接收到CAN消息
                    can_msg = None
                    can_message_received = False
                    self.logger.info(f"本轮CAN队列为空，将使用默认值发送MQTT消息")

                # 2. 统一数据收集
                collected_data = self.data_collector.collect_all_data(
                    can_msg=can_msg,
                    mqtt_handler=self.mqtt_handler,
                    translator=self.translator
                )
                
                # 3. 数据合并
                merged_data = self.data_merger.merge_data(collected_data)
                
                # 4. 发布合并后的数据
                if merged_data:
                    # 获取非控制数据（用于对外RTK数据）
                    non_control_dict = self.mqtt_handler.get_non_control_data()
                    
                    # 4.1 对内协议 - 向大屏 APP 发送分类数据
                    internal_data = self._prepare_internal_data(merged_data)
                    # 使用配置中的完整话题模板
                    internal_topic = self.config_manager.get_internal_topic_template()
                    self.mqtt_handler.publish_status(internal_topic, internal_data)
                    self.logger.debug(f"已发布内部数据给大屏APP: {internal_topic}")
                    
                    # 4.2 对外协议 - 向矿方中控台发送RTK信息
                    external_data = self._prepare_external_rtk_data(non_control_dict)
                    if external_data:
                        # 使用配置中的完整话题模板
                        external_topic = self.config_manager.get_external_topic_template()
                        self.mqtt_handler.publish_status(external_topic, external_data)
                        self.logger.debug(f"已发布RTK数据给矿方中控台: {external_topic}")
                
                #self.status_queue.task_done()
                if can_message_received:
                    self.status_queue.task_done()

            #except queue.Empty:
                #self.logger.warning(f"本轮CAN队列为空{self.status_queue},可能影响后续MQTT发送话题,持续等待到CAN队列非空")
                #continue
            except Exception as e:
                self.logger.error(f"处理状态消息时发生错误: {e}", exc_info=True)
            
            # 休眠逗辑
            can_config = self.config_manager.get_can_config()
            listen_interval_sec = can_config.get('listen_timeout_ms', 1000) / 1000.0
            if self.shutdown_event.wait(listen_interval_sec):
                break
        
        self.logger.info("状态消息处理器线程已停止。")
    
    def _prepare_internal_data(self, merged_data):
        """准备对内数据 - 向大屏APP发送分类数据（完全配置驱动）"""
        class_mapping = self.config_manager.get_internal_class_mapping()
        internal_data = {}
        
        # 使用协议处理器构建各个类别的数据
        for class_name, class_config in class_mapping.items():
            source = class_config.get('source', '')
            
            # 从合并数据中获取源数据
            source_data = merged_data.get(source, {})
            
            # 使用协议处理器映射数据
            class_data = self.protocol_processor.map_class_data_by_protocol(source_data, class_config)
            internal_data[class_name] = class_data
            
        count_info = ', '.join([f'{k}({len(v)}个)' for k, v in internal_data.items()])
        self.logger.debug(f"准备内部数据 - {count_info}")
        return internal_data
    
    def _prepare_external_rtk_data(self, non_control_dict):
        """准备对外RTK数据 - 向矿方中控台发送RTK信息（完全配置驱动）"""
        # 获取对外协议状态字段映射配置
        external_fields = self.config_manager.get_external_status_fields()
        
        if not external_fields:
            self.logger.warning("未找到对外协议状态字段映射配置，使用默认数据")
            return self._get_default_external_data_from_config({})
        
        # 使用协议处理器映射数据
        external_data = self.protocol_processor.map_data_by_protocol(
            non_control_dict, external_fields
        )
        
        # 获取必需字段列表
        fields_config = external_fields.get('fields', {})
        required_fields = list(fields_config.keys())
        
        # 验证数据完整性
        is_valid, missing_fields = self.protocol_processor.validate_protocol_data(
            external_data, required_fields
        )
        
        if not is_valid:
            self.logger.warning(f"对外数据缺少字段: {missing_fields}，使用默认值填充")
            # 与默认数据合并
            default_data = self._get_default_external_data_from_config(fields_config)
            external_data = self.protocol_processor.merge_with_defaults(external_data, default_data)
            
        self.logger.debug(f"准备对外RTK数据: {external_data}")
        return external_data
    
    def _get_default_external_data_from_config(self, fields_config):
        """从配置中获取默认的对外数据"""
        default_data = {}
        for field_key, field_config in fields_config.items():
            default_value = field_config.get('default_value')
            if default_value is not None:
                default_data[field_key] = default_value
            else:
                # 根据类型推断默认值
                data_type = field_config.get('type', 'string')
                default_data[field_key] = self.protocol_processor._get_default_value_by_type(data_type)
        return default_data
    
    def _get_default_external_data(self):
        """获取默认的对外数据"""
        return {
            "status_11": 102.13154800381285,  # 经度
            "status_12": 27.904670302925,     # 纬度
            "status_13": 1541.74523257812,    # 高度
            "status_14": 2.531362536152344,   # 横滚角
            "status_15": 0.5235541609256810,  # 俯仰角
            "status_16": -153.45096251959513, # 偏航角
            "status_17": -153.45096251959513, # 偏航角
            "status_18": "1704720307.3"       # 时间戳
        }
    

class DataCollector:
    """数据收集器 - 负责从各个数据源收集数据"""
    
    def __init__(self, config_manager, control_processor):
        self.logger = get_logger()
        self.config_manager = config_manager
        self.control_processor = control_processor
        self.simulation_config = config_manager.get_protocol_config().get('simulation_config', {})
        # 获取默认值配置（保持向后兼容）
        self.default_values = config_manager.get_protocol_config().get('default_values', {})
        # 获取CAN信号定义
        self.can_to_mqtt_rules = config_manager.get_can_to_mqtt_rules()
        self.mqtt_to_mqtt_rules = config_manager.get_protocol_config().get('mqtt_to_mqtt', {})
        self.last_sent_data = {}
    
    def _get_can_default_values(self, last_sent_data=None):
        """从 CAN 信号定义中提取默认值，并优先使用上一次发送的数据"""
        default_values = {}

        # 使用上次发送的数据（如果提供）来填充默认值
        if last_sent_data:
            for signal_name, last_value in last_sent_data.items():
                # 如果上次发送的数据中有该信号的值，优先使用
                if last_value is not None:
                    default_values[signal_name] = last_value

        # 如果没有使用上次发送的数据或上次没有该值，继续从 can_to_mqtt 规则中提取默认值
        for can_id, rule in self.can_to_mqtt_rules.items():
            signals = rule.get('signals', {})
            for signal_name, signal_def in signals.items():
                # 如果 signal_name 不在 last_sent_data 中，且没有默认值，则提取配置中的默认值
                if signal_name not in default_values:
                    default_value = signal_def.get('default_value')
                    if default_value is not None:
                        default_values[signal_name] = default_value

        # 如果没有新的默认值定义，使用旧的配置（向后兼容）
        if not default_values and self.default_values.get('can_data'):
            default_values = self.default_values['can_data'].copy()

        return default_values

    
    def collect_can_data(self, translator, can_msg):
        """收集CAN数据，并填充默认值"""
        # 从信号定义中获取默认值
        can_data = self._get_can_default_values(self.last_sent_data)
        
        # 如果有CAN消息，则更新实际数据
        if can_msg:
            payload_dict = translator.translate_can_to_mqtt(can_msg)
            if payload_dict:
                self.last_sent_data = payload_dict.copy()  # 保存上次发送的CAN翻译数据
                can_data.update(payload_dict)  # 用实际数据覆盖默认值
                self.logger.debug(f"CAN数据收集完成: {len(payload_dict)} 个实际信号，{len(can_data)} 个总信号（含默认值）")
            else:
                self.logger.debug(f"CAN数据无法解析，使用默认值: {len(can_data)} 个信号")
        else:
            self.logger.debug(f"CAN数据为空，使用默认值: {len(can_data)} 个信号")
        
        return can_data
    
    def collect_mqtt_data(self, mqtt_handler):
        """收集MQTT非控制主题数据，并填充默认值"""
        # 从 MQTT 规则中获取默认值
        mqtt_data = self._get_mqtt_default_values()
        
        # 获取所有非控制主题数据
        non_control_data = mqtt_handler.get_non_control_data()
        if non_control_data:
            # 用实际数据更新默认值
            for key, value in non_control_data.items():
                if key in mqtt_data:
                    # 如果是字典类型，递归更新
                    if isinstance(mqtt_data[key], dict) and isinstance(value, dict):
                        mqtt_data[key].update(value)
                    else:
                        mqtt_data[key] = value
                else:
                    # 新的key直接添加
                    mqtt_data[key] = value
            
            self.logger.debug(f"MQTT数据收集完成: {len(non_control_data)} 个实际主题，{len(mqtt_data)} 个总主题（含默认值）")
        else:
            self.logger.debug(f"MQTT数据为空，使用默认值: {len(mqtt_data)} 个主题")
        
        return mqtt_data
    
    def _get_mqtt_default_values(self):
        """从 MQTT 规则中提取默认值"""
        default_values = {}
        
        # 从 mqtt_to_mqtt 规则中提取默认值
        for topic, rule in self.mqtt_to_mqtt_rules.items():
            target_key = rule.get('target_key', topic)
            default_value = rule.get('default_value')
            if default_value is not None:
                default_values[target_key] = default_value
        
        # 如果没有新的默认值定义，使用旧的配置（向后兼容）
        if not default_values and self.default_values.get('mqtt_data'):
            default_values = self.default_values['mqtt_data'].copy()
        
        return default_values
    
    def collect_simulation_data(self):
        """收集模拟数据，基于简化配置和子函数联动逻辑"""
        # 从简化配置中获取基础参数
        if not self.simulation_config.get('enable', True):
            return self._get_simulation_default_values()
        
        # 获取当前档位
        current_gear = self._get_current_gear()
        
        # 生成模拟数据
        simulation_data = {}
        
        # 1. 档位状态（直接从MQTT控制指令获取）
        simulation_data['status_31'] = self._generate_gear_status(current_gear)
        
        # 2. 能耗数据（与档位联动）
        simulation_data['status_36'] = self._generate_energy_consumption(current_gear)
        
        # 3. 动态系统状态（基础值+随机波动）
        simulation_data.update(self._generate_dynamic_system_status())
        
        # 4. 其他系统状态
        simulation_data.update(self._generate_other_system_status())
        
        self.logger.debug(f"模拟数据收集完成: {len(simulation_data)} 个信号（含默认值），档位: {current_gear}")
        return simulation_data
    
    def _get_current_gear(self):
        """获取当前档位状态"""
        topic_base = self.config_manager.get_mqtt_config().get('control_topic_base', "")
        topic_gear = topic_base + "power17"
        try:
            gear = int(self.control_processor.latest_updates_ctrl_dict.get(topic_gear, "0"))
            # 限制档位范围在0-10之间
            if gear < 0 or gear > 10:
                gear = 0  # 默认档位
            return gear
        except (ValueError, TypeError):
            return 0  # 默认档位
    
    def _generate_gear_status(self, current_gear):
        """生成档位状态数据（优先级：下发数据>=1 > 配置默认值 > 0）"""
        # 优先级检查：如果从下发数据中获取到>=1的档位，优先使用
        if current_gear >= 1:
            return current_gear
        
        # 否则使用配置文件中的默认值
        default_values = self.simulation_config.get('default_values', {})
        config_default = default_values.get('status_31')
        
        if config_default is not None:
            return config_default
        
        # 配置文件没有默认值就使用0
        return 0
    
    def _generate_energy_consumption(self, current_gear):
        """生成能耗数据（与档位联动）"""
        # 从配置获取各档位对应的基础能耗值
        gear_energy_base = self.simulation_config.get('gear_energy_consumption', 
                                                     [8, 11.5, 16, 20, 23, 28, 30, 32, 34, 36, 38])
        
        # 根据档位选择基础能耗值
        if 0 <= current_gear < len(gear_energy_base):
            base_energy = gear_energy_base[current_gear]
        else:
            # 档位超出范围，使用默认值
            base_energy = self.simulation_config.get('default_values', {}).get('status_36', 32.0)
        
        # 添加随机波动
        random_range = self.simulation_config.get('random_range', [0.1, 1.5])
        precision = self.simulation_config.get('precision', 3)
        random_float = round(random.uniform(*random_range), precision)
        
        return base_energy + random_float
    
    def _generate_dynamic_system_status(self):
        """生成动态系统状态数据（基础值+随机波动）"""
        dynamic_data = {}
        default_values = self.simulation_config.get('default_values', {})  # 使用default_values而不base_values
        random_range = self.simulation_config.get('random_range', [0.1, 1.5])
        precision = self.simulation_config.get('precision', 3)
        
        # 为需要动态变化的状态生成数据
        dynamic_fields = ['status_32', 'status_33', 'status_34', 'status_35']
        
        for field in dynamic_fields:
            base_value = default_values.get(field, 0)  # 从 default_values 获取基础值
            random_float = round(random.uniform(*random_range), precision)
            dynamic_data[field] = base_value + random_float
        
        return dynamic_data
    
    def _generate_other_system_status(self):
        """生成其他系统状态数据"""
        # 目前没有其他需要生成的系统状态数据
        return {}
    
    def _get_simulation_default_values(self):
        """从简化配置中获取默认值"""
        default_values = self.simulation_config.get('default_values', {})
        
        # 如果没有新的默认值定义，使用旧的配置（向后兼容）
        if not default_values and self.default_values.get('simulation_data'):
            default_values = self.default_values['simulation_data'].copy()
        
        return default_values.copy()
    
    def collect_all_data(self, can_msg=None, mqtt_handler=None, translator=None):
        """收集所有数据源的数据"""
        collected_data = {
            'can_data': {},
            'mqtt_data': {},
            'simulation_data': {}
        }
        
        # 收集CAN数据
        if can_msg and translator:
            collected_data['can_data'] = self.collect_can_data(translator, can_msg)
        
        # 收集MQTT数据
        if mqtt_handler:
            collected_data['mqtt_data'] = self.collect_mqtt_data(mqtt_handler)
        
        # 收集模拟数据
        collected_data['simulation_data'] = self.collect_simulation_data()
        
        return collected_data


class DataMerger:
    """数据合并器 - 负责将各数据源的数据合并为两层嵌套结构，确保默认值的应用"""
    
    def __init__(self, config_manager=None):
        self.logger = get_logger()
        self.config_manager = config_manager
        # 获取默认值配置（保持向后兼容）
        if config_manager:
            self.default_values = config_manager.get_protocol_config().get('default_values', {})
        else:
            self.default_values = {}
    
    def merge_data(self, collected_data):
        """
        将收集的数据合并为两层嵌套字典结构，确保默认值的应用
        
        输入结构:
        {
            'can_data': {key: value, ...},
            'mqtt_data': {key: value, ...},
            'simulation_data': {key: value, ...}
        }
        
        输出结构:
        {
            'can_data': {...},
            'mqtt_data': {...},
            'simulation_data': {...}
        }
        """
        merged_data = {}
        
        # 定义数据源类型
        data_source_types = ['can_data', 'mqtt_data', 'simulation_data']
        
        # 为每个数据源类型确保默认值
        for source_type in data_source_types:
            # 从默认值开始
            default_for_type = self.default_values.get(source_type, {})
            
            # 获取实际数据
            actual_data = collected_data.get(source_type, {})
            
            if default_for_type or actual_data:
                # 合并默认值和实际数据
                merged_source_data = default_for_type.copy() if default_for_type else {}
                if actual_data:
                    merged_source_data.update(actual_data)
                
                # 只添加非空数据源
                if merged_source_data:
                    merged_data[source_type] = merged_source_data
        
        # 记录合并结果
        total_sources = len(merged_data)
        total_signals = sum(len(data) if isinstance(data, dict) else 1 for data in merged_data.values())
        
        # 计算默认值和实际值的数量
        default_count = sum(len(self.default_values.get(t, {})) for t in data_source_types)
        actual_count = sum(len(collected_data.get(t, {})) for t in data_source_types)
        
        self.logger.debug(f"数据合并完成: {total_sources} 个数据源, 共 {total_signals} 个信号 (默认:{default_count}, 实际:{actual_count})")
        
        return merged_data
