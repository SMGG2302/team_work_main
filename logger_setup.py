import logging
import logging.handlers
import sys
import os
import threading

_log_setup_lock = threading.Lock()
_logger_initialized = False
_log_file_path = None # Store the configured log file path

# 简化 get_logger，它只返回实例，不进行配置
# 配置将在 setup_logger 中显式完成
def get_logger():
    """获取日志记录器实例 (此时可能未配置)"""
    return logging.getLogger("ExcavatorController")

def setup_logger(config):
    """根据配置设置日志记录器"""
    global _logger_initialized, _log_file_path
    logger = get_logger() # 获取实例

    with _log_setup_lock:
        # 防止重复初始化，或在 fork 后重新添加文件处理器
        if _logger_initialized:
            has_file_handler = any(isinstance(h, logging.FileHandler) for h in logger.handlers)
            if _log_file_path and not has_file_handler:
                logger.warning("Logger 已初始化但文件处理器丢失，尝试重新添加。")
                # 需要 formatter 实例
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(threadName)s] - %(filename)s:%(lineno)d - %(message)s')
                _add_file_handler(logger, config, formatter) # 重新添加
            # logger.debug("Logger 已初始化，跳过设置。") # 可以取消注释此行进行调试
            return logger
        
        # print(f"断点-- 日志所有配置原始数据: {config}")
        # log_config = config.get('logging', {})
        log_config = config # 调用setup_logger(config)时，传过来的直接就是专门提取过的日志配置，不包含非日志的配置。无需调用config.get('logging', {})提取  
        # print(f"断点-- 日志所有配置处理后数据: {log_config}")

        log_level_str = log_config.get('level', 'INFO').upper()
        # print(f"断点-- 日志级别: {log_level_str}")
        log_level = getattr(logging, log_level_str, logging.INFO)
        log_file_name = log_config.get('file') # 基础文件名
        # print(f"断点-- 日志相对路径: {log_file_name}")

        # --- 计算日志文件绝对路径 ---
        if log_file_name:
            if os.path.isabs(log_file_name):
                _log_file_path = log_file_name
            else:
                try:
                    # 优先使用 __file__ 确定脚本目录
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    _log_file_path = os.path.join(script_dir, log_file_name)
                except NameError:
                    # __file__ 不可用时，回退到当前工作目录
                    print(f"警告：无法确定脚本目录 (__file__ 不可用)，将使用当前工作目录 '{os.getcwd()}' 处理相对日志文件路径。", file=sys.stderr)
                    _log_file_path = os.path.abspath(log_file_name) # 基于当前工作目录
            logger.debug(f"计算出的日志文件绝对路径: {_log_file_path}") # 添加调试日志
        else:
            _log_file_path = None
            logger.debug("配置文件中未指定日志文件名。")

        # 获取或创建记录器 (再次获取确保是同一个)
        logger = logging.getLogger("ExcavatorController")
        # 清除现有处理器 (非常重要，防止 basicConfig 或重复调用干扰)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        # 设置传播，确保不会传递到 root logger (除非需要)
        logger.propagate = False

        # 创建 Formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(threadName)s] - %(filename)s:%(lineno)d - %(message)s')

        # 明确记录将要设置的级别
        logger.debug(f"从配置读取日志级别字符串: '{log_level_str}', 解析为 logging 级别: {log_level}")
        logger.setLevel(log_level)

        # --- 控制台处理器 ---
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        # --- 文件处理器 ---
        _add_file_handler(logger, config, formatter) # 传递 formatter

        logger.info(f"日志记录器初始化完成，级别设置为 {log_level_str} ({log_level})") # 同时显示字符串和数字级别
        _logger_initialized = True
        return logger

def _add_file_handler(logger, config, formatter):
    """辅助函数：添加文件日志处理器"""
    # log_file_path 来自全局变量 _log_file_path
    global _log_file_path
    # log_config = config.get('logging', {}) # 重新获取日志部分配置
    # print(f"断点-- 日志config在_add_file_handler角落: {config}")
    log_config = config # 同样的问题，直接传入的就是独属于log的配置，无需再次提取
    log_file = _log_file_path # 使用已计算好的完整路径

    max_bytes = log_config.get('max_bytes', 10*1024*1024)
    backup_count = log_config.get('backup_count', 5)

    if log_file:
        try:
            # 确保目录存在
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                # 使用 logger 可能会有问题（如果文件处理器还未成功添加）
                print(f"INFO: 日志目录不存在，尝试创建: {log_dir}", file=sys.stderr)
                try:
                    os.makedirs(log_dir, exist_ok=True)
                except OSError as e:
                     print(f"ERROR: 创建日志目录失败: {e}", file=sys.stderr)
                     # 此时 logger 可能无法写入文件，依赖控制台
                     logger.error(f"创建日志目录 '{log_dir}' 失败: {e}")
                     return # 无法继续

            # 检查目录写权限
            check_path = log_dir if log_dir else os.path.dirname(log_file) # 如果log_file在根目录，log_dir为空
            if not check_path: # 如果 log_file 只是文件名，检查当前目录
                 check_path = '.'
            if not os.access(check_path, os.W_OK):
                logger.error(f"没有写入日志目录 '{check_path}' 的权限。文件日志将不可用。")
                return

            # 创建文件处理器
            fh = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
            )
            fh.setFormatter(formatter) # 使用传入的 formatter
            logger.addHandler(fh)
            # 这个消息现在会同时输出到控制台和（刚添加成功的）文件
            logger.info(f"文件日志处理器已添加，将记录到: {log_file}")

        except PermissionError as e:
            logger.error(f"设置文件日志处理器失败：无法写入文件或目录 (权限错误) '{log_file}' - {e}", exc_info=False)
        except Exception as e:
            logger.error(f"设置文件日志处理器时发生未知错误: {e}", exc_info=True)
    else:
        # 只有在 _log_file_path 确实为 None 或空时才打印这个
        logger.info("未配置有效的日志文件路径，仅使用控制台日志。")
        logger.info(f"日志文件路径:{log_file}")

