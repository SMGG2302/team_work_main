import struct
import math
import time
import threading
from logger_setup import get_logger # 保留导入

class TranslationError(Exception):
    """自定义转换错误异常"""
    pass

class Translator:
    def __init__(self, config_manager):
        # 在 __init__ 中获取 logger 实例
        self.logger = get_logger()
        self.config_manager = config_manager
        # MqttHandler 会记录 Broker 信息，这里不再重复记录
        self.mqtt_topic_base = config_manager.get_mqtt_config().get('control_topic_base', '')
        self.can_to_mqtt_rules = config_manager.get_can_to_mqtt_rules()
        self.mqtt_to_can_raw_rules = config_manager.get_mqtt_to_can_rules()
        self.signals_by_can_id = config_manager.get_signals_by_can_id()
        self._signal_state = {} # 存储所有信号状态的字典-中转站
        self._state_lock = threading.Lock()
        self._heartbeat_counters = {}
        self._initialize_signal_state()
        self.logger.info("Translator 初始化完成。")

    def _initialize_signal_state(self):
        """根据 protocol.json 中的 initial_value 初始化信号状态"""
        with self._state_lock:
            self._signal_state.clear()
            self._heartbeat_counters.clear()
            for rules_for_can_id in self.signals_by_can_id.values():
                for signal_name, rule in rules_for_can_id.items():
                    initial_value = rule.get('initial_value')
                    if rule.get('type') == 'bool' and initial_value is not None:
                         initial_value = bool(initial_value)
                    self._signal_state[signal_name] = initial_value
                    if rule.get('generated', False):
                        self._heartbeat_counters[signal_name] = initial_value if initial_value is not None else 0
            self.logger.debug(f"信号初始状态: {self._signal_state}")

    def _set_value_in_bytearray(self, data_array, byte_index, start_bit, length, value):
        """在 bytearray 的指定位置设置位值 (支持跨字节)"""
        if byte_index >= len(data_array):
            self.logger.error(f"设置位值错误：字节索引 {byte_index} 超出数据长度 {len(data_array)}")
            return False
        if start_bit < 0 or start_bit > 7 or length <= 0:
            self.logger.error(f"设置位值错误：无效的位参数 (byte={byte_index}, bit={start_bit}, len={length}) ")
            return False
        
        # 计算需要修改的字节范围
        end_bit = start_bit + length - 1
        start_byte = byte_index
        end_byte = byte_index + (end_bit // 8)
        
        if end_byte >= len(data_array):
            self.logger.error(f"设置位值错误：信号长度超出数据范围 (需要到字节 {end_byte}) ")
            return False
        
        # 清空需要设置的位
        for i in range(start_byte, end_byte + 1):
            local_start_bit = 0 if i > start_byte else start_bit
            local_end_bit = 7 if i < end_byte else (start_bit + length - 1) % 8
            mask = ((1 << (local_end_bit - local_start_bit + 1)) - 1) << local_start_bit
            data_array[i] &= ~mask
        
        # 设置新值（小端序）
        value_masked = int(value) & ((1 << length) - 1)
        value_shifted = value_masked << start_bit
        
        for i in range(start_byte, end_byte + 1):
            byte_mask = 0xFF << (i - start_byte) * 8
            byte_value = (value_shifted & byte_mask) >> ((i - start_byte) * 8)
            data_array[i] |= byte_value
        
        return True

    def _get_value_from_bytearray(self, data_array, byte_index, start_bit, length):
        """从 bytearray 的指定位置获取位值 (不跨字节)"""
        if byte_index >= len(data_array):
            raise TranslationError(f"获取位值错误：字节索引 {byte_index} 超出数据长度 {len(data_array)}")
        if start_bit < 0 or start_bit > 7 or length <= 0 or start_bit + length > 8:
            raise TranslationError(f"获取位值错误：无效的位参数 (byte={byte_index}, bit={start_bit}, len={length})")
        mask = ((1 << length) - 1) << start_bit
        value = (data_array[byte_index] & mask) >> start_bit
        return value

    def _unpack_signal(self, data_bytes, signal_def):
        """
        从字节串中解包单个信号值。
        (代码逻辑保持不变，只修改日志调用)
        """
        signal_type = signal_def.get('type', 'uint8')
        start_byte = signal_def.get('byte')
        length_bits = signal_def.get('length')
        start_bit = signal_def.get('bit')
        scale = signal_def.get('scale', 1.0)
        offset = signal_def.get('offset', 0.0)

        if start_byte is None or length_bits is None:
            raise TranslationError("信号定义缺少 'byte' 或 'length'")
        if length_bits <= 0:
             raise TranslationError("信号定义 'length' 必须为正数")

        effective_start_bit = start_bit if start_bit is not None else 0
        if effective_start_bit < 0 or effective_start_bit > 7:
            raise TranslationError(f"无效的起始位: {effective_start_bit}")

        abs_start_bit = start_byte * 8 + effective_start_bit
        abs_end_bit_exclusive = abs_start_bit + length_bits
        start_byte_idx = abs_start_bit // 8
        end_byte_idx_exclusive = math.ceil(abs_end_bit_exclusive / 8)

        if end_byte_idx_exclusive > len(data_bytes):
            raise TranslationError(f"CAN数据长度 ({len(data_bytes)}) 不足以解包信号 (需要到字节 {end_byte_idx_exclusive})")

        raw_bytes = data_bytes[start_byte_idx : end_byte_idx_exclusive]

        raw_value = 0
        int_value = int.from_bytes(raw_bytes, byteorder='little', signed=False)
        bit_offset_in_int = abs_start_bit % 8
        mask = (1 << length_bits) - 1
        shifted_value = int_value >> bit_offset_in_int
        raw_value = shifted_value & mask

        is_signed = signal_type.startswith('int')
        if is_signed:
            sign_bit_mask = 1 << (length_bits - 1)
            if (raw_value & sign_bit_mask) != 0:
                raw_value = raw_value - (1 << length_bits)

        final_value = 0
        if signal_type == 'bool':
            final_value = bool(raw_value != 0)
            ## self.logger.debug(f"解包信号 (bit): byte[{start_byte}:{effective_start_bit} len={length_bits}] -> raw={raw_value}, final={final_value} (bool)")
            return final_value
        elif signal_type == 'float':
             if length_bits == 32 and effective_start_bit == 0:
                 try:
                     if len(raw_bytes) == 4:
                        final_value = struct.unpack('<f', raw_bytes)[0]
                        self.logger.debug(f"解包信号 (float32): byte[{start_byte_idx}:{start_byte_idx+4}] -> raw={raw_bytes.hex()}, final={final_value}")
                     else:
                          raise TranslationError(f"Float 类型需要 4 字节对齐数据，得到 {len(raw_bytes)} 字节")
                 except struct.error as e:
                     raise TranslationError(f"解包 float 失败: {e}")
             else:
                 raise TranslationError("Float 类型必须是 32 位且字节对齐")
        else:
             final_value = raw_value

        final_value = final_value * scale + offset

        if 'int' in signal_type and not signal_type == 'float':
            final_value = round(final_value)

        ## self.logger.debug(f"解包信号: byte[{start_byte}:{effective_start_bit} len={length_bits}] -> raw={raw_value}, scaled/offset={final_value} (type={signal_type})")
        return final_value

    def translate_can_to_mqtt(self, can_msg):
        """将 CAN 消息转换为 MQTT payload dict"""
        rule = self.can_to_mqtt_rules.get(can_msg.arbitration_id)
        if not rule:
            return None

        signal_defs = rule.get('signals')
        if not signal_defs:
            self.logger.error(f"CAN ID {hex(can_msg.arbitration_id)} 的上报规则不完整。")
            return None

        payload = {}
        can_data = can_msg.data
        ## self.logger.debug(f"尝试解包 CAN ID {hex(can_msg.arbitration_id)}, Data: {can_data.hex()}")

        for signal_name, signal_def in signal_defs.items():
            try:
                ## self.logger.debug(f"解包信号 '{signal_name}' 定义: {signal_def}")
                value = self._unpack_signal(can_data, signal_def)
                payload[signal_name] = value
            except TranslationError as e:
                self.logger.warning(f"解包信号 '{signal_name}' (CAN ID {hex(can_msg.arbitration_id)}) 失败: {e}")
            except Exception as e:
                self.logger.error(f"解包信号 '{signal_name}' 时发生意外错误: {e}", exc_info=True)

        if not payload:
            self.logger.warning(f"未能从 CAN ID {hex(can_msg.arbitration_id)} (Data: {can_data.hex()}) 解包任何有效信号。")
            return None

        self.logger.debug(f"CAN->MQTT 转换成功: CAN ID={hex(can_msg.arbitration_id)} -> Payload={payload}")
        return payload

    def update_signal_state_from_mqtt(self, topic, payload_str):
        """根据 MQTT 消息更新内部信号状态"""
        if not topic.startswith(self.mqtt_topic_base):
            self.logger.warning(f"忽略与基础主题 '{self.mqtt_topic_base}' 不匹配的 MQTT 主题: '{topic}'")
            return False
        topic_suffix = topic[len(self.mqtt_topic_base):]

        rule = self.mqtt_to_can_raw_rules.get(topic_suffix)
        if not rule:
            self.logger.warning(f"找不到 MQTT 主题后缀 '{topic_suffix}' 对应的控制规则。")
            return False

        signal_name = rule.get('signal')
        if not signal_name:
             self.logger.error(f"MQTT 规则 '{topic_suffix}' 缺少 'signal' 键。")
             return False

        value = None
        signal_type = rule.get('type', 'uint8')
        try:
            if signal_type == 'bool':
                value = payload_str.lower() in ['true', '1', 'on', 'yes']
            elif 'int' in signal_type:
                value = int(round(float(payload_str)))
            elif signal_type == 'float':
                value = float(payload_str)
            else:
                value = int(payload_str)

            with self._state_lock:
                self._signal_state[signal_name] = value
            self.logger.debug(f"信号状态更新: {signal_name} = {value} (来自 MQTT: {topic})")
            return True

        except ValueError:
             self.logger.error(f"无法将 MQTT payload '{payload_str}' (主题: {topic}) 转换为信号 '{signal_name}' 需要的类型 ({signal_type})。")
             return False
        except Exception as e:
             self.logger.error(f"更新信号状态时出错: {e}", exc_info=True)
             return False

    def build_can_frame(self, can_id):
        """
        根据当前信号状态构建指定 CAN ID 的完整数据帧 (bytearray)。
        """
        if can_id not in self.signals_by_can_id:
            self.logger.error(f"无法构建帧：未找到 CAN ID {hex(can_id)} 的信号定义。")
            return None

        can_data = bytearray(8)
        signals_for_this_id = self.signals_by_can_id[can_id]

        heartbeats_to_update = {}
        for signal_name, rule in signals_for_this_id.items():
             if rule.get('generated', False):
                 with self._state_lock:
                     if signal_name in self._heartbeat_counters:
                         current_count = self._heartbeat_counters[signal_name]
                         next_count = (current_count + 1) % 256
                         self._heartbeat_counters[signal_name] = next_count
                         heartbeats_to_update[signal_name] = next_count
                         self.logger.debug(f"生成心跳信号 {signal_name}: {next_count}")
                     else:
                         self.logger.warning(f"信号 '{signal_name}' 标记为 generated 但找不到对应计数器。使用 0。")
                         heartbeats_to_update[signal_name] = 0

        with self._state_lock:
            for signal_name, rule in signals_for_this_id.items():
                byte_index = rule.get('byte')
                start_bit = rule.get('bit')
                length = rule.get('length')
                is_generated = rule.get('generated', False)

                if byte_index is None or start_bit is None or length is None:
                    self.logger.error(f"信号 '{signal_name}' (CAN ID {hex(can_id)}) 定义不完整 (缺少 byte/bit/length)。")
                    continue

                value_to_pack = None
                if is_generated:
                    value_to_pack = heartbeats_to_update.get(signal_name, 0)
                else:
                    value_to_pack = self._signal_state.get(signal_name)

                if value_to_pack is None:
                     value_to_pack = rule.get('initial_value')
                     if rule.get('type') == 'bool' and value_to_pack is None:
                          value_to_pack = 0
                     elif value_to_pack is None:
                          self.logger.warning(f"信号 '{signal_name}' (CAN ID {hex(can_id)}) 当前状态和初始值均为 None，将使用 0 打包。")
                          value_to_pack = 0

                try:
                    if rule.get('type') == 'bool':
                        pack_val_int = 1 if value_to_pack else 0
                    else:
                        pack_val_int = int(value_to_pack)

                    if not self._set_value_in_bytearray(can_data, byte_index, start_bit, length, pack_val_int): # 打包信号函数的调用
                        self.logger.error(f"打包信号 '{signal_name}' 到 CAN 数据失败。")
                except Exception as e:
                     self.logger.error(f"打包信号 '{signal_name}' (值: {value_to_pack}) 时发生错误: {e}", exc_info=True)

        self.logger.debug(f"构建完成 CAN Data for ID {hex(can_id)}: {can_data.hex()}")
        return can_data

    def get_target_can_ids_for_sending(self):
        """获取所有需要周期性发送控制帧的 CAN ID 列表"""
        valid_ids = []
        raw_ids = self.signals_by_can_id.keys()
        for can_id in raw_ids:
             if isinstance(can_id, int):
                  valid_ids.append(can_id)
             else:
                  self.logger.warning(f"内部信号定义中发现非整数 CAN ID: {can_id}，已忽略。")
        return valid_ids
