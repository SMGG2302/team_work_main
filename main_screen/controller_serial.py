import sys
import traceback

from PySide6.QtCore import QObject, Signal
from loguru import logger
from serial.threaded import Protocol
from app.common.serial_connect.crc16 import check_crc16

from app.core.config import cfg

class ControllerProtocol(Protocol, QObject):
    controller_data = Signal(dict)
    # 固定请求信息
    data_for_request = bytes.fromhex('5aa5a20100008032')

    def __init__(self):
        super().__init__()
        self.buffer = bytearray()
        self.transport = None
        self.buffer_reset = True
        self.AI_Type = 1
        self.controller_data_dict:dict = dict()

        # === 方向盘状态（私有）===
        self.__steering_state = {
            'initialized': False,
            'last_angle': 0.0,
            'accumulated_delta': 0.0,
            'last_power': 0
        }

    def connection_made(self, transport):
        """保存连接"""
        self.transport = transport
        # sys.stdout.write('port opened\n')

    def connection_lost(self, exc):
        if exc:
            traceback.print_exception(exc)
        # sys.stdout.write('port closed\n')

    def send_request(self):
        """发送请求"""
        self.transport.write(self.data_for_request)
        # print('request sent\n')

    def data_received(self, data: bytes):
        """处理接收到的数据"""

        # 处理重置信号
        # logger.debug(f"接收数据{data}")
        if self.buffer_reset:
            if data.hex() == '5a':
                self.buffer_reset = False
            else:
                return

        # 检查帧头是否合法
        if len(self.buffer) > 1:
            if not self.buffer.startswith(bytes.fromhex('5aa5')):
                # 重置
                self.buffer.clear()
                self.buffer_reset = True
                return

        # 添加到 buffer
        self.buffer.extend(data)

        if len(self.buffer) >= 70:

            # 分割
            frame = self.buffer[:70]
            self.buffer = self.buffer[70:]
            # logger.debug(f"data_received-1: {frame.hex(sep=' ')}")
            # logger.debug(f"data_received-0: {frame}")
            # logger.error("补充：帧校验暂时取消，直接解析")
            if cfg.machineType == "chi":
                self.parse_chi(frame)
            elif cfg.machineType == "xi":
                self.parse_xi(frame)
            elif cfg.machineType == "chi_12":
                self.parse_chi_12(frame)
            elif cfg.machineType == "chi_21":
                self.parse_chi_21(frame)
            elif cfg.machineType == "chi_22":
                self.parse_chi_22(frame)
            elif cfg.machineType == "su":
                self.parse_su(frame)
            elif cfg.machineType == "JS01_AZ001" or cfg.machineType == "AZ001" or cfg.machineType == "AZ001_xiling":
                self.parse_JS01_AZ001(frame)
            elif cfg.machineType == "CZ001":
                self.parse_CZ001(frame)
            else:
                logger.debug("机型指定无法匹配")
            # 校验
            #if check_crc16(frame):
                #self.parse(frame)
                #logger.success("帧校验通过")
            #else:
                # 重置
                #self.buffer.clear()
                #self.buffer_reset = True
                #logger.error("帧校验不通过")
            if cfg.modified_number == "xiling":
                self.AI_Type = 2
            else:
                self.AI_Type = 1

    def parse_chi(self, frame: bytearray):
        # logger.error("补充：进入解析函数parse")
        """解析数据"""
        # 5a a5 a2 81 00 3e 01 00 3b 01 05 00 00 00 00 00 02 0a 00 00
        # 00 00 00 00 00 00 00 00 03 18 08 00 08 27 08 00 08 00 00 03
        # 07 ef 08 01 00 03 00 02 00 03 00 02 00 02 04 02 00 00 05 03
        # 31 30 31 06 03 31 30 31 cc ef
        # di_data = tuple([int(i) for i in format(frame[11], '08b')])

        di_data = tuple(int(i) for byte in frame[11:15] for i in format(byte, '08b'))
        # di_data = tuple([int(i) for i in format(frame[11], '08b')])
        ai_data = tuple(frame[index] * 256 + frame[index + 1] for index in range(30, 44, 2))
        # logger.debug(f"原始帧-{frame=}、数字量-{di_data=}、模拟量-{ai_data=}")

        # centers = [600, 870, 1110, 1400, 1650, 1900, 2200, 2500, 2750, 3000, 3350]
        # distances = [abs(ai_data[4] - center) for center in centers]
        # mapped_value = distances.index(min(distances))

        now_controller_data = dict(
            emergency_stop=di_data[7],                      # DI1 急停
            voltage_380V=di_data[6],                        # 2 380V
            bucketBoom_up=di_data[5],                       # 3 斗轮臂架上升
            bucketBoom_down=di_data[4],                     # 4 斗轮臂架下降
            swingRun_left=di_data[3],                       # 5 转弯行走左
            swingRun_right=di_data[2],                      # 6 转弯行走右
            safetyLoop_up=di_data[1],                       # 7 提升安全回路接通（黑色）
            obstacle=di_data[0],                            # DI8 故障解除 / 应答（绿色）

            swing_couple=di_data[15],                       # DI9 回转耦合 收回 / 移出
            up_interlock=di_data[14],                       # 10 提升联锁 / 解锁
            run_interlock=di_data[13],                      # 11 行走联锁 / 解锁
            bucketBoom_up_interlock=di_data[12],            # 12 斗轮臂架提升 联锁 / 解锁
            bucket_interlock=di_data[11],                   # 13 斗轮 联锁 / 解锁
            upperSwing_interlock=di_data[10],               # 14 上部回转 联锁 / 解锁
            run_forward=di_data[9],                         # 15 行走前
            run_backward=di_data[8],                        # DI16 行走后

            swing_left=di_data[23],                         # DI17 回转左
            swing_right=di_data[22],                        # 18 回转右
            monitor_control_switch=di_data[21],             # 19 监控 / 遥控 切换
            central_control=di_data[20],                    # 20 集中控制 关 / 开
            launch_warning=di_data[19],                     # 21 启动警告（绿色）
            cab_up=di_data[18],                             # 22 驾驶室提升
            cab_down=di_data[17],                           # 23 驾驶室下降
            belt_conveyor=di_data[16],                      # DI24 胶带机断开 / 接通（红色）

            run_emergencyState=di_data[31],                 # DI25 行走紧急状态断开 / 接通（红色）


            swing_velocity=self.cal_dead_zone(ai_data[0]),              # 1 回转速度
            waveTest=self.cal_dead_zone(ai_data[2]),                    # 3 自波动-测试用信号

            # {device_id} / phy / emergency_stop
            # {device_id} / phy / voltage_380V
            # {device_id} / phy / bucketBoom_up
            # {device_id} / phy / bucketBoom_down
            # {device_id} / phy / swingRun_left
            # {device_id} / phy / swingRun_right
            # {device_id} / phy / safetyLoop_up
            # {device_id} / phy / obstacle
            # {device_id} / phy / swing_couple
            # {device_id} / phy / up_interlock
            # {device_id} / phy / run_interlock
            # {device_id} / phy / bucketBoom_up_interlock
            # {device_id} / phy / bucket_interlock
            # {device_id} / phy / upperSwing_interlock
            # {device_id} / phy / run_forward
            # {device_id} / phy / run_backward
            # {device_id} / phy / swing_left
            # {device_id} / phy / swing_right
            # {device_id} / phy / monitor_control_switch
            # {device_id} / phy / central_control
            # {device_id} / phy / launch_warning
            # {device_id} / phy / cab_up
            # {device_id} / phy / cab_down
            # {device_id} / phy / belt_conveyor
            # {device_id} / phy / run_emergencyState
            #
            # {device_id} / phy / swing_velocity

            # 急停
            # 380V
            # 斗轮臂架上升
            # 斗轮臂架下降
            # 转弯行走左
            # 转弯行走右
            # 提升安全回路接通（黑色）
            # 故障解除 / 应答（绿色）
            # 回转耦合 收回 / 移出
            # 提升联锁 / 解锁
            # 行走联锁 / 解锁
            # 斗轮臂架提升 联锁 / 解锁
            # 斗轮 联锁 / 解锁
            # 上部回转 联锁 / 解锁
            # 行走前
            # 行走后
            # 回转左
            # 回转右
            # 监控 / 遥控 切换
            # 集中控制 关 / 开
            # 启动警告（绿色）
            # 驾驶室提升
            # 驾驶室下降
            # 胶带机断开 / 接通（红色）
            # 行走紧急状态断开 / 接通（红色）
            # 回转速度


        )
        # logger.error("补充：字典生成完成,如下")
        # logger.info(now_controller_data)
        if self.controller_data_dict != now_controller_data:
            # or (now_controller_data["horn"] == 1) or (now_controller_data["ignition"] == 1)
                                      # 此项条件拿掉，西昌项目的字典中没有horn这个话题的
        # if self.controller_data_dict != now_controller_data:
            # logger.error("补充：字典更新判断完成")
            self.controller_data_dict.update(now_controller_data)
            #logger.error("补充：更新字典")
            self.controller_data.emit(self.controller_data_dict)
            # logger.error("补充：发射信号完成")
            # logger.info(now_controller_data)
        # logger.error("补充：解析函数结束-带发射信号判断")

    def cal_dead_zone(self, raw):
        return 2040 if 2020 < raw < 2060 else raw

    # 话题高频在发，说明发射信号高频被触发，而触发发射信号的条件是，字典更新，那么字典是否有微小更新被认为是更新了呢？比如死区附近的晃动需要强行回到中位
    # {'stop': 1, 'left_button': 0, 'ventilation_excitation': 0, 'rise_lock': 0, 'host_stop': 1, 'host_start': 0,
    #  'dc_split_close': 1, 'dc_split_open': 0, 'right_button': 0, 'mode': 0, 'pressurize_coupling': 0,
    #  'air_compressor': 0, 'swing_run_swing': 0, 'swing_run_run': 0, 'turn_left': 0, 'turn_right': 0, 'ventilation': 0,
    #  'rare_oil': 0, 'dry_oil_1': 0, 'dry_oil_2': 0, 'pressurize': 2035, 'run_swing': 2034, 'rise': 2035, 'bucket': 2035}
    #
    # {'stop': 1, 'left_button': 0, 'ventilation_excitation': 0, 'rise_lock': 0, 'host_stop': 1, 'host_start': 0,
    #  'dc_split_close': 1, 'dc_split_open': 0, 'right_button': 0, 'mode': 0, 'pressurize_coupling': 0,
    #  'air_compressor': 0, 'swing_run_swing': 0, 'swing_run_run': 0, 'turn_left': 0, 'turn_right': 0, 'ventilation': 0,
    #  'rare_oil': 0, 'dry_oil_1': 0, 'dry_oil_2': 0, 'pressurize': 2035, 'run_swing': 2034, 'rise': 2034, 'bucket': 2035}

    def parse_xi(self, frame: bytearray):
        # logger.error("补充：进入解析函数parse")
        """解析数据"""
        # 5a a5 a2 81 00 3e 01 00 3b 01 05 00 00 00 00 00 02 0a 00 00
        # 00 00 00 00 00 00 00 00 03 18 08 00 08 27 08 00 08 00 00 03
        # 07 ef 08 01 00 03 00 02 00 03 00 02 00 02 04 02 00 00 05 03
        # 31 30 31 06 03 31 30 31 cc ef
        # di_data = tuple([int(i) for i in format(frame[11], '08b')])

        di_data = tuple(int(i) for byte in frame[11:14] for i in format(byte, '08b'))
        # di_data = tuple([int(i) for i in format(frame[11], '08b')])
        ai_data = tuple(frame[index] * 256 + frame[index + 1] for index in range(30, 44, 2))
        # logger.debug(f"原始帧-{frame=}、数字量-{di_data=}、模拟量-{ai_data=}")

        # centers = [600, 870, 1110, 1400, 1650, 1900, 2200, 2500, 2750, 3000, 3350]
        # distances = [abs(ai_data[4] - center) for center in centers]
        # mapped_value = distances.index(min(distances))

        now_controller_data = dict(
            stop=di_data[7],                     # DI1 急停按钮
            left_button=di_data[6],              # 2 左手柄按钮
            none=di_data[5],                     # 3 无
            ventilation_excitation=di_data[4],   # 4 通风励磁
            rise_lock=di_data[3],                # 5 提升抱闸
            host_stop=di_data[2],                # 6 主机停止
            host_start=di_data[1],               # 7
            dc_split_close=di_data[0],           # 8 直流分闸

            dc_split_open=di_data[15],           # DI9 直流合闸
            right_button=di_data[14],            # 右手柄按钮
            mode=di_data[13],                    # 监控/遥控切换
            pressurize_coupling=di_data[12],     # 推压耦合 关/开
            air_compressor=di_data[11],          # 空压机 关/开
            swing_run_swing=di_data[10],         # 回转/行走-回转
            swing_run_run=di_data[9],            # 回转/行走-行走
            turn_left=di_data[8],                # 左右转-左转

            turn_right=di_data[23],         # DI17左右转-右转
            ventilation=di_data[22],        # 机棚通风 开/关
            rare_oil=di_data[21],           # 稀油润滑 开/关
            dry_oil_1=di_data[20],          # 干油润滑 开/关
            dry_oil_2=di_data[19],          # 干油润滑2 开/关


            pressurize=self.cal_dead_zone(ai_data[0]),           # 1 推压收回（左手柄前后）
            #pressurize=ai_data[0],
            run_swing=self.cal_dead_zone(ai_data[1]),            # 2 行走转弯（左手柄左右）
            #run_swing=ai_data[1],
            rise=self.cal_dead_zone(ai_data[2]),                 # 3 提升 / 下降（右手柄前后）
            #rise=ai_data[2],
            bucket=self.cal_dead_zone(ai_data[3]),               # 4 开斗 / 喇叭（右手柄左右）
            #bucket=ai_data[3],

            # lock=di_data[7],                                # 先导开关 液压锁
            # stop=di_data[6],                                # 急停
            # horn=di_data[4],                                # 鸣笛
            # energize=di_data[2],                            # 上电
            # ignition=di_data[1],                            # 启动
            #
            #
            # left_handler=self.cal_dead_zone(ai_data[0]),    # 左手柄-左右-回旋
            # bucket_arm=self.cal_dead_zone(ai_data[1]),      # 左手柄-前后-斗杆
            # bucket=self.cal_dead_zone(ai_data[2]),          # 右手柄-左右-铲斗
            # boom=self.cal_dead_zone(ai_data[3]),            # 右手柄-前后-大臂
            # left_pedal=self.cal_dead_zone(ai_data[5]),      # 左脚踏
            # right_pedal=self.cal_dead_zone(ai_data[6]),     # 右脚踏
        )
        # logger.error("补充：字典生成完成,如下")
        # logger.info(now_controller_data)
        if self.controller_data_dict != now_controller_data:
            # or (now_controller_data["horn"] == 1) or (now_controller_data["ignition"] == 1)
                                      # 此项条件拿掉，西昌项目的字典中没有horn这个话题的
        # if self.controller_data_dict != now_controller_data:
            # logger.error("补充：字典更新判断完成")
            self.controller_data_dict.update(now_controller_data)
            #logger.error("补充：更新字典")
            self.controller_data.emit(self.controller_data_dict)
            # logger.error("补充：发射信号完成")
            # logger.info(now_controller_data)
        # logger.error("补充：解析函数结束-带发射信号判断")

    def parse_chi_12(self, frame: bytearray):
        # logger.error("补充：进入解析函数parse")
        """解析数据"""
        # 5a a5 a2 81 00 3e 01 00 3b 01 05 00 00 00 00 00 02 0a 00 00
        # 00 00 00 00 00 00 00 00 03 18 08 00 08 27 08 00 08 00 00 03
        # 07 ef 08 01 00 03 00 02 00 03 00 02 00 02 04 02 00 00 05 03
        # 31 30 31 06 03 31 30 31 cc ef

        di_data = tuple(int(i) for byte in frame[11:15] for i in format(byte, '08b'))
        # di_data = tuple([int(i) for i in format(frame[11], '08b')])
        ai_data = tuple(frame[index] * 256 + frame[index + 1] for index in range(30, 44, 2))
        # logger.debug(f"原始帧-{frame=}、数字量-{di_data=}、模拟量-{ai_data=}")

        # centers = [600, 870, 1110, 1400, 1650, 1900, 2200, 2500, 2750, 3000, 3350]
        # distances = [abs(ai_data[4] - center) for center in centers]
        # mapped_value = distances.index(min(distances))

        now_controller_data = dict(
            emergency_stop=di_data[7],                       # DI1 急停
            loadBoom_up=di_data[6],                          # 2 转载臂架提升
            loadBoom_down=di_data[5],                        # 3
            swingRun_left=di_data[4],                        # 4 回转行走左
            swingRun_right=di_data[3],                       # 5
            voltage_380V=di_data[2],                         # 6
            obstacle=di_data[1],                             # 7 故障
            loadBoom_run_forward=di_data[0],                 # DI8

            loadBoom_run_backward=di_data[15],               # DI9 转载臂架行走后
            loadBoom_funnel_left=di_data[14],                # 10 转载臂架漏斗左
            loadBoom_funnel_right=di_data[13],               # 11
            monitor_control_switch=di_data[12],              # 12
            launch_warning=di_data[11],                      # 13
            rope_3B=di_data[10],                             # 14
            hydraulic_pump_open=di_data[9],                  # 15
            hydraulic_pump_close=di_data[8],                 # DI16

            loadConveyor_forward=di_data[23],                # DI17 转载胶带机前
            loadConveyor_backward=di_data[22],               # 18


            swing_velocity=self.cal_dead_zone(ai_data[0]),  # 1 回转速度
            waveTest=self.cal_dead_zone(ai_data[2]),        # 3 自波动-测试用信号

        )
        # logger.info(now_controller_data)
        if self.controller_data_dict != now_controller_data:
            self.controller_data_dict.update(now_controller_data)
            self.controller_data.emit(self.controller_data_dict)
            # logger.error("补充：发射信号完成")
            # logger.info(now_controller_data)

    def parse_chi_21(self, frame: bytearray):
        # logger.error("补充：进入解析函数parse")
        """解析数据"""
        # 5a a5 a2 81 00 3e 01 00 3b 01 05 00 00 00 00 00 02 0a 00 00
        # 00 00 00 00 00 00 00 00 03 18 08 00 08 27 08 00 08 00 00 03
        # 07 ef 08 01 00 03 00 02 00 03 00 02 00 02 04 02 00 00 05 03
        # 31 30 31 06 03 31 30 31 cc ef

        di_data = tuple(int(i) for byte in frame[11:15] for i in format(byte, '08b'))
        # di_data = tuple([int(i) for i in format(frame[11], '08b')])
        ai_data = tuple(frame[index] * 256 + frame[index + 1] for index in range(30, 44, 2))
        # logger.debug(f"原始帧-{frame=}、数字量-{di_data=}、模拟量-{ai_data=}")

        # centers = [600, 870, 1110, 1400, 1650, 1900, 2200, 2500, 2750, 3000, 3350]
        # distances = [abs(ai_data[4] - center) for center in centers]
        # mapped_value = distances.index(min(distances))

        now_controller_data = dict(
            emergency_stop=di_data[7],                       # DI1 急停
            dischargeConveyor_down=di_data[6],               # 2 转载臂架提升
            dischargeConveyor_up=di_data[5],                        # 3
            belt_swing_left=di_data[4],                        # 4 回转行走左
            belt_swing_right=di_data[3],                       # 5
            obstacle=di_data[2],                         # 6
            safetyLoop=di_data[1],                             # 7 故障
            voltage_380V=di_data[0],                 # DI8

            conveyor=di_data[15],                            # DI9 转载臂架行走后
            run_forward=di_data[14],                # 10 转载臂架漏斗左
            run_backward=di_data[13],               # 11
            swing_left=di_data[12],              # 12
            swing_right=di_data[11],                      # 13
            monitor_control_switch=di_data[10],                             # 14
            launch_warning=di_data[9],                  # 15
            conveyor_stop=di_data[8],                 # DI16

            pending=di_data[23],                            # DI17 转载胶带机前


            swing_velocity=self.cal_dead_zone(ai_data[0]),  # 1 回转速度

            waveTest=self.cal_dead_zone(ai_data[2]),        # 3 自波动-测试用信号

        )
        # logger.info(now_controller_data)
        if self.controller_data_dict != now_controller_data:
            self.controller_data_dict.update(now_controller_data)
            self.controller_data.emit(self.controller_data_dict)
            # logger.error("补充：发射信号完成")
            # logger.info(now_controller_data)

    def parse_chi_22(self, frame: bytearray):
        # logger.error("补充：进入解析函数parse")
        """解析数据"""
        # 5a a5 a2 81 00 3e 01 00 3b 01 05 00 00 00 00 00 02 0a 00 00
        # 00 00 00 00 00 00 00 00 03 18 08 00 08 27 08 00 08 00 00 03
        # 07 ef 08 01 00 03 00 02 00 03 00 02 00 02 04 02 00 00 05 03
        # 31 30 31 06 03 31 30 31 cc ef

        di_data = tuple(int(i) for byte in frame[11:15] for i in format(byte, '08b'))
        # di_data = tuple([int(i) for i in format(frame[11], '08b')])
        ai_data = tuple(frame[index] * 256 + frame[index + 1] for index in range(30, 44, 2))
        # logger.debug(f"原始帧-{frame=}、数字量-{di_data=}、模拟量-{ai_data=}")

        # centers = [600, 870, 1110, 1400, 1650, 1900, 2200, 2500, 2750, 3000, 3350]
        # distances = [abs(ai_data[4] - center) for center in centers]
        # mapped_value = distances.index(min(distances))

        now_controller_data = dict(
            emergency_stop=di_data[7],                       # DI1 急停
            receivingConveyor_down=di_data[6],               # 2 转载臂架提升
            receivingConveyor_up=di_data[5],                        # 3
            dumperBaffle_swing_in=di_data[4],                        # 4 回转行走左
            dumperBaffle_swing_out=di_data[3],                       # 5
            obstacle=di_data[2],                         # 6
            launch_warning=di_data[1],                             # 7 故障
            middleConveyor_run_forward=di_data[0],                 # DI8

            middleConveyor_run_backward=di_data[15],         # DI9 转载臂架行走后
            middleConveyor_swing_left=di_data[14],                # 10 转载臂架漏斗左
            middleConveyor_swing_right=di_data[13],               # 11
            left_up_45degree=di_data[12],              # 12
            left_down_45degree=di_data[11],                      # 13
            right_up_45degree=di_data[10],                             # 14
            right_down_45degree=di_data[9],                  # 15
            monitor_control_switch=di_data[8],                      # DI16

            dumperDirection_1=di_data[23],                     # DI17 转载胶带机前
            dumperDirection_2=di_data[22],             # DI18
            dumper_stop=di_data[21],                   # DI19
            conveyor_stop=di_data[20],                 # DI20


            swing_velocity=self.cal_dead_zone(ai_data[0]),  # 1 回转速度

            waveTest=self.cal_dead_zone(ai_data[2]),        # 3 自波动-测试用信号

        )
        # logger.info(now_controller_data)
        if self.controller_data_dict != now_controller_data:
            self.controller_data_dict.update(now_controller_data)
            self.controller_data.emit(self.controller_data_dict)
            # logger.error("补充：发射信号完成")
            # logger.info(now_controller_data)

    def parse_su(self, frame: bytearray):
        #logger.debug("补充：开始解析")
        """解析数据"""
        # 5a a5 a2 81 00 3e 01 00 3b 01 05 00 00 00 00 00 02 0a 00 00
        # 00 00 00 00 00 00 00 00 03 18 08 00 08 27 08 00 08 00 00 03
        # 07 ef 08 01 00 03 00 02 00 03 00 02 00 02 04 02 00 00 05 03
        # 31 30 31 06 03 31 30 31 cc ef
        di_data = tuple([int(i) for i in format(frame[11], '08b')])
        ai_data = tuple(frame[index] * 256 + frame[index + 1] for index in range(30, 44, 2))
        # di = dict(zip(self.di_name, di_data))
        # ai = dict(zip(self.ai_name, ai_data))
        # di_name = (
        #     'lock',  # 1 先导开关 液压锁
        #     'stop',  # 2 急停按钮
        #     'left_button',  # 3 左手柄按钮
        #     'horn',  # 4 右手柄按钮 - 喇叭
        #     'power',  # 5  5+6 通电
        #     'energize_ignition',  # 6
        #     'ignition',  # 7 6+7 点火
        #     'seat_belt',  # 8 安全带
        # )
        # ai_name = (
        #     'left_handler',  # 1 左手柄左右操作 - 座舱左右旋转
        #     'bucket_arm',  # 2 左手柄前后操作 - 斗杆卸载、挖掘
        #     'bucket',  # 3 右手柄左右操作 - 铲斗挖掘、卸载
        #     'boom',  # 4 右手柄前后操作 - 动臂提升、下降
        #     'speed',  # 5 油门
        #     'left_pedal',  # 6 左脚踏
        #     'right_pedal',  # 7 右脚踏
        # )

        centers = [600, 870, 1110, 1400, 1650, 1900, 2200, 2500, 2750, 3000, 3350]
        distances = [abs(ai_data[4] - center) for center in centers]
        mapped_value = distances.index(min(distances))

        now_controller_data = dict(
            power6=di_data[7],  # 先导开关 液压锁
            power1=di_data[6],  # 急停
            aux2=di_data[4],  # 鸣笛
            power16=di_data[5],  # 左按钮
            power4=di_data[2],  # 上电
            power5=di_data[1],  # 启动

            action2=self.cal_dead_zone_su(ai_data[0]),  # 左手柄-左右-回旋
            action1=self.cal_dead_zone_su(ai_data[1]),  # 左手柄-前后-斗杆
            action4=self.cal_dead_zone_su(ai_data[2]),  # 右手柄-左右-铲斗
            action3=self.cal_dead_zone_su(ai_data[3]),  # 右手柄-前后-大臂
            action5=self.cal_dead_zone_su(ai_data[5]),  # 左脚踏
            action6=self.cal_dead_zone_su(ai_data[6]),  # 右脚踏
            power17=mapped_value,  # 油门
        )

        if (self.controller_data_dict != now_controller_data) or (now_controller_data["aux2"] == 1) or (
                now_controller_data["power5"] == 1) or (now_controller_data["power16"] == 1):
            # if self.controller_data_dict != now_controller_data:
            self.controller_data_dict.update(now_controller_data)
            self.controller_data.emit(self.controller_data_dict)
        #logger.info(now_controller_data)

    def linear_map(self, U_Lever, Y_PWM):
        x1 = U_Lever[0]
        x2 = U_Lever[1]
        y1 = Y_PWM[0]
        y2 = Y_PWM[1]
        k = (y2 - y1) / (x2 - x1)
        b = y1 - k * x1
        Coefficient = [b, k]

        return Coefficient

    def cal_dead_zone_su(self, raw):
        value_deadZone = 2048 if 1968 < raw < 2128 else raw
        # 解释：死区，基准上下正负x之间的波动，都算做基准值

        U_Lever = [0, 4096, 2048] # [最小值，最大值, 中间值]
        Y_PWM = [0, 255, 127.5]
        coefficient = self.linear_map(U_Lever, Y_PWM)
        value_map = coefficient[0] + coefficient[1] * value_deadZone
        value_map_int = int(value_map)

        return value_map_int


    def parse_CZ001(self, frame: bytearray):
        #logger.debug("补充：开始解析")
        """解析数据"""
        # 5a a5 a2 81 00 3e 01 00 3b 01   05 00 00 00 00 00 02 0a 00 00
        # 00 00 00 00 00 00 00 00 03 18   08 00 08 27 08 00 08 00 00 03
        # 07 ef 08 01 00 03 00 02 00 03   00 02 00 02 04 02 00 00 05 03
        # 31 30 31 06 03 31 30 31 cc ef
        # di_data = tuple([int(i) for i in format(frame[11], '08b')])
        di_data = tuple(int(i) for byte in frame[11:15] for i in format(byte, '08b')) # 最大容量32=(15-11)*8
        ai_data = tuple(frame[index] * 256 + frame[index + 1] for index in range(30, 44, 2)) # 最大容量7=(44-30)/2

        # centers = [780, 1125, 1450, 1800, 2148, 2485, 2826, 3150]
        # distances = [abs(ai_data[6] - center) for center in centers]
        # mapped_value = distances.index(min(distances))

        if self.AI_Type == 2:
            now_controller_data = dict(

                power2=di_data[7],     # DI1  急停
                aux3=di_data[6],       # DI2  双闪
                aux6=di_data[5],       # DI3  警示灯
                power6=di_data[4],     # DI4  备用开关1
                aux2=di_data[3],       # DI5  备用开关2
                power15=di_data[2],       # DI6  通电
                power16=di_data[1],    # DI7  点火
                # power3=di_data[0],    # DI8  监控

                power3=di_data[15],    # DI9  遥控监控
                power4=di_data[14],    # DI10 转向灯1
                power1=di_data[13],    # DI11 转向灯2
                aux9=di_data[12],    # DI12 鸣笛
                aux8=di_data[11],      # DI13 驻车
                power9=di_data[10],      # DI14 龟兔1
                power5=di_data[9],     # DI15 龟兔2
                power7=di_data[8],     # DI16 振动频率1

                power8=di_data[23],    # DI17 振动频率2
                aux7=di_data[22],    # DI18 振动开关
                # power17_3=di_data[21],  # DI19 3档
                # power17_4=di_data[20],  # DI20 4档
                power17=self.gear_transfer(di_data[23], di_data[22], di_data[21], di_data[20]),  # DI20 4档
                aux4=di_data[19],       # DI21 左转向灯
                aux5=di_data[18],       # DI22 右转向灯
                # aux1=di_data[17],       # DI23 示廓灯
                #power17=di_data[16],   # DI24 近光灯

                #power17=di_data[31],    # DI25 远光灯
                # aux2=di_data[30],        # DI26 鸣笛

                action9=self.__update_steering_angle(ai_data[0], di_data[23]),  # AI1 方向机
                action1=self.pedal_dead_zone_CZ001(ai_data[1], 1),   # AI2 油门旋钮 初始值0踩到底4096，单向踏板，区别于挖机上的双向踏板。新实现cal_dead_zone内部实现
                action5=self.cal_dead_zone_CZ001(ai_data[2]),  # AI3 （手柄X轴）
                action3=self.cal_dead_zone_CZ001(ai_data[3]),  # AI4 （手柄Y轴）
                # 'action5':self.cal_dead_zone_CZ001(ai_data[4]),                  # AI5
                # action3:self.cal_dead_zone_CZ001(ai_data[5]),    # AI6
                # power17:mapped_value,                            # AI7 旋钮/油门
            )
        else:
            now_controller_data = dict(

                power2=di_data[7],  # DI1  急停
                aux3=di_data[6],  # DI2  双闪
                aux6=di_data[5],  # DI3  警示灯
                power6=di_data[4],  # DI4  备用开关1
                aux2=di_data[3],  # DI5  备用开关2
                aux7=di_data[2],  # DI6  手柄顶部按钮
                power15=di_data[1],  # DI7  通电
                power16=di_data[0],  # DI8  启动

                # aux2=di_data[15],    # DI9  预热
                power3=di_data[14],  # DI10 遥控监控
                power4=di_data[13],  # DI11 转向灯1
                power1=di_data[12],  # DI12 转向灯2
                aux9=di_data[11],  # DI13 喇叭
                aux8=di_data[10],  # DI14 驻车
                # power9=di_data[9],     # DI15 备用开关2
                power5=di_data[8],  # DI16 龟兔

                power7=di_data[23],  # DI17 拨档开关上按
                power8=di_data[22],  # DI18 拨档开关下按
                # power17_3=di_data[21],  # DI19 3档
                # power17_4=di_data[20],  # DI20 4档
                power17=self.gear_transfer(di_data[23], di_data[22], di_data[21], di_data[20]),  # DI20 4档
                aux4=di_data[19],  # DI21 左转向灯
                aux5=di_data[18],  # DI22 右转向灯
                # aux1=di_data[17],       # DI23 示廓灯
                # power17=di_data[16],   # DI24 近光灯

                action9=self.__update_steering_angle(ai_data[0], di_data[14]),  # AI1 方向机
                action7=self.pedal_dead_zone_CZ001(ai_data[1], 1),   # AI2 刹车 初始值0踩到底4096，单向踏板，区别于挖机上的双向踏板。新实现cal_dead_zone内部实现
                action11=self.pedal_dead_zone_CZ001(ai_data[2], 2),  # AI3 油门 单向踏板，输出范围0-3600数值
                action3=self.cal_dead_zone_CZ001(ai_data[3]),  # AI4 铲挖/铲卸（手柄X轴）
                action5=self.cal_dead_zone_CZ001(ai_data[4]),  # AI5 动臂上/下（手柄Y轴）
                # action3:self.cal_dead_zone_CZ001(ai_data[5]),    # AI6
                # power17:mapped_value,                            # AI7 旋钮/油门
            )

        if (self.controller_data_dict != now_controller_data) or (now_controller_data["aux2"] == 1) or (
                now_controller_data["power4"] == 1) or (now_controller_data["power16"] == 1): # 喇叭、点火、复位
            self.controller_data_dict.clear()
            self.controller_data_dict.update(now_controller_data)
            self.controller_data.emit(self.controller_data_dict)
        logger.debug(now_controller_data)

    def linear_map_CZ001(self, U_Lever, Y_PWM):
        x1 = U_Lever[0]
        x2 = U_Lever[1]
        y1 = Y_PWM[0]
        y2 = Y_PWM[1]
        k = (y2 - y1) / (x2 - x1)
        b = y1 - k * x1
        Coefficient = [b, k]

        return Coefficient

    def cal_dead_zone_CZ001(self, raw):
        value_deadZone = 2040 if 1940 < raw < 2140 else raw   # 所有摇杆已经重新标定工作范围到0-4096
        value_useZone = min(max(value_deadZone, 300), 3780)   
        U_Lever = [300, 3780, 2040] # [最小值，最大值, 中间值]    # 功能2：映射，定义域-值域
        
        Y_PWM = [0, 255, 127.5] #不同模式下共用的转换范围
        coefficient = self.linear_map_CZ001(U_Lever, Y_PWM)
        value_map = coefficient[0] + coefficient[1] * value_useZone
        value_map_int = int(value_map) # 下位机不接受小数

        return value_map_int

    def pedal_dead_zone_CZ001(self, raw, ai_data_type):
        value_deadZone = 0 if raw < 300 else raw  # 单踏板未运行时保持0值
        value_useZone = min(max(value_deadZone, 300), 3780)
        U_Lever = [300, 3780, 2040]  # [最小值，最大值, 中间值]    # 功能2：映射，定义域-值域

        if ai_data_type == 1:
            Y_PWM = [0, 255, 127.5]  # 制动踏板映射范围0-255
        else:
            Y_PWM = [0, 3600, 1800]  # 油门踏板映射范围0-3600

        coefficient = self.linear_map_CZ001(U_Lever, Y_PWM)
        value_map = coefficient[0] + coefficient[1] * value_useZone
        value_map_int = int(value_map)  # 下位机不接受小数

        return value_map_int

    def gear_transfer(self, power_0, power_1, power_2, power_3):
        powers = [power_0, power_1, power_2, power_3]
        if sum(powers) == 0:
            return 2
        else:
            return powers.index(1)
        # for i in range(4):
        #     if powers[i] == 1:  #查找当前挡位状态
        #         return i+1


    def __adc_to_angle(self, raw_adc: int) -> float:
        """
        将 ADC 值 (17~4090) 映射为 0-360° 角度
        """
        min_adc, max_adc = 17, 4090 # 17-4090
        clamped = max(min_adc, min(max_adc, raw_adc))
        return (clamped - min_adc) / (max_adc - min_adc) * 360.0
    def __update_steering_angle(self, raw_adc: int, power: int) -> int:
        """
        计算连续方向盘角度
        输出 = 1080 + 累计转动量
        支持跨 0°/360°，开机初始化
        """
        state = self.__steering_state
        raw_angle = self.__adc_to_angle(raw_adc)
        raw_angle = raw_angle % 360.0  # 规范化

        # 检测上升沿：开机
        rising_edge = (power == 1 and state['last_power'] == 0)

        if rising_edge and not state['initialized']:
            state['accumulated_delta'] = 0.0
            state['last_angle'] = raw_angle
            state['initialized'] = True
            state['last_power'] = power
            return 1080

        if power == 0:
            state['initialized'] = False
            state['last_power'] = 0
            return 1080

        # 已开机，累计角度变化
        if state['initialized']:
            d = raw_angle - state['last_angle']
            if d > 180:
                d -= 360
            elif d < -180:
                d += 360
            state['accumulated_delta'] += d
            state['last_angle'] = raw_angle

        state['last_power'] = power
        return int(round(1080 + state['accumulated_delta']))


    def parse_JS01_AZ001(self, frame: bytearray):
        #logger.debug("补充：开始解析")
        """解析数据"""
        # 5a a5 a2 81 00 3e 01 00 3b 01   05 00 00 00 00 00 02 0a 00 00
        # 00 00 00 00 00 00 00 00 03 18   08 00 08 27 08 00 08 00 00 03
        # 07 ef 08 01 00 03 00 02 00 03   00 02 00 02 04 02 00 00 05 03
        # 31 30 31 06 03 31 30 31 cc ef
        # di_data = tuple([int(i) for i in format(frame[11], '08b')])
        di_data = tuple(int(i) for byte in frame[11:15] for i in format(byte, '08b'))
        ai_data = tuple(frame[index] * 256 + frame[index + 1] for index in range(30, 44, 2))

        centers = [475, 790, 1140, 1500, 1840, 2160, 2470, 2826, 3150, 3500]
        distances = [abs(ai_data[6] - center) for center in centers]
        mapped_value = (len(centers) - 1) - distances.index(min(distances))

        if self.AI_Type == 2:
            now_controller_data = dict(

                #power14=di_data[7],     # DI1  急停
                #power15=di_data[6],     # DI2  备用
                aux2=di_data[5],        # DI3  龟档
                power12=di_data[4],     # DI4  兔档
                power13=di_data[3],     # DI5  先导开
                power2=di_data[2],      # DI6  先导关
                power7=di_data[1],      # DI7  左手柄左按钮
                power6=di_data[0],      # DI8  左手柄右按钮

                power18=di_data[15],    # DI9  左手柄下按钮/鸣笛
                power19=di_data[14],    # DI10 左手柄使能开关/复位
                #power4=di_data[13],    # DI11 上电
                #power5=di_data[12],    # DI12 启动
                #powerY=di_data[11],    # DI13 监控
                power10=di_data[10],    # DI14 遥控
                power11=di_data[9],     # DI15 备用1
                #power4=di_data[8],     # DI16 备用2

                power4=di_data[23],     # DI17 右手柄左按钮
                power5=di_data[22],     # DI18 右手柄右按钮
                #power=di_data[21],     # DI19 右手柄下按钮/切换窗口
                power1=di_data[20],     # DI20 右手柄使能开关
                power16=di_data[19],    # DI21 备用开关（左钮子开关）
                power8=di_data[18],     # DI22 备用开关（右钮子开关）
                power9=di_data[17],     # DI23 备用开关（右钮子开关
                power21=self.speed_Type(di_data[7],di_data[6]),   # DI24 虚拟挡位

                # 31DI25 备用开关（右钮子开关
                # 30DI26 备用开关（右钮子开关
                # 29DI27 备用开关（右钮子开关
                # 28DI28 备用开关（右钮子开关

                action5=self.cal_dead_zone_JS01_AZ001(ai_data[0]),  # AI1 左脚踏
                action2=self.cal_dead_zone_JS01_AZ001(ai_data[1]),  # AI2 右脚踏
                action1=max(0,min( 255 , 254 - self.cal_dead_zone_JS01_AZ001(ai_data[2]))),  # AI3 左手柄左右
                action4=self.cal_dead_zone_JS01_AZ001(ai_data[4]),  # AI5 右手柄左右
                action3=max(0,min( 255 , 254 - self.cal_dead_zone_JS01_AZ001(ai_data[5]))),  # AI6 右手柄前后
                action7=0 if 0 <= ai_data[3] <= 10 else ai_data[3]  # AI7 旋钮/油门
            )
        else:
            now_controller_data = dict(

                power2=di_data[7],  # DI1  急停
                # power0=di_data[6],   # DI2  备用
                # aux0=di_data[5],     # DI3  龟档
                power3=di_data[4],  # DI4  兔档
                power6=di_data[3],  # DI5  先导开
                # power0=di_data[2],   # DI6  先导关
                power8=di_data[1],  # DI7  左手柄左按钮
                power9=di_data[0],  # DI8  左手柄右按钮

                power12=di_data[15],  # DI9  左手柄下按钮/鸣笛
                power16=di_data[14],  # DI10 左手柄使能开关/复位
                power4=di_data[13],  # DI11 上电
                power5=di_data[12],  # DI12 启动
                # powerY=di_data[11],  # DI13 监控
                power1=di_data[10],  # DI14 遥控
                # powerY=di_data[9],   # DI15 备用1
                # powerZ=di_data[8],   # DI16 备用2

                power10=di_data[23],  # DI17 右手柄左按钮
                power11=di_data[22],  # DI18 右手柄右按钮
                power13=di_data[21],  # DI19 右手柄下按钮/切换窗口
                aux2=di_data[20],  # DI20 右手柄使能开关
                # aux2=di_data[19],    # DI21 备用开关（左钮子开关）
                # aux2=di_data[18],    # DI22 备用开关（右钮子开关）

                action5=self.cal_dead_zone_JS01_AZ001(ai_data[0]),  # AI1 左脚踏
                action6=self.cal_dead_zone_JS01_AZ001(ai_data[1]),  # AI2 右脚踏
                action2=self.cal_dead_zone_JS01_AZ001(ai_data[2]),  # AI3 左手柄左右
                action1=self.cal_dead_zone_JS01_AZ001(ai_data[3]),  # AI4 左手柄前后
                action4=self.cal_dead_zone_JS01_AZ001(ai_data[4]),  # AI5 右手柄左右
                action3=self.cal_dead_zone_JS01_AZ001(ai_data[5]),  # AI6 右手柄前后
                power17=mapped_value,  # AI7 旋钮/油门
            )


        if (self.controller_data_dict != now_controller_data) or (now_controller_data["aux2"] == 1) or (
                now_controller_data["power5"] == 1) or (now_controller_data["power16"] == 1):
            self.controller_data_dict.clear()
            self.controller_data_dict.update(now_controller_data)
            self.controller_data.emit(self.controller_data_dict)
        #logger.info(now_controller_data)

    def linear_map_JS01_AZ001(self, U_Lever, Y_PWM):
        x1 = U_Lever[0]
        x2 = U_Lever[1]
        y1 = Y_PWM[0]
        y2 = Y_PWM[1]
        k = (y2 - y1) / (x2 - x1)
        b = y1 - k * x1
        Coefficient = [b, k]

        return Coefficient

    def cal_dead_zone_JS01_AZ001(self, raw):
        value_deadZone = 2040 if 1940 < raw < 2140 else raw   # 功能1：死区，座舱不操作时，中位值上下正负100之间的波动，都算做中位值
        value_useZone = min(max(value_deadZone, 300), 3780)   # 座舱输出不稳定，取所有信号稳定区间的子集使用，溢出子集部分收回界内 座舱实际输出[410~510, 3660~3700]
        U_Lever = [300, 3780, 2040] # [最小值，最大值, 中间值]    # 功能2：映射，定义域-值域

        Y_PWM = [0, 255, 127.5]
        coefficient = self.linear_map_JS01_AZ001(U_Lever, Y_PWM)
        value_map = coefficient[0] + coefficient[1] * value_useZone
        value_map_int = int(value_map) # 下位机不接受小数

        return value_map_int

    def speed_Type(self, Flag_F, Flag_S):
        if Flag_F == 1 and Flag_S == 0:
            speed_type = 1
        elif Flag_F == 0 and Flag_S == 0:
            speed_type = 2
        elif Flag_F == 0 and Flag_S == 1:
            speed_type = 3
        else:
            speed_type = 1
        return speed_type




