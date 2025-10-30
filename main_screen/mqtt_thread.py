# coding = utf-8
import re
import time
import threading

import orjson
from PySide6.QtCore import Signal, QThread, Slot, QObject
from loguru import logger
from paho.mqtt import client as mqtt

from app.core.config import cfg


class MQTTWorker(QObject):
    # MQTT服务器
    statusSignal = Signal(dict)     # 用于传递车辆状态信息
    errorSignal = Signal(int, int)      # 用于传递车辆异常信息
    mqtt_error_Signal = Signal()    # 用于传递mqtt服务器异常信息


    def __init__(self, excavator_id):
        super().__init__()
        # 创建了一个 Queue 对象，该对象可用于多线程编程中线程间通信和数据共享
        # self.excavator_type = 1
        self.rtk_warn_flag = 0
        self.forced_reset_end_time = 0.0
        self.last_clear_time = 0.0  # 记录上次行人消失的时间
        self.reset_time = 20.0
        self.allow_alarm = True  # 是否允许报警
        self.local_model = False
        self.control_topic = dict()
        self.old_control_data = dict()
        logger.success("创建MQTT连接")
        self.excavatorId = excavator_id
        self.heartbeat_counter = 0
        self.running = True
        self.heartbeat_topic = f"{self.excavatorId}/main_screen/heartbeat"
        self.mqttClient = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, reconnect_on_failure=False)
        self.mqttClient.on_connect = self.on_connect  # 返回连接状态的回调函数
        self.mqttClient.on_message = self.on_message  # 返回订阅消息回调函数
        self.mqttClient.on_publish = self.on_publish
        self.mqttClient.on_subscribe = self.on_subscribe
        self.mqttClient.on_unsubscribe = self.on_unsubscribe
        # self.mqttClient.on_log = self.on_log
        self.mqttClient.username_pw_set(cfg.MQTTServerUser, cfg.MQTTServerPassword)  # MQTT服务器账号密码
                                        # 解释解释：cfg就是个对象，通过对象.属性的格式来拿值，等价于字典[键]的格式拿值
                                        # 解释：拿到值之后，就续上原来熟悉的编程思维了
        if cfg.machineType == "chi":
            self.control_key = [
                "emergency_stop","voltage_380V","bucketBoom_up","bucketBoom_down","swingRun_left","swingRun_right","safetyLoop_up","obstacle",
                "swing_couple","up_interlock","run_interlock","bucketBoom_up_interlock","bucket_interlock","upperSwing_interlock","run_forward","run_backward",
                "swing_left","swing_right","monitor_control_switch","central_control","launch_warning","cab_up","cab_down","belt_conveyor",
                "run_emergencyState",
                "swing_velocity","waveTest",
            ]
                                # 解释：key-话题名（部分，还有前缀ID/phy）在这个地方。重要的是话题名和话题内容对应上，不要错位！
                                # 解释：通过control_key生成cntrol_topic,再匹配control_topic和controller_data
                                # 解释解释解释：controller_data是槽函数的输入，是发送信号时以参数的形式传递过来的controller_data_dict
            # 解释-业务：做不同机型的适配，根据配置文件中机型名字，切换control_key的赋值
            # 解释：通过cfg对象拿值，用于判断。cfg.MQTTServerUser类似的格式
        elif cfg.machineType == "xi":
            self.control_key = [
                "stop", "left_button", "none", "ventilation_excitation", "rise_lock", "host_stop", "host_start", "dc_split_close",
                "dc_split_open", "right_button", "mode", "pressurize_coupling", "air_compressor", "swing_run_swing",
                "swing_run_run", "turn_left",
                "turn_right", "ventilation", "rare_oil", "dry_oil_1", 'dry_oil_2',
                "pressurize", 'run_swing', "rise", "bucket",
            ]
        elif cfg.machineType == "chi_12":
            self.control_key = [
                "emergency_stop", "loadBoom_up", "loadBoom_down", "swingRun_left", "swingRun_right", "voltage_380V", "obstacle", "loadBoom_run_forward",
                "loadBoom_run_backward", "loadBoom_funnel_left", "loadBoom_funnel_right", "monitor_control_switch", "launch_warning", "rope_3B", "hydraulic_pump_open", "hydraulic_pump_close",
                "loadConveyor_forward", "loadConveyor_backward",

                "swing_velocity", "waveTest",
            ]
        elif cfg.machineType == "chi_21":
            self.control_key = [
                'emergency_stop', 'dischargeConveyor_down', 'dischargeConveyor_up', 'belt_swing_left', 'belt_swing_right', 'obstacle', 'safetyLoop', 'voltage_380V',
                'conveyor', 'run_forward', 'run_backward', 'swing_left', 'swing_right', 'monitor_control_switch', 'launch_warning', 'conveyor_stop',
                'pending',

                'swing_velocity', 'waveTest',
            ]
        elif cfg.machineType == "chi_22":
            self.control_key = [
                'emergency_stop', 'receivingConveyor_down', 'receivingConveyor_up', 'dumperBaffle_swing_in',
                'dumperBaffle_swing_out', 'obstacle', 'launch_warning', 'middleConveyor_run_forward',

                'middleConveyor_run_backward', 'middleConveyor_swing_left', 'middleConveyor_swing_right', 'left_up_45degree',
                'left_down_45degree', 'right_up_45degree', 'right_down_45degree', 'monitor_control_switch',

                'dumperDirection_1', 'dumperDirection_2', 'dumper_stop', 'conveyor_stop',

                'swing_velocity', 'waveTest',
            ]
        elif cfg.machineType == "su":
            self.control_key = [
                'power6', 'power1', 'aux2', 'power16',
                'power4', 'power5',

                'action2', 'action1', 'action4', 'action3', 'action5', 'action6','power17',
            ]
        elif cfg.machineType == "JS01_AZ001" or cfg.machineType == "AZ001" or cfg.machineType == "AZ001_xiling":
            self.control_key = [
                'power2', 'power3', 'power6', 'aux2', 'power16', 'power4', 'power5', 'power1',
                'aux3', 'power7', 'power8', 'power9', 'power10', 'power11', 'power12', 'power13',
                'power14', 'power15', 'power18', 'power19', 'power20', 'power21',

                'action5', 'action6', 'action2', 'action1', 'action4', 'action3','power17',
                'action7'
            ]
        elif cfg.machineType == "CZ001":
            self.control_key = [
                'power2', 'aux3', 'aux6', 'aux2', 'aux7', 'power16', 'power6', 'power7' # 8个一组，空白的空置
                'power3', 'power4', 'power1', 'aux8', 'power5', 'power9', 'power10', 'power8',
                'power17', 'aux4', 'aux5', 'power15', 'aux9'

                'action9', 'action7', 'action11', 'action3', 'action5', 'action6', 'action2', 'action1', 'action4'
            ]

        else:
            logger.debug("机型指定无法匹配")

    def on_log(self, client, userdata, level, buf):
        logger.info(buf)

    def mqtt_connect(self):
        # 连接异常返回False
        try:
            if self.mqttClient.connect(cfg.MQTTServerIP, cfg.MQTTServerPort, 60) == 0:  # MQTT地址、端口、心跳间隔（单位为秒）
                self.mqttClient.loop_start()
                heartbeat_thread = threading.Thread(target=self.send_heartbeat, daemon=True)
                heartbeat_thread.start()
                return True
            else:
                return False
        except OSError as e:
            logger.error(f"网络异常，尝试操作一个无法连接的主机{e}")
            return False

    def send_heartbeat(self):
        """定时发送 0~255 循环的心跳包"""
        while self.running:
            payload = str(self.heartbeat_counter)
            self.publishMsg(self.heartbeat_topic, payload)
            # print(f"发送心跳包: {payload} 到 {self.heartbeat_topic}")
            self.heartbeat_counter = (self.heartbeat_counter + 1) % 256
            time.sleep(0.1)  # 100ms

    def on_message(self, client, userdata, message):
        # 接受消息处理
        if message.topic == f"{self.excavatorId}/resp":
            # logger.debug(f"控制命令应答数据：{message.payload}")
            # 按照协议文档此处返回为以","分割的topicId和result，topicId 为主题对应的编号。result: 1 成功，2 错误
            if message.payload.split(",")[1] == "2":
                logger.error(f"控制命令应答数据返回错误{message.payload}")
        # elif message.topic == f"{self.excavatorId}/ctrl/bucket arm":
        #     logger.info("receive mqtt")
        # elif message.topic == f"{self.excavatorId}/ctrl/right_button":
        #     state_dict = dict()
        #     # logger.info(f"Smart窗口切换信号1message{message.payload=}")
        #     try:
        #         state_dict["smartScreen_display"] = int(message.payload.decode('utf-8'))
        #     except KeyError:
        #         logger.info("没有Smart窗口切换信息")
        #     self.statusSignal.emit(state_dict)
            # logger.info(f"Smart窗口切换信号2{state_dict=}")
        elif message.topic == f"{self.excavatorId}/resp/up/status":
            pass
            # todo 目前协议文档还没定义清楚，现在是随便搞得
        # elif message.topic == f"up/exp/{self.excavatorId}":
        #     try:
        #         logger.debug(f"车辆状态{orjson.loads(message.payload)['exp']}")
        #         mqtt_data = orjson.loads(message.payload)['exp']
        #         if isinstance(mqtt_data, list) and set(mqtt_data).issubset({0, 1, 2}):
        #             self.errorSignal.emit(mqtt_data[:9])
        #             # self.errorSignal.emit(mqtt_data)
        #         else:
        #             logger.error(f"错误的mqtt消息，topic:{message.topic},message:{message.payload}")
        #     except KeyError as e:
        #         logger.error(f"错误的mqtt消息，topic:{message.topic},message:{message.payload}")

        elif message.topic == f"up/status/{self.excavatorId}":
            state_dict = dict()
            error_state = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
            mqtt_data = orjson.loads(message.payload)
            # logger.info(f"收到的plc__数据：{mqtt_data}")
            if cfg.machineType == "default":
                state_dict.update(self.getValueByKey('gear', 'gear', mqtt_data, 0, 9))
                state_dict.update(self.getValueByKey('oilMass', 'oilMass', mqtt_data, 0, 100, "%"))
                state_dict.update(self.getValueByKey('avgOilComsume', 'avgOilComsume', mqtt_data, 0, 100, "L/h"))
                state_dict.update(self.getValueByKey('waterTankTemp', 'waterTankTemp', mqtt_data, 0, unit="℃"))
                state_dict.update(self.getValueByKey('oilTemp', 'oilTemp', mqtt_data, 0, unit="℃"))
                state_dict.update(self.getValueByKey('vol', 'vol', mqtt_data, 0, unit="V"))
                # state_dict.update(self.getValueByKey('frontDip', 'frontDip', mqtt_data, 0, unit="°", unit2="'"))
                # state_dict.update(self.getValueByKey('afterDip', 'afterDip', mqtt_data, 0, unit="°", unit2="'"))
            elif cfg.machineType == "su" or cfg.machineType == "JS01_AZ001":
                state_dict.update(self.getValueByKey('status_1', 'state_value_7', mqtt_data, -400, 400, "°"))
                state_dict.update(self.getValueByKey('status_2', 'state_value_8', mqtt_data, -400, 400, "°"))
                state_dict.update(self.getValueByKey('status_11', 'state_value_1', mqtt_data, -400, 400, ""))
                state_dict.update(self.getValueByKey('status_12', 'state_value_2', mqtt_data, -400, 400, "%"))
                state_dict.update(self.getValueByKey('status_13', 'state_value_3', mqtt_data, -400, 400, "°"))
                state_dict.update(self.getValueByKey('status_14', 'state_value_4', mqtt_data, -400, 400, "°"))
                state_dict.update(self.getValueByKey('status_15', 'state_value_5', mqtt_data, -400, 400, "V"))
                state_dict.update(self.getValueByKey('status_16', 'state_value_6', mqtt_data, -400, 400, "L/h"))
            elif cfg.machineType == "AZ001":
                mqtt_data_class2 = mqtt_data['class2']
                mqtt_data_class3 = mqtt_data['class3']
                state_dict.update(self.getValueByKey('status_25', 'state_value_7', mqtt_data_class2, -10000, 10000, "°"))
                state_dict.update(self.getValueByKey('status_24', 'state_value_8', mqtt_data_class2, -10000, 10000, "°"))
                state_dict.update(self.getValueByKey('status_31', 'state_value_1', mqtt_data_class3, -10000, 10000, ""))
                state_dict.update(self.getValueByKey('status_32', 'state_value_2', mqtt_data_class3, -10000, 10000, "%"))
                state_dict.update(self.getValueByKey('status_33', 'state_value_3', mqtt_data_class3, -10000, 10000, "°"))
                state_dict.update(self.getValueByKey('status_34', 'state_value_4', mqtt_data_class3, -10000, 10000, "°"))
                state_dict.update(self.getValueByKey('status_35', 'state_value_5', mqtt_data_class3, -10000, 10000, "V"))
                state_dict.update(self.getValueByKey('status_36', 'state_value_6', mqtt_data_class3, -10000, 10000, "L/h"))
            elif cfg.machineType == "xi":
                state_dict.update(self.getValueByKey('info_144', 'voltage', mqtt_data, 0, 100000, "kV", 0.001))
                state_dict.update(self.getValueByKey('info_162', 'air_temp', mqtt_data, 0, 100000, times=0.1))
                state_dict.update(self.getBoolValueByKey('info_14', 'kv1', mqtt_data))
                state_dict.update(self.getBoolValueByKey('info_7', 'kv2', mqtt_data))
                state_dict.update(self.getBoolValueByKey('info_9', 'dc_gate', mqtt_data))
                state_dict.update(self.getBoolValueByKey('info_68', 'phase_seq_err', mqtt_data, "错误", "正确"))
                state_dict.update(self.getValueByKey('info_164', 'info_temp_1', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_165', 'info_temp_2', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_166', 'info_temp_3', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_167', 'info_temp_4', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_171', 'info_temp_5', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_168', 'info_temp_6', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_169', 'info_temp_7', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_170', 'info_temp_8', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_159', 'info_temp_9', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_160', 'info_temp_10', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_161', 'info_temp_11', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_163', 'info_temp_12', mqtt_data, -50, 1000, "℃", deffer=40))
                state_dict.update(self.getValueByKey('info_151', 'info_current_1', mqtt_data, 0, 10000, "A"))
                state_dict.update(self.getValueByKey('info_155', 'info_current_2', mqtt_data, 0, 10000, "A"))
                state_dict.update(self.getValueByKey('info_158', 'info_current_3', mqtt_data, 0, 10000, "A"))
                try:
                    current_time = time.time()
                    if current_time > self.forced_reset_end_time:
                        error_state[0] = mqtt_data['info_detectDict']['class_11']
                        error_state[2] = mqtt_data['info_detectDict']['class_12']
                        error_state[3] = mqtt_data['info_detectDict']['class_13']
                        error_state[9] = mqtt_data['info_detectDict']['class_14']
                        self.errorSignal.emit(error_state[0], 0)
                        self.errorSignal.emit(error_state[2], 2)
                        self.errorSignal.emit(error_state[3], 3)
                        self.errorSignal.emit(error_state[9], 9)
                except KeyError:
                    logger.info("没有报警状态信息")
            else:
                mqtt_data_class2 = mqtt_data['class2']
                mqtt_data_class3 = mqtt_data['class3']
                state_dict.update(self.getValueByKey('status_25', 'state_value_7', mqtt_data_class2, -10000, 10000, "°"))
                state_dict.update(self.getValueByKey('status_24', 'state_value_8', mqtt_data_class2, -10000, 10000, "°"))
                state_dict.update(self.getValueByKey('status_31', 'state_value_1', mqtt_data_class3, -10000, 10000, ""))
                state_dict.update(self.getValueByKey('status_32', 'state_value_2', mqtt_data_class3, -10000, 10000, "%"))
                state_dict.update(self.getValueByKey('status_33', 'state_value_3', mqtt_data_class3, -10000, 10000, "°"))
                state_dict.update(self.getValueByKey('status_34', 'state_value_4', mqtt_data_class3, -10000, 10000, "°"))
                state_dict.update(self.getValueByKey('status_35', 'state_value_5', mqtt_data_class3, -10000, 10000, "V"))
                state_dict.update(self.getValueByKey('status_36', 'state_value_6', mqtt_data_class3, -10000, 10000, "L/h"))

            # todo 其他运行状态信息待协议定义后实现
            self.statusSignal.emit(state_dict)

        elif message.topic == f"RTK/angles":
            # logger.info(f"接收到RTK消息")
            state_dict = dict()
            # 将消息负载解码为字符串
            msg_payload = message.payload.decode('utf-8')

            # 使用正则表达式从消息中提取 Roll 和 Pitch 值
            match_angle = re.search(r'Roll:\s*(-?\d+\.\d+),\s*Pitch:\s*(-?\d+\.\d+)', msg_payload)
            # logger.info(f"RTK.match={match_angle}")

            if match_angle:
                roll = round(float(match_angle.group(1)), 1)  # 提取 Roll
                pitch = round(float(match_angle.group(2)), 1)  # 提取 Pitch
                # 更新 state_dict 中的相应字段
                state_dict["frontDip"] = f"{pitch}°"
                state_dict["afterDip"] = f"{roll}°"
                # logger.info(f"RTK.pitch={pitch}")
                if abs(pitch) > 10.0 or abs(roll) > 10.0:
                    logger.info(f"RTK倾角信息警告")
                    self.errorSignal.emit(1, 8)
                    self.rtk_warn_flag = 1
                elif (abs(pitch) <= 10.0 or abs(roll) <= 10.0) and self.rtk_warn_flag == 1:
                    # logger.info(f"RTK倾角信息警告恢复")
                    self.errorSignal.emit(0, 8)
                    self.rtk_warn_flag = 0
            self.statusSignal.emit(state_dict)

        elif message.topic == f"perception/object_detection":
            current_time = time.time()
            # if current_time < self.forced_reset_end_time:
            #     self.errorSignal.emit(0, 7)
            #     return
            state_dict = dict()
            mqtt_data = orjson.loads(message.payload)
            try:
                if mqtt_data['peopleCount'] != 0:
                    # 检查是否在最近20秒内行人消失过
                    if self.last_clear_time is not None and (current_time - self.last_clear_time) < 20.0 and self.allow_alarm == False:
                        # 在20秒内，不触发报警
                        self.last_clear_time = current_time
                    else:
                        # 触发报警
                        self.errorSignal.emit(1, 7)
                        self.allow_alarm = True
                elif mqtt_data['peopleCount'] == 0:
                    self.errorSignal.emit(0, 7)
            except KeyError:
                logger.info("没有行人检测报警状态信息")
            try:
                if isinstance(mqtt_data["toothDetection"], list) & len(mqtt_data["toothDetection"]) == 5 & all(x in (0, 1) for x in mqtt_data["toothDetection"]):
                    state_dict["tooth_status"] = mqtt_data["toothDetection"]
                    self.statusSignal.emit(state_dict)
                else:
                    logger.error("斗齿状态信息格式异常")
            except KeyError:
                logger.info("没有斗齿状态信息")

        elif message.topic == f"{self.excavatorId}/ctrl/alram":
            current_time = time.time()
            self.forced_reset_end_time = current_time + self.reset_time  # 设置强制不报警结束时间
            # 记录当前时间作为行人消失时间（确保后续20秒内不触发报警）
            self.last_clear_time = current_time
            self.allow_alarm = False
            for i in range(10):
                self.errorSignal.emit(0, i)


    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error(f"连接失败: {reason_code}. ")
            self.mqtt_error_Signal.emit()
        else:
            logger.success("连接成功")
            topics = [
                f"{self.excavatorId}/resp",             # 订阅返回信息
                f"{self.excavatorId}/resp/up/status",   # 订阅状态信息
                f"up/status/{self.excavatorId}",
                f"up/exp/{self.excavatorId}",           # 订阅告警信息
                f"{self.excavatorId}/ctrl/alram",
                f"{self.excavatorId}/ctrl/bucket arm",    # 计算延迟
                f"{self.excavatorId}/ctrl/right_button",
                f"RTK/angles",
                f"perception/object_detection"
            ]
            for topic in topics:
                client.subscribe(topic)
                logger.info(f"尝试订阅{topic}:{client.subscribe(topic)}")

        self.control_topic.update({key:f"{self.excavatorId}/ctrl/{key}" for key in self.control_key})

        # self.control_topic.update(
        #     bucket_arm=f"{self.excavatorId}/phy/bucket arm",
        #     left_handler=f"{self.excavatorId}/phy/left_handler",
        #     boom=f"{self.excavatorId}/phy/boom",
        #     bucket=f"{self.excavatorId}/phy/bucket",
        #     left_pedal=f"{self.excavatorId}/phy/left_pedal",
        #     right_pedal=f"{self.excavatorId}/phy/right_pedal",
        #     energize=f"{self.excavatorId}/phy/energize",
        #     ignition=f"{self.excavatorId}/phy/ignition",
        #     lock=f"{self.excavatorId}/phy/lock",
        #     stop=f"{self.excavatorId}/phy/stop",
        #     horn=f"{self.excavatorId}/ctrl/horn",
        #     change_gear=f"{self.excavatorId}/ctrl/change_gear",
        # )

    def on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        # 由于我们仅订阅单个频道，reason_code_list 包含单个条目
        if reason_code_list[0].is_failure:
            logger.error(f"拒绝订阅: {reason_code_list[0]}")
        else:
            logger.success(f"授予以下 QoS: {reason_code_list[0].value}")

    def on_unsubscribe(self, client, userdata, mid, reason_code_list, properties):
        # 请注意，reason_code_list 仅存在于 MQTTv5 中。
        # 在 MQTTv3 中它将始终为空
        if len(reason_code_list) == 0 or not reason_code_list[0].is_failure:
            logger.success("取消订阅成功（如果在 MQTTv3 中收到 SUBACK 则成功）")
                         # 解释code：首次测试，日志中出现此信息
        else:
            logger.error(f"代理回复失败: {reason_code_list[0]}")
        self.running = False
        client.disconnect()

    def on_publish(self, client, userdata, mid, reason_code, properties):
        # Reason_code 和属性仅出现在 MQTTv5 中。在 MQTTv3 中始终未设置
        try:
            userdata.remove(mid)
        except KeyError:
            logger.error(f"On publish failed, KeyError:{reason_code}")

    def connectServer(self):
        try:
            self.mqttClient.connect(cfg.MQTTServerIP, cfg.MQTTServerPort, 60)
            # MQTT地址、端口、心跳间隔（单位为秒）
            self.mqttClient.loop_start()
        except OSError:
            logger.error("网络异常，尝试操作一个无法连接的主机")
            raise OSError("[WinError 10065] 套接字操作尝试一个无法连接的主机。")

    def publishMsg(self, topic: str, payload, qos=2):
        # logger.error(f"补充：进入发布函数publishMsg")
        unacked_publish = set()
        self.mqttClient.user_data_set(unacked_publish)
        # 发布消息
        msg_info = self.mqttClient.publish(topic, payload, qos)
        unacked_publish.add(msg_info.mid)
        # 等待消息发布
        logger.debug(f"发布消息-topic:{topic},payload:{payload},qos:{qos}")
        try:
            msg_info.wait_for_publish()
        except Exception as e:
            logger.error(f"消息发布失败，与服务器的连接错误{e}")

    @Slot()
    def controller_data_publish(self, controller_data:dict):
        # 比较两个 字典的差异，并将不同的部分通过mqtt服务发布出去
        # logger.error(f"补充：进入发布话题槽函数")
        for k in controller_data.keys():
            # logger.error(f"补充：调用publishMsg函数发布话题")
            self.publishMsg(self.control_topic[k], controller_data[k])

    def getValueByKey(self, info_num: str, key: str, mqtt_data: dict, min_v: int = 0, max_v: int = 65535, unit: str = "", times: float = 1, deffer:float = 0.0, decimal:int = 1, unit2: str="" ) -> dict:
        # 校验mqtt收到的消息是否合法, 获取dict中的key对应的value，与最大值最小值进行比较，并在最后加上单位如有，不合法返回空字典
        try:
            if min_v <= mqtt_data[info_num] <= max_v:
                if unit2 == "":
                    if times == 1:
                        return {key: f"{round((mqtt_data[info_num] - deffer), decimal)}{unit}"}
                    else:
                        return {key: f"{round(((mqtt_data[info_num] - deffer) * times), decimal)}{unit}"}
                elif unit2 == "'":
                    return {key: f"{int(mqtt_data[info_num] - deffer) * times}{unit}{int((mqtt_data[info_num] - int(mqtt_data[info_num])) * times * 60)}{unit2}"}
            else:
                logger.error(f"{key}信息不合法")
            # logger.info(f"{int(mqtt_data[info_num]) * times}")
        except KeyError:
            logger.error(f"没有{key}信息")
        return {}

    def getBoolValueByKey(self, info_num: str, key: str, mqtt_data: dict, unit1: str = "开", unit2: str="关" ) -> dict:
        # 校验mqtt收到的消息是否合法, 获取dict中的key对应的value，与最大值最小值进行比较，并在最后加上单位如有，不合法返回空字典
        try:
            if int(mqtt_data[info_num]) == 1:
                return {key: f"{unit1}"}
            elif int(mqtt_data[info_num]) == 0:
                return {key: f"{unit2}"}
            else:
                logger.error(f"{key}信息不合法")
            # logger.info(f"{int(mqtt_data[info_num])}")
        except KeyError:
            logger.error(f"没有{key}信息")
        return {}

    def set_local_model(self):
        self.local_model = True

    def reset_controller(self):
        if cfg.machineType == "xi":
            controller_data = dict(
                run_swing=2040,  # 左手柄-左右-回旋
                pressurize=2040,  # 左手柄-前后-斗杆
                bucket=2040,  # 右手柄-左右-铲斗
                rise=2040,  # 右手柄-前后-大臂
            )
        elif cfg.machineType == "CZ001":
            controller_data = dict(
                action1=0,    # 油门
                action3=127,    # 铲斗up-down
                action5=127,    # 动臂up-down
                action7=0,    # 制动
                action9=1080,    # 方向盘
            )
        else:
            controller_data = dict(
                action2=127,    # 左手柄-左右-回旋
                action1=127,    # 左手柄-前后-斗杆
                action4=127,    # 右手柄-左右-铲斗
                action3=127,    # 右手柄-前后-大臂
                action5=127,    # 左脚踏
                action6=127,    # 右脚踏
            )
        for i in range(2):
            for k,v in controller_data.items():
                self.publishMsg(self.control_topic[k], v)

    # def set_excavator_type(self, excavator_type):
    #     self.excavator_type = excavator_type


# todo 无/通风/励磁-三个位置只有1bit两状态、按钮长按虽然不变也需要发送（DI3=1=无，DI4=1=通风励磁，DI4=0=通风，用了两个bit可以的，不过少了无这个话题，有一个通风励磁话题01传递两个信号，还差无这个话题来传递无这个信号）
# 误报——回转行走+中位=3个位置只有1bit两状态（看错了，分两个话题的，可以了）