import time
import threading
import signal
import sys
import os
import queue
import logging # 保留导入 logging

# 导入自定义模块
from logger_setup import setup_logger, get_logger # 保留导入
from config_manager import ConfigManager, ConfigError
from translator import Translator # TranslationError 未在此文件使用，可移除
from mqtt_handler import MqttHandler
from can_handler import CanHandler
from processors import ControlProcessor, StatusProcessor

# 全局关闭事件
shutdown_event = threading.Event()

def signal_handler(sig, frame):
    """处理操作系统信号 (如 Ctrl+C)"""
    # 在函数内部获取 logger 实例
    logger = get_logger()
    if shutdown_event.is_set():
         print("\n强制退出...", file=sys.stderr)
         logger.warning("收到重复的关闭信号，执行强制退出！")
         os._exit(1)
    print("\n接收到关闭信号，正在优雅停止...", file=sys.stderr)
    logger.warning("接收到关闭信号 (%s)，正在启动优雅停止流程...", signal.Signals(sig).name)
    shutdown_event.set()

def main():
    logger = None # 初始化为 None
    try:
        # --- 1. 配置加载与日志初始化 (确保顺序正确) ---
        # 确定基础目录
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, 'config.json')
        print(f"断点-- 配置文件路径: {config_path}")

        # 初始化 ConfigManager (它内部会调用 get_logger，但此时 logger 还未配置)
        config_manager = ConfigManager(config_path=config_path)

        # **关键：在实例化其他组件之前，配置 Logger**
        # setup_logger 会获取配置并设置好 ExcavatorController logger
        # setup_logger 现在返回 logger 实例
        logger = setup_logger(config_manager.get_logging_config())

        # 现在 logger 实例已经配置好了

    except ConfigError as e:
        # 尝试使用 print，因为 logger 可能失败
        print(f"错误：配置加载失败 - {e}", file=sys.stderr)
        if logger: # 如果 logger 部分初始化成功，也记录一下
            logger.critical(f"配置加载失败: {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        print(f"错误：程序初始化失败 - {e}", file=sys.stderr)
        # 尝试用基础日志记录
        logging.basicConfig(level=logging.ERROR) # 备用 basicConfig
        logging.critical("程序初始化时发生严重错误", exc_info=True)
        if logger:
            logger.critical("程序初始化时发生严重错误", exc_info=True)
        sys.exit(1)

    # --- 程序启动日志 ---
    logger.info("--- 挖掘机远程控制器启动 ---")
    sim_mode_str = '仿真' if config_manager.is_simulation_mode() else '上机'
    logger.info(f"当前运行模式: {sim_mode_str}")

    # --- 2. 设置信号处理 ---
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.info("操作系统信号处理器已设置 (SIGINT, SIGTERM)。")

    # --- 3. 创建线程安全队列 ---
    queue_config = config_manager.get_queue_config()
    control_queue_size = queue_config.get('control_queue_maxsize', 200)
    status_queue_size = queue_config.get('status_queue_maxsize', 200)
    
    control_queue = queue.Queue(maxsize=control_queue_size)
    status_queue = queue.Queue(maxsize=status_queue_size)
    logger.info("消息队列已创建 (Control: %d, Status: %d)。", control_queue.maxsize, status_queue.maxsize)

    # --- 4. 初始化核心组件 (现在它们的 __init__ 会获取配置好的 logger) ---
    try:
        translator = Translator(config_manager)
        mqtt_handler = MqttHandler(config_manager, control_queue, shutdown_event)
        can_handler = CanHandler(config_manager, status_queue, shutdown_event)

        # ControlProcessor 需要 config_manager 来获取发送间隔
        control_processor = ControlProcessor(control_queue, translator, can_handler, config_manager, shutdown_event, mqtt_handler)
        status_processor = StatusProcessor(status_queue, translator, mqtt_handler, shutdown_event, control_processor, config_manager)
    except Exception as e:
        logger.critical(f"核心组件初始化失败: {e}", exc_info=True)
        sys.exit(1)

    # --- 5. 准备启动线程 ---
    service_threads = [] # 通信处理器 (MQTT, CAN)
    processor_threads = [control_processor, status_processor] # 数据处理

    try:
        logger.info("准备启动通信和处理线程...")

        # 启动 CAN 监听器
        if not can_handler.start_listening():
             logger.critical("CAN 监听器启动失败，程序退出。")
             shutdown_event.set()
             # 等待其他可能已启动的线程一点时间退出
             timeout_config = config_manager.get_timeout_config()
             startup_wait = timeout_config.get('startup_wait_sec', 0.5)
             time.sleep(startup_wait)
             sys.exit(1)
        if can_handler.listener_thread:
            service_threads.append(can_handler.listener_thread)
        if config_manager.is_simulation_mode() and can_handler.simulation_listener_threads:
            service_threads.extend(can_handler.simulation_listener_threads)

        # 启动 MQTT 处理器
        mqtt_handler.start()
        if mqtt_handler.thread:
            service_threads.append(mqtt_handler.thread)
        if mqtt_handler.heartbeat_thread:
            service_threads.append(mqtt_handler.heartbeat_thread)


        # 启动数据处理器线程
        for t in processor_threads:
            t.start()

        logger.info(".........所有服务和处理器线程已启动，程序运行中.........")
        logger.info(".........如果需要停止，可按 Ctrl+C 停止程序.........")

        # --- 6. 主线程监控与等待 ---
        while not shutdown_event.is_set():
            all_threads = service_threads + processor_threads
            alive_threads = [t for t in all_threads if t and t.is_alive()]

            if len(alive_threads) < len(all_threads):
                 dead_threads = [t.name for t in all_threads if t and not t.is_alive()]
                 logger.warning(f"检测到线程意外停止: {', '.join(dead_threads)}！正在触发程序关闭...")
                 shutdown_event.set()
                 break

            # 短暂休眠
            # time.sleep(1.5) # 原始间隔
            # 使用 wait 可以更快响应 shutdown_event
            monitoring_config = config_manager.get_monitoring_config()
            monitor_interval = monitoring_config.get('main_loop_monitor_interval_sec', 3.0)
            shutdown_event.wait(monitor_interval) # 等待指定秒数或直到 shutdown_event 被设置


    except KeyboardInterrupt:
        logger.info("捕获到 KeyboardInterrupt，开始关闭...")
        if not shutdown_event.is_set():
             shutdown_event.set()
    except Exception as e:
        logger.critical(f"主循环中发生未处理的异常: {e}", exc_info=True)
        if not shutdown_event.is_set():
             shutdown_event.set()
    finally:
        # --- 7. 执行优雅关闭 ---
        logger.warning("--- 开始执行关闭流程 ---")
        shutdown_event.set() # 确保事件已设置

        logger.info("正在停止 MQTT 处理器...")
        mqtt_handler.stop()
        logger.info("正在停止 CAN 处理器...")
        can_handler.stop()

        logger.info("等待所有工作线程退出...")
        main_thread = threading.current_thread()
        all_threads_to_join = service_threads + processor_threads
        
        timeout_config = config_manager.get_timeout_config()
        thread_join_timeout = timeout_config.get('thread_join_timeout_sec', 5.0)

        for t in all_threads_to_join:
             if t and t is not main_thread and t.is_alive():
                 logger.debug(f"等待线程: {t.name} (ID: {t.ident})...")
                 try:
                     t.join(timeout=thread_join_timeout)
                     if t.is_alive():
                          logger.warning(f"线程 {t.name} 未能在 {thread_join_timeout} 秒内正常停止。")
                     else:
                          logger.debug(f"线程 {t.name} 已成功停止。")
                 except Exception as e:
                      logger.error(f"等待线程 {t.name} 时出错: {e}")

        # 检查队列 (可选)
        # 此时生产者已停止，消费者应该也即将停止或已停止
        shutdown_wait = timeout_config.get('shutdown_wait_sec', 0.2)
        time.sleep(shutdown_wait) # 短暂等待消费者处理最后的消息
        if not control_queue.empty():
             logger.warning(f"程序关闭时，控制队列中仍有 {control_queue.qsize()} 条未处理的消息。")
        if not status_queue.empty():
             logger.warning(f"程序关闭时，状态队列中仍有 {status_queue.qsize()} 条未处理的消息。")


        logger.warning("--- 程序关闭完成 ---")
        sys.exit(0)

if __name__ == "__main__":
    # 添加版本检查 (可选)
    # if sys.version_info < (3, 7):
    #     print("错误：需要 Python 3.7 或更高版本。", file=sys.stderr)
    #     sys.exit(1)
    main()
