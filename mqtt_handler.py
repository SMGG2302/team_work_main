import paho.mqtt.client as mqtt
import json
import threading
import time
import random
import string
import queue
from typing import Optional
import paho.mqtt.client as mqtt
from logger_setup import get_logger # 保留导入

class MqttHandler:
    def __init__(self, config_manager, control_message_queue, shutdown_event):
        # 在 __init__ 中获取 logger 实例
        self.logger = get_logger()
        self.config_manager = config_manager
        self.control_message_queue = control_message_queue # 生产数据放入队列
        self.shutdown_event = shutdown_event
        self.simulation_mode = config_manager.is_simulation_mode()

        self.client: Optional[mqtt.Client] = None
        # 获取重试配置
        retry_config = config_manager.get_retry_config()
        self.connection_retry_delay = retry_config.get('mqtt_connect_retry_sec', 30)
        
        self.is_connected = False
        self.thread = None
        self.client_id = None # 在 connect_and_loop 中设置
        self.non_control_topics = config_manager.get_mqtt_config().get('non_control_topics', []) # 提前获取非控制主题，不放在on_message中防止耗时
        self.non_control_dict = {} # 非控制主题payload存储字典
        self.mqtt_to_mqtt_rules = config_manager.get_protocol_config().get('mqtt_to_mqtt', {}) # 获取MQTT到MQTT的映射规则

        self.safe_main_screen_heartbeat = 0 # 功能安全的心跳值
        self.safe_main_screen_heartbeat_window = [] # 存储心跳历史值的列表
        self.is_heartbeating = True # 心跳状态标志位
        self.heartbeat_thread = None # 心跳检测线程


    def get_is_connected(self):
            """返回当前 MQTT 连接状态"""
            return self.is_connected
    def _on_connect(self, client, userdata, flags, rc):
        """连接回调"""
        if rc == 0:
            self.is_connected = True
            current_mqtt_config = self.config_manager.get_mqtt_config() # 获取当前配置
            self.logger.info(f"成功连接到 MQTT Broker: {current_mqtt_config['broker']} (ClientID: {self.client_id})")

            control_base = current_mqtt_config.get('control_topic_base', '')
            # 订阅控制主题
            topics_to_subscribe = []
            for command_suffix, rule in self.config_manager.get_mqtt_to_can_rules().items():
                 if not rule.get('generated', False):
                     topic = control_base + command_suffix
                     topics_to_subscribe.append((topic, 0)) 

            # 订阅非控制主题
            ## 功能安全主题
            topic_safe = current_mqtt_config.get('safe_topic', '')
            if topic_safe: 
                 topics_to_subscribe.append((topic_safe, 0))
            else:
                 self.logger.warning("功能安全主题无法订阅，请检查配置文件")
            ## 批处理订阅其他非控制主题-各模块的报警信息
            for topic in self.non_control_topics:
                # print(f"断点-- 其他非控制主题: {topic}")
                topics_to_subscribe.append((topic, 0))

            if topics_to_subscribe:
                 # 类型检查：确保 client 不为 None
                 if self.client is not None:
                     result, _ = self.client.subscribe(topics_to_subscribe)
                     if result == mqtt.MQTT_ERR_SUCCESS:
                          subscribed_topics_str = ", ".join([t[0] for t in topics_to_subscribe])
                          self.logger.info(f"成功订阅控制主题: {subscribed_topics_str}")
                     else:
                          self.logger.error(f"订阅控制主题失败，错误码: {result}")
                 else:
                     self.logger.error("MQTT 客户端未初始化，无法订阅主题")
            else:
                 self.logger.warning("协议文件中没有定义可订阅的非生成控制主题。")
        else:
            self.is_connected = False
            self.logger.error(f"连接 MQTT Broker 失败，返回码: {rc}. 将在 {self.connection_retry_delay} 秒后重试...")

    def _on_disconnect(self, client, userdata, rc):
        """断开连接回调"""
        self.is_connected = False
        self.logger.warning(f"与 MQTT Broker 断开连接，返回码: {rc}.")
        if rc != 0 and not self.shutdown_event.is_set():
             self.logger.info("请检查网络，正在尝试重连... ")

    def _on_message(self, client, userdata, msg):
        """收到消息回调 (控制指令)"""
        topic = msg.topic
        try:
            if not msg.payload:
                self.logger.warning(f"收到空 payload 的 MQTT 消息 - 主题: {topic}，已忽略。")
                return
            payload = msg.payload.decode('utf-8')
            self.logger.debug(f"MQTT 收到消息 - 主题: {topic}, 内容: '{payload}'")
            # 功能安全主题赋值给属性，非控制主题放入字典，控制主题放入队列
            if topic == self.config_manager.get_mqtt_config().get('safe_topic', ''):
                self.safe_main_screen_heartbeat = payload
                self.logger.debug(f"功能安全主题心跳值已更新为: {self.safe_main_screen_heartbeat}")
            elif topic in self.non_control_topics:
                # 根据mqtt_to_mqtt规则处理非控制主题数据
                rule = self.mqtt_to_mqtt_rules.get(topic)
                if rule:
                    target_key = rule.get('target_key', topic)  # 使用target_key或原主题作为key
                    try:
                        parsed_payload = json.loads(payload)
                        self.non_control_dict[target_key] = parsed_payload
                        self.logger.debug(f"非控制主题数据已更新: {target_key} = {parsed_payload}")
                    except json.JSONDecodeError as e:
                        self.logger.warning(f"无法解析非控制主题JSON数据 - 主题: {topic}, 错误: {e}")
                        # 如果不是JSON，保存原始字符串
                        self.non_control_dict[target_key] = payload
                else:
                    # 没有找到规则，直接存储
                    self.non_control_dict[topic] = payload
                    self.logger.debug(f"非控制主题数据已存储（无规则）: {topic} = {payload}")
            else:
                self.control_message_queue.put_nowait((topic, payload))
        except UnicodeDecodeError:
             self.logger.warning(f"无法解码 MQTT payload (非 UTF-8?) - 主题: {topic}")
        except queue.Full:
            self.logger.warning(f"控制指令队列已满，丢弃消息: {topic}")
        except Exception as e:
             self.logger.error(f"处理 MQTT 消息放入队列时出错: {e}", exc_info=True)

    def _on_publish(self, client, userdata, mid):
         """消息发布成功回调 (可选)"""
         self.logger.debug(f"MQTT 消息已发布 (MID: {mid})")

    def connect_and_loop(self):
        """连接并启动 MQTT 网络循环"""
        while not self.shutdown_event.is_set():
            try:
                current_mqtt_config = self.config_manager.get_mqtt_config() # 获取最新配置
                broker = current_mqtt_config['broker']
                port = current_mqtt_config.get('port', 1883)
                keepalive = current_mqtt_config['keepalive']
                username = current_mqtt_config['username']
                password = current_mqtt_config['password']
                client_id_prefix = current_mqtt_config.get('client_id_prefix', 'excavator_ctrl_')

                random_suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
                self.client_id = client_id_prefix + random_suffix

                # 从配置获取clean_session设置
                mqtt_timeouts = self.config_manager.get_mqtt_protocol_timeouts()
                clean_session = mqtt_timeouts.get('clean_session', True)
                self.client = mqtt.Client(client_id=self.client_id, clean_session=clean_session)

                self.client.username_pw_set(username, password)
                self.client.on_connect = self._on_connect
                self.client.on_disconnect = self._on_disconnect
                self.client.on_message = self._on_message
                self.client.on_publish = self._on_publish
                
                # 从配置获取重连参数
                mqtt_timeouts = self.config_manager.get_mqtt_protocol_timeouts()
                min_delay = mqtt_timeouts.get('reconnect_min_delay_sec', 30)
                max_delay = mqtt_timeouts.get('reconnect_max_delay_sec', 120)
                self.client.reconnect_delay_set(min_delay=min_delay, max_delay=max_delay)
                

                self.logger.info(f"尝试连接到 MQTT Broker: {broker}:{port} (ClientID: {self.client_id})")
                self.client.connect(broker, port, keepalive)
                self.client.loop_forever() # 阻塞式后台 连接成功后，直到断联alive时间后执行结束？结束条件？看源码去
                self.logger.warning("阻塞式loop_forever运行结束。")

                if self.shutdown_event.is_set():
                    self.logger.info("MQTT 循环因程序关闭而停止。")
                    break
                else:
                    self.logger.warning("MQTT loop_forever 意外退出。")
                    self.is_connected = False

            except ConnectionRefusedError:
                 self.logger.error(f"MQTT 连接被拒绝，请检查 Broker 地址/端口和网络设置。")
                 self.is_connected = False
            except OSError as e:
                 self.logger.error(f"MQTT 连接时发生网络错误: {e}")
                 self.is_connected = False
            except Exception as e:
                self.logger.error(f"运行 MQTT 循环时发生未知错误: {e}", exc_info=True)
                self.is_connected = False

            if not self.shutdown_event.is_set():
                self.logger.info(f"等待 {self.connection_retry_delay} 秒后重试 MQTT 连接...")
                self.shutdown_event.wait(self.connection_retry_delay)

        self.logger.info("MQTT 连接和循环线程已结束。")


    def start(self):
        """启动 MQTT 处理线程"""
        if (self.thread and self.thread.is_alive()) and (self.heartbeat_thread and self.heartbeat_thread.is_alive()):
            self.logger.warning("MQTT 处理器线程、心跳检测线程都已在运行。")
            return

        self.thread = threading.Thread(target=self.connect_and_loop, name="MQTTHandlerThread")
        self.thread.daemon = True
        self.thread.start()
        self.logger.info("MQTT 处理器线程已启动。")

        # 启动心跳检测线程
        self.heartbeat_thread = threading.Thread(target=self.detect_heartbeat, name="HeartbeatThread")
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
        self.logger.info("心跳检测线程已启动。")


    def stop(self):
        """请求停止 MQTT 客户端"""
        self.logger.info("正在停止 MQTT 客户端...")
        if self.client and self.is_connected:
            rc = self.client.disconnect()
            self.logger.info(f"MQTT disconnect() 调用返回: {rc}")
        else:
             self.logger.info("MQTT 客户端未连接或未初始化，无需断开。")


    def publish_status(self, full_topic, payload_dict):
        """发布状态信息到 MQTT (由 StatusProcessor 调用)"""
        if not self.is_connected or not self.client:
            self.logger.warning("MQTT 未连接，无法发布状态消息。")
            return False

        # 直接使用传入的完整话题名，不再添加前缀
        # TODO 临时处理，后续调整通用性
        if full_topic == "prefix_temp":
            full_topic = "up/alarm/HJ133022221762"
        try:
            payload_json = json.dumps(payload_dict, allow_nan=False)
            result, mid = self.client.publish(full_topic, payload=payload_json, qos=0, retain=False)

            if result == mqtt.MQTT_ERR_SUCCESS:
                self.logger.debug(f"成功发布状态到 MQTT: Topic='{full_topic}', Payload={payload_json}")
                return True
            else:
                self.logger.warning(f"发布状态到 MQTT 主题 '{full_topic}' 失败，错误码: {result} ({mqtt.error_string(result)})")
                return False
        except TypeError as e:
             self.logger.error(f"无法将状态 payload 序列化为 JSON (可能含 NaN/Infinity?): {payload_dict} - {e}")
             return False
        except Exception as e:
            self.logger.error(f"发布 MQTT 状态时发生错误: {e}", exc_info=True)
            return False
        
    # 检测心跳的方法
    def detect_heartbeat(self):
        """
        接收到的心跳为0-255循环，通过滑动窗口的形式对最近接收到的n个心跳数据判断，
        如果n个数据都不变化，判断为n*100ms内心跳停止，标志位置1
        """
        window_size = self.config_manager.get_mqtt_config().get('safe_window_size', 4)
        # print(f"断点-- 检测心跳窗口大小: {window_size}")
        while not self.shutdown_event.is_set():
            # 仅对连接正常时的心跳进行检测。能否将未连接时的心跳也进行检测？冲突点-如果MQTT未连接，心跳窗会被心跳初始值填满，初始异常
            if self.is_connected and True: # 确保MQTT服务器已连接 且 上游心跳话题已开始发送 —— 断网作为单独的CAN帧发送条件使用
                self.safe_main_screen_heartbeat_window.append(self.safe_main_screen_heartbeat)

                # 保持窗口尺寸的上限为window_size
                if len(self.safe_main_screen_heartbeat_window) > window_size:
                    self.safe_main_screen_heartbeat_window.pop(0) # 指定索引移除最旧值，列表是默认移除最新值-end索引，队列才是先进先出

                # 如果窗口满，且所有值都相同，则认为心跳停止
                if len(self.safe_main_screen_heartbeat_window) == window_size and len(set(self.safe_main_screen_heartbeat_window)) == 1:
                    self.is_heartbeating = False # or self.simulation_mode # True False 如果仿真时必须查看发送的CAN帧 强制True，否则将触发功能安全保护不发送 
                    self.logger.debug("上游心跳异常 - 上游与域控之间通过MQTT通信，大屏崩溃，停止发送CAN帧[PS:仿真模式下不影响虚拟CAN帧发送]")
                else:
                    self.is_heartbeating = True
                    self.logger.debug(f"上游心跳正常 - 心跳标志位{self.is_heartbeating}，心跳值为{self.safe_main_screen_heartbeat}，心跳窗口为{self.safe_main_screen_heartbeat_window}")
            else:
                self.is_heartbeating = False
                self.logger.debug("MQTT未连接 - 上游心跳必然无")
            can_config = self.config_manager.get_can_config()
            mqtt_timeouts = self.config_manager.get_mqtt_protocol_timeouts()
            heartbeat_interval = mqtt_timeouts.get('heartbeat_detection_interval_sec', 1.0)
            time.sleep(heartbeat_interval) # 每指定间隔检查一次心跳
    def get_non_control_data(self):
        """获取所有非控制主题的数据"""
        return self.non_control_dict.copy()  # 返回副本避免外部修改

    def clear_non_control_data(self):
        """清空非控制主题数据（可选）"""
        self.non_control_dict.clear()
        
        self.logger.info("心跳检测线程已结束。")
