import json
import os
from logger_setup import get_logger # 保留导入
import threading

class ConfigError(Exception):
    """自定义配置错误异常"""
    pass

class ConfigManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, config_path='config.json', protocol_path=None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfigManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_path='config.json', protocol_path=None):
        if hasattr(self, '_initialized') and self._initialized:
            return

        # 在 __init__ 中获取 logger 实例
        self.logger = get_logger()

        self.config_path = config_path
        self.config = self._load_json(config_path, "基础配置")

        if protocol_path is None:
            protocol_path = self.config.get('protocol_file', 'protocol.json')
            config_dir = os.path.dirname(self.config_path)
            # 只有当 protocol_path 是相对路径且 config_path 包含目录时才拼接
            if not os.path.isabs(protocol_path) and config_dir:
                protocol_path = os.path.join(config_dir, protocol_path)
            elif not os.path.isabs(protocol_path):
                # 如果 config_path 也没有目录 (例如直接运行 `python main.py` 且 config 在当前目录)
                # 则 protocol_path 也是相对于当前工作目录
                protocol_path = os.path.abspath(protocol_path)


        self.protocol_path = protocol_path
        self.protocol = self._load_json(protocol_path, "协议定义")

        self._validate_config()
        self._initialized = True
        self.logger.info("配置管理器初始化完成。") 

    def reload_config(self):
        """重新加载配置文件"""
        self.logger.info("重新加载配置文件...")
        try:
            # 重新加载主配置文件
            self.config = self._load_json(self.config_path, "基础配置")
            
            # # 重新加载协议文件
            # self.protocol = self._load_json(self.protocol_path, "协议定义")
            
            self._validate_config()
            self.logger.info("基础配置文件重新加载完成。")
            return True
        except Exception as e:
            self.logger.error(f"重新加载基础配置文件失败: {e}")
            return False

    def _load_json(self, file_path, description="配置"):
        """加载 JSON 文件并处理错误"""
        try:
            self.logger.info(f"尝试加载 {description} 文件: {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.logger.info(f"{description} 文件加载成功。")
            return data
        except FileNotFoundError:
            self.logger.error(f"{description} 文件未找到: {file_path}")
            raise ConfigError(f"{description} 文件未找到: {file_path}")
        except json.JSONDecodeError as e:
            self.logger.error(f"{description} 文件 JSON 格式错误: {file_path} - {e}")
            raise ConfigError(f"无效的 JSON 文件: {file_path}")
        except Exception as e:
            self.logger.error(f"加载 {description} 文件时发生未知错误: {file_path} - {e}", exc_info=True)
            raise ConfigError(f"加载文件失败: {file_path}")

    def _validate_config(self):
        """对加载的配置进行基本验证"""
        required_mqtt_keys = ['broker', 'port', 'keepalive', 'simulation_broker']
        required_can_keys = ['interface', 'bitrate', 'send_interval_ms']
        required_root_keys = ['mqtt', 'can', 'logging', 'protocol_file', 'simulation_mode']

        for key in required_root_keys:
            if key not in self.config:
                raise ConfigError(f"基础配置文件 '{self.config_path}' 缺少顶级键: '{key}'")

        if not isinstance(self.config['simulation_mode'], bool):
             raise ConfigError(f"基础配置文件 '{self.config_path}' 中的 'simulation_mode' 必须是布尔值 (true/false)")

        for key in required_mqtt_keys:
            if key not in self.config['mqtt']:
                raise ConfigError(f"基础配置文件 '{self.config_path}' 的 'mqtt' 部分缺少键: '{key}'")

        for key in required_can_keys:
            if key not in self.config['can']:
                raise ConfigError(f"基础配置文件 '{self.config_path}' 的 'can' 部分缺少键: '{key}'")

        if 'mqtt_to_can' not in self.protocol:
             raise ConfigError(f"协议文件 '{self.protocol_path}' 缺少 'mqtt_to_can' 部分")
        if 'can_to_mqtt' not in self.protocol:
             raise ConfigError(f"协议文件 '{self.protocol_path}' 缺少 'can_to_mqtt' 部分")

        if self.config['simulation_mode'] and 'simulation_receive_messages' in self.config['can']:
            sim_msgs = self.config['can']['simulation_receive_messages']
            if not isinstance(sim_msgs, list):
                 raise ConfigError("配置 'can.simulation_receive_messages' 必须是一个列表。")
            for i, msg_cfg in enumerate(sim_msgs):
                if not isinstance(msg_cfg, dict):
                    raise ConfigError(f"模拟接收消息配置列表的第 {i+1} 项不是一个字典。")
                if 'id' not in msg_cfg or 'data' not in msg_cfg or 'interval_ms' not in msg_cfg:
                     raise ConfigError(f"模拟接收消息配置列表的第 {i+1} 项缺少 'id', 'data', 或 'interval_ms' 键。")
                try:
                    int(msg_cfg['id'], 16)
                except ValueError:
                     raise ConfigError(f"模拟接收消息配置列表的第 {i+1} 项 'id' ('{msg_cfg['id']}') 不是有效的十六进制字符串。")
                if not isinstance(msg_cfg['data'], str) or len(msg_cfg['data']) % 2 != 0:
                    raise ConfigError(f"模拟接收消息配置列表的第 {i+1} 项 'data' ('{msg_cfg['data']}') 不是有效的十六进制字节字符串。")
                if not isinstance(msg_cfg['interval_ms'], int) or msg_cfg['interval_ms'] <= 0:
                     raise ConfigError(f"模拟接收消息配置列表的第 {i+1} 项 'interval_ms' ('{msg_cfg['interval_ms']}') 必须是正整数。")

        self.logger.debug("配置基础验证通过。")

    def _replace_placeholders(self, obj):
        """递归替换对象中的占位符"""
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                result[key] = self._replace_placeholders(value)
            return result
        elif isinstance(obj, list):
            return [self._replace_placeholders(item) for item in obj]
        elif isinstance(obj, str):
            return self._replace_string_placeholders(obj)
        else:
            return obj
    
    def _replace_string_placeholders(self, text):
        """替换字符串中的占位符"""
        if not isinstance(text, str):
            return text
        
        device_config = self.config.get('mqtt', {}).get('device_config', {})
        device_serial = device_config.get('device_serial', '2')
        
        # 先替换 device_serial 占位符
        text = text.replace('{device_serial}', device_serial)
        
        # 获取 excavator_id 并替换其中的占位符
        excavator_id_template = device_config.get('excavator_id', 'LSVHJ133022221762')
        excavator_id = excavator_id_template.replace('{device_serial}', device_serial)
        
        # 然后替换 excavator_id 占位符
        text = text.replace('{excavator_id}', excavator_id)
        
        return text

    def get(self, key, default=None):
        """获取顶层配置项"""
        return self.config.get(key, default)

    def is_simulation_mode(self):
        return self.config.get('simulation_mode', False)

    def get_mqtt_config(self) -> dict:
        mqtt_cfg = self.config.get('mqtt', {}).copy()
        sim_mode = self.is_simulation_mode()
        actual_broker = mqtt_cfg.get('simulation_broker') if sim_mode else mqtt_cfg.get('broker')
        mqtt_cfg['broker'] = actual_broker
        
        # 动态替换占位符
        result = self._replace_placeholders(mqtt_cfg)
        
        # 确保返回的是字典类型
        if isinstance(result, dict):
            return result
        else:
            self.logger.warning(f"配置处理后类型异常，返回默认配置: {type(result)}")
            return mqtt_cfg

    def get_can_config(self):
        return self.config.get('can', {})

    # 提示输出类型 Python是动态类型语言，类型提示不会影响代码的实际执行，但它可以提高代码的可读性
    def get_logging_config(self) -> dict: 
        # print(f"断点-- log配置的对象，其实就是个字典对象: {self.config.get('logging', {})}")
        return self.config.get('logging', {})        

    def get_protocol_config(self):
        return self.protocol

    def get_mqtt_to_can_rules(self):
        """获取 MQTT 到 CAN 的规则 (原始格式)"""
        return self.protocol.get('mqtt_to_can', {})

    def get_can_to_mqtt_rules(self):
        """获取 CAN 到 MQTT 的规则，并将 CAN ID 键转换为整数"""
        rules = self.protocol.get('can_to_mqtt', {})
        int_key_rules = {}
        for can_id_str, rule in rules.items():
            try:
                can_id_int = int(can_id_str, 16)
                int_key_rules[can_id_int] = rule
            except ValueError:
                self.logger.warning(f"协议文件中发现无效的 CAN ID 格式: '{can_id_str}' (在 can_to_mqtt 中)，已忽略该规则。")
        return int_key_rules

    def get_signals_by_can_id(self):
        """将 mqtt_to_can 规则按 CAN ID 分组，方便按帧构建"""
        signals_by_id = {}
        mqtt_rules = self.get_mqtt_to_can_rules()
        for topic_suffix, rule in mqtt_rules.items():
             can_id_str = rule.get('can_id')
             signal_name = rule.get('signal')
             if not can_id_str or not signal_name:
                 self.logger.warning(f"mqtt_to_can 规则 '{topic_suffix}' 缺少 'can_id' 或 'signal'，已忽略。")
                 continue
             try:
                 can_id_int = int(can_id_str, 16)
                 if can_id_int not in signals_by_id:
                     signals_by_id[can_id_int] = {}
                 signals_by_id[can_id_int][signal_name] = rule # signals_by_id[can_id_int]是一个子字典 便于理解[][]字典嵌套
             except ValueError:
                  self.logger.warning(f"mqtt_to_can 规则 '{topic_suffix}' 的 CAN ID '{can_id_str}' 格式无效，已忽略。")
        return signals_by_id

    # 新增：系统配置相关方法
    def get_system_config(self):
        """获取系统配置"""
        return self.config.get('system', {})
    
    def get_queue_config(self):
        """获取队列配置"""
        return self.get_system_config().get('queue_sizes', {})
    
    def get_timeout_config(self):
        """获取超时配置"""
        return self.get_system_config().get('timeouts', {})
    
    def get_monitoring_config(self):
        """获取监控配置"""
        return self.get_system_config().get('monitoring', {})
    
    def get_retry_config(self):
        """获取重试配置"""
        return self.get_system_config().get('retry_delays', {})
    
    # 新增：协议超时配置相关方法
    def get_can_protocol_timeouts(self):
        """获取CAN协议超时配置"""
        return self.get_system_config().get('can_timeouts', {})
    
    def get_mqtt_protocol_timeouts(self):
        """获取MQTT协议超时配置"""
        return self.get_system_config().get('mqtt_timeouts', {})
    
    def get_status_topics_config(self) -> dict:
        """获取状态主题配置"""
        mqtt_config = self.get_mqtt_config()
        return mqtt_config.get('status_topics', {}) if isinstance(mqtt_config, dict) else {}
    
    def get_device_config(self) -> dict:
        """获取设备配置"""
        mqtt_config = self.get_mqtt_config()
        return mqtt_config.get('device_config', {}) if isinstance(mqtt_config, dict) else {}
    
    def get_excavator_id(self):
        """获取挖掘机ID（也就是设备序列号）"""
        device_config = self.config.get('mqtt', {}).get('device_config', {})
        device_serial = device_config.get('device_serial', '2')
        excavator_id_template = device_config.get('excavator_id', 'UNKNOWN')
        # 替换占位符
        excavator_id = excavator_id_template.replace('{device_serial}', device_serial)
        return excavator_id
    
    def get_device_serial(self):
        """获取设备序号"""
        return self.get_device_config().get('device_serial', '2')
    
    def get_equipment_serial_number(self):
        """获取设备序列号（与excavator_id相同）"""
        return self.get_excavator_id()  # 两者是同一个值
    
    def get_protocol_mapping(self):
        """获取协议映射配置"""
        return self.get_protocol_config().get('protocol_mapping', {})
    
    def get_external_status_fields(self):
        """获取对外协议状态字段映射"""
        return self.get_protocol_mapping().get('external_status_fields', {})
    
    def get_internal_class_mapping(self):
        """获取对内协议类别映射"""
        return self.get_protocol_mapping().get('internal_class_mapping', {}).get('classes', {})
    
    def get_external_topic_template(self):
        """获取对外协议主题模板（完整话题名）"""
        topic_template = self.get_protocol_mapping().get('external_status_fields', {}).get('target_topic_template', 'remote_ctrl/console/equipment_status')
        return self._replace_string_placeholders(topic_template)
    
    def get_internal_topic_template(self):
        """获取对内协议主题模板（完整话题名）"""
        topic_template = self.get_protocol_mapping().get('internal_class_mapping', {}).get('target_topic_template', 'up/status/{excavator_id}')
        return self._replace_string_placeholders(topic_template)
