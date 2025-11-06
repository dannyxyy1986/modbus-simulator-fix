# modbus_simulator_final.py
import socket
import struct
import threading
import time
import random
from datetime import datetime
import json
import logging
import inspect

class ModbusTCPSimulator:
    def __init__(self, host='localhost', port=502):
        self.host = host
        self.port = port
        self.running = False
        self.server_socket = None
        self.data_config = {
            'coils': {},
            'discrete_inputs': {},
            'holding_registers': {},
            'input_registers': {}
        }
        # 新增：bit位配置存储
        self.bit_config = {
            'holding_registers': {},
            'input_registers': {}
        }
        self.setup_logging()
    
    def setup_logging(self):
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('modbus_simulator.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def set_data_config(self, address_type, address, value, interval=1, data_range=None, data_type='int16'):
        if address_type not in self.data_config:
            raise ValueError(f"不支持的地址类型: {address_type}")
            
        self.data_config[address_type][address] = {
            'value': value,
            'interval': interval,
            'last_update': 0,
            'data_range': data_range,
            'data_type': data_type  # 新增数据类型字段
        }
        self.logger.info(f"设置 {address_type}[{address}] = {value}, 间隔: {interval}s, 范围: {data_range}, 类型: {data_type}")
        
        # 立即初始化值
        current_time = time.time()
        config = self.data_config[address_type][address]
        config['last_update'] = current_time
        config['current_value'] = self.generate_data(config, current_time)
        self.logger.info(f"初始化 {address_type}[{address}] = {config['current_value']} (类型: {type(config['current_value'])})")
    
    # 新增方法：设置bit位配置
    def set_bit_config(self, address_type, address, bit_configs):
        """
        设置寄存器的bit位配置
        address_type: 'holding_registers' 或 'input_registers'
        address: 寄存器地址
        bit_configs: 字典，key为bit位(0-15)，value为配置字典
        """
        if address_type not in self.bit_config:
            raise ValueError(f"不支持的地址类型: {address_type}")
            
        if address not in self.bit_config[address_type]:
            self.bit_config[address_type][address] = {}
            
        for bit, config in bit_configs.items():
            if bit < 0 or bit > 15:
                raise ValueError(f"Bit位必须在0-15之间: {bit}")
                
            self.bit_config[address_type][address][bit] = {
                'value': config.get('value', 0),
                'interval': config.get('interval', 1),
                'last_update': 0,
                'data_range': config.get('data_range'),
                'data_type': 'bool',  # bit位只能是布尔类型
                'description': config.get('description', f'Bit{bit}'),
                'is_bit_config': True  # 标记这是bit配置
            }
            
            # 初始化bit值
            current_time = time.time()
            bit_config = self.bit_config[address_type][address][bit]
            bit_config['last_update'] = current_time
            bit_config['current_value'] = self.generate_data(bit_config, current_time)
        
        self.logger.info(f"设置 {address_type}[{address}] 的bit位配置: {list(bit_configs.keys())}")
    
    def generate_data(self, config, current_time):
        """根据配置生成数据 - 扩展支持bit位"""
        # 如果是bit配置，直接处理
        if config.get('is_bit_config', False):
            value = config['value']
            data_type = config.get('data_type', 'bool')
            
            if callable(value):
                try:
                    sig = inspect.signature(value)
                    param_count = len(sig.parameters)
                    
                    if config['data_range']:
                        if param_count == 2:
                            raw_value = value(config['data_range'][0], config['data_range'][1])
                        elif param_count == 1:
                            raw_value = value(config['data_range'])
                        else:
                            raw_value = value()
                    else:
                        if param_count > 0:
                            self.logger.warning(f"函数需要参数但未配置数据范围，使用默认调用")
                            raw_value = value()
                        else:
                            raw_value = value()
                    
                    # 根据数据类型转换结果
                    return self.convert_to_data_type(raw_value, data_type)
                except Exception as e:
                    self.logger.error(f"数据生成函数错误: {e}")
                    return self.convert_to_data_type(0, data_type)
            else:
                return self.convert_to_data_type(value, data_type)
        
        # 原有逻辑保持不变
        value = config['value']
        data_type = config.get('data_type', 'int16')
        
        if callable(value):
            try:
                sig = inspect.signature(value)
                param_count = len(sig.parameters)
                
                if config['data_range']:
                    if param_count == 2:
                        raw_value = value(config['data_range'][0], config['data_range'][1])
                    elif param_count == 1:
                        raw_value = value(config['data_range'])
                    else:
                        raw_value = value()
                else:
                    if param_count > 0:
                        self.logger.warning(f"函数需要参数但未配置数据范围，使用默认调用")
                        raw_value = value()
                    else:
                        raw_value = value()
                
                # 根据数据类型转换结果
                return self.convert_to_data_type(raw_value, data_type)
            except Exception as e:
                self.logger.error(f"数据生成函数错误: {e}")
                return self.convert_to_data_type(0, data_type)
        else:
            return self.convert_to_data_type(value, data_type)

    def convert_to_data_type(self, value, data_type):
        """将值转换为指定的数据类型"""
        try:
            if data_type == 'int16':
                return int(value) & 0xFFFF
            elif data_type == 'uint16':
                return int(value) & 0xFFFF
            elif data_type == 'int32':
                return int(value)
            elif data_type == 'uint32':
                return int(value) & 0xFFFFFFFF
            elif data_type == 'float32':
                return float(value)
            elif data_type == 'float64':
                return float(value)
            elif data_type == 'bool':
                return bool(value)
            elif data_type == 'string':
                return str(value)
            else:
                self.logger.warning(f"未知数据类型: {data_type}, 使用int16")
                return int(value) & 0xFFFF
        except (ValueError, TypeError) as e:
            self.logger.error(f"数据类型转换错误: {e}, 值: {value}, 类型: {data_type}")
            return 0

    def pack_value_to_registers(self, value, data_type):
        """将值打包为寄存器数组"""
        try:
            if data_type == 'int16':
                return [int(value) & 0xFFFF]
            elif data_type == 'uint16':
                return [int(value) & 0xFFFF]
            elif data_type == 'int32':
                # 32位整数占用2个寄存器 - 大端序
                int_val = int(value)
                return [(int_val >> 16) & 0xFFFF, int_val & 0xFFFF]
            elif data_type == 'uint32':
                # 32位无符号整数占用2个寄存器 - 大端序
                uint_val = int(value) & 0xFFFFFFFF
                return [(uint_val >> 16) & 0xFFFF, uint_val & 0xFFFF]
            elif data_type == 'float32':
                # 32位浮点数占用2个寄存器 - IEEE754标准
                float_val = float(value)
                packed = struct.pack('>f', float_val)  # 大端序
                return [struct.unpack('>H', packed[0:2])[0], struct.unpack('>H', packed[2:4])[0]]
            elif data_type == 'float64':
                # 64位浮点数占用4个寄存器 - IEEE754标准
                double_val = float(value)
                packed = struct.pack('>d', double_val)  # 大端序
                return [
                    struct.unpack('>H', packed[0:2])[0],
                    struct.unpack('>H', packed[2:4])[0],
                    struct.unpack('>H', packed[4:6])[0],
                    struct.unpack('>H', packed[6:8])[0]
                ]
            elif data_type == 'bool':
                return [1 if bool(value) else 0]
            elif data_type == 'string':
                # 字符串类型，每个字符占用一个寄存器（16位）
                str_val = str(value)
                registers = []
                for char in str_val[:125]:  # 限制长度
                    registers.append(ord(char) & 0xFFFF)
                return registers
            else:
                self.logger.warning(f"未知数据类型: {data_type}, 使用int16")
                return [int(value) & 0xFFFF]
        except Exception as e:
            self.logger.error(f"值打包错误: {e}, 值: {value}, 类型: {data_type}")
            return [0]

    def get_register_count(self, data_type):
        """根据数据类型返回所需的寄存器数量"""
        # 使用一个示例值0来获取寄存器列表，然后返回列表长度
        return len(self.pack_value_to_registers(0, data_type))

    # 新增方法：生成带bit位配置的寄存器值
    def generate_register_with_bits(self, address_type, address, current_time):
        """生成包含bit位配置的寄存器值"""
        register_value = 0
        
        # 首先获取基础寄存器值（如果有配置）
        if address in self.data_config.get(address_type, {}):
            config = self.data_config[address_type][address]
            if current_time - config['last_update'] >= config['interval']:
                config['last_update'] = current_time
                config['current_value'] = self.generate_data(config, current_time)
            
            base_value = config.get('current_value', config['value'])
            # 将基础值转换为16位整数
            if isinstance(base_value, (int, float)):
                register_value = int(base_value) & 0xFFFF
            else:
                register_value = 0
        else:
            # 如果没有基础配置，默认为0
            register_value = 0
        
        # 应用bit位配置
        if address in self.bit_config.get(address_type, {}):
            for bit, config in self.bit_config[address_type][address].items():
                # 更新bit值
                if current_time - config['last_update'] >= config['interval']:
                    config['last_update'] = current_time
                    config['current_value'] = self.generate_data(config, current_time)
                
                bit_value = config.get('current_value', config['value'])
                
                # 设置或清除对应的bit位
                if bool(bit_value):
                    register_value |= (1 << bit)
                else:
                    register_value &= ~(1 << bit)
                
                self.logger.debug(f"设置 {address_type}[{address}] bit{bit} = {bit_value}, 寄存器值: {register_value:016b}")
        
        return register_value

    def create_modbus_response(self, transaction_id, unit_id, function_code, data):
        """创建Modbus响应报文"""
        self.logger.debug(f"创建响应: 事务ID={transaction_id}, 单元ID={unit_id}, 功能码={function_code}, 数据={data}")
        
        try:
            response_body = b""
            
            if function_code == 1:  # 读线圈
                byte_count = (len(data) + 7) // 8
                response_body += struct.pack('>B', byte_count)
                
                # 打包位数据
                for i in range(byte_count):
                    byte_val = 0
                    for bit in range(8):
                        idx = i * 8 + bit
                        if idx < len(data) and data[idx]:
                            byte_val |= (1 << bit)
                    response_body += struct.pack('>B', byte_val)
                    
            elif function_code == 2:  # 读离散输入
                byte_count = (len(data) + 7) // 8
                response_body += struct.pack('>B', byte_count)
                
                # 打包位数据
                for i in range(byte_count):
                    byte_val = 0
                    for bit in range(8):
                        idx = i * 8 + bit
                        if idx < len(data) and data[idx]:
                            byte_val |= (1 << bit)
                    response_body += struct.pack('>B', byte_val)
                    
            elif function_code == 3:  # 读保持寄存器
                # 修复：直接处理寄存器值列表
                register_data = []
                for value in data:
                    # 数据已经是16位寄存器值，直接使用
                    register_data.append(int(value) & 0xFFFF)
                
                byte_count = len(register_data) * 2
                response_body += struct.pack('>B', byte_count)
                for val in register_data:
                    response_body += struct.pack('>H', val)
                    
            elif function_code == 4:  # 读输入寄存器
                # 修复：直接处理寄存器值列表
                register_data = []
                for value in data:
                    # 数据已经是16位寄存器值，直接使用
                    register_data.append(int(value) & 0xFFFF)
                
                byte_count = len(register_data) * 2
                response_body += struct.pack('>B', byte_count)
                for val in register_data:
                    response_body += struct.pack('>H', val)
                    
            else:
                # 非法功能码错误响应
                self.logger.warning(f"不支持的函数码: {function_code}")
                function_code = function_code | 0x80  # 设置错误标志
                response_body = struct.pack('>B', 0x01)  # 异常码: 非法功能
            
            # 构建完整的Modbus TCP响应
            # MBAP头部: 事务ID(2) + 协议ID(2) + 长度(2) + 单元ID(1)
            # 长度 = 单元ID(1) + 功能码(1) + 响应数据长度
            length = 1 + 1 + len(response_body)  # 单元ID + 功能码 + 数据
            
            header = struct.pack('>HHHB', 
                               transaction_id,    # 事务标识符
                               0,                 # 协议标识符 (Modbus=0)
                               length,            # 长度字段
                               unit_id)           # 单元标识符
            
            # 功能码字节
            function_byte = struct.pack('>B', function_code)
            
            full_response = header + function_byte + response_body
            
            self.logger.debug(f"完整响应长度: {len(full_response)} 字节")
            return full_response
            
        except Exception as e:
            self.logger.error(f"创建响应错误: {e}")
            # 返回服务器设备故障错误
            error_header = struct.pack('>HHHBB', 
                                     transaction_id, 0, 3, 
                                     unit_id, function_code | 0x80)
            error_body = struct.pack('>B', 0x04)  # 服务器设备故障
            return error_header + error_body
    
    def parse_modbus_request(self, data):
        """解析Modbus请求"""
        if len(data) < 8:
            self.logger.warning(f"请求数据过短: {len(data)} 字节")
            return None
            
        try:
            # 解析MBAP头部
            transaction_id, protocol_id, length, unit_id = struct.unpack('>HHHB', data[:7])
            function_code = struct.unpack('>B', data[7:8])[0]
            
            # 剩余数据
            request_data = data[8:8+length-2]  # -2 for unit_id and function_code
            
            self.logger.debug(f"解析请求: 事务ID={transaction_id}, 协议ID={protocol_id}, 长度={length}, 单元ID={unit_id}, 功能码={function_code}")
            
            return {
                'transaction_id': transaction_id,
                'unit_id': unit_id,
                'function_code': function_code,
                'data': request_data
            }
        except Exception as e:
            self.logger.error(f"解析Modbus请求错误: {e}")
            return None
    
    def handle_read_request(self, request, start_address, quantity):
        """处理读请求"""
        function_code = request['function_code']
        current_time = time.time()
        response_data = []
        
        address_type_map = {
            1: 'coils',
            2: 'discrete_inputs', 
            3: 'holding_registers',
            4: 'input_registers'
        }
        
        address_type = address_type_map.get(function_code)
        if not address_type:
            return response_data
            
        # 检查数量限制
        max_quantity = {
            1: 2000,  # 线圈
            2: 2000,  # 离散输入
            3: 125,   # 保持寄存器
            4: 125    # 输入寄存器
        }.get(function_code, 125)
        
        if quantity > max_quantity:
            quantity = max_quantity
            self.logger.warning(f"请求数量超过限制，调整为: {quantity}")
        
        self.logger.info(f"处理读请求: 类型={address_type}, 起始地址={start_address}, 数量={quantity}")
        self.logger.info(f"当前配置的地址: {list(self.data_config[address_type].keys())}")
        
        if function_code in [1, 2]:  # 线圈和离散输入
            for i in range(quantity):
                addr = start_address + i
                if addr in self.data_config[address_type]:
                    config = self.data_config[address_type][addr]
                    if current_time - config['last_update'] >= config['interval']:
                        config['last_update'] = current_time
                        config['current_value'] = self.generate_data(config, current_time)
                        self.logger.info(f"更新地址 {addr} 的值: {config['current_value']} (类型: {config.get('data_type', 'int16')})")
                    
                    value = config.get('current_value', config['value'])
                    response_data.append(bool(value))
                    self.logger.info(f"地址 {addr} 的值: {value}")
                else:
                    response_data.append(False)
                    self.logger.info(f"地址 {addr} 未配置，使用默认值 False")
        else:  # 功能码3和4：保持寄存器和输入寄存器
            # 初始化响应数据为0列表
            response_data = [0] * quantity

            # 遍历当前地址类型的所有配置
            for addr, config in self.data_config[address_type].items():
                # 检查配置的地址是否在请求范围内
                if addr >= start_address and addr < start_address + quantity:
                    # 生成当前值
                    if current_time - config['last_update'] >= config['interval']:
                        config['last_update'] = current_time
                        config['current_value'] = self.generate_data(config, current_time)
                        self.logger.info(f"更新地址 {addr} 的值: {config['current_value']} (类型: {config.get('data_type', 'int16')})")

                    value = config.get('current_value', config['value'])
                    data_type = config.get('data_type', 'int16')

                    # 将值打包成寄存器列表
                    registers = self.pack_value_to_registers(value, data_type)
                    n = len(registers)

                    # 计算在响应数据中的起始索引
                    start_index = addr - start_address

                    # 确保不越界
                    end_index = start_index + n
                    if end_index <= quantity:
                        response_data[start_index:end_index] = registers
                        self.logger.info(f"地址 {addr} 的寄存器值: {registers} (数据类型: {data_type})")
                    else:
                        # 如果越界，只复制不越界的部分
                        response_data[start_index:quantity] = registers[:quantity - start_index]
                        self.logger.info(f"地址 {addr} 的寄存器值(部分): {registers[:quantity - start_index]} (数据类型: {data_type})")
                else:
                    # 检查配置是否跨越请求范围（多寄存器数据）
                    data_type = config.get('data_type', 'int16')
                    register_count = self.get_register_count(data_type)
                    config_end_addr = addr + register_count - 1
                    
                    # 如果配置跨越请求范围的开始部分
                    if addr < start_address and config_end_addr >= start_address:
                        # 生成当前值
                        if current_time - config['last_update'] >= config['interval']:
                            config['last_update'] = current_time
                            config['current_value'] = self.generate_data(config, current_time)
                        
                        value = config.get('current_value', config['value'])
                        registers = self.pack_value_to_registers(value, data_type)
                        
                        # 计算在响应数据中的起始位置
                        overlap_start = start_address - addr
                        registers_to_copy = registers[overlap_start:]
                        
                        # 复制到响应数据
                        copy_count = min(len(registers_to_copy), quantity)
                        response_data[:copy_count] = registers_to_copy[:copy_count]
                        self.logger.info(f"地址 {addr} 的跨越寄存器值: {registers_to_copy[:copy_count]} (数据类型: {data_type})")

            # 新增：处理bit位配置
            for i in range(quantity):
                addr = start_address + i
                # 检查该地址是否有bit位配置
                if addr in self.bit_config.get(address_type, {}):
                    register_value = self.generate_register_with_bits(address_type, addr, current_time)
                    response_data[i] = register_value
                    self.logger.info(f"地址 {addr} 应用bit位配置后的值: {register_value} (二进制: {register_value:016b})")

        self.logger.info(f"最终响应数据: {response_data}")
        return response_data
    
    def handle_client(self, client_socket, address):
        """处理客户端连接"""
        self.logger.info(f"客户端连接: {address}")
        
        try:
            while self.running:
                # 接收数据
                data = client_socket.recv(256)
                if not data:
                    break
                
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
            self.logger.info(f"客户端断开: {address}")
    
    def start(self):
        """启动Modbus TCP服务器"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1)
            
            self.running = True
            self.logger.info(f"Modbus TCP模拟器启动在 {self.host}:{self.port}")
            
            # 打印当前配置状态
            self.logger.info("当前配置状态:")
            for reg_type, configs in self.data_config.items():
                self.logger.info(f"{reg_type}: {list(configs.keys())}")
            
            # 打印bit位配置状态
            self.logger.info("Bit位配置状态:")
            for reg_type, configs in self.bit_config.items():
                if configs:
                    self.logger.info(f"{reg_type} bit配置: {list(configs.keys())}")
            
            while self.running:
                try:
                    client_socket, address = self.server_socket.accept()
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, address)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.logger.error(f"接受连接错误: {e}")
                    
        except Exception as e:
            self.logger.error(f"启动服务器错误: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """停止服务器"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        self.logger.info("Modbus TCP模拟器已停止")

class ModbusConfigManager:
    def __init__(self):
        self.configs = []
    
    def add_coil(self, address, value, interval=1, description=""):
        self.configs.append({
            'type': 'coils',
            'address': address,
            'value': value,
            'interval': interval,
            'description': description,
            'data_type': 'bool'  # 线圈只能是布尔类型
        })
    
    def add_discrete_input(self, address, value, interval=1, description=""):
        self.configs.append({
            'type': 'discrete_inputs',
            'address': address,
            'value': value,
            'interval': interval,
            'description': description,
            'data_type': 'bool'  # 离散输入只能是布尔类型
        })
    
    def add_holding_register(self, address, value, interval=1, data_range=None, data_type='int16', description=""):
        self.configs.append({
            'type': 'holding_registers',
            'address': address,
            'value': value,
            'interval': interval,
            'data_range': data_range,
            'data_type': data_type,  # 新增数据类型参数
            'description': description
        })
    
    def add_input_register(self, address, value, interval=1, data_range=None, data_type='int16', description=""):
        self.configs.append({
            'type': 'input_registers',
            'address': address,
            'value': value,
            'interval': interval,
            'data_range': data_range,
            'data_type': data_type,  # 新增数据类型参数
            'description': description
        })
    
    def apply_to_simulator(self, simulator):
        for config in self.configs:
            simulator.set_data_config(
                config['type'],
                config['address'],
                config['value'],
                config['interval'],
                config.get('data_range'),
                config.get('data_type', 'int16')  # 传递数据类型
            )

def create_sample_simulator():
    """创建示例模拟器"""
    simulator = ModbusTCPSimulator('localhost', 502)
    config_manager = ModbusConfigManager()
    
    # 保持寄存器配置 - 多种数据类型示例
    config_manager.add_holding_register(0, 
                                       lambda min_val, max_val: random.randint(min_val, max_val),
                                       2, [20, 30], "int16", "温度传感器")
    config_manager.add_holding_register(1, 3.14159, 1, None, "float32", "圆周率")
    config_manager.add_holding_register(2, 
                                       lambda min_val, max_val: random.randint(min_val, max_val),
                                       2, [1000, 50000], "int32", "大整数")
    config_manager.add_holding_register(3, 123.456789, 5, None, "float64", "高精度浮点数")
    config_manager.add_holding_register(4, "Hello", 10, None, "string", "字符串数据")
    
    # 添加更多测试寄存器
    for i in range(5, 10):
        config_manager.add_holding_register(i, i * 100, 10, None, "int16", f"测试寄存器{i}")
    
    config_manager.apply_to_simulator(simulator)
    
    # 新增：添加bit位配置示例
    # 示例1：地址100的保持寄存器，配置多个bit位
    bit_config_100 = {
        0: {'value': True, 'interval': 2, 'description': '设备就绪'},
        1: {'value': lambda: random.choice([True, False]), 'interval': 3, 'description': '随机状态'},
        2: {'value': False, 'interval': 5, 'description': '报警状态'},
        7: {'value': lambda: random.choice([True, False]), 'interval': 1, 'description': '快速开关'},
        15: {'value': True, 'interval': 10, 'description': '高bit位'}
    }
    simulator.set_bit_config('holding_registers', 100, bit_config_100)
    
    # 示例2：地址101的输入寄存器，配置bit位
    bit_config_101 = {
        3: {'value': lambda: random.choice([True, False]), 'interval': 2, 'description': '传感器A'},
        4: {'value': lambda: random.choice([True, False]), 'interval': 2, 'description': '传感器B'},
        5: {'value': True, 'interval': 60, 'description': '常开信号'},
        8: {'value': lambda: (int(time.time()) % 10) < 5, 'interval': 1, 'description': '周期信号'}
    }
    simulator.set_bit_config('input_registers', 101, bit_config_101)
    
    return simulator

if __name__ == "__main__":
    simulator = create_sample_simulator()
    
    try:
        server_thread = threading.Thread(target=simulator.start)
        server_thread.daemon = True
        server_thread.start()
        
        print("Modbus TCP数据模拟器已启动（支持多种数据类型和bit位配置）")
        print("监听地址: localhost:502")
        print("按 Ctrl+C 停止服务器")
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n正在停止服务器...")
        simulator.stop()