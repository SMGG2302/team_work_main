# team_work_main

工程机械远程控制通信主程序，使用 Python 实现 MQTT 控制指令与 CAN 报文之间的转换，以及设备状态的采集、合并和回传。仓库同时包含大屏通信集成模块和用于联调的 Tkinter 控制面板。

[English](README.en.md) · [Gitee 源仓库](https://gitee.com/SMGG21/team_work_main) · [配套测试软件](https://github.com/SMGG2302/simulation_tools)

## 功能与数据流

- **控制下行**：订阅 MQTT 控制主题，按协议更新信号状态，周期性组装并发送 CAN 帧。
- **状态上行**：解析 CAN 状态，合并 MQTT 传感器数据，按对内、对外协议发布状态消息。
- **协议配置**：通过 `protocol.json` 定义 CAN ID、字节/位位置、信号类型、初始值及数据映射。
- **心跳监测**：监测上游大屏心跳；控制线程在心跳异常时重置信号状态，周期发送受 MQTT 连接和心跳状态约束。
- **仿真联调**：按配置生成模拟 CAN 接收数据，并在日志中记录待发送 CAN 帧，无需 CAN 硬件；MQTT 仍需实际 Broker。
- **运行管理**：线程安全队列、连接重试、滚动日志，以及 Ctrl+C 关闭流程。

```text
大屏 / 测试面板 → MQTT → MqttHandler → 控制队列 → ControlProcessor
                                                     ↓ Translator 编码
                                                 CanHandler → CAN 设备

CAN 设备 / 模拟报文 → CanHandler → 状态队列 → StatusProcessor
                                               ↑ MQTT 传感器数据
                                               ↓ 解码、采集与合并
                                         MQTT 对内 / 对外状态主题
```

## 目录说明

| 路径 | 用途 |
| --- | --- |
| `main.py` | 主入口，初始化通信组件与工作线程，处理退出 |
| `config.json` / `config_manager.py` | 运行配置、校验及设备占位符替换 |
| `protocol.json` / `translator.py` | 信号协议、MQTT/CAN 编解码与信号状态 |
| `mqtt_handler.py` | MQTT 连接、订阅、发布及心跳检测 |
| `can_handler.py` | Linux SocketCAN 通信及模拟收发 |
| `processors.py` | 控制处理、状态处理、数据采集和合并 |
| `protocol_processor.py` | 协议字段映射、转换和校验 |
| `config_set.py` | 配置修改辅助类 |
| `logger_setup.py` | 控制台日志与滚动文件日志 |
| `test_tools/` | Tkinter 控制面板、MQTT 控制与心跳模拟器 |
| `main_screen/` | 大屏 MQTT 与串口集成模块，依赖外部 `app` 工程 |

## 环境与安装

需要 Python 3、Git，以及可连接的 MQTT Broker。仓库未提供依赖锁文件或已验证的 Python 版本矩阵。

```bash
git clone https://github.com/SMGG2302/team_work_main.git
cd team_work_main
python -m venv .venv
```

激活虚拟环境：

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux
source .venv/bin/activate
```

安装主程序依赖：

```bash
python -m pip install "paho-mqtt>=1.6,<2" python-can
```

上述 Paho 范围用于匹配当前代码的旧版回调接口，并非项目原有锁定版本。测试面板还需要 Tkinter，可用 `python -m tkinter` 检查；部分 Linux 发行版需另行安装系统 Tkinter 包。

`main_screen/` 的额外依赖包括 `PySide6`、`loguru`、`orjson`、`pyserial`，以及本仓库未包含的 `app.core.config` 和 `app.common.serial_connect.crc16`。这两个模块需集成回相应大屏工程，单独安装第三方包不足以独立运行完整大屏。

## 配置

主程序从自身目录读取 `config.json`，再根据 `protocol_file` 读取协议。请从仓库根目录启动，便于定位日志和测试工具。

| 配置项 | 作用 / 当前默认值 |
| --- | --- |
| `simulation_mode` | `true`：模拟 CAN；`false`：真实 SocketCAN |
| `mqtt.simulation_broker` / `mqtt.broker` | 分别用于仿真/上机模式，当前均为 `127.0.0.1` |
| `mqtt.port` | Broker 端口，默认 `1883` |
| `mqtt.username` / `mqtt.password` | 需与实际 Broker 的认证配置匹配 |
| `mqtt.device_config` | 设备序号与设备 ID 模板 |
| `mqtt.control_topic_base` | `{excavator_id}/ctrl/`，后接协议中的信号名 |
| `mqtt.safe_topic` | 心跳主题，默认 `touch_screen/heartbeat` |
| `mqtt.status_topics` | 对内和对外状态发布主题 |
| `can.interface` / `can.bitrate` | 默认 `can0` / `250000` bit/s |
| `can.send_interval_ms` | 控制帧发送周期，默认 `1000` ms |
| `can.simulation_receive_messages` | 模拟接收的 CAN ID、十六进制数据与周期 |
| `logging` | 日志级别、文件、大小和备份数 |
| `system` | 队列容量、超时、监控周期和重试间隔 |
| `protocol_file` | 默认 `protocol.json` |

配置中的 `{device_serial}` 和 `{excavator_id}` 由 `ConfigManager` 展开。当前设备序号为 `1`，主程序控制主题前缀为 `LSVHJ133022221761/ctrl/`。

## 仿真启动

1. 准备 MQTT Broker，核对地址、端口、账号和主题访问权限。
2. 保持 `config.json` 中 `simulation_mode` 为 `true`，配置 `mqtt.simulation_broker`。
3. 编辑 `test_tools/simulated_main_screen.py` 中 `run_simulator()` 的配置，使 Broker、认证和控制主题与主程序一致。测试工具目前硬编码的控制前缀以 `...762/ctrl/` 结尾，和主程序的 `...761/ctrl/` **不一致，必须先对齐**。测试工具的账号也单独配置，不会自动读取根目录配置。
4. 在已激活虚拟环境的两个终端中分别运行：

```bash
# 终端一：通信主程序
python main.py
```

```bash
# 终端二：大屏模拟器与控制面板
python test_tools/simulated_main_screen.py
```

检查 MQTT 连接、控制主题订阅、心跳状态，以及主程序中的 `[SIMULATION]` CAN 发送日志。默认日志文件为 `excavator_controller.log`。测试面板发送控制信号并维持递增心跳；单独启动主程序而没有正常心跳时，不应以“未发送控制帧”判断启动失败。

按 Ctrl+C 停止主程序；关闭测试面板结束模拟器。`test_tools/` 是手动联调工具，不是自动化测试套件。

## 真实 CAN 环境

当前真实 CAN 后端固定为 Linux `socketcan`，需要可用的 CAN 适配器、驱动和已配置好的网络接口。将 `simulation_mode` 设为 `false`，核对 `mqtt.broker`、`can.interface` 和设备要求的波特率。接口须在操作系统中配置并启用，不能只依靠 JSON 中的 `bitrate` 字段完成系统配置。

协议中的 CAN ID、信号范围、初始值和心跳行为须与目标设备匹配；先完成仿真和台架核对，再连接实际执行机构。本 README 未声称完成实机验证或功能安全认证。

## 常见问题

| 现象 | 排查方向 |
| --- | --- |
| 无法连接 MQTT | Broker 是否运行；地址、端口、账号、网络和主题权限是否正确 |
| MQTT 已连接但没有控制响应 | 控制主题是否一致；心跳是否持续变化；信号名是否存在于协议 |
| CAN 初始化反复重试 | 是否使用 Linux；SocketCAN 接口、驱动、波特率与权限是否正确 |
| 找不到 `app` 模块 | `main_screen/` 依赖外部大屏工程，不能作为本仓库独立入口运行 |
| MQTT 回调参数错误 | 检查 Paho 版本；安装说明采用与现有回调签名匹配的 1.x 范围 |
| GUI 无法打开 | 检查 Tkinter 和桌面显示环境；无桌面环境不适合直接运行控制面板 |

## 仓库访问与贡献

本 GitHub 仓库公开可读，访客可以查看、下载、克隆和 Fork，但未获写权限的访客不能直接推送、修改或合并本仓库代码。如需提出改进，可通过 Issue 或 Pull Request，由维护者审阅。

仓库目前未附带开源许可证；公开可读不等于已授予任意再分发或商业使用许可。原有 Gitee 提交历史和分支在迁移中保留，README 补充作为独立提交记录。
