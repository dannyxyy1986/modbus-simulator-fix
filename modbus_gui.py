# modbus_gui.py
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import json
import random
import threading
import time
from datetime import datetime
import csv
import os
import pandas as pd
from openpyxl import Workbook, load_workbook
import socket
import struct
import math
import logging

# 导入之前创建的Modbus模拟器
from modbus_simulator_final import ModbusTCPSimulator, ModbusConfigManager

class ExtendedModbusTCPSimulator(ModbusTCPSimulator):
    """扩展的Modbus模拟器，添加监控功能"""
    
    def __init__(self, host='localhost', port=502, gui_callback=None):
        super().__init__(host, port)
        self.gui_callback = gui_callback  # GUI回调函数
        self.active_clients = {}  # 活跃客户端字典
        self.original_data_config = {}  # 存储原始配置
    
    def handle_client(self, client_socket, address):
        """处理客户端连接 - 扩展版本"""
        # 通知GUI有新的客户端连接
        if self.gui_callback:
            self.gui_callback('client_connect', address)
        
        # 记录活跃客户端
        self.active_clients[address] = {
            'socket': client_socket,
            'connect_time': datetime.now(),
            'request_count': 0
        }
        
        self.logger.info(f"客户端连接: {address}")
        
        try:
            while self.running:
                # 接收数据
                data = client_socket.recv(256)
                if not data:
                    break
                
                # 通知GUI收到请求
                if self.gui_callback:
                    self.gui_callback('request_received', address)
                
                self.logger.debug(f"收到原始数据: {len(data)} 字节: {data.hex()}")
                
                # 解析Modbus请求
                request = self.parse_modbus_request(data)
                if not request:
                    self.logger.warning("无法解析Modbus请求")
                    continue
                
                self.logger.info(f"收到Modbus请求: 功能码={request['function_code']}, 单元ID={request['unit_id']}")
                
                function_code = request['function_code']
                request_data = request['data']
                
                response = None
                
                if function_code in [1, 2, 3, 4]:  # 读操作
                    if len(request_data) >= 4:
                        try:
                            start_address, quantity = struct.unpack('>HH', request_data[:4])
                            self.logger.info(f"读请求: 起始地址={start_address}, 数量={quantity}")
                            
                            response_data = self.handle_read_request(request, start_address, quantity)
                            response = self.create_modbus_response(
                                request['transaction_id'],
                                request['unit_id'],
                                function_code,
                                response_data
                            )
                        except Exception as e:
                            self.logger.error(f"处理读请求错误: {e}")
                            # 返回服务器设备故障错误
                            response = struct.pack('>HHHBB', 
                                                 request['transaction_id'], 0, 3, 
                                                 request['unit_id'], function_code | 0x80)
                            response += struct.pack('>B', 0x04)  # 服务器设备故障
                    else:
                        self.logger.error("请求数据长度不足")
                        # 返回非法数据地址错误
                        response = struct.pack('>HHHBB', 
                                             request['transaction_id'], 0, 3, 
                                             request['unit_id'], function_code | 0x80)
                        response += struct.pack('>B', 0x02)  # 非法数据地址
                        
                elif function_code in [5, 6, 15, 16]:  # 写操作
                    # 简化处理写操作，直接返回成功
                    response = data
                    self.logger.info(f"写操作: 功能码={function_code}")
                else:
                    # 不支持的函数码
                    self.logger.warning(f"不支持的函数码: {function_code}")
                    response = struct.pack('>HHHBB', 
                                         request['transaction_id'], 0, 3, 
                                         request['unit_id'], function_code | 0x80)
                    response += struct.pack('>B', 0x01)  # 非法功能
                
                if response:
                    self.logger.debug(f"发送响应: {len(response)} 字节: {response.hex()}")
                    sent = client_socket.send(response)
                    self.logger.debug(f"实际发送: {sent} 字节")
                    
        except Exception as e:
            if self.running:
                self.logger.error(f"处理客户端错误: {e}")
        finally:
            client_socket.close()
            # 通知GUI客户端断开
            if self.gui_callback:
                self.gui_callback('client_disconnect', address)
            
            # 移除活跃客户端
            if address in self.active_clients:
                del self.active_clients[address]
                
            self.logger.info(f"客户端断开: {address}")
    
    def get_active_clients(self):
        """获取活跃客户端信息"""
        clients = []
        for address, info in self.active_clients.items():
            ip, port = address
            connect_time = info['connect_time'].strftime("%H:%M:%S")
            request_count = info['request_count']
            clients.append((ip, str(port), connect_time, f"活跃({request_count}请求)"))
        return clients

    def generate_data(self, config, current_time):
        """重写数据生成方法，确保数据范围被正确处理"""
        value = config['value']
        data_type = config.get('data_type', 'int16')
        
        # 如果是函数，调用函数生成数据
        if callable(value):
            try:
                # 检查函数是否需要参数
                import inspect
                sig = inspect.signature(value)
                param_count = len(sig.parameters)
                
                self.logger.debug(f"生成数据: 函数参数数量={param_count}, 数据范围={config.get('data_range')}, 数据类型={data_type}")
                
                # 如果有数据范围配置
                if config.get('data_range'):
                    # 检查是否是随机列表（多个值的列表）
                    if isinstance(config['data_range'], list) and len(config['data_range']) > 2:
                        # 随机列表，直接调用函数
                        result = value()
                        self.logger.debug(f"随机列表函数调用: 结果={result}")
                        return self.convert_to_data_type(result, data_type)
                    elif param_count == 2:
                        # 函数需要两个参数 (min, max)
                        result = value(config['data_range'][0], config['data_range'][1])
                        self.logger.debug(f"使用两个参数调用: min={config['data_range'][0]}, max={config['data_range'][1]}, 结果={result}")
                        return self.convert_to_data_type(result, data_type)
                    elif param_count == 1:
                        # 函数需要一个参数 (range_tuple)
                        result = value(config['data_range'])
                        self.logger.debug(f"使用一个参数调用: range={config['data_range']}, 结果={result}")
                        return self.convert_to_data_type(result, data_type)
                    else:
                        # 函数不需要参数，但我们有数据范围
                        result = value()
                        self.logger.debug(f"无参数函数调用，期望已通过闭包捕获范围: 结果={result}")
                        # 验证结果是否在范围内（对于随机递增计数函数，跳过范围检查）
                        if config['data_range'] and (result < config['data_range'][0] or result > config['data_range'][1]):
                            # 检查是否是随机递增计数函数
                            description = config.get('description', '')
                            # 检查函数本身是否是随机递增计数函数
                            is_random_increment = False
                            if callable(config['value']):
                                try:
                                    # 通过检查函数闭包中的变量来判断
                                    if hasattr(config['value'], '__closure__') and config['value'].__closure__:
                                        closure_vars = [c.cell_contents for c in config['value'].__closure__]
                                        # 检查闭包中是否有current列表（随机递增计数函数的特征）
                                        for var in closure_vars:
                                            if isinstance(var, list) and len(var) == 1 and isinstance(var[0], int):
                                                is_random_increment = True
                                                break
                                except:
                                    pass
                            
                            if '随机递增计数' in description or is_random_increment:
                                # 对于随机递增计数函数，允许超出范围继续累计
                                self.logger.debug(f"随机递增计数函数返回值 {result} 超出配置范围 {config['data_range']}，允许继续累计")
                            else:
                                self.logger.warning(f"函数返回值 {result} 超出配置范围 {config['data_range']}")
                                # 如果超出范围，强制修正到范围内
                                result = max(config['data_range'][0], min(config['data_range'][1], result))
                                self.logger.info(f"强制修正返回值到: {result}")
                        return self.convert_to_data_type(result, data_type)
                else:
                    # 没有数据范围配置
                    if param_count > 0:
                        # 函数需要参数但没有提供，使用默认值
                        self.logger.warning(f"函数需要参数但未配置数据范围，使用默认调用")
                        result = value()
                        self.logger.debug(f"无数据范围，使用默认调用: 结果={result}")
                        return self.convert_to_data_type(result, data_type)
                    else:
                        # 函数不需要参数
                        result = value()
                        self.logger.debug(f"无参数函数调用: 结果={result}")
                        return self.convert_to_data_type(result, data_type)
            except Exception as e:
                self.logger.error(f"数据生成函数错误: {e}")
                return self.convert_to_data_type(0, data_type)
        # 如果是固定值，直接返回并转换类型
        else:
            self.logger.debug(f"使用固定值: {value}")
            return self.convert_to_data_type(value, data_type)

    def save_original_config(self):
        """保存原始配置，用于重置数据"""
        import copy
        self.original_data_config = copy.deepcopy(self.data_config)
        self.logger.info("原始配置已保存")

    def reset_data(self):
        """重置所有数据到初始状态"""
        if hasattr(self, 'original_data_config') and self.original_data_config:
            # 恢复原始配置
            self.data_config = self.original_data_config
            self.logger.info("数据已重置到初始状态")
        else:
            # 如果没有保存原始配置，重新初始化所有数据
            current_time = time.time()
            for address_type in self.data_config:
                for address, config in self.data_config[address_type].items():
                    config['last_update'] = current_time
                    config['current_value'] = self.generate_data(config, current_time)
                    self.logger.info(f"重置 {address_type}[{address}] = {config['current_value']}")
            self.logger.info("数据已重新初始化")

class ModbusConfigGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Modbus数据模拟器配置工具 v2.2 - 支持多种数据类型和Bit位配置 By HuiYY 2025-11")
        self.root.geometry("1100x800")
        
        # 设置日志
        self.setup_logging()
        
        # 存储配置
        self.configs = {
            'coils': [],
            'discrete_inputs': [],
            'holding_registers': [],
            'input_registers': []
        }
        
        # 模拟器实例
        self.simulator = None
        self.simulator_thread = None
        self.is_running = False
        
        # 监控数据
        self.client_connections = []
        self.request_count = 0
        self.start_time = None
        
        self.create_widgets()
        self.load_default_config()
    
    def setup_logging(self):
        """设置日志"""
        self.logger = logging.getLogger('ModbusConfigGUI')
        self.logger.setLevel(logging.DEBUG)
        
        # 创建控制台处理器
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        
        # 创建文件处理器
        fh = logging.FileHandler('modbus_gui.log')
        fh.setLevel(logging.DEBUG)
        
        # 创建格式化器
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        fh.setFormatter(formatter)
        
        # 添加处理器到日志器
        self.logger.addHandler(ch)
        self.logger.addHandler(fh)
    
    def create_widgets(self):
        """创建GUI组件"""
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置服务器设置
        server_frame = ttk.LabelFrame(main_frame, text="服务器设置", padding="5")
        server_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(server_frame, text="IP地址:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.ip_entry = ttk.Entry(server_frame, width=15)
        self.ip_entry.insert(0, "localhost")
        self.ip_entry.grid(row=0, column=1, padx=5)
        
        ttk.Label(server_frame, text="端口:").grid(row=0, column=2, sticky=tk.W, padx=5)
        self.port_entry = ttk.Entry(server_frame, width=10)
        self.port_entry.insert(0, "502")
        self.port_entry.grid(row=0, column=3, padx=5)
        
        # 服务器控制按钮
        self.start_btn = ttk.Button(server_frame, text="启动服务器", command=self.start_server)
        self.start_btn.grid(row=0, column=4, padx=10)
        
        self.stop_btn = ttk.Button(server_frame, text="停止服务器", command=self.stop_server, state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=5, padx=5)
        
        # 状态显示
        self.status_var = tk.StringVar(value="服务器未启动")
        status_label = ttk.Label(server_frame, textvariable=self.status_var, foreground="red")
        status_label.grid(row=0, column=6, padx=10)
        
        # 创建选项卡
        notebook = ttk.Notebook(main_frame)
        notebook.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        
        # 线圈配置选项卡
        self.coils_frame = ttk.Frame(notebook, padding="5")
        notebook.add(self.coils_frame, text="01线圈 (0x)")
        self.create_register_tab(self.coils_frame, "coils")
        
        # 离散输入配置选项卡
        self.discrete_inputs_frame = ttk.Frame(notebook, padding="5")
        notebook.add(self.discrete_inputs_frame, text="02离散输入 (1x)")
        self.create_register_tab(self.discrete_inputs_frame, "discrete_inputs")
        
        # 保持寄存器配置选项卡
        self.holding_registers_frame = ttk.Frame(notebook, padding="5")
        notebook.add(self.holding_registers_frame, text="03保持寄存器 (4x)")
        self.create_register_tab(self.holding_registers_frame, "holding_registers")
        
        # 输入寄存器配置选项卡
        self.input_registers_frame = ttk.Frame(notebook, padding="5")
        notebook.add(self.input_registers_frame, text="04输入寄存器 (3x)")
        self.create_register_tab(self.input_registers_frame, "input_registers")
        
        # 实时监控选项卡
        self.monitor_frame = ttk.Frame(notebook, padding="5")
        notebook.add(self.monitor_frame, text="实时监控")
        self.create_monitor_tab()
        
        # 控制按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, columnspan=2, pady=10)
        
        ttk.Button(button_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="加载配置", command=self.load_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="导入Excel", command=self.import_excel).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="导出Excel", command=self.export_excel).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="导入CSV", command=self.import_csv).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="导出CSV", command=self.export_csv).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="重置配置", command=self.reset_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="使用帮助", command=self.show_help).pack(side=tk.LEFT, padx=5)
        
        # 配置根窗口的网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)
    
    def create_register_tab(self, parent, register_type):
        """创建寄存器配置选项卡"""
        # 创建树形视图显示配置
        if register_type in ['coils', 'discrete_inputs']:
            columns = ("地址", "值类型", "值/函数", "间隔", "范围", "描述")
        else:
            columns = ("地址", "值类型", "值/函数", "数据类型", "间隔", "范围", "描述", "Bit位配置")
            
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=12)
        
        # 设置列标题
        for col in columns:
            tree.heading(col, text=col)
            # 根据列名设置不同的宽度
            if col == "描述":
                tree.column(col, width=150)
            elif col == "Bit位配置":
                tree.column(col, width=120)
            else:
                tree.column(col, width=100)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=2, sticky=(tk.N, tk.S))
        
        # 绑定双击事件
        tree.bind("<Double-1>", lambda e: self.edit_register(register_type))
        
        # 存储树形视图引用
        setattr(self, f"{register_type}_tree", tree)
        
        # 按钮框架
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=1, column=0, columnspan=2, pady=5, sticky=tk.W)
        
        ttk.Button(btn_frame, text="添加", 
                  command=lambda: self.add_register_dialog(register_type)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="编辑", 
                  command=lambda: self.edit_register(register_type)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="删除", 
                  command=lambda: self.delete_register(register_type)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="批量添加", 
                  command=lambda: self.batch_add_dialog(register_type)).pack(side=tk.LEFT, padx=5)
        
        # 配置网格权重
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
    
    def create_monitor_tab(self):
        """创建实时监控选项卡"""
        # 服务器状态框架
        status_frame = ttk.LabelFrame(self.monitor_frame, text="服务器状态", padding="5")
        status_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # 运行时间
        ttk.Label(status_frame, text="运行时间:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.uptime_var = tk.StringVar(value="00:00:00")
        ttk.Label(status_frame, textvariable=self.uptime_var).grid(row=0, column=1, sticky=tk.W, padx=5)
        
        # 客户端连接数
        ttk.Label(status_frame, text="客户端连接:").grid(row=0, column=2, sticky=tk.W, padx=5)
        self.client_count_var = tk.StringVar(value="0")
        ttk.Label(status_frame, textvariable=self.client_count_var).grid(row=0, column=3, sticky=tk.W, padx=5)
        
        # 请求计数
        ttk.Label(status_frame, text="请求计数:").grid(row=0, column=4, sticky=tk.W, padx=5)
        self.request_count_var = tk.StringVar(value="0")
        ttk.Label(status_frame, textvariable=self.request_count_var).grid(row=0, column=5, sticky=tk.W, padx=5)
        
        # 客户端连接列表
        client_frame = ttk.LabelFrame(self.monitor_frame, text="客户端连接", padding="5")
        client_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        columns = ("IP地址", "端口", "连接时间", "状态")
        self.client_tree = ttk.Treeview(client_frame, columns=columns, show="headings", height=8)
        
        for col in columns:
            self.client_tree.heading(col, text=col)
            self.client_tree.column(col, width=120)
        
        client_scrollbar = ttk.Scrollbar(client_frame, orient=tk.VERTICAL, command=self.client_tree.yview)
        self.client_tree.configure(yscrollcommand=client_scrollbar.set)
        
        self.client_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        client_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # 实时日志
        log_frame = ttk.LabelFrame(self.monitor_frame, text="实时日志", padding="5")
        log_frame.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5, padx=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, width=50, height=20, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 控制按钮
        monitor_btn_frame = ttk.Frame(self.monitor_frame)
        monitor_btn_frame.grid(row=2, column=0, columnspan=2, pady=5)
        
        ttk.Button(monitor_btn_frame, text="刷新", command=self.refresh_monitor).pack(side=tk.LEFT, padx=5)
        ttk.Button(monitor_btn_frame, text="清空日志", command=self.clear_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(monitor_btn_frame, text="断开选中客户端", command=self.disconnect_client).pack(side=tk.LEFT, padx=5)
        
        # 配置网格权重
        self.monitor_frame.columnconfigure(0, weight=1)
        self.monitor_frame.columnconfigure(1, weight=1)
        self.monitor_frame.rowconfigure(1, weight=1)
        client_frame.columnconfigure(0, weight=1)
        client_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
    
    def simulator_callback(self, event_type, data):
        """模拟器回调函数"""
        if event_type == 'client_connect':
            self.add_client_connection(data)
        elif event_type == 'client_disconnect':
            self.remove_client_connection(data)
        elif event_type == 'request_received':
            self.add_request_log(f"收到来自 {data} 的请求")
    
    def add_register_dialog(self, register_type, config=None, is_edit=False):
        """打开添加/编辑寄存器对话框 - 修复function_frame未定义问题"""
        dialog = tk.Toplevel(self.root)
        if is_edit:
            dialog.title(f"编辑{self.get_register_type_name(register_type)}")
        else:
            dialog.title(f"添加{self.get_register_type_name(register_type)}")
        dialog.geometry("500x650")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 存储对话框中的控件引用
        dialog_controls = {}
        current_row = 0
        
        # 地址
        ttk.Label(dialog, text="地址:").grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=5)
        address_entry = ttk.Entry(dialog, width=10)
        address_entry.grid(row=current_row, column=1, sticky=tk.W, padx=5, pady=5)
        dialog_controls['address'] = address_entry
        current_row += 1
        
        # 值类型
        ttk.Label(dialog, text="值类型:").grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=5)
        value_type_var = tk.StringVar(value="fixed")
        value_type_frame = ttk.Frame(dialog)
        value_type_frame.grid(row=current_row, column=1, sticky=tk.W, padx=5, pady=5)
        
        ttk.Radiobutton(value_type_frame, text="固定值", variable=value_type_var, value="fixed").pack(side=tk.LEFT)
        ttk.Radiobutton(value_type_frame, text="随机值", variable=value_type_var, value="random").pack(side=tk.LEFT)
        ttk.Radiobutton(value_type_frame, text="随机列表", variable=value_type_var, value="random_list").pack(side=tk.LEFT)
        if register_type in ['holding_registers', 'input_registers']:
            ttk.Radiobutton(value_type_frame, text="函数", variable=value_type_var, value="function").pack(side=tk.LEFT)
        
        dialog_controls['value_type'] = value_type_var
        current_row += 1
        
        # 数据类型选择（仅对寄存器类型可用）
        if register_type in ['holding_registers', 'input_registers']:
            ttk.Label(dialog, text="数据类型:").grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=5)
            data_type_var = tk.StringVar(value="int16")
            data_type_combo = ttk.Combobox(dialog, textvariable=data_type_var, width=15, state="readonly")
            data_type_combo['values'] = [
                "int16", "uint16", "int32", "uint32", "float32", "float64", "bool", "string"
            ]
            data_type_combo.grid(row=current_row, column=1, sticky=tk.W, padx=5, pady=5)
            dialog_controls['data_type'] = data_type_var
            current_row += 1
        else:
            # 线圈和离散输入只能是布尔类型
            data_type_var = tk.StringVar(value="bool")
            dialog_controls['data_type'] = data_type_var
        
        # 值/函数
        ttk.Label(dialog, text="值/函数:").grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=5)
        value_frame = ttk.Frame(dialog)
        value_frame.grid(row=current_row, column=1, sticky=tk.W, padx=5, pady=5)
        
        fixed_value_var = tk.StringVar()
        fixed_value_entry = ttk.Entry(value_frame, textvariable=fixed_value_var, width=15)
        fixed_value_entry.grid(row=0, column=0)
        dialog_controls['fixed_value'] = fixed_value_var
        
        # 对于线圈和离散输入，使用复选框
        if register_type in ['coils', 'discrete_inputs']:
            bool_var = tk.BooleanVar(value=True)
            bool_check = ttk.Checkbutton(value_frame, text="True", variable=bool_var)
            bool_check.grid(row=0, column=1, padx=5)
            dialog_controls['bool_value'] = bool_var
        current_row += 1
        
        # 范围
        range_frame = ttk.Frame(dialog)
        range_frame.grid(row=current_row, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)
        
        ttk.Label(range_frame, text="范围:").pack(side=tk.LEFT)
        min_range_entry = ttk.Entry(range_frame, width=8)
        min_range_entry.pack(side=tk.LEFT, padx=2)
        dialog_controls['min_range'] = min_range_entry
        
        ttk.Label(range_frame, text="到").pack(side=tk.LEFT)
        max_range_entry = ttk.Entry(range_frame, width=8)
        max_range_entry.pack(side=tk.LEFT, padx=2)
        dialog_controls['max_range'] = max_range_entry
        current_row += 1
        
        # 数字列表输入框
        ttk.Label(dialog, text="数字列表(逗号分隔):").grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=5)
        random_list_entry = ttk.Entry(dialog, width=30)
        random_list_entry.grid(row=current_row, column=1, sticky=tk.W, padx=5, pady=5)
        dialog_controls['random_list'] = random_list_entry
        current_row += 1
        
        # 间隔
        ttk.Label(dialog, text="更新间隔(秒):").grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=5)
        interval_entry = ttk.Entry(dialog, width=10)
        interval_entry.insert(0, "1")
        interval_entry.grid(row=current_row, column=1, sticky=tk.W, padx=5, pady=5)
        dialog_controls['interval'] = interval_entry
        current_row += 1
        
        # 描述
        ttk.Label(dialog, text="描述:").grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=5)
        description_entry = ttk.Entry(dialog, width=30)
        description_entry.grid(row=current_row, column=1, sticky=tk.W, padx=5, pady=5)
        dialog_controls['description'] = description_entry
        current_row += 1
        
        # 函数选择（仅对寄存器类型可用）
        function_var = None
        function_combo = None
        if register_type in ['holding_registers', 'input_registers']:
            ttk.Label(dialog, text="函数:").grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=5)
            function_var = tk.StringVar()
            
            # 定义函数列表 - 添加Bit位周期开关
            functions = [
                "随机开关",
                "周期开关", 
                "递增计数",
                "随机递增计数",
                "正弦波",
                "时间戳",
                "完整时间戳",
                "年月日",
                "时分秒",
                "工作日标志",
                "随机温度",
                "随机湿度",
                "随机压力",
                "Bit位周期开关"  # 新增Bit位函数
            ]
            
            function_combo = ttk.Combobox(dialog, textvariable=function_var, width=25, state="readonly")
            function_combo['values'] = functions
            function_combo.grid(row=current_row, column=1, sticky=tk.W, padx=5, pady=5)
            dialog_controls['function'] = function_var
            current_row += 1
        
        # Bit位配置区域（仅当选择Bit位函数时显示）
        if register_type in ['holding_registers', 'input_registers']:
            # Bit位配置框架
            bit_config_frame = ttk.LabelFrame(dialog, text="Bit位配置", padding="5")
            bit_config_frame.grid(row=current_row, column=0, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=5)
            current_row += 1
            
            # 创建Bit位配置表格
            bit_columns = ("Bit位", "变化类型", "周期(S)", "描述")
            bit_tree = ttk.Treeview(bit_config_frame, columns=bit_columns, show="headings", height=6)
            
            for col in bit_columns:
                bit_tree.heading(col, text=col)
                bit_tree.column(col, width=80)
            
            bit_scrollbar = ttk.Scrollbar(bit_config_frame, orient=tk.VERTICAL, command=bit_tree.yview)
            bit_tree.configure(yscrollcommand=bit_scrollbar.set)
            
            bit_tree.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
            bit_scrollbar.grid(row=0, column=2, sticky=(tk.N, tk.S))
            
            # Bit位配置按钮
            bit_btn_frame = ttk.Frame(bit_config_frame)
            bit_btn_frame.grid(row=1, column=0, columnspan=2, pady=5)
            
            def add_bit_config():
                """添加Bit位配置"""
                # 打开Bit位配置对话框
                bit_dialog = tk.Toplevel(dialog)
                bit_dialog.title("添加Bit位配置")
                bit_dialog.geometry("400x250")
                bit_dialog.transient(dialog)
                bit_dialog.grab_set()
                
                ttk.Label(bit_dialog, text="Bit位配置").grid(row=0, column=0, columnspan=2, pady=10)
                
                ttk.Label(bit_dialog, text="Bit位(0-15):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
                bit_pos_var = tk.StringVar()
                bit_pos_entry = ttk.Entry(bit_dialog, textvariable=bit_pos_var, width=10)
                bit_pos_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
                
                # 新增：变化类型选择
                ttk.Label(bit_dialog, text="变化类型:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
                change_type_var = tk.StringVar(value="periodic")
                change_type_frame = ttk.Frame(bit_dialog)
                change_type_frame.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
                ttk.Radiobutton(change_type_frame, text="周期变化", variable=change_type_var, value="periodic").pack(side=tk.LEFT)
                ttk.Radiobutton(change_type_frame, text="随机变化", variable=change_type_var, value="random").pack(side=tk.LEFT)
                
                ttk.Label(bit_dialog, text="周期(S):").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
                bit_interval_var = tk.StringVar(value="2")
                bit_interval_entry = ttk.Entry(bit_dialog, textvariable=bit_interval_var, width=10)
                bit_interval_entry.grid(row=3, column=1, sticky=tk.W, padx=5, pady=5)
                
                ttk.Label(bit_dialog, text="描述:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
                bit_desc_var = tk.StringVar()
                bit_desc_entry = ttk.Entry(bit_dialog, textvariable=bit_desc_var, width=20)
                bit_desc_entry.grid(row=4, column=1, sticky=tk.W, padx=5, pady=5)
                
                def save_bit_config():
                    try:
                        bit_pos = int(bit_pos_var.get())
                        if bit_pos < 0 or bit_pos > 15:
                            messagebox.showerror("错误", "Bit位必须在0-15之间")
                            return
                        
                        interval = float(bit_interval_var.get())
                        if interval <= 0:
                            messagebox.showerror("错误", "周期必须大于0")
                            return
                        
                        # 检查是否已存在相同的Bit位
                        for item in bit_tree.get_children():
                            values = bit_tree.item(item, 'values')
                            if int(values[0]) == bit_pos:
                                messagebox.showerror("错误", f"Bit位 {bit_pos} 已配置")
                                return
                        
                        # 添加Bit位配置
                        change_type_display = "周期" if change_type_var.get() == "periodic" else "随机"
                        bit_tree.insert("", "end", values=(bit_pos, change_type_display, interval, bit_desc_var.get()))
                        bit_dialog.destroy()
                    except ValueError:
                        messagebox.showerror("错误", "Bit位和周期必须是数字")
                
                ttk.Button(bit_dialog, text="保存", command=save_bit_config).grid(row=5, column=0, pady=10)
                ttk.Button(bit_dialog, text="取消", command=bit_dialog.destroy).grid(row=5, column=1, pady=10)
            
            def remove_bit_config():
                """删除选中的Bit位配置"""
                selection = bit_tree.selection()
                if not selection:
                    messagebox.showwarning("警告", "请先选择一个Bit位配置")
                    return
                
                for item in selection:
                    bit_tree.delete(item)
            
            ttk.Button(bit_btn_frame, text="+", command=add_bit_config, width=3).pack(side=tk.LEFT, padx=5)
            ttk.Button(bit_btn_frame, text="-", command=remove_bit_config, width=3).pack(side=tk.LEFT, padx=5)
            
            # 存储Bit位配置引用
            dialog_controls['bit_tree'] = bit_tree
            dialog_controls['bit_config_frame'] = bit_config_frame
            
            # 初始隐藏Bit位配置区域
            bit_config_frame.grid_remove()
            
            # 配置网格权重
            bit_config_frame.columnconfigure(0, weight=1)
            bit_config_frame.rowconfigure(0, weight=1)
        
        # 按钮框架
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=current_row, column=0, columnspan=2, pady=10)
        current_row += 1
        
        # 存储原始地址（用于编辑模式）
        original_address = None
        
        # 如果是编辑模式，填充现有数据
        if is_edit and config:
            original_address = config['address']  # 保存原始地址
            address_entry.insert(0, str(config['address']))
            
            # 设置数据类型
            if 'data_type' in dialog_controls:
                data_type = config.get('data_type', 'int16')
                dialog_controls['data_type'].set(data_type)
            
            # 根据配置确定值类型
            value = config['value']
            data_range = config.get('data_range')
            description = config.get('description', '')
            step_range = config.get('step_range', [1, 10])
            function_type = config.get('function_type', '')
            bit_config = config.get('bit_config', {})  # 获取Bit位配置
            
            # 填充Bit位配置
            if register_type in ['holding_registers', 'input_registers'] and 'bit_tree' in dialog_controls:
                bit_tree = dialog_controls['bit_tree']
                # 清空现有Bit位配置
                for item in bit_tree.get_children():
                    bit_tree.delete(item)
                
                # 添加Bit位配置
                for bit, bit_cfg in bit_config.items():
                    change_type = bit_cfg.get('change_type', 'periodic')
                    change_type_display = "周期" if change_type == "periodic" else "随机"
                    bit_tree.insert("", "end", values=(
                        bit, 
                        change_type_display, 
                        bit_cfg.get('interval', ''), 
                        bit_cfg.get('description', '')
                    ))
            
            # 修复：优先判断随机列表类型
            if data_range and isinstance(data_range, list) and len(data_range) > 2:
                # 这是随机列表类型
                value_type_var.set("random_list")
                random_list_entry.insert(0, ','.join(map(str, data_range)))
                if function_var is not None:
                    function_var.set('')  # 清空函数选择
            elif callable(value) and function_type == "随机值":
                # 这是随机值类型
                value_type_var.set("random")
                if data_range and len(data_range) == 2:
                    min_range_entry.insert(0, str(data_range[0]))
                    max_range_entry.insert(0, str(data_range[1]))
                if function_var is not None:
                    function_var.set('')  # 清空函数选择
            elif callable(value):
                # 这是函数类型
                value_type_var.set("function")
                
                # 根据存储的函数类型或描述推断函数类型
                if function_type and function_var is not None:
                    function_var.set(function_type)
                elif function_var is not None:
                    # 根据描述推断函数类型
                    if '随机递增计数' in description:
                        function_var.set("随机递增计数")
                    elif '递增计数' in description:
                        function_var.set("递增计数")
                    elif '正弦波' in description:
                        function_var.set("正弦波")
                    elif '周期开关' in description:
                        function_var.set("周期开关")
                    elif '随机开关' in description:
                        function_var.set("随机开关")
                    elif '时间戳' in description or '完整时间戳' in description:
                        function_var.set("完整时间戳")
                    elif '年月日' in description:
                        function_var.set("年月日")
                    elif '时分秒' in description:
                        function_var.set("时分秒")
                    elif '工作日标志' in description:
                        function_var.set("工作日标志")
                    elif '温度' in description:
                        function_var.set("随机温度")
                    elif '湿度' in description:
                        function_var.set("随机湿度")
                    elif '压力' in description:
                        function_var.set("随机压力")
                    elif 'Bit位' in description:
                        function_var.set("Bit位周期开关")
                    else:
                        function_var.set("随机开关")  # 默认
            
                # 对于需要范围的函数，填充范围值
                if function_var is not None and function_var.get() in ["随机递增计数", "递增计数", "随机温度", "随机湿度", "随机压力", "正弦波"]:
                    if data_range and len(data_range) == 2:
                        min_range_entry.insert(0, str(data_range[0]))
                        max_range_entry.insert(0, str(data_range[1]))
            else:
                # 固定值类型
                value_type_var.set("fixed")
                if register_type in ['coils', 'discrete_inputs']:
                    if 'bool_value' in dialog_controls:
                        dialog_controls['bool_value'].set(bool(value))
                else:
                    fixed_value_var.set(str(value))
        
            # 设置其他字段
            interval_entry.delete(0, tk.END)
            interval_entry.insert(0, str(config['interval']))
            
            if config.get('description'):
                description_entry.insert(0, config['description'])
    
        def on_ok():
            try:
                address = int(address_entry.get())
                interval = float(interval_entry.get())
                description = description_entry.get()
                
                value_type = value_type_var.get()
                data_type = dialog_controls['data_type'].get() if 'data_type' in dialog_controls else 'bool'
                
                # 根据值类型处理数据
                if value_type == "fixed":
                    if register_type in ['coils', 'discrete_inputs']:
                        value = bool_var.get() if 'bool_var' in locals() else (fixed_value_var.get().lower() == 'true')
                    else:
                        # 根据数据类型转换固定值
                        value_str = fixed_value_var.get() if fixed_value_var.get() else "0"
                        value = self.convert_value_by_type(value_str, data_type)
                    data_range = None
                    step_range = None
                    function_type = None
                    bit_config = {}
                elif value_type == "random":
                    min_val = self.convert_value_by_type(min_range_entry.get() if min_range_entry.get() else "0", data_type)
                    max_val = self.convert_value_by_type(max_range_entry.get() if max_range_entry.get() else "100", data_type)
                    # 对于布尔范围 [0,1]，使用专门的布尔函数
                    if data_type == 'bool' or (min_val == 0 and max_val == 1):
                        value = self.create_robust_boolean_function()
                        function_type = "随机开关"
                    else:
                        value = self.create_robust_random_function(min_val, max_val, data_type)
                        function_type = "随机值"
                    data_range = [min_val, max_val]
                    step_range = None
                    bit_config = {}
                elif value_type == "random_list":
                    # 解析数字列表
                    list_text = random_list_entry.get().strip()
                    if list_text:
                        try:
                            # 分割字符串并转换为适当类型
                            number_list = [self.convert_value_by_type(x.strip(), data_type) for x in list_text.split(',')]
                            if number_list:
                                value = self.create_robust_random_list_function(number_list)
                                data_range = number_list
                                function_type = "随机列表"
                                step_range = None
                                bit_config = {}
                            else:
                                raise ValueError("数字列表不能为空")
                        except ValueError as e:
                            messagebox.showerror("错误", f"数字列表格式错误: {e}")
                            return
                    else:
                        messagebox.showerror("错误", "请输入数字列表")
                        return
                else:  # function
                    if function_var is None:
                        messagebox.showerror("错误", "该寄存器类型不支持函数")
                        return
                        
                    func_name = function_var.get()
                    
                    # 如果是Bit位函数，处理Bit位配置
                    if func_name == "Bit位周期开关":
                        # 收集Bit位配置
                        bit_config = {}
                        if 'bit_tree' in dialog_controls:
                            bit_tree = dialog_controls['bit_tree']
                            for item in bit_tree.get_children():
                                values = bit_tree.item(item, 'values')
                                bit_pos = int(values[0])
                                change_type_display = values[1]  # "周期" 或 "随机"
                                change_type = "periodic" if change_type_display == "周期" else "random"
                                interval = float(values[2])
                                desc = values[3]
                                bit_config[str(bit_pos)] = {
                                    'change_type': change_type,  # 存储变化类型
                                    'interval': interval,
                                    'description': desc
                                }
                        
                        if not bit_config:
                            messagebox.showerror("错误", "请至少配置一个Bit位")
                            return
                        
                        # 对于Bit位函数，值设为0，实际数据由bit_config生成
                        value = 0
                        function_type = "Bit位周期开关"
                        data_range = None
                        step_range = None
                    else:
                        min_val = self.convert_value_by_type(min_range_entry.get() if min_range_entry.get() else "0", data_type)
                        max_val = self.convert_value_by_type(max_range_entry.get() if max_range_entry.get() else "100", data_type)
                        
                        # 对于随机递增计数函数，需要获取步进范围
                        if func_name == "随机递增计数":
                            # 这里需要添加步进范围的输入控件，暂时使用默认值
                            min_step = 1
                            max_step = 10
                            value = self.create_random_increment_function(
                                start=min_val, 
                                min_step=min_step, 
                                max_step=max_step, 
                                max_value=max_val,
                                data_type=data_type
                            )
                            step_range = [min_step, max_step]
                        else:
                            value = self.get_function_by_name(func_name, register_type, min_val, max_val, data_type)
                            step_range = None
                        
                        data_range = [min_val, max_val] if min_range_entry.get() and max_range_entry.get() else None
                        function_type = func_name
                        bit_config = {}
                
                if is_edit:
                    # 更新现有配置
                    found = False
                    for i, cfg in enumerate(self.configs[register_type]):
                        if cfg['address'] == original_address:  # 使用原始地址查找
                            # 检查新地址是否与现有地址冲突（除了当前正在编辑的地址）
                            if address != original_address and any(c['address'] == address for c in self.configs[register_type]):
                                messagebox.showerror("错误", f"地址 {address} 已存在")
                                return
                            
                            # 更新配置
                            self.configs[register_type][i] = {
                                'address': address,  # 使用新地址
                                'value': value,
                                'interval': interval,
                                'data_range': data_range,
                                'step_range': step_range,
                                'bit_config': bit_config,  # 存储Bit位配置
                                'description': description,
                                'function_type': function_type,
                                'data_type': data_type  # 存储数据类型
                            }
                            found = True
                            break
                    
                    if not found:
                        messagebox.showerror("错误", f"未找到地址 {original_address} 的配置")
                        return
                else:
                    # 检查地址是否已存在
                    if any(cfg['address'] == address for cfg in self.configs[register_type]):
                        messagebox.showerror("错误", f"地址 {address} 已存在")
                        return
                    
                    # 添加到配置
                    self.configs[register_type].append({
                        'address': address,
                        'value': value,
                        'interval': interval,
                        'data_range': data_range,
                        'step_range': step_range,
                        'bit_config': bit_config,  # 存储Bit位配置
                        'description': description,
                        'function_type': function_type,
                        'data_type': data_type  # 存储数据类型
                    })
                
                # 更新树形视图
                self.update_register_tree(register_type)
                
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("错误", f"配置错误: {e}")
        
        def on_cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="确定", command=on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=on_cancel).pack(side=tk.LEFT, padx=5)
        
        # 根据值类型更新UI
        def update_ui(*args):
            value_type = value_type_var.get()
            func_name = function_var.get() if function_var is not None else ""
            
            # 显示/隐藏Bit位配置区域
            if 'bit_config_frame' in dialog_controls:
                if func_name == "Bit位周期开关":
                    dialog_controls['bit_config_frame'].grid()
                else:
                    dialog_controls['bit_config_frame'].grid_remove()
            
            if value_type == "fixed":
                fixed_value_entry.config(state=tk.NORMAL)
                min_range_entry.config(state=tk.DISABLED)
                max_range_entry.config(state=tk.DISABLED)
                random_list_entry.config(state=tk.DISABLED)
                if function_combo is not None:
                    function_combo.config(state=tk.DISABLED)
            elif value_type == "random":
                fixed_value_entry.config(state=tk.DISABLED)
                min_range_entry.config(state=tk.NORMAL)
                max_range_entry.config(state=tk.NORMAL)
                random_list_entry.config(state=tk.DISABLED)
                if function_combo is not None:
                    function_combo.config(state=tk.DISABLED)
            elif value_type == "random_list":
                fixed_value_entry.config(state=tk.DISABLED)
                min_range_entry.config(state=tk.DISABLED)
                max_range_entry.config(state=tk.DISABLED)
                random_list_entry.config(state=tk.NORMAL)
                if function_combo is not None:
                    function_combo.config(state=tk.DISABLED)
            else:  # function
                fixed_value_entry.config(state=tk.DISABLED)
                min_range_entry.config(state=tk.NORMAL)
                max_range_entry.config(state=tk.NORMAL)
                random_list_entry.config(state=tk.DISABLED)
                if function_combo is not None:
                    function_combo.config(state=tk.NORMAL)
        
        # 对于线圈和离散输入，不需要函数选项，所以不需要额外处理
        
        value_type_var.trace('w', update_ui)
        if function_var is not None:
            function_var.trace('w', update_ui)
        update_ui()
    
    def convert_value_by_type(self, value_str, data_type):
        """根据数据类型转换值"""
        try:
            if data_type == 'int16':
                return int(value_str)
            elif data_type == 'uint16':
                return int(value_str) & 0xFFFF
            elif data_type == 'int32':
                return int(value_str)
            elif data_type == 'uint32':
                return int(value_str) & 0xFFFFFFFF
            elif data_type == 'float32':
                return float(value_str)
            elif data_type == 'float64':
                return float(value_str)
            elif data_type == 'bool':
                if isinstance(value_str, str):
                    return value_str.lower() in ['true', '1', 'yes', 'y']
                else:
                    return bool(value_str)
            elif data_type == 'string':
                return str(value_str)
            else:
                return int(value_str)
        except (ValueError, TypeError):
            return 0
    
    def create_robust_boolean_function(self):
        """创建返回0或1的健壮布尔函数"""
        def boolean_func():
            return random.choice([0, 1])
        return boolean_func
    
    def create_robust_periodic_boolean_function(self, period=10):
        """创建周期性返回0或1的健壮函数"""
        def periodic_boolean_func():
            return 1 if (int(time.time()) % period) < (period // 2) else 0
        return periodic_boolean_func
    
    def create_robust_random_function(self, min_val, max_val, data_type='int16'):
        """创建更健壮的随机数生成函数"""
        def random_func():
            if data_type in ['float32', 'float64']:
                return random.uniform(min_val, max_val)
            else:
                return random.randint(min_val, max_val)
        return random_func
    
    def create_robust_random_list_function(self, number_list):
        """创建从指定数字列表中随机选择的函数"""
        def random_list_func():
            return random.choice(number_list)
        return random_list_func
    
    def create_robust_sine_wave_function(self, amplitude=500, offset=1000, frequency=0.1, data_type='int16'):
        """创建更健壮的正弦波生成函数"""
        def sine_wave_func():
            result = amplitude * math.sin(time.time() * frequency) + offset
            if data_type in ['int16', 'uint16', 'int32', 'uint32']:
                return int(result)
            else:
                return result
        return sine_wave_func
    
    def create_ramp_function(self, start=0, step=1, max_value=65535, data_type='int16'):
        """创建斜坡函数"""
        current = [start]
        def ramp_func():
            current[0] = (current[0] + step) % max_value
            if data_type in ['int16', 'uint16', 'int32', 'uint32']:
                return int(current[0])
            else:
                return current[0]
        return ramp_func
    
    def create_random_increment_function(self, start=0, min_step=1, max_step=10, max_value=65535, data_type='int16'):
        """创建随机递增计数函数"""
        current = [start]
        def random_increment_func():
            step = random.randint(min_step, max_step)
            current[0] = current[0] + step
            if data_type in ['int16', 'uint16', 'int32', 'uint32']:
                return int(current[0])
            else:
                return current[0]
        return random_increment_func
    
    def create_bit_periodic_function(self, bit_config):
        """创建Bit位周期开关函数"""
        # 对于Bit位函数，返回固定值0，实际数据在模拟器中通过bit_config生成
        def bit_func():
            return 0
        return bit_func
    
    def get_function_by_name(self, func_name, register_type, min_val=0, max_val=100, data_type='int16', step_range=None):
        """根据函数名返回对应的函数"""
        # 处理None值
        if min_val is None:
            min_val = 0
        if max_val is None:
            max_val = 100
        
        # 对于布尔范围 [0,1]，使用专门的布尔函数
        if data_type == 'bool' or (min_val == 0 and max_val == 1):
            if func_name == "随机开关":
                return self.create_robust_boolean_function()
            elif func_name == "周期开关":
                return self.create_robust_periodic_boolean_function()
            else:
                return self.create_robust_boolean_function()
        
        # 正常范围的处理
        if func_name == "随机开关":
            return lambda: random.choice([True, False])
        elif func_name == "周期开关":
            return self.create_robust_periodic_boolean_function()
        elif func_name == "递增计数":
            return self.create_ramp_function(start=min_val, step=1, max_value=max_val+1, data_type=data_type)
        elif func_name == "随机递增计数":
            min_step = step_range[0] if step_range and len(step_range) >= 2 else 1
            max_step = step_range[1] if step_range and len(step_range) >= 2 else 10
            return self.create_random_increment_function(start=min_val, min_step=min_step, max_step=max_step, max_value=65535, data_type=data_type)
        elif func_name == "正弦波":
            amplitude = (max_val - min_val) / 2
            offset = min_val + amplitude
            return self.create_robust_sine_wave_function(amplitude, offset, 0.1, data_type)
        elif func_name == "时间戳":
            if max_val <= 2359:
                return lambda: int(datetime.now().strftime("%H%M"))
            elif max_val <= 12312359:
                return lambda: int(datetime.now().strftime("%m%d%H%M"))
            else:
                return lambda: int(time.time() % (max_val + 1))
        elif func_name == "完整时间戳":
            return lambda: int(time.time())
        elif func_name == "年月日":
            return lambda: int(datetime.now().strftime("%Y%m%d"))
        elif func_name == "时分秒":
            return lambda: int(datetime.now().strftime("%H%M%S"))
        elif func_name == "工作日标志":
            return lambda: 1 if datetime.now().weekday() < 5 else 0
        elif func_name == "随机温度":
            return self.create_robust_random_function(min_val, max_val, data_type)
        elif func_name == "随机湿度":
            return self.create_robust_random_function(min_val, max_val, data_type)
        elif func_name == "随机压力":
            return self.create_robust_random_function(min_val, max_val, data_type)
        elif func_name == "Bit位周期开关":
            # 对于Bit位函数，返回一个固定值，实际数据在模拟器中生成
            return lambda: 0
        else:
            return lambda: 0
    
    def batch_add_dialog(self, register_type):
        """批量添加对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title(f"批量添加{self.get_register_type_name(register_type)}")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="起始地址:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        start_addr_entry = ttk.Entry(dialog, width=10)
        start_addr_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        start_addr_entry.insert(0, "0")
        
        ttk.Label(dialog, text="数量:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        count_entry = ttk.Entry(dialog, width=10)
        count_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        count_entry.insert(0, "10")
        
        ttk.Label(dialog, text="初始值:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        init_value_entry = ttk.Entry(dialog, width=10)
        init_value_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        init_value_entry.insert(0, "0")
        
        ttk.Label(dialog, text="间隔:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        interval_entry = ttk.Entry(dialog, width=10)
        interval_entry.grid(row=3, column=1, sticky=tk.W, padx=5, pady=5)
        interval_entry.insert(0, "1")
        
        ttk.Label(dialog, text="描述前缀:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        desc_prefix_entry = ttk.Entry(dialog, width=20)
        desc_prefix_entry.grid(row=4, column=1, sticky=tk.W, padx=5, pady=5)
        desc_prefix_entry.insert(0, f"{self.get_register_type_name(register_type)}")
        
        def on_ok():
            try:
                start_addr = int(start_addr_entry.get())
                count = int(count_entry.get())
                init_value = int(init_value_entry.get())
                interval = float(interval_entry.get())
                desc_prefix = desc_prefix_entry.get()
                
                for i in range(count):
                    addr = start_addr + i
                    # 检查地址是否已存在
                    if not any(cfg['address'] == addr for cfg in self.configs[register_type]):
                        self.configs[register_type].append({
                            'address': addr,
                            'value': init_value + i,
                            'interval': interval,
                            'data_range': None,
                            'step_range': None,
                            'bit_config': {},
                            'description': f"{desc_prefix}_{addr}",
                            'function_type': None,
                            'data_type': 'int16'  # 默认数据类型
                        })
                
                # 更新树形视图
                self.update_register_tree(register_type)
                
                dialog.destroy()
                messagebox.showinfo("成功", f"成功添加 {count} 个{self.get_register_type_name(register_type)}")
            except Exception as e:
                messagebox.showerror("错误", f"批量添加错误: {e}")
        
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=5, column=0, columnspan=2, pady=10)
        
        ttk.Button(button_frame, text="确定", command=on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def get_register_type_name(self, register_type):
        """获取寄存器类型的中文名称"""
        names = {
            'coils': '线圈',
            'discrete_inputs': '离散输入',
            'holding_registers': '保持寄存器',
            'input_registers': '输入寄存器'
        }
        return names.get(register_type, register_type)
    
    def update_register_tree(self, register_type):
        """更新寄存器树形视图"""
        tree = getattr(self, f"{register_type}_tree")
        
        # 清空树
        for item in tree.get_children():
            tree.delete(item)
        
        # 添加数据
        for config in self.configs[register_type]:
            address = config['address']
            value = config['value']
            interval = config['interval']
            data_range = config.get('data_range', '')
            step_range = config.get('step_range', '')
            bit_config = config.get('bit_config', {})
            description = config.get('description', '')
            function_type = config.get('function_type', '')
            data_type = config.get('data_type', 'int16')
            
            # 修复：准确识别值类型显示
            if callable(value):
                # 检查是否是随机列表函数
                if isinstance(data_range, list) and len(data_range) > 2:
                    value_type = "随机列表"
                    value_display = f"随机列表({len(data_range)}个值)"
                elif function_type == "随机值":  # 修复：准确识别随机值类型
                    value_type = "随机值"
                    value_display = f"随机值({data_range[0]}-{data_range[1]})"
                else:
                    value_type = "函数"
                    # 使用存储的函数类型名称，而不是根据描述推断
                    if function_type:
                        value_display = function_type
                    else:
                        # 如果没有存储函数类型，根据描述推断
                        if '随机递增计数' in description:
                            value_display = "随机递增计数"
                        elif '递增计数' in description:
                            value_display = "递增计数"
                        elif '正弦波' in description:
                            value_display = "正弦波"
                        elif '周期开关' in description:
                            value_display = "周期开关"
                        elif '随机开关' in description:
                            value_display = "随机开关"
                        elif '时间戳' in description or '完整时间戳' in description:
                            value_display = "完整时间戳"
                        elif '年月日' in description:
                            value_display = "年月日"
                        elif '时分秒' in description:
                            value_display = "时分秒"
                        elif '工作日标志' in description:
                            value_display = "工作日标志"
                        elif '温度' in description:
                            value_display = "随机温度"
                        elif '湿度' in description:
                            value_display = "随机湿度"
                        elif '压力' in description:
                            value_display = "随机压力"
                        elif 'Bit位' in description:
                            value_display = "Bit位周期开关"
                        else:
                            value_display = "随机函数"
            else:
                value_type = "固定值"
                value_display = str(value)
            
            # 格式化范围显示
            range_display = ""
            if data_range:
                if isinstance(data_range, list) and len(data_range) > 2:
                    # 如果是数字列表，显示前几个数字和总数
                    if len(data_range) > 5:
                        range_display = f"{data_range[:5]}... (共{len(data_range)}个)"
                    else:
                        range_display = str(data_range)
                else:
                    range_display = f"{data_range[0]}-{data_range[1]}" if data_range else ""
            
            # 对于随机递增计数函数，显示步进范围
            if function_type == "随机递增计数" and step_range and len(step_range) == 2:
                range_display = f"初始:{data_range[0]}-{data_range[1]}, 步进:{step_range[0]}-{step_range[1]}"
            
            # 显示Bit位配置信息
            bit_config_display = ""
            if bit_config:
                bit_count = len(bit_config)
                bit_list = []
                for bit, cfg in bit_config.items():
                    change_type = cfg.get('change_type', 'periodic')
                    change_type_display = "周期" if change_type == "periodic" else "随机"
                    bit_list.append(f"{bit}({change_type_display})")
                
                bit_list = bit_list[:3]  # 显示前3个bit位
                bit_config_display = f"{bit_count}个Bit位({','.join(bit_list)}{'...' if bit_count > 3 else ''})"
            
            # 构建树形视图行数据
            if register_type in ['coils', 'discrete_inputs']:
                tree.insert("", "end", values=(
                    address, value_type, value_display, interval, range_display, description
                ))
            else:
                tree.insert("", "end", values=(
                    address, value_type, value_display, data_type, interval, range_display, description, bit_config_display
                ))
    
    def edit_register(self, register_type):
        """编辑选中的寄存器配置"""
        tree = getattr(self, f"{register_type}_tree")
        selection = tree.selection()
        
        if not selection:
            messagebox.showwarning("警告", "请先选择一个配置项")
            return
        
        # 获取选中的配置项索引
        item = selection[0]
        index = tree.index(item)
        
        # 获取当前配置
        config = self.configs[register_type][index]
        
        # 打开编辑对话框
        self.add_register_dialog(register_type, config, is_edit=True)
    
    def delete_register(self, register_type):
        """删除选中的寄存器配置"""
        tree = getattr(self, f"{register_type}_tree")
        selection = tree.selection()
        
        if not selection:
            messagebox.showwarning("警告", "请先选择一个配置项")
            return
        
        if messagebox.askyesno("确认", "确定要删除选中的配置项吗？"):
            # 获取选中的配置项索引（倒序删除，避免索引变化）
            items = tree.selection()
            indices = [tree.index(item) for item in items]
            
            # 从大到小排序，避免删除时索引变化
            indices.sort(reverse=True)
            
            for index in indices:
                del self.configs[register_type][index]
            
            # 更新树形视图
            self.update_register_tree(register_type)
    
    def load_default_config(self):
        """加载默认配置，使用修复后的函数工厂"""
        # 重置配置
        self.configs = {
            'coils': [],
            'discrete_inputs': [],
            'holding_registers': [],
            'input_registers': []
        }
        
        # 线圈配置
        self.configs['coils'].append({
            'address': 0,
            'value': True,
            'interval': 1,
            'data_range': None,
            'step_range': None,
            'bit_config': {},
            'description': '设备电源',
            'function_type': None,
            'data_type': 'bool'
        })
        
        self.configs['coils'].append({
            'address': 1,
            'value': self.create_robust_boolean_function(),
            'interval': 5,
            'data_range': [0, 1],
            'step_range': None,
            'bit_config': {},
            'description': '随机开关',
            'function_type': '随机开关',
            'data_type': 'bool'
        })
        
        # 保持寄存器配置 - 多种数据类型示例
        self.configs['holding_registers'].append({
            'address': 0,
            'value': 1000,
            'interval': 1,
            'data_range': None,
            'step_range': None,
            'bit_config': {},
            'description': '速度设定',
            'function_type': None,
            'data_type': 'int16'
        })
        
        # 输入寄存器配置 - 使用修复后的函数工厂
        self.configs['input_registers'].append({
            'address': 0,
            'value': self.create_robust_random_function(20, 30, 'int16'),
            'interval': 2,
            'data_range': [20, 30],
            'step_range': None,
            'bit_config': {},
            'description': '温度传感器',
            'function_type': '随机值',
            'data_type': 'int16'
        })
        
        self.configs['input_registers'].append({
            'address': 1,
            'value': self.create_robust_random_function(40, 60, 'int16'),
            'interval': 3,
            'data_range': [40, 60],
            'step_range': None,
            'bit_config': {},
            'description': '湿度传感器',
            'function_type': '随机值',
            'data_type': 'int16'
        })
        
        # 新增Bit位配置示例 - 修复：添加变化类型
        self.configs['holding_registers'].append({
            'address': 100,
            'value': self.create_bit_periodic_function({}),
            'interval': 1,
            'data_range': None,
            'step_range': None,
            'bit_config': {
                '0': {'change_type': 'periodic', 'interval': 2, 'description': '开门状态'},
                '1': {'change_type': 'periodic', 'interval': 2, 'description': '关门状态'},
                '2': {'change_type': 'random', 'interval': 2, 'description': '自动模式'},
                '3': {'change_type': 'random', 'interval': 2, 'description': '手动模式'},
                '4': {'change_type': 'periodic', 'interval': 5, 'description': '隔离模式'},
                '5': {'change_type': 'random', 'interval': 3, 'description': '开门故障'},
                '6': {'change_type': 'random', 'interval': 3, 'description': '关门故障'},
                '7': {'change_type': 'periodic', 'interval': 10, 'description': 'DUC故障'},
                '8': {'change_type': 'periodic', 'interval': 10, 'description': '电机故障'},
                '9': {'change_type': 'random', 'interval': 5, 'description': '电磁锁故障'},
                '10': {'change_type': 'periodic', 'interval': 2, 'description': '手动解锁'}
            },
            'description': 'Bit位周期开关示例',
            'function_type': 'Bit位周期开关',
            'data_type': 'int16'
        })
        
        # 更新所有树形视图
        for register_type in self.configs.keys():
            self.update_register_tree(register_type)
        
        self.logger.info("默认配置已加载")
    
    def save_config(self):
        """保存配置到文件"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                # 准备可序列化的配置
                serializable_config = {}
                for reg_type, configs in self.configs.items():
                    serializable_config[reg_type] = []
                    for config in configs:
                        # 对于函数类型，保存更详细的信息以便准确重建
                        if callable(config['value']):
                            # 分析函数类型
                            function_info = self.analyze_function(config['value'], config.get('description', ''))
                            
                            # 修复：准确识别值类型
                            if isinstance(config.get('data_range'), list) and len(config['data_range']) > 2:
                                value_type = "随机列表"
                            else:
                                value_type = "函数"
                            
                            serializable_config[reg_type].append({
                                'address': config['address'],
                                'interval': config['interval'],
                                'data_range': config.get('data_range'),
                                'step_range': config.get('step_range'),  # 保存步进范围
                                'bit_config': config.get('bit_config', {}),  # 保存Bit位配置
                                'description': config.get('description', ''),
                                'value_type': value_type,
                                'function_info': function_info,
                                'function_type': config.get('function_type'),  # 存储函数类型
                                'data_type': config.get('data_type', 'int16'),  # 保存数据类型
                                'value': 'dynamic'
                            })
                        else:
                            # 修复：准确识别固定值类型
                            value_type = "固定值"
                            serializable_config[reg_type].append({
                                'address': config['address'],
                                'interval': config['interval'],
                                'data_range': config.get('data_range'),
                                'step_range': config.get('step_range'),  # 保存步进范围
                                'bit_config': config.get('bit_config', {}),  # 保存Bit位配置
                                'description': config.get('description', ''),
                                'value_type': value_type,
                                'function_type': config.get('function_type'),  # 存储函数类型
                                'data_type': config.get('data_type', 'int16'),  # 保存数据类型
                                'value': config['value']
                            })
                
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(serializable_config, f, indent=2, ensure_ascii=False)
                
                messagebox.showinfo("成功", "配置已保存")
                self.logger.info(f"配置已保存到 {filename}")
            except Exception as e:
                messagebox.showerror("错误", f"保存配置失败: {e}")
                self.logger.error(f"保存配置失败: {e}")
    
    def load_config(self):
        """从文件加载配置"""
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                
                # 重置当前配置
                self.configs = {
                    'coils': [],
                    'discrete_inputs': [],
                    'holding_registers': [],
                    'input_registers': []
                }
                
                # 加载配置
                for reg_type, configs in loaded_config.items():
                    for config in configs:
                        # 确保data_range变量始终存在
                        data_range = config.get('data_range')
                        step_range = config.get('step_range')  # 获取步进范围
                        bit_config = config.get('bit_config', {})  # 获取Bit位配置
                        value_type = config.get('value_type', '固定值')
                        description = config.get('description', '')
                        function_type = config.get('function_type')  # 获取存储的函数类型
                        data_type = config.get('data_type', 'int16')  # 获取数据类型
                        
                        # 修复：根据值类型重建函数
                        if value_type == '函数':
                            function_info = config.get('function_info', {})
                            
                            # 如果有保存的函数信息，使用它来重建函数
                            if function_info:
                                value = self.reconstruct_function_from_info(function_info, data_range, step_range)
                                self.logger.info(f"从function_info重建函数: {function_info.get('type', 'unknown')}")
                            elif function_type:
                                # 如果有存储的函数类型，使用它来重建函数
                                if function_type == "Bit位周期开关":
                                    # 对于Bit位函数，使用专门的函数
                                    value = self.create_bit_periodic_function(bit_config)
                                else:
                                    min_val = data_range[0] if data_range and len(data_range) >= 2 else 0
                                    max_val = data_range[1] if data_range and len(data_range) >= 2 else 100
                                    value = self.get_function_by_name(function_type, reg_type, min_val, max_val, data_type)
                                self.logger.info(f"从存储的函数类型重建函数: {function_type}")
                            else:
                                # 没有函数信息，使用描述推断
                                value = self.reconstruct_function_from_description(description, data_range, step_range)
                                self.logger.info(f"从描述重建函数: {description}")
                                
                        elif value_type == '随机列表':
                            # 随机列表类型
                            if data_range and isinstance(data_range, list) and len(data_range) > 2:
                                value = self.create_robust_random_list_function(data_range)
                                self.logger.info(f"创建随机列表函数: {len(data_range)}个值")
                            else:
                                value = 0
                                self.logger.warning("随机列表类型但数据范围无效，使用默认值0")
                                
                        elif value_type == '随机值':  # 修复：处理随机值类型
                            # 随机值类型
                            if data_range and len(data_range) >= 2:
                                value = self.create_robust_random_function(data_range[0], data_range[1], data_type)
                                self.logger.info(f"创建随机值函数: {data_range[0]}-{data_range[1]}")
                            else:
                                value = self.create_robust_random_function(0, 100, data_type)
                                self.logger.warning("随机值类型但数据范围无效，使用默认范围0-100")
                                
                        elif value_type == '固定值':
                            # 固定值类型
                            value = config['value']
                            self.logger.info(f"加载固定值: {value}")
                            
                        else:
                            # 未知类型，默认为固定值
                            value = config.get('value', 0)
                            self.logger.warning(f"未知值类型: {value_type}，使用固定值: {value}")
                    
                        self.configs[reg_type].append({
                            'address': config['address'],
                            'value': value,
                            'interval': config['interval'],
                            'data_range': data_range,
                            'step_range': step_range,  # 保存步进范围
                            'bit_config': bit_config,  # 保存Bit位配置
                            'description': description,
                            'function_type': function_type,  # 存储函数类型
                            'data_type': data_type  # 存储数据类型
                        })
                
                # 更新所有树形视图
                for register_type in self.configs.keys():
                    self.update_register_tree(register_type)
                
                messagebox.showinfo("成功", "配置已加载")
                self.logger.info(f"配置已从 {filename} 加载")
            except Exception as e:
                messagebox.showerror("错误", f"加载配置失败: {e}")
                self.logger.error(f"加载配置失败: {e}")
    
    def analyze_function(self, func, description=''):
        """分析函数类型和参数，返回可序列化的函数信息"""
        function_info = {
            'type': 'unknown',
            'description': description,
            'parameters': {}
        }
        
        # 根据描述和函数特征准确识别函数类型
        if '随机递增计数' in description:
            function_info['type'] = '随机递增计数'
            function_info['parameters'] = {
                'start': 0,
                'min_step': 1,
                'max_step': 10,
                'max_value': 65535
            }
        elif '递增计数' in description:
            function_info['type'] = '递增计数'
            function_info['parameters'] = {
                'start': 0,
                'step': 1,
                'max_value': 65535
            }
        elif '正弦波' in description:
            function_info['type'] = '正弦波'
            function_info['parameters'] = {
                'amplitude': 500,
                'offset': 1000,
                'frequency': 0.1
            }
        elif '周期开关' in description:
            function_info['type'] = '周期开关'
            function_info['parameters'] = {
                'period': 10
            }
        elif '随机开关' in description:
            function_info['type'] = '随机开关'
        elif '随机列表' in description:
            function_info['type'] = '随机列表'
        elif '时间戳' in description or '完整时间戳' in description:
            function_info['type'] = '完整时间戳'
        elif '年月日' in description:
            function_info['type'] = '年月日'
        elif '时分秒' in description:
            function_info['type'] = '时分秒'
        elif '随机' in description and '温度' in description:
            function_info['type'] = '随机温度'
        elif '随机' in description and '湿度' in description:
            function_info['type'] = '随机湿度'
        elif '随机' in description and '压力' in description:
            function_info['type'] = '随机压力'
        elif '工作日' in description:
            function_info['type'] = '工作日标志'
        elif 'Bit位' in description:
            function_info['type'] = 'Bit位周期开关'
        else:
            function_info['type'] = '随机值'  # 默认随机函数
        
        return function_info
    
    def reconstruct_function_from_info(self, function_info, data_range, step_range=None):
        """根据函数信息重建函数"""
        func_type = function_info.get('type', 'unknown')
        params = function_info.get('parameters', {})
        
        if func_type == '随机递增计数':
            start = params.get('start', 0)
            min_step = params.get('min_step', 1)
            max_step = params.get('max_step', 10)
            max_value = params.get('max_value', 65535)
            
            # 优先使用传入的步进范围
            if step_range and len(step_range) == 2:
                min_step = step_range[0]
                max_step = step_range[1]
            
            return self.create_random_increment_function(
                start=start, min_step=min_step, max_step=max_step, max_value=max_value
            )
        elif func_type == '递增计数':
            start = params.get('start', 0)
            step = params.get('step', 1)
            max_value = params.get('max_value', 65535)
            return self.create_ramp_function(start=start, step=step, max_value=max_value)
        elif func_type == '正弦波':
            amplitude = params.get('amplitude', 500)
            offset = params.get('offset', 1000)
            frequency = params.get('frequency', 0.1)
            return self.create_robust_sine_wave_function(amplitude, offset, frequency)
        elif func_type == '随机开关':
            return self.create_robust_boolean_function()
        elif func_type == '周期开关':
            period = params.get('period', 10)
            return self.create_robust_periodic_boolean_function(period=period)
        elif func_type == '随机列表':
            if data_range and isinstance(data_range, list) and len(data_range) > 2:
                return self.create_robust_random_list_function(data_range)
            else:
                return self.create_robust_random_list_function([0, 1])
        elif func_type == '完整时间戳':
            return lambda: int(time.time())
        elif func_type == '年月日':
            return lambda: int(datetime.now().strftime("%Y%m%d"))
        elif func_type == '时分秒':
            return lambda: int(datetime.now().strftime("%H%M%S"))
        elif func_type == '随机温度':
            if data_range and len(data_range) >= 2:
                return self.create_robust_random_function(data_range[0], data_range[1])
            else:
                return self.create_robust_random_function(20, 30)
        elif func_type == '随机湿度':
            if data_range and len(data_range) >= 2:
                return self.create_robust_random_function(data_range[0], data_range[1])
            else:
                return self.create_robust_random_function(40, 60)
        elif func_type == '随机压力':
            if data_range and len(data_range) >= 2:
                return self.create_robust_random_function(data_range[0], data_range[1])
            else:
                return self.create_robust_random_function(980, 1020)
        elif func_type == '工作日标志':
            return lambda: 1 if datetime.now().weekday() < 5 else 0
        elif func_type == 'Bit位周期开关':
            # 对于Bit位函数，返回固定值0
            return lambda: 0
        else:
            # 默认情况：使用随机函数
            if data_range and len(data_range) >= 2:
                return self.create_robust_random_function(data_range[0], data_range[1])
            else:
                return self.create_robust_random_function(0, 100)
    
    def reconstruct_function_from_description(self, description, data_range, step_range=None):
        """根据描述和数据范围重建函数"""
        if '随机递增计数' in description:
            start = data_range[0] if data_range and len(data_range) >= 2 else 0
            max_val = data_range[1] if data_range and len(data_range) >= 2 else 65535
            min_step = step_range[0] if step_range and len(step_range) >= 2 else 1
            max_step = step_range[1] if step_range and len(step_range) >= 2 else 10
            return self.create_random_increment_function(start=start, min_step=min_step, max_step=max_step, max_value=max_val+1)
        elif '递增计数' in description:
            start = data_range[0] if data_range and len(data_range) >= 2 else 0
            max_val = data_range[1] if data_range and len(data_range) >= 2 else 65535
            return self.create_ramp_function(start=start, step=1, max_value=max_val+1)
        elif '正弦波' in description:
            if data_range and len(data_range) >= 2:
                amplitude = (data_range[1] - data_range[0]) / 2
                offset = data_range[0] + amplitude
            else:
                amplitude = 250
                offset = 500
            return self.create_robust_sine_wave_function(amplitude=amplitude, offset=offset, frequency=0.05)
        elif '随机开关' in description:
            return self.create_robust_boolean_function()
        elif '周期开关' in description:
            return self.create_robust_periodic_boolean_function()
        elif '时间戳' in description or '完整时间戳' in description:
            return lambda: int(time.time())
        elif '年月日' in description:
            return lambda: int(datetime.now().strftime("%Y%m%d"))
        elif '时分秒' in description:
            return lambda: int(datetime.now().strftime("%H%M%S"))
        elif '温度' in description:
            if data_range and len(data_range) >= 2:
                return self.create_robust_random_function(data_range[0], data_range[1])
            else:
                return self.create_robust_random_function(20, 30)
        elif '湿度' in description:
            if data_range and len(data_range) >= 2:
                return self.create_robust_random_function(data_range[0], data_range[1])
            else:
                return self.create_robust_random_function(40, 60)
        elif '压力' in description:
            if data_range and len(data_range) >= 2:
                return self.create_robust_random_function(data_range[0], data_range[1])
            else:
                return self.create_robust_random_function(980, 1020)
        elif '工作日' in description:
            return lambda: 1 if datetime.now().weekday() < 5 else 0
        elif 'Bit位' in description:
            # 对于Bit位函数，返回固定值0
            return lambda: 0
        else:
            # 默认情况：使用随机函数
            if data_range and len(data_range) >= 2:
                return self.create_robust_random_function(data_range[0], data_range[1])
            else:
                return self.create_robust_random_function(0, 100)
    
    def import_excel(self):
        """从Excel文件导入配置"""
        filename = filedialog.askopenfilename(
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                # 读取Excel文件
                df = pd.read_excel(filename)
                
                # 重置当前配置
                self.configs = {
                    'coils': [],
                    'discrete_inputs': [],
                    'holding_registers': [],
                    'input_registers': []
                }
                
                # 处理每一行数据
                for _, row in df.iterrows():
                    reg_type = row.get('类型', '').strip().lower()
                    address = int(row.get('地址', 0))
                    value_type = row.get('值类型', '固定值').strip()
                    value_data = row.get('值', '0')
                    data_type = row.get('数据类型', 'int16').strip()
                    interval = float(row.get('间隔', 1))
                    min_range = row.get('最小值')
                    max_range = row.get('最大值')
                    min_step = row.get('最小步进')  # 新增：最小步进
                    max_step = row.get('最大步进')  # 新增：最大步进
                    list_values = row.get('数字列表', '')
                    description = row.get('描述', '')
                    function_type = row.get('函数类型', '')
                    bit_config_str = row.get('Bit位配置', '')  # 新增：Bit位配置
                    
                    # 解析Bit位配置
                    bit_config = {}
                    if bit_config_str and isinstance(bit_config_str, str):
                        try:
                            # Bit位配置格式: "0:periodic:2:开门状态,1:random:2:关门状态"
                            bit_items = bit_config_str.split(',')
                            for item in bit_items:
                                if ':' in item:
                                    parts = item.split(':')
                                    if len(parts) >= 4:
                                        bit_pos = parts[0].strip()
                                        change_type = parts[1].strip()  # 变化类型
                                        bit_interval = float(parts[2].strip())
                                        bit_desc = parts[3].strip()
                                        bit_config[bit_pos] = {
                                            'change_type': change_type,  # 存储变化类型
                                            'interval': bit_interval,
                                            'description': bit_desc
                                        }
                        except Exception as e:
                            self.logger.warning(f"解析Bit位配置失败: {e}")
                    
                    # 修复：确保data_range变量始终存在且正确处理
                    data_range = None
                    step_range = None  # 初始化步进范围
                    
                    # 修复：清晰的值类型处理逻辑
                    if value_type == '固定值':
                        # 修复：正确处理不同类型的值
                        if reg_type in ['coils', 'discrete_inputs']:
                            # 对于布尔类型，确保值是字符串
                            if isinstance(value_data, str):
                                value = value_data.lower() == 'true'
                            else:
                                # 如果是数字，1为True，0为False
                                value = bool(value_data)
                        else:
                            # 对于其他类型，直接使用convert_value_by_type
                            # 确保传入的是字符串
                            if pd.isna(value_data):
                                value_str = "0"
                            else:
                                value_str = str(value_data)
                            value = self.convert_value_by_type(value_str, data_type)
                        data_range = None
                        step_range = None
                        stored_function_type = None
                        
                    elif value_type == '随机值':
                        # 使用函数工厂确保范围值被正确捕获
                        min_val = self.convert_value_by_type(min_range, data_type) if pd.notna(min_range) else 0
                        max_val = self.convert_value_by_type(max_range, data_type) if pd.notna(max_range) else 100
                        data_range = [min_val, max_val]
                        # 对于布尔范围 [0,1]，使用专门的布尔函数
                        if data_type == 'bool' or (min_val == 0 and max_val == 1):
                            value = self.create_robust_boolean_function()
                            stored_function_type = "随机开关"
                        else:
                            value = self.create_robust_random_function(min_val, max_val, data_type)
                            stored_function_type = "随机值"  # 修复：正确设置为随机值类型
                            
                    elif value_type == '随机列表':
                        if pd.notna(list_values) and list_values:
                            try:
                                # 解析数字列表
                                number_list = [self.convert_value_by_type(x.strip(), data_type) for x in str(list_values).split(',')]
                                value = self.create_robust_random_list_function(number_list)
                                data_range = number_list
                                stored_function_type = "随机列表"
                            except (ValueError, TypeError) as e:
                                self.logger.warning(f"解析数字列表失败: {e}, 使用默认值0")
                                value = 0
                                data_range = None
                                stored_function_type = None
                        else:
                            self.logger.warning("随机列表类型但未提供数字列表，使用默认值0")
                            value = 0
                            data_range = None
                            stored_function_type = None
                            
                    else:  # 函数类型
                        # 修复：优先使用函数类型列
                        if function_type:
                            # 使用中文函数类型
                            if function_type == "Bit位周期开关":
                                # 对于Bit位函数，使用专门的函数
                                value = self.create_bit_periodic_function(bit_config)
                                stored_function_type = "Bit位周期开关"
                                data_range = None
                                step_range = None
                            else:
                                min_val = self.convert_value_by_type(min_range, data_type) if pd.notna(min_range) else 0
                                max_val = self.convert_value_by_type(max_range, data_type) if pd.notna(max_range) else 100
                                
                                # 对于随机递增计数函数，处理步进范围
                                if function_type == "随机递增计数":
                                    min_step_val = int(min_step) if pd.notna(min_step) else 1
                                    max_step_val = int(max_step) if pd.notna(max_step) else 10
                                    value = self.create_random_increment_function(
                                        start=min_val, 
                                        min_step=min_step_val, 
                                        max_step=max_step_val, 
                                        max_value=max_val,
                                        data_type=data_type
                                    )
                                    step_range = [min_step_val, max_step_val]
                                else:
                                    value = self.get_function_by_name(function_type, reg_type, min_val, max_val, data_type)
                                    step_range = None
                                
                                stored_function_type = function_type
                                self.logger.info(f"使用函数类型: {function_type}")
                                
                                # 设置数据范围
                                if function_type in ['随机值', '随机温度', '随机湿度', '随机压力', 
                                                   '随机递增计数', '递增计数', '正弦波'] and pd.notna(min_range) and pd.notna(max_range):
                                    data_range = [min_val, max_val]
                                elif function_type == '随机列表' and pd.notna(list_values) and list_values:
                                    try:
                                        data_range = [self.convert_value_by_type(x.strip(), data_type) for x in str(list_values).split(',')]
                                    except (ValueError, TypeError):
                                        data_range = None
                                else:
                                    data_range = None
                        else:
                            # 根据描述推断函数类型
                            value = self.reconstruct_function_from_description(description, data_range)
                            stored_function_type = None
                            self.logger.info(f"根据描述推断函数类型: {description}")
                    
                    # 添加到配置
                    if reg_type in self.configs:
                        self.configs[reg_type].append({
                            'address': address,
                            'value': value,
                            'interval': interval,
                            'data_range': data_range,
                            'step_range': step_range,  # 保存步进范围
                            'bit_config': bit_config,  # 保存Bit位配置
                            'description': description,
                            'function_type': stored_function_type,
                            'data_type': data_type  # 存储数据类型
                        })
                        self.logger.info(f"导入配置: {reg_type}[{address}] = {value_type}, 函数类型: {function_type}, 数据类型: {data_type}")
                
                # 更新所有树形视图
                for register_type in self.configs.keys():
                    self.update_register_tree(register_type)
                
                # 如果服务器正在运行，重新应用配置
                if self.is_running and self.simulator:
                    self.apply_config_to_simulator()
                
                messagebox.showinfo("成功", "Excel配置已导入")
                self.logger.info(f"Excel配置已从 {filename} 导入")
            except Exception as e:
                messagebox.showerror("错误", f"导入Excel配置失败: {e}")
                self.logger.error(f"导入Excel配置失败: {e}")
    
    def export_excel(self):
        """导出配置到Excel文件"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                # 创建工作簿
                wb = Workbook()
                ws = wb.active
                ws.title = "Modbus配置"
                
                # 添加表头
                headers = ["类型", "地址", "值类型", "函数类型", "数据类型", "值", "间隔", "最小值", "最大值", "最小步进", "最大步进", "数字列表", "Bit位配置", "描述"]
                ws.append(headers)
                
                # 添加数据
                for reg_type, configs in self.configs.items():
                    for config in configs:
                        address = config['address']
                        value = config['value']
                        interval = config['interval']
                        data_range = config.get('data_range')
                        step_range = config.get('step_range')  # 获取步进范围
                        bit_config = config.get('bit_config', {})  # 获取Bit位配置
                        description = config.get('description', '')
                        function_type = config.get('function_type', '')
                        data_type = config.get('data_type', 'int16')
                        
                        # 修复：准确识别值类型和函数类型
                        if callable(value):
                            # 检查是否是随机列表函数
                            if isinstance(data_range, list) and len(data_range) > 2:
                                value_type = "随机列表"
                                value_display = "动态生成"
                                list_values = ','.join(map(str, data_range))
                                # 使用存储的函数类型
                                if not function_type:
                                    function_type = "随机列表"
                            else:
                                value_type = "函数"
                                value_display = "动态生成"
                                list_values = ""
                                # 使用存储的函数类型，如果没有则根据描述推断
                                if not function_type:
                                    function_info = self.analyze_function(value, description)
                                    function_type = function_info.get('type', '未知')
                        else:
                            value_type = "固定值"
                            value_display = str(value)
                            list_values = ""
                        
                        # 确定范围
                        min_val = data_range[0] if data_range and isinstance(data_range, list) and len(data_range) == 2 else ""
                        max_val = data_range[1] if data_range and isinstance(data_range, list) and len(data_range) == 2 else ""
                        
                        # 确定步进范围
                        min_step_val = step_range[0] if step_range and len(step_range) == 2 else ""
                        max_step_val = step_range[1] if step_range and len(step_range) == 2 else ""
                        
                        # 格式化Bit位配置
                        bit_config_str = ""
                        if bit_config:
                            bit_items = []
                            for bit, cfg in bit_config.items():
                                change_type = cfg.get('change_type', 'periodic')
                                bit_items.append(f"{bit}:{change_type}:{cfg.get('interval', '')}:{cfg.get('description', '')}")
                            bit_config_str = ','.join(bit_items)
                        
                        # 添加行
                        ws.append([
                            reg_type, address, value_type, function_type, data_type, value_display, 
                            interval, min_val, max_val, min_step_val, max_step_val, list_values, bit_config_str, description
                        ])
                
                # 保存文件
                wb.save(filename)
                messagebox.showinfo("成功", "配置已导出到Excel")
                self.logger.info(f"配置已导出到 {filename}")
            except Exception as e:
                messagebox.showerror("错误", f"导出Excel配置失败: {e}")
                self.logger.error(f"导出Excel配置失败: {e}")
    
    def import_csv(self):
        """从CSV文件导入配置"""
        filename = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                # 读取CSV文件
                df = pd.read_csv(filename)
                
                # 重置当前配置
                self.configs = {
                    'coils': [],
                    'discrete_inputs': [],
                    'holding_registers': [],
                    'input_registers': []
                }
                
                # 处理每一行数据
                for _, row in df.iterrows():
                    reg_type = row.get('类型', '').strip().lower()
                    address = int(row.get('地址', 0))
                    value_type = row.get('值类型', '固定值').strip()
                    value_data = row.get('值', '0')
                    data_type = row.get('数据类型', 'int16').strip()
                    interval = float(row.get('间隔', 1))
                    min_range = row.get('最小值')
                    max_range = row.get('最大值')
                    min_step = row.get('最小步进')  # 新增：最小步进
                    max_step = row.get('最大步进')  # 新增：最大步进
                    list_values = row.get('数字列表', '')
                    description = row.get('描述', '')
                    function_type = row.get('函数类型', '')
                    bit_config_str = row.get('Bit位配置', '')  # 新增：Bit位配置
                    
                    # 解析Bit位配置
                    bit_config = {}
                    if bit_config_str and isinstance(bit_config_str, str):
                        try:
                            # Bit位配置格式: "0:periodic:2:开门状态,1:random:2:关门状态"
                            bit_items = bit_config_str.split(',')
                            for item in bit_items:
                                if ':' in item:
                                    parts = item.split(':')
                                    if len(parts) >= 4:
                                        bit_pos = parts[0].strip()
                                        change_type = parts[1].strip()  # 变化类型
                                        bit_interval = float(parts[2].strip())
                                        bit_desc = parts[3].strip()
                                        bit_config[bit_pos] = {
                                            'change_type': change_type,  # 存储变化类型
                                            'interval': bit_interval,
                                            'description': bit_desc
                                        }
                        except Exception as e:
                            self.logger.warning(f"解析Bit位配置失败: {e}")
                    
                    # 修复：确保data_range变量始终存在且正确处理
                    data_range = None
                    step_range = None  # 初始化步进范围
                    
                    # 修复：清晰的值类型处理逻辑
                    if value_type == '固定值':
                        # 修复：正确处理不同类型的值
                        if reg_type in ['coils', 'discrete_inputs']:
                            # 对于布尔类型，确保值是字符串
                            if isinstance(value_data, str):
                                value = value_data.lower() == 'true'
                            else:
                                # 如果是数字，1为True，0为False
                                value = bool(value_data)
                        else:
                            # 对于其他类型，直接使用convert_value_by_type
                            # 确保传入的是字符串
                            if pd.isna(value_data):
                                value_str = "0"
                            else:
                                value_str = str(value_data)
                            value = self.convert_value_by_type(value_str, data_type)
                        data_range = None
                        step_range = None
                        stored_function_type = None
                        
                    elif value_type == '随机值':
                        # 使用函数工厂确保范围值被正确捕获
                        min_val = self.convert_value_by_type(min_range, data_type) if pd.notna(min_range) else 0
                        max_val = self.convert_value_by_type(max_range, data_type) if pd.notna(max_range) else 100
                        data_range = [min_val, max_val]
                        # 对于布尔范围 [0,1]，使用专门的布尔函数
                        if data_type == 'bool' or (min_val == 0 and max_val == 1):
                            value = self.create_robust_boolean_function()
                            stored_function_type = "随机开关"
                        else:
                            value = self.create_robust_random_function(min_val, max_val, data_type)
                            stored_function_type = "随机值"  # 修复：正确设置为随机值类型
                            
                    elif value_type == '随机列表':
                        if pd.notna(list_values) and list_values:
                            try:
                                # 解析数字列表
                                number_list = [self.convert_value_by_type(x.strip(), data_type) for x in str(list_values).split(',')]
                                value = self.create_robust_random_list_function(number_list)
                                data_range = number_list
                                stored_function_type = "随机列表"
                            except (ValueError, TypeError) as e:
                                self.logger.warning(f"解析数字列表失败: {e}, 使用默认值0")
                                value = 0
                                data_range = None
                                stored_function_type = None
                        else:
                            self.logger.warning("随机列表类型但未提供数字列表，使用默认值0")
                            value = 0
                            data_range = None
                            stored_function_type = None
                            
                    else:  # 函数类型
                        # 修复：优先使用函数类型列
                        if function_type:
                            # 使用中文函数类型
                            if function_type == "Bit位周期开关":
                                # 对于Bit位函数，使用专门的函数
                                value = self.create_bit_periodic_function(bit_config)
                                stored_function_type = "Bit位周期开关"
                                data_range = None
                                step_range = None
                            else:
                                min_val = self.convert_value_by_type(min_range, data_type) if pd.notna(min_range) else 0
                                max_val = self.convert_value_by_type(max_range, data_type) if pd.notna(max_range) else 100
                                
                                # 对于随机递增计数函数，处理步进范围
                                if function_type == "随机递增计数":
                                    min_step_val = int(min_step) if pd.notna(min_step) else 1
                                    max_step_val = int(max_step) if pd.notna(max_step) else 10
                                    value = self.create_random_increment_function(
                                        start=min_val, 
                                        min_step=min_step_val, 
                                        max_step=max_step_val, 
                                        max_value=max_val,
                                        data_type=data_type
                                    )
                                    step_range = [min_step_val, max_step_val]
                                else:
                                    value = self.get_function_by_name(function_type, reg_type, min_val, max_val, data_type)
                                    step_range = None
                                
                                stored_function_type = function_type
                                self.logger.info(f"使用函数类型: {function_type}")
                                
                                # 设置数据范围
                                if function_type in ['随机值', '随机温度', '随机湿度', '随机压力', 
                                                   '随机递增计数', '递增计数', '正弦波'] and pd.notna(min_range) and pd.notna(max_range):
                                    data_range = [min_val, max_val]
                                elif function_type == '随机列表' and pd.notna(list_values) and list_values:
                                    try:
                                        data_range = [self.convert_value_by_type(x.strip(), data_type) for x in str(list_values).split(',')]
                                    except (ValueError, TypeError):
                                        data_range = None
                                else:
                                    data_range = None
                        else:
                            # 根据描述推断函数类型
                            value = self.reconstruct_function_from_description(description, data_range)
                            stored_function_type = None
                            self.logger.info(f"根据描述推断函数类型: {description}")
                    
                    # 添加到配置
                    if reg_type in self.configs:
                        self.configs[reg_type].append({
                            'address': address,
                            'value': value,
                            'interval': interval,
                            'data_range': data_range,
                            'step_range': step_range,  # 保存步进范围
                            'bit_config': bit_config,  # 保存Bit位配置
                            'description': description,
                            'function_type': stored_function_type,
                            'data_type': data_type  # 存储数据类型
                        })
                        self.logger.info(f"导入配置: {reg_type}[{address}] = {value_type}, 函数类型: {function_type}, 数据类型: {data_type}")
                
                # 更新所有树形视图
                for register_type in self.configs.keys():
                    self.update_register_tree(register_type)
                
                # 如果服务器正在运行，重新应用配置
                if self.is_running and self.simulator:
                    self.apply_config_to_simulator()
                
                messagebox.showinfo("成功", "CSV配置已导入")
                self.logger.info(f"CSV配置已从 {filename} 导入")
            except Exception as e:
                messagebox.showerror("错误", f"导入CSV配置失败: {e}")
                self.logger.error(f"导入CSV配置失败: {e}")
    
    def export_csv(self):
        """导出配置到CSV文件"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                # 准备数据
                data = []
                for reg_type, configs in self.configs.items():
                    for config in configs:
                        address = config['address']
                        value = config['value']
                        interval = config['interval']
                        data_range = config.get('data_range')
                        step_range = config.get('step_range')  # 获取步进范围
                        bit_config = config.get('bit_config', {})  # 获取Bit位配置
                        description = config.get('description', '')
                        function_type = config.get('function_type', '')
                        data_type = config.get('data_type', 'int16')
                        
                        # 修复：准确识别值类型和函数类型
                        if callable(value):
                            # 检查是否是随机列表函数
                            if isinstance(data_range, list) and len(data_range) > 2:
                                value_type = "随机列表"
                                value_display = "动态生成"
                                list_values = ','.join(map(str, data_range))
                                # 使用存储的函数类型
                                if not function_type:
                                    function_type = "随机列表"
                            else:
                                value_type = "函数"
                                value_display = "动态生成"
                                list_values = ""
                                # 使用存储的函数类型，如果没有则根据描述推断
                                if not function_type:
                                    function_info = self.analyze_function(value, description)
                                    function_type = function_info.get('type', '未知')
                        else:
                            value_type = "固定值"
                            value_display = str(value)
                            list_values = ""
                        
                        # 确定范围
                        min_val = data_range[0] if data_range and isinstance(data_range, list) and len(data_range) == 2 else ""
                        max_val = data_range[1] if data_range and isinstance(data_range, list) and len(data_range) == 2 else ""
                        
                        # 确定步进范围
                        min_step_val = step_range[0] if step_range and len(step_range) == 2 else ""
                        max_step_val = step_range[1] if step_range and len(step_range) == 2 else ""
                        
                        # 格式化Bit位配置
                        bit_config_str = ""
                        if bit_config:
                            bit_items = []
                            for bit, cfg in bit_config.items():
                                change_type = cfg.get('change_type', 'periodic')
                                bit_items.append(f"{bit}:{change_type}:{cfg.get('interval', '')}:{cfg.get('description', '')}")
                            bit_config_str = ','.join(bit_items)
                        
                        # 添加行
                        data.append([
                            reg_type, address, value_type, function_type, data_type, value_display, 
                            interval, min_val, max_val, min_step_val, max_step_val, list_values, bit_config_str, description
                        ])
                
                # 创建DataFrame并保存
                df = pd.DataFrame(data, columns=["类型", "地址", "值类型", "函数类型", "数据类型", "值", "间隔", "最小值", "最大值", "最小步进", "最大步进", "数字列表", "Bit位配置", "描述"])
                df.to_csv(filename, index=False, encoding='utf-8-sig')
                
                messagebox.showinfo("成功", "配置已导出到CSV")
                self.logger.info(f"配置已导出到 {filename}")
            except Exception as e:
                messagebox.showerror("错误", f"导出CSV配置失败: {e}")
                self.logger.error(f"导出CSV配置失败: {e}")
    
    def reset_config(self):
        """重置所有配置"""
        if messagebox.askyesno("确认", "确定要重置所有配置吗？"):
            self.configs = {
                'coils': [],
                'discrete_inputs': [],
                'holding_registers': [],
                'input_registers': []
            }
            
            # 更新所有树形视图
            for register_type in self.configs.keys():
                self.update_register_tree(register_type)
            
            self.logger.info("配置已重置")
    
    def apply_config_to_simulator(self):
        """将当前配置应用到模拟器"""
        if self.simulator:
            # 清空模拟器现有配置
            self.simulator.data_config = {
                'coils': {},
                'discrete_inputs': {},
                'holding_registers': {},
                'input_registers': {}
            }
            
            # 清空Bit位配置
            self.simulator.bit_config = {
                'holding_registers': {},
                'input_registers': {}
            }
            
            # 应用新配置
            for reg_type, configs in self.configs.items():
                for config in configs:
                    # 应用配置到模拟器
                    self.simulator.set_data_config(
                        reg_type,
                        config['address'],
                        config['value'],
                        config['interval'],
                        config.get('data_range'),
                        config.get('data_type', 'int16')  # 传递数据类型
                    )
                    
                    # 应用Bit位配置（仅对寄存器类型）
                    if reg_type in ['holding_registers', 'input_registers'] and config.get('bit_config'):
                        bit_configs = {}
                        for bit, bit_cfg in config['bit_config'].items():
                            change_type = bit_cfg.get('change_type', 'periodic')
                            interval = bit_cfg.get('interval', 2)
                            
                            # 根据变化类型选择不同的函数
                            if change_type == 'periodic':
                                # 周期变化
                                value_func = self.create_robust_periodic_boolean_function(period=interval)
                            else:
                                # 随机变化
                                value_func = self.create_robust_boolean_function()
                            
                            bit_configs[int(bit)] = {
                                'value': value_func,
                                'interval': interval,
                                'description': bit_cfg.get('description', f'Bit{bit}')
                            }
                        
                        if bit_configs:
                            self.simulator.set_bit_config(reg_type, config['address'], bit_configs)
            
            self.logger.info("配置已应用到模拟器")
    
    def start_server(self):
        """启动Modbus服务器"""
        try:
            ip = self.ip_entry.get()
            port = int(self.port_entry.get())
            
            # 创建扩展模拟器
            self.simulator = ExtendedModbusTCPSimulator(ip, port, self.simulator_callback)
            
            # 保存原始配置
            self.simulator.save_original_config()
            
            # 应用配置
            self.apply_config_to_simulator()
            
            # 在后台线程中启动服务器
            self.is_running = True
            self.simulator_thread = threading.Thread(target=self.simulator.start)
            self.simulator_thread.daemon = True
            self.simulator_thread.start()
            
            # 记录启动时间
            self.start_time = time.time()
            self.request_count = 0
            self.client_connections = []
            
            # 更新UI状态
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.status_var.set(f"服务器运行中 - {ip}:{port}")
            
            # 启动监控更新
            self.update_monitor()
            
            messagebox.showinfo("成功", "Modbus服务器已启动")
            self.logger.info(f"Modbus服务器已启动在 {ip}:{port}")
            
        except Exception as e:
            messagebox.showerror("错误", f"启动服务器失败: {e}")
            self.logger.error(f"启动服务器失败: {e}")
    
    def stop_server(self):
        """停止Modbus服务器"""
        if self.simulator:
            # 停止服务器
            self.simulator.stop()
            
            # 重置数据到初始状态
            self.simulator.reset_data()
            
            self.is_running = False
            
            # 更新UI状态
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.status_var.set("服务器已停止")
            
            messagebox.showinfo("成功", "Modbus服务器已停止，数据已重置")
            self.logger.info("Modbus服务器已停止，数据已重置")
    
    def update_monitor(self):
        """更新监控信息"""
        if self.is_running and self.simulator:
            # 更新运行时间
            if self.start_time:
                uptime = int(time.time() - self.start_time)
                hours = uptime // 3600
                minutes = (uptime % 3600) // 60
                seconds = uptime % 60
                self.uptime_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
            
            # 更新客户端连接数
            self.client_count_var.set(str(len(self.simulator.active_clients)))
            
            # 更新请求计数
            total_requests = sum(client['request_count'] for client in self.simulator.active_clients.values())
            self.request_count_var.set(str(total_requests))
            
            # 注意：客户端列表不再自动刷新，只在用户点击"刷新"按钮时更新
            # 这样可以避免选中客户端时列表自动刷新导致无法断开
            
            # 每秒更新一次
            self.root.after(1000, self.update_monitor)
    
    def refresh_monitor(self):
        """刷新监控信息"""
        if self.simulator:
            # 清空客户端列表
            for item in self.client_tree.get_children():
                self.client_tree.delete(item)
            
            # 添加当前客户端连接
            clients = self.simulator.get_active_clients()
            for client in clients:
                self.client_tree.insert("", "end", values=client)
    
    def clear_log(self):
        """清空日志"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.logger.info("GUI日志已清空")
    
    def disconnect_client(self):
        """断开选中的客户端"""
        selection = self.client_tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个客户端")
            return
        
        # 获取选中的客户端信息
        item = selection[0]
        values = self.client_tree.item(item, 'values')
        ip = values[0]
        port = int(values[1])
        address = (ip, port)
        
        # 断开客户端连接
        if self.simulator and address in self.simulator.active_clients:
            client_socket = self.simulator.active_clients[address]['socket']
            try:
                client_socket.close()
            except:
                pass
            
            # 从活跃客户端中移除
            del self.simulator.active_clients[address]
            
            # 更新监控
            self.refresh_monitor()
            messagebox.showinfo("成功", f"已断开客户端 {ip}:{port}")
            self.logger.info(f"已断开客户端 {ip}:{port}")
        else:
            messagebox.showwarning("警告", "无法找到选中的客户端")
            self.logger.warning(f"无法找到客户端 {ip}:{port}")
    
    def add_client_connection(self, address):
        """添加客户端连接"""
        ip, port = address
        connect_time = datetime.now().strftime("%H:%M:%S")
        
        # 添加日志
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{connect_time}] 客户端连接: {ip}:{port}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        self.logger.info(f"客户端连接: {ip}:{port}")
    
    def remove_client_connection(self, address):
        """移除客户端连接"""
        ip, port = address
        disconnect_time = datetime.now().strftime("%H:%M:%S")
        
        # 添加日志
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{disconnect_time}] 客户端断开: {ip}:{port}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        self.logger.info(f"客户端断开: {ip}:{port}")
    
    def add_request_log(self, request_info):
        """添加请求日志"""
        log_time = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{log_time}] {request_info}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        self.logger.info(request_info)

    def show_help(self):
        """显示使用帮助"""
        help_window = tk.Toplevel(self.root)
        help_window.title("Modbus数据模拟器使用帮助")
        help_window.geometry("900x700")
        help_window.transient(self.root)
        
        # 创建滚动文本框
        help_text = scrolledtext.ScrolledText(help_window, wrap=tk.WORD, width=100, height=40)
        help_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 读取帮助内容
        try:
            with open('使用功能说明.md', 'r', encoding='utf-8') as f:
                help_content = f.read()
        except FileNotFoundError:
            help_content = "帮助文件未找到，请确保 '使用功能说明.md' 文件存在。"
        
        # 插入帮助内容
        help_text.insert(tk.END, help_content)
        help_text.config(state=tk.DISABLED)
        
        # 添加关闭按钮
        close_button = ttk.Button(help_window, text="关闭", command=help_window.destroy)
        close_button.pack(pady=10)
        

if __name__ == "__main__":
    root = tk.Tk()
    app = ModbusConfigGUI(root)
    root.mainloop()