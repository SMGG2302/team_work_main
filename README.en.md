# team_work_main

Python communication controller for remotely operated construction machinery. It translates MQTT control messages into CAN frames, collects device and sensor status, and publishes status through internal and external MQTT topics.

[中文完整文档](README.md) · [Original Gitee repository](https://gitee.com/SMGG21/team_work_main)

## Components

- `main.py`: configuration, worker startup, monitoring and shutdown.
- `mqtt_handler.py`: MQTT communication and upstream heartbeat monitoring.
- `can_handler.py`: Linux SocketCAN access and simulated CAN traffic.
- `translator.py`, `protocol.json`: signal encoding, decoding and protocol definitions.
- `processors.py`, `protocol_processor.py`: control processing, status aggregation and field mapping.
- `config.json`, `config_manager.py`, `config_set.py`: runtime configuration and helpers.
- `logger_setup.py`: console and rotating file logs.
- `test_tools/`: a Tkinter control panel and MQTT/heartbeat simulator.
- `main_screen/`: integration modules for an external screen application, not a standalone UI.

## Setup

Use Python 3 and a reachable MQTT broker. No dependency lockfile or validated Python version matrix is included.

```bash
git clone https://github.com/SMGG2302/team_work_main.git
cd team_work_main
python -m venv .venv
```

Activate `.venv` with `.\.venv\Scripts\Activate.ps1` in Windows PowerShell or `source .venv/bin/activate` on Linux, then install:

```bash
python -m pip install "paho-mqtt>=1.6,<2" python-can
```

The Paho range matches the existing legacy callback signatures; it is not an original project lock. The GUI simulator also needs Tkinter and a desktop display. Check Tkinter with `python -m tkinter`.

## Simulation

1. Prepare an MQTT broker and configure its address and authentication in `config.json`.
2. Keep `simulation_mode` set to `true`; this mode uses `mqtt.simulation_broker`. CAN is simulated, but MQTT still requires a real broker.
3. Align the settings inside `run_simulator()` in `test_tools/simulated_main_screen.py` with the controller. The simulator has its own hardcoded settings and does not read the root configuration. Its default control prefix ends in `...762/ctrl/`, whereas the controller currently expands to `LSVHJ133022221761/ctrl/`. Correct this mismatch before testing and check both accounts against the broker.
4. Run these commands from the repository root in separate activated terminals:

```bash
python main.py
```

```bash
python test_tools/simulated_main_screen.py
```

Check MQTT connection messages, heartbeat state and `[SIMULATION]` CAN output in the logs. The default log file is `excavator_controller.log`. Periodic control transmission requires both an MQTT connection and a healthy upstream heartbeat. Stop the controller with Ctrl+C and close the test panel to end the simulator.

## Configuration and hardware

`config.json` selects the mode, broker, device identifiers, topic templates, CAN interface, timing, queues and logging. `protocol.json` defines signal locations, CAN IDs, initial values and mapping rules. Device placeholders are expanded by `ConfigManager`.

Hardware mode (`simulation_mode: false`) currently uses Linux SocketCAN. Configure and enable the OS CAN interface, then match its name and bitrate to the device and configuration; the JSON bitrate alone does not configure the OS interface. Verify protocol and heartbeat behavior on a test bench before connecting actuators. Hardware operation has not been validated as part of the repository migration.

The `main_screen/` modules additionally import `PySide6`, `loguru`, `orjson`, `pyserial` and external `app.core.config` / `app.common.serial_connect.crc16` modules absent from this repository. They must be integrated into their screen application. `test_tools/` contains manual integration tools, not an automated test suite. See the Chinese README for the full configuration table and troubleshooting guide.

## Access and contributions

The GitHub repository is publicly readable. Visitors can view, clone and fork it, but cannot push or merge changes into this repository without write access. Suggestions can be submitted through issues or pull requests for maintainer review.

No open-source license is currently included. Public visibility does not itself grant unrestricted redistribution or commercial-use rights. Original Gitee history and branches are retained; documentation improvements are recorded as a separate commit.
