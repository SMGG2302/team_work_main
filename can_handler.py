import can
import threading
import time
import queue
import binascii
from logger_setup import get_logger # 保留导入

class CanQueueListener(can.Listener):
    def __init__(self, message_queue, logger):
        self.queue = message_queue
        self.logger = logger # 存储 logger 实例
        self.last_log_time = 0
        self.dropped_count = 0

    def on_message_received(self, msg):
        if msg.is_error_frame:
            self.logger.warning(f"接收到 CAN 错误帧: {msg}")
            return
        if msg.is_remote_frame:
            self.logger.debug(f"接收到 CAN 远程帧 (RTR), 已忽略: ID={hex(msg.arbitration_id)}")
            return

        self.logger.debug(f"CAN 收到消息: {msg}")
        try:
            self.queue.put_nowait(msg)
            if self.dropped_count > 0:
                 self.logger.warning(f"队列恢复，之前丢弃了 {self.dropped_count} 条 CAN 消息。")
                 self.dropped_count = 0
        except queue.Full:
            self.dropped_count += 1
            current_time = time.time()
            if current_time - self.last_log_time > 1.0:
                self.logger.warning(f"CAN 状态消息队列已满，正在丢弃消息... (已丢弃 {self.dropped_count} 条)")
                self.last_log_time = current_time
        except Exception as e:
             self.logger.error(f"放入 CAN 消息到队列时出错: {e}", exc_info=True)

    def on_error(self, exc):
        self.logger.error(f"CAN Listener 内部错误: {exc}", exc_info=True)

class CanHandler:
    def __init__(self, config_manager, status_message_queue, shutdown_event):
        # 在 __init__ 中获取 logger 实例
        self.logger = get_logger()
        self.config_manager = config_manager
        self.can_config = config_manager.get_can_config()
        self.status_message_queue = status_message_queue
        self.shutdown_event = shutdown_event
        self.simulation_mode = config_manager.is_simulation_mode()

        self.bus = None
        self.notifier = None
        self.listener_thread = None
        self.simulation_listener_threads = []
        self.simulation_timers = []

        self.can_filters = None
        if not self.simulation_mode:
            self.can_filters = self._setup_can_filters()

        # 获取重试配置
        retry_config = config_manager.get_retry_config()
        self.connect_retry_delay = retry_config.get('can_connect_retry_sec', 5)
        
        # 获取CAN协议超时配置
        self.can_timeouts = config_manager.get_can_protocol_timeouts()

    def _setup_can_filters(self):
        """根据 protocol.json 中的 can_to_mqtt 规则设置 CAN 过滤器"""
        filters = []
        can_to_mqtt_rules = self.config_manager.get_can_to_mqtt_rules()
        if not can_to_mqtt_rules:
            self.logger.warning("协议中未定义 CAN->MQTT 规则，将监听所有标准 CAN 消息。")
            return [{"can_id": 0, "can_mask": 0, "extended": False}]

        unique_ids = set(can_to_mqtt_rules.keys())
        for can_id_int in unique_ids:
            filters.append({"can_id": can_id_int, "can_mask": 0x7FF, "extended": False})

        self.logger.info(f"已设置 CAN 过滤器以监听 {len(filters)} 个特定 ID: {[hex(f['can_id']) for f in filters]}")
        return filters

    def _initialize_bus(self):
        """初始化 CAN 总线 (上机模式)"""
        interface = self.can_config.get('interface')
        bitrate = self.can_config.get('bitrate')

        if not interface or not bitrate:
            self.logger.critical("真实 CAN 配置缺少 'interface' 或 'bitrate'。")
            return False

        while not self.shutdown_event.is_set():
            try:
                self.logger.info(f"尝试初始化真实 CAN 总线: {interface} @ {bitrate} bps")
                self.bus = can.interface.Bus(
                    channel=interface,
                    bustype='socketcan',
                    bitrate=bitrate,
                    can_filters=self.can_filters
                )
                self.logger.info(f"真实 CAN 总线初始化成功。接口状态: {self.bus.state}")
                return True
            except can.CanError as e:
                self.logger.error(f"初始化 CAN 总线失败 (CanError): {e}")
            except OSError as e:
                 self.logger.error(f"初始化 CAN 时发生系统错误 (接口 '{interface}' 是否存在? 权限?): {e}")
            except ImportError as e:
                 self.logger.error(f"初始化 CAN 失败：缺少依赖库 ({e})。请确保安装了所选 bustype 的驱动或库。")
            except Exception as e:
                 self.logger.error(f"初始化 CAN 时发生未知错误: {e}", exc_info=True)

            self.logger.info(f"等待 {self.connect_retry_delay} 秒后重试 CAN 初始化...")
            if self.shutdown_event.wait(self.connect_retry_delay):
                 break

        self.logger.warning("未能初始化真实 CAN 总线。")
        return False

    def _real_can_listener_task(self):
        """使用 can.Notifier 进行真实 CAN 监听的任务"""
        if not self.bus:
            self.logger.error("真实 CAN 总线未初始化，无法启动监听器。")
            return

        self.logger.info("启动真实 CAN Notifier 监听器...")
        # 将 logger 实例传递给 Listener
        msg_listener = CanQueueListener(self.status_message_queue, self.logger)
        try:
            notifier_timeout = self.can_timeouts.get('notifier_timeout_sec', 0.1)
            self.notifier = can.Notifier(self.bus, [msg_listener], timeout=notifier_timeout)
            self.logger.info("真实 CAN Notifier 已启动。")
            while not self.shutdown_event.is_set():
                 self.shutdown_event.wait(1.0)

        except Exception as e:
             self.logger.error(f"真实 CAN Notifier 运行期间发生错误: {e}", exc_info=True)
        finally:
             if self.notifier:
                 try:
                     notifier_stop_timeout = self.can_timeouts.get('notifier_stop_timeout_sec', 1.0)
                     self.notifier.stop(timeout=notifier_stop_timeout)
                     self.logger.info("真实 CAN Notifier 已请求停止。")
                 except Exception as e:
                     self.logger.error(f"停止 CAN Notifier 时出错: {e}", exc_info=True)
             self.notifier = None

    def _simulation_can_message_sender(self, msg_config):
        """模拟发送单个配置的 CAN 消息的线程目标函数"""
        try:
            can_id = int(msg_config['id'], 16)
            can_data_hex = msg_config['data'].replace(" ", "")
            if len(can_data_hex) % 2 != 0:
                self.logger.error(f"模拟 CAN 消息数据 '{can_data_hex}' (ID: {hex(can_id)}) 长度无效，必须是偶数位。")
                return
            try:
                 can_data = binascii.unhexlify(can_data_hex)
            except binascii.Error:
                 self.logger.error(f"模拟 CAN 消息数据 '{can_data_hex}' (ID: {hex(can_id)}) 包含无效的十六进制字符。")
                 return

            interval_sec = msg_config['interval_ms'] / 1000.0
            sim_msg = can.Message(
                arbitration_id=can_id,
                data=can_data,
                is_extended_id=False,
                timestamp=time.time() # 模拟接收时设置时间戳
            )

            self.logger.info(f"启动模拟 CAN 消息发送器: ID={hex(can_id)}, Data={can_data.hex()}, Interval={interval_sec:.3f}s")

            while not self.shutdown_event.is_set():
                sim_msg.timestamp = time.time() # 更新时间戳
                try:
                    self.status_message_queue.put_nowait(sim_msg)
                    self.logger.debug(f"[SIMULATION] 模拟接收 CAN: {sim_msg}")
                except queue.Full:
                    self.logger.warning(f"[SIMULATION] 状态队列满，无法放入模拟 CAN 消息 (ID: {hex(can_id)})")
                except Exception as e:
                     self.logger.error(f"[SIMULATION] 放入模拟 CAN 消息时出错: {e}", exc_info=True)

                if self.shutdown_event.wait(interval_sec):
                    break

            self.logger.info(f"停止模拟 CAN 消息发送器: ID={hex(can_id)}")

        except Exception as e:
            self.logger.error(f"模拟 CAN 消息发送线程 (ID: {msg_config.get('id', 'N/A')}) 异常退出: {e}", exc_info=True)

    def _simulation_listener_task(self):
        """启动所有模拟 CAN 消息的发送线程"""
        sim_messages_config = self.can_config.get('simulation_receive_messages', [])
        if not sim_messages_config:
            self.logger.warning("[SIMULATION] 配置中未找到 'simulation_receive_messages'，将不模拟接收 CAN 消息。")
            while not self.shutdown_event.is_set():
                 self.shutdown_event.wait(1.0)
            return

        self.simulation_listener_threads = []
        for msg_config in sim_messages_config:
            thread = threading.Thread(
                target=self._simulation_can_message_sender,
                args=(msg_config,),
                name=f"SimCAN-{msg_config.get('id','?')}",
                daemon=True
            )
            self.simulation_listener_threads.append(thread)
            thread.start()

        self.logger.info(f"[SIMULATION] 已启动 {len(self.simulation_listener_threads)} 个模拟 CAN 消息发送器。")
        while not self.shutdown_event.is_set():
            all_alive = all(t.is_alive() for t in self.simulation_listener_threads)
            if not all_alive:
                self.logger.warning("[SIMULATION] 一个或多个模拟 CAN 发送线程已意外停止。")
                # break # 选择退出主监听循环

            sim_stop_wait = self.can_timeouts.get('simulation_stop_wait_sec', 2.0)
            self.shutdown_event.wait(sim_stop_wait)

        self.logger.info("[SIMULATION] 模拟 CAN 监听任务正在停止所有子线程...")
        sim_join_timeout = self.can_timeouts.get('simulation_join_timeout_sec', 1.0)
        for t in self.simulation_listener_threads:
            t.join(timeout=sim_join_timeout)

        self.logger.info("[SIMULATION] 模拟 CAN 监听任务已结束。")

    def start_listening(self):
        """启动 CAN 监听 (根据模式选择真实或模拟)"""
        if self.listener_thread and self.listener_thread.is_alive():
             self.logger.warning("CAN 监听线程已在运行。")
             return True

        if self.simulation_mode:
            self.logger.info("处于仿真模式，启动模拟 CAN 监听器...")
            self.listener_thread = threading.Thread(target=self._simulation_listener_task, name="SimCANListenerMgr")
            self.listener_thread.daemon = True
            self.listener_thread.start()
            self.logger.info("模拟 CAN 监听任务已启动。")
            return True
        else:
            self.logger.info("处于上机模式，启动真实 CAN 监听器...")
            if not self._initialize_bus():
                self.logger.critical("真实 CAN 总线初始化失败，无法启动监听。")
                self.shutdown_event.set()
                return False

            self.listener_thread = threading.Thread(target=self._real_can_listener_task, name="RealCANListenerThread")
            self.listener_thread.daemon = True
            self.listener_thread.start()
            self.logger.info("真实 CAN 监听线程已启动。")
            return True

    def stop(self):
        """停止 CAN 监听并关闭总线"""
        self.logger.info("正在停止 CAN 处理器...")
        self.shutdown_event.set()

        if self.listener_thread and self.listener_thread.is_alive():
            self.logger.info(f"等待 CAN 监听主线程 ({self.listener_thread.name}) 结束...")
            can_listener_timeout = self.can_timeouts.get('can_listener_join_timeout_sec', 3.0)
            self.listener_thread.join(timeout=can_listener_timeout)
            if self.listener_thread.is_alive():
                 self.logger.warning(f"CAN 监听主线程 ({self.listener_thread.name}) 未能在规定时间内停止。")
            else:
                 self.logger.info(f"CAN 监听主线程 ({self.listener_thread.name}) 已结束。")
        else:
            self.logger.info("CAN 监听主线程未运行或已结束。")

        if not self.simulation_mode and self.bus:
            self.logger.info("正在关闭真实 CAN 总线...")
            try:
                self.bus.shutdown()
                self.logger.info("真实 CAN 总线已关闭。")
            except Exception as e:
                self.logger.error(f"关闭真实 CAN 总线时出错: {e}", exc_info=True)
            finally:
                self.bus = None

    def send_message(self, can_msg):
        """发送 CAN 消息 (由 ControlProcessor 调用)"""
        if self.simulation_mode:
            # 注意：这里打印的 can_msg 是 ControlProcessor 构建的，其 timestamp 默认为 0
            self.logger.info(f"[SIMULATION] 发送 CAN 消息: {can_msg}")
            return True
        else:
            if not self.bus:
                self.logger.error("真实 CAN 总线未初始化或已关闭，无法发送消息。")
                return False
            try:
                send_timeout = self.can_timeouts.get('send_timeout_sec', 0.1)
                self.bus.send(can_msg, timeout=send_timeout)
                self.logger.debug(f"成功发送真实 CAN 消息: {can_msg}")
                return True
            except can.CanError as e:
                self.logger.error(f"发送真实 CAN 消息失败 (CanError): {e}")
                if hasattr(self.bus, 'state'):
                     self.logger.warning(f"当前 CAN 总线状态: {self.bus.state}")
                return False
            except Exception as e:
                self.logger.error(f"发送真实 CAN 消息时发生意外错误: {e}", exc_info=True)
                return False
