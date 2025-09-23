#!/usr/bin/env python3
"""
协议数据处理工具类
提供通用的数据映射、转换和验证功能
"""

from logger_setup import get_logger

class ProtocolDataProcessor:
    """协议数据处理器 - 提供通用的数据处理功能"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.logger = get_logger()
    
    def map_data_by_protocol(self, source_data, mapping_config, target_prefix="status"):
        """
        根据协议配置映射数据
        
        Args:
            source_data: 源数据字典
            mapping_config: 映射配置
            target_prefix: 目标字段前缀
            
        Returns:
            映射后的数据字典
        """
        mapped_data = {}
        
        if not mapping_config or not source_data:
            self.logger.debug("映射配置或源数据为空，返回空字典")
            return mapped_data
        
        # 处理新的字段映射格式
        fields_config = mapping_config.get('fields', mapping_config)
        
        # 遍历映射配置
        for target_key, field_config in fields_config.items():
            if not isinstance(field_config, dict):
                continue
                
            source = field_config.get('source', '')
            field = field_config.get('field', '')
            data_type = field_config.get('type', 'string')
            default_value = field_config.get('default_value')
            
            # 提取并转换数据
            value = self._extract_and_convert_value(
                source_data, source, field, data_type, default_value
            )
            mapped_data[target_key] = value
            
        self.logger.debug(f"数据映射完成: {len(mapped_data)} 个字段")
        return mapped_data
    
    def map_class_data_by_protocol(self, source_data, class_config):
        """
        根据类别配置映射数据（用于内部协议）
        
        Args:
            source_data: 源数据字典
            class_config: 类别配置
            
        Returns:
            映射后的数据字典
        """
        mapped_data = {}
        
        if not class_config or not source_data:
            self.logger.debug("类别配置或源数据为空，返回空字典")
            return mapped_data
        
        field_mapping = class_config.get('field_mapping', {})
        
        # 遍历字段映射配置
        for target_key, field_config in field_mapping.items():
            if not isinstance(field_config, dict):
                continue
                
            source_field = field_config.get('source_field', '')
            data_type = field_config.get('type', 'string')
            default_value = field_config.get('default_value')
            
            # 提取值（支持嵌套字段如 rtk_info.longitude）
            value = self._extract_nested_field_value(
                source_data, source_field, data_type, default_value
            )
            mapped_data[target_key] = value
            
        self.logger.debug(f"类别数据映射完成: {len(mapped_data)} 个字段")
        return mapped_data
    
    def _extract_nested_field_value(self, source_data, field_path, data_type, default_value=None):
        """
        提取嵌套字段的值
        
        Args:
            source_data: 源数据
            field_path: 字段路径（如 rtk_info.longitude）
            data_type: 数据类型
            default_value: 默认值
            
        Returns:
            提取的值
        """
        if not source_data or not field_path:
            return default_value if default_value is not None else self._get_default_value_by_type(data_type)
        
        # 处理嵌套字段路径
        current_data = source_data
        field_parts = field_path.split('.')
        
        try:
            for part in field_parts:
                if isinstance(current_data, dict) and part in current_data:
                    current_data = current_data[part]
                else:
                    # 字段不存在，使用默认值
                    return default_value if default_value is not None else self._get_default_value_by_type(data_type)
            
            # 找到值，进行类型转换
            return self._convert_value_type(current_data, data_type, default_value)
            
        except (KeyError, TypeError, AttributeError):
            return default_value if default_value is not None else self._get_default_value_by_type(data_type)
    
    def _extract_and_convert_value(self, source_data, source, field, data_type, default_value=None):
        """提取并转换数据值"""
        # 特殊处理device_config数据源
        if source == 'device_config':
            # 从config_manager获取设备配置
            device_config = self.config_manager.get_device_config()
            if field in device_config:
                raw_value = device_config[field]
            else:
                raw_value = None
        # 获取源数据
        elif source and source in source_data:
            nested_data = source_data[source]
            if isinstance(nested_data, dict) and field in nested_data:
                raw_value = nested_data[field]
            else:
                raw_value = None
        else:
            raw_value = None
        
        # 数据类型转换
        return self._convert_value_type(raw_value, data_type, default_value)
    
    def _convert_value_type(self, value, data_type, default_value=None):
        """数据类型转换"""
        if value is None:
            return default_value if default_value is not None else self._get_default_value_by_type(data_type)
        
        try:
            if data_type == 'float':
                return float(value)
            elif data_type == 'int':
                return int(value)
            elif data_type == 'string':
                return str(value)
            elif data_type == 'bool':
                return bool(value)
            else:
                return value
        except (ValueError, TypeError) as e:
            self.logger.warning(f"类型转换失败: {value} -> {data_type}, 错误: {e}")
            return default_value if default_value is not None else self._get_default_value_by_type(data_type)
    
    def _get_default_value_by_type(self, data_type):
        """根据数据类型获取默认值"""
        defaults = {
            'float': 0.0,
            'int': 0,
            'string': '',
            'bool': False
        }
        return defaults.get(data_type, 0)
    
    def validate_protocol_data(self, data, required_fields=None):
        """
        验证协议数据的完整性
        
        Args:
            data: 要验证的数据
            required_fields: 必需字段列表
            
        Returns:
            (is_valid, missing_fields)
        """
        if required_fields is None:
            required_fields = []
        
        if not isinstance(data, dict):
            return False, ["数据不是字典格式"]
        
        missing_fields = []
        for field in required_fields:
            if field not in data:
                missing_fields.append(field)
        
        is_valid = len(missing_fields) == 0
        return is_valid, missing_fields
    
    def merge_with_defaults(self, data, defaults):
        """
        将数据与默认值合并
        
        Args:
            data: 实际数据
            defaults: 默认值字典
            
        Returns:
            合并后的数据
        """
        merged = defaults.copy() if defaults else {}
        if data and isinstance(data, dict):
            merged.update(data)
        return merged
    
    def format_status_data(self, raw_data, status_mapping):
        """
        格式化状态数据，将原始数据按状态字段映射
        
        Args:
            raw_data: 原始数据字典
            status_mapping: 状态映射配置 {status_key: source_key}
            
        Returns:
            格式化后的状态数据
        """
        formatted_data = {}
        
        if not raw_data or not status_mapping:
            return formatted_data
        
        raw_keys = list(raw_data.keys())
        
        for status_key, source_pattern in status_mapping.items():
            # 如果source_pattern是索引，使用索引获取值
            if isinstance(source_pattern, int) and source_pattern < len(raw_keys):
                source_key = raw_keys[source_pattern]
                formatted_data[status_key] = raw_data[source_key]
            # 如果source_pattern是字符串，直接获取值
            elif isinstance(source_pattern, str) and source_pattern in raw_data:
                formatted_data[status_key] = raw_data[source_pattern]
            else:
                # 使用默认值
                formatted_data[status_key] = self._get_default_value_by_type('float')
        
        return formatted_data