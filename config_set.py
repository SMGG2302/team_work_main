import json
import re
import sys
import sys
import logging
from pathlib import Path
from logger_setup import get_logger # 保留导入
from config_manager import ConfigManager

class ConfigSet:
    @staticmethod
    def is_valid_ip(ip):
        # 简单IP校验
        return re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip) is not None or re.match(r"^[a-zA-Z]+(\.[a-zA-Z])+",ip) is not None

    @staticmethod
    def is_valid_serial(serial):
        return serial.isdigit()

    @staticmethod
    def prompt_and_update_config(config_path):
        """
        设置并且更新broker和设备序号
        """
        # 获取logger实例
        logger = get_logger()
        # 加载配置文件
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            configured = config.get("configured", False)
            logger.info("当前配置：configured=%s", configured)
        if configured:
            logger.info("broker与device配置已存在，进入调试配置流程。")
        else:       
            try:
                # 循环获取用户输入
                while True:
                    broker = input("请输入MQTT broker地址（如 192.168.1.100）：")
                    if ConfigSet.is_valid_ip(broker):
                        config["mqtt"]["broker"] = broker
                        config["mqtt"]["simulation_broker"] = broker
                        break
                    else:
                        print("输入格式有误，请重新输入。")
                        continue
                # 双while防止重新输入broker
                while True:
                    device_serial = input("请输入设备序号（数字）：")
                    if ConfigSet.is_valid_serial(device_serial):
                        config["mqtt"]["device_config"]["device_serial"] = device_serial
                        break
                    else:
                        print("输入格式有误，请重新输入。")
                        continue
                # 更新配置
                config["configured"] = True
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                logger.info("配置已更新，broker地址为：%s，设备序号为：%s，将进入调试配置流程。", broker, device_serial)
                
                # 重新加载配置
                config_manager = ConfigManager()
                config_manager.reload_config()
            # 捕获Ctrl+C和EOF异常, 防止卡死
            except (KeyboardInterrupt, EOFError):
                logger.error("\n配置输入被中断，程序退出。")
                sys.exit(0)
    @staticmethod
    def test_config_set(config_path):
        """
        若处于非开机自启状态，则设置调试模式的相关配置
        若处于开机自启状态，则不允许重新配置，跳过
        """
        # 获取logger实例
        logger = get_logger()
        # 防止卡死
        try:
            # 加载配置文件
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            # 判断是否处于调试模式
            if ConfigSet.is_debug_mode():
                logger.info("当前为非开机自启模式，允许重新配置。")
                while True:
                    answer = input("是否应用默认测试配置？(y/n)")
                    if answer == "y":
                        # 使用默认测试配置
                        config["simulation_mode"] = True
                        config["can"]["send_interval_ms"] = 1000
                        config["logging"]["level"] = "DEBUG"
                        config["system"]["heartbeat_detection_interval_sec"] = 1
                        # 写入配置
                        with open(config_path, "w", encoding="utf-8") as f:
                            json.dump(config, f, ensure_ascii=False, indent=2)
                        logger.info("配置已更新，程序即将启动。")
                        
                        # 重新加载配置
                        config_manager = ConfigManager()
                        config_manager.reload_config()
                        
                        # 更新日志级别
                        log_level = getattr(logging, config["logging"]["level"])
                        logging.getLogger("ExcavatorController").setLevel(log_level)
                        break
                    elif answer == "n":
                        logger.info("取消自动配置，将手动配置。")
                        # 手动配置仿真模式
                        while True:
                            simulation_mode = input("是否为仿真模式（y/n）：")
                            if simulation_mode == "y":
                                config["simulation_mode"] = True
                                break
                            elif simulation_mode == "n":
                                config["simulation_mode"] = False
                                break
                            else:
                                print("输入格式有误，请重新输入。")
                                continue
                        # 手动配置CAN发送间隔
                        while True:
                            send_interval = input("请输入CAN发送间隔（毫秒，建议1000）：")
                            if send_interval.isdigit() and int(send_interval) > 0:
                                config["can"]["send_interval_ms"] = int(send_interval)
                                break
                            else:
                                print("输入格式有误，请重新输入。")
                                continue
                        # 手动配置日志等级
                        log_level = "DEBUG"  # 默认值
                        while True:
                            log_level = input("请输入日志等级（DEBUG, INFO, WARNING, ERROR, CRITICAL，建议DEBUG）：").upper()
                            if log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
                                config["logging"]["level"] = log_level
                                break
                            else:
                                print("输入格式有误，请重新输入。")
                                continue
                        # 手动配置心跳检测间隔
                        while True:
                            heartbeat_interval = input("请输入心跳检测间隔（秒，建议1）：")
                            try:
                                interval_value = float(heartbeat_interval)
                                if interval_value >= 0.1:
                                    config["system"]["heartbeat_detection_interval_sec"] = interval_value
                                    break
                                else:
                                    print("输入值必须大于等于0.1，请重新输入。")
                                    continue
                            # 若非合理数字则会抛出异常
                            except ValueError:
                                print("输入格式有误，请输入一个有效的数字。")
                                continue
                        # 写入配置
                        with open(config_path, "w", encoding="utf-8") as f:
                            json.dump(config, f, ensure_ascii=False, indent=2)
                        logger.info("配置已更新，程序即将启动。")
                        
                        # 重新加载配置
                        config_manager = ConfigManager()
                        config_manager.reload_config()
                        
                        # 更新日志级别
                        log_level_value = getattr(logging, log_level)
                        logging.getLogger("ExcavatorController").setLevel(log_level_value)
                        break
                    else:
                        print("输入格式有误，请重新输入。")
            else:
                logger.info("当前为开机自启模式，使用上机配置。")
                # 使用默认测试配置
                config["simulation_mode"] = False
                config["can"]["send_interval_ms"] = 100
                config["logging"]["level"] = "WARNING"
                config["system"]['mqtt_timeouts']["heartbeat_detection_interval_sec"] = 0.1
                # 写入配置
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                logger.info("配置已更新，程序即将启动。")
                
                # 重新加载配置
                config_manager = ConfigManager()
                config_manager.reload_config()
                
                # 更新日志级别
                log_level = getattr(logging, config["logging"]["level"])
                logging.getLogger("ExcavatorController").setLevel(log_level)
        except (KeyboardInterrupt, EOFError):
            logger.error("\n配置输入被中断，程序退出。")
            sys.exit(0)
    
    @staticmethod
    def is_debug_mode():
        """
        检测是否处于调试模式
        如果 auto_start.sh 文件存在，则为正常运行模式（非调试）
        如果 auto_start.sh 文件不存在，则为调试模式
        """
        # 获取程序所在目录的父目录（因为auto_start.sh与项目文件夹同级）
        script_dir = Path(__file__).parent.absolute().parent
        auto_start_file = script_dir / "auto_start.sh"
        
        # 如果文件存在，说明是正常开机自启模式
        # 如果文件不存在，说明是调试模式
        return not auto_start_file.exists()
    
