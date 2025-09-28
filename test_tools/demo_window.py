import tkinter as tk
from tkinter import ttk
import time
import threading
import queue

class ControlPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("模拟操作台")

        # 创建控制信号界面
        self.control_frame = ttk.LabelFrame(self.root, text="模拟操作台", padding="70")
        self.control_frame.grid(row=0, column=40, padx=10, pady=10)

        # 创建最大值和最小值输入框（8组）以及布尔开关
        self.max_min_switches = []  # 存储布尔开关
        self.update_queue = {}  # 存储数据更新的字典
        self.previous_update_queue = {}  # 上次的更新字典
        row = 0  # 初始行号
        for i in range(8):  # 修改为 8 对
            self.create_switch(f"Send Data {i+1}", row)  # 创建布尔按钮
            row += 1  # 布尔按钮后面留空一行
            self.create_value_input(f"Action{i+1}_Max", 0, 255, 127, row)  # 创建Max Value输入框
            row += 1
            self.create_value_input(f"Action{i+1}_Min", 0, 255, 0, row)  # 创建Min Value输入框
            row += 2  # 留空一行作为间隔

        # 创建10个布尔值按钮
        self.bool_buttons = []
        for i in range(21):
            if i < 8:
                self.create_bool_button(f"power{i+1}", i+15)
            elif i < 9:
                continue 
            elif i < 14:
                self.create_bool_button(f"power{i}", i+15)
            elif i < 15:
                continue 
            elif i < 17:
                self.create_bool_button(f"power{i+1}", i+15)
            elif i < 18:
                continue 
            else:
                self.create_bool_button(f"aux{i-17}", i+15)

        # 创建更新按钮
        self.create_update_button()

        # 启动一个独立线程，每秒输出布尔按钮的状态并添加心跳标志
        self.bool_thread = threading.Thread(target=self.output_bool_status)
        self.bool_thread.daemon = True  # 确保主程序退出时，线程也会退出
        self.bool_thread.start()

        # 启动心跳线程，每隔1秒输出心跳值
        self.heartbeat_thread = threading.Thread(target=self.generate_heartbeat)
        self.heartbeat_thread.daemon = True
        self.heartbeat_value = 0  # 初始心跳值
        self.heartbeat_thread.start()

    def create_value_input(self, label, min_val, max_val, default_val, row):
        """创建文本框和标签"""
        bool_var = tk.BooleanVar()

        # 创建文本框和标签并插入默认值
        label_widget = ttk.Label(self.control_frame, text=label)
        label_widget.grid(row=row, column=1, sticky="w", padx=5)

        entry_widget = ttk.Entry(self.control_frame)
        entry_widget.insert(0, str(default_val))  # 设置默认值
        entry_widget.grid(row=row, column=2, pady=5)

        # 将每个输入框和开关作为属性存储在实例中
        setattr(self, f"{label.lower().replace(' ', '_').replace('(', '').replace(')', '')}_entry", entry_widget)

    def create_switch(self, label, row):
        """创建布尔开关按钮"""
        bool_var = tk.BooleanVar()
        switch = ttk.Checkbutton(self.control_frame, text=label, variable=bool_var)
        switch.grid(row=row, column=1, columnspan=2, pady=5)
        self.max_min_switches.append(bool_var)  # 将布尔值存储在列表中

    def create_bool_button(self, label, index):
        """创建布尔值按钮"""
        bool_var = tk.BooleanVar()
        button = ttk.Checkbutton(self.control_frame, text=label, variable=bool_var)
        button.grid(row=index-10, column=20, columnspan=2, pady=5)
        self.bool_buttons.append(bool_var)

    def create_update_button(self):
        """创建更新按钮"""
        self.update_button = ttk.Button(self.control_frame, text="Update", command=self.update)
        self.update_button.grid(row=30, column=20, columnspan=2, pady=10)

    def update(self):
        """更新按钮点击事件"""
        try:
            # 获取用户输入的最大值、最小值
            max_vals = [int(getattr(self, f"action{i+1}_max_entry").get()) for i in range(8)]  # 8个线性值
            min_vals = [int(getattr(self, f"action{i+1}_min_entry").get()) for i in range(8)]  # 8个线性值

            # 将信号更新操作移到一个新的线程中，避免阻塞主线程
            update_thread = threading.Thread(target=self.send_control_signals, args=(max_vals, min_vals))
            update_thread.daemon = True
            update_thread.start()

        except ValueError:
            print("无效的输入。请输入有效的数字。")


    def send_signal(self, i, max_val, min_val, bool_var):
        """在子线程中发送控制信号"""
        if bool_var.get():  # 如果布尔值为 True，则发送该组最大值到最小值的数据
            # 进行步退，并确保最后输出值是0
            for val in range(max_val, min_val-1, -5):
                # 更新数据到 update_queue 字典
                self.update_queue[f"action{i+1}"] = val
                self.update_queue[f"action_heartbeat"] = self.heartbeat_value
                # 检查字典变化并删除不需要的键（仅针对线性值）
                self.check_and_print_update_queue()
                time.sleep(0.2)  # 心跳每秒输出一次
        
            # 在循环结束后，确保最后的值是0
            if self.update_queue.get(f"action{i+1}") != 0:
                self.update_queue[f"action{i+1}"] = 0
                self.check_and_print_update_queue()  # 确保更新输出

    def send_control_signals(self, max_vals, min_vals):
        """在新的线程中执行控制信号的发送并更新update_queue"""
        threads = []
        for i, (max_val, min_val, bool_var) in enumerate(zip(max_vals, min_vals, self.max_min_switches)):
            # 创建线程并启动
            thread = threading.Thread(target=self.send_signal, args=(i, max_val, min_val, bool_var))
            threads.append(thread)
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join()


    def output_bool_status(self):
        """每秒输出一次所有布尔值按钮的状态并加上心跳值"""
        while True:
            bool_status = []
            for i, bool_var in enumerate(self.bool_buttons):
                if i < 13:
                    bool_status.append(f"power{i+1} {'True' if bool_var.get() else 'False'}")
                    self.update_queue[f"power{i+1}"] = 'True' if bool_var.get() else 'False'
                elif i < 15:
                    bool_status.append(f"power{i+3} {'True' if bool_var.get() else 'False'}")
                    self.update_queue[f"power{i+3}"] = 'True' if bool_var.get() else 'False'
                else:
                    bool_status.append(f"aux{i-14} {'1' if bool_var.get() else '0'}")
                    self.update_queue[f"aux{i-14}"] = '1' if bool_var.get() else '0'
            
            time.sleep(0.1)  # 每秒输出一次布尔值状态

    def check_and_print_update_queue(self):
        """检查 update_queue 是否发生变化，如果有变化则打印，并摧毁相同键（仅针对线性值）"""
        for key in list(self.update_queue.keys()):
            # 仅针对线性数据检查（max、min 值），布尔值每次都更新
            if key.startswith('action'):  # 如果是线性数据的key
                # 如果当前字典中的值与上次的值相同，则摧毁该键
                if self.update_queue[key] == 0:
                    del self.update_queue[key]

    def generate_heartbeat(self):
        """生成心跳值并循环"""
        while True:
            self.heartbeat_value = (self.heartbeat_value + 1) % 256  # 心跳值循环
            time.sleep(1)  # 每秒更新一次心跳值

    def getout_update_queue(self):
        """获取 update_queue 字典"""
        #print("获取 update_queue 字典: ", self.update_queue.copy())
        return self.update_queue.copy()