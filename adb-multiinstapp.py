#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ADB 批量管理工具 v2.0
用于局域网内批量发现 ADB 设备并进行应用安装/卸载管理
增强版：支持版本检测、失败重试、自定义端口
"""

import sys
import os
import subprocess
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QTableWidget, QTableWidgetItem,
    QGroupBox, QSpinBox, QFileDialog, QProgressBar, QTabWidget,
    QMessageBox, QHeaderView, QComboBox, QRadioButton, QButtonGroup
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QIcon, QTextCursor


class ADBWorker:
    """ADB 操作工具类"""
    
    def __init__(self, adb_path=None):
        # 使用当前工作目录查找（用户运行 exe 的目录）
        if adb_path is None:
            cwd = os.getcwd()
            
            # 尝试各种可能的 adb 路径
            adb_paths = [
                os.path.join(cwd, "adb", "adb.exe"),      # 当前目录的 adb 文件夹
                os.path.join(cwd, "adb.exe"),             # 当前目录
            ]
            
            # 查找第一个存在的 adb
            for path in adb_paths:
                if os.path.exists(path):
                    self.adb_path = path
                    return
            
            # 未找到，使用系统 PATH
            self.adb_path = "adb"
        else:
            self.adb_path = adb_path
    
    def _run_adb(self, device_id, *args, timeout=60):
        """执行 ADB 命令"""
        cmd = [self.adb_path, "-s", device_id] + list(args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "Timeout"
        except Exception as e:
            return False, "", str(e)
    
    def connect(self, ip, port=5555, timeout=5):
        """连接 ADB 设备"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            if result != 0:
                return False, "端口未开放"
            
            cmd = [self.adb_path, "connect", f"{ip}:{port}"]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if "connected" in proc.stdout or "already connected" in proc.stdout:
                return True, "已连接"
            return False, proc.stderr.strip() or "未知错误"
        except Exception as e:
            return False, str(e)
    
    def disconnect(self, ip, port=5555):
        """断开 ADB 连接"""
        cmd = [self.adb_path, "disconnect", f"{ip}:{port}"]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return True, "已断开"
        except Exception as e:
            return False, str(e)
    
    def get_device_info(self, device_id):
        """获取设备信息"""
        info = {"state": "unknown", "model": "unknown", "version": "unknown"}
        
        success, stdout, _ = self._run_adb(device_id, "get-state", timeout=10)
        if success:
            info["state"] = stdout
        
        success, stdout, _ = self._run_adb(device_id, "shell", "getprop", "ro.product.model", timeout=10)
        if success and stdout:
            info["model"] = stdout
        
        success, stdout, _ = self._run_adb(device_id, "shell", "getprop", "ro.build.version.release", timeout=10)
        if success and stdout:
            info["version"] = stdout
        
        return info
    
    def is_installed(self, device_id, package_name):
        """检查应用是否已安装"""
        success, stdout, _ = self._run_adb(
            device_id, "shell", "pm", "list", "packages", package_name, timeout=30
        )
        if success and stdout:
            return f"package:{package_name}" in stdout
        return False
    
    def get_installed_version(self, device_id, package_name):
        """获取已安装应用的版本号"""
        success, stdout, _ = self._run_adb(
            device_id, "shell", "dumpsys", "package", package_name, timeout=30
        )
        if success and stdout:
            # 优先获取 versionName
            match = re.search(r'versionName=([\d.]+)', stdout)
            if match:
                return match.group(1)
            # 如果没有 versionName，使用 versionCode
            match = re.search(r'versionCode=(\d+)', stdout)
            if match:
                return match.group(1)
        return None
    
    def get_apk_version(self, apk_path):
        """获取 APK 文件的版本信息 - 纯 Python 实现"""
        try:
            import zipfile
            import struct
            
            with zipfile.ZipFile(apk_path, 'r') as zip_ref:
                # 查找 AndroidManifest.xml
                manifest_names = [n for n in zip_ref.namelist() 
                                  if n.endswith('AndroidManifest.xml')]
                if not manifest_names:
                    return None, None
                
                xml_data = zip_ref.read(manifest_names[0])
                return self._parse_axml_v2(xml_data)
        except Exception as e:
            return None, None
    
    def _parse_axml_v2(self, xml_data):
        """增强版 AXML 解析器 - 支持标准格式的 APK"""
        import struct
        
        if len(xml_data) < 8:
            return None, None
        
        version_code = None
        version_name = None
        
        # 检查是否是二进制 AXML (使用 hex 比较，避免转义问题)
        is_binary = xml_data[:4].hex() == '03000800'
        
        if not is_binary:
            # 尝试作为文本 XML 解析
            import re
            try:
                xml_text = xml_data.decode('utf-8', errors='ignore')
                code_match = re.search(r'android:versionCode="(\d+)"', xml_text)
                version_code = int(code_match.group(1)) if code_match else None
                name_match = re.search(r'android:versionName="([\d.]+)"', xml_text)
                version_name = name_match.group(1) if name_match else None
                if version_code or version_name:
                    return version_code, version_name
            except:
                pass
            return None, None
        
        # ========== 解析二进制 AXML ==========
        
        # 1. 解析字符串池
        pool_offset = 8
        header_size = struct.unpack('<H', xml_data[pool_offset+2:pool_offset+4])[0]
        string_count = struct.unpack('<I', xml_data[pool_offset+8:pool_offset+12])[0]
        strings_start = struct.unpack('<I', xml_data[pool_offset+20:pool_offset+24])[0]
        
        str_table_start = pool_offset + header_size
        pool_data_start = pool_offset + strings_start
        
        # 读取字符串
        strings = []
        for i in range(string_count):
            if str_table_start + i*4 + 4 > len(xml_data):
                strings.append('')
                continue
            str_offset = struct.unpack('<I', xml_data[str_table_start + i*4:str_table_start + i*4 + 4])[0]
            str_pos = pool_data_start + str_offset
            if str_pos >= len(xml_data):
                strings.append('')
                continue
            try:
                str_len = struct.unpack('<H', xml_data[str_pos:str_pos+2])[0]
                s = xml_data[str_pos+2:str_pos+2+str_len*2].decode('utf-16-le', errors='ignore')
                strings.append(s)
            except:
                strings.append('')
        
        # 2. 查找 manifest 元素及其属性
        # 跳过字符串池
        chunk_size = struct.unpack('<I', xml_data[pool_offset+4:pool_offset+8])[0]
        offset = pool_offset + chunk_size
        
        # 跳过资源映射表等，直接找 START_ELEMENT
        while offset < len(xml_data) - 8:
            chunk_type = struct.unpack('<H', xml_data[offset:offset+2])[0]
            chunk_size = struct.unpack('<I', xml_data[offset+4:offset+8])[0]
            
            if chunk_type == 0x0102:  # XML_START_ELEMENT
                break
            offset += chunk_size
        
        # 解析所有元素，查找 manifest
        while offset < len(xml_data) - 24:
            chunk_type = struct.unpack('<H', xml_data[offset:offset+2])[0]
            header_size = struct.unpack('<H', xml_data[offset+2:offset+4])[0]
            chunk_size = struct.unpack('<I', xml_data[offset+4:offset+8])[0]
            
            if chunk_type == 0x0102:  # XML_START_ELEMENT
                # 获取元素名称索引
                name_idx = struct.unpack('<I', xml_data[offset+12:offset+16])[0]
                attr_count = struct.unpack('<H', xml_data[offset+28:offset+30])[0]
                
                # 检查是否是 manifest 元素
                # 正常 APK: name_idx 是字符串索引
                # 混淆 APK: name_idx = 0xFFFFFFFF，需要用其他方式识别
                elem_name = strings[name_idx] if name_idx < len(strings) else ''
                
                # 如果是第一个元素且 name_idx 无效，可能是混淆 APK，直接解析属性
                is_manifest = (elem_name == 'manifest')
                is_obfuscated = (name_idx == 0xFFFFFFFF)
                
                if is_manifest or is_obfuscated:
                    # 解析属性
                    attr_start = offset + header_size
                    for i in range(attr_count):
                        if attr_start + 20 > len(xml_data):
                            break
                        
                        attr_name_idx = struct.unpack('<I', xml_data[attr_start+4:attr_start+8])[0]
                        attr_type = xml_data[attr_start + 13]
                        attr_value = struct.unpack('<I', xml_data[attr_start+16:attr_start+20])[0]
                        
                        # 获取属性名
                        attr_name = strings[attr_name_idx] if attr_name_idx < len(strings) else ''
                        
                        # 对于混淆 APK，属性名也可能是资源 ID
                        # versionCode = 0x0101021b, versionName = 0x0101021c
                        is_version_code = (attr_name == 'versionCode' or attr_name_idx == 0x0101021b)
                        is_version_name = (attr_name == 'versionName' or attr_name_idx == 0x0101021c)
                        
                        # 查找 versionCode 和 versionName
                        if is_version_code:
                            # 类型 0x10=INT_DEC, 0x00=复杂类型 (加固 APK)
                            if attr_type in [0x10, 0x00]:
                                version_code = attr_value
                        elif is_version_name:
                            if attr_type == 0x03:  # TYPE_STRING
                                str_idx = attr_value & 0xFFFF
                                if str_idx < len(strings):
                                    version_name = strings[str_idx]
                            elif attr_type == 0x00:
                                # 加固 APK，值直接是字符串索引
                                str_idx = attr_value
                                if str_idx < len(strings):
                                    version_name = strings[str_idx]
                        
                        attr_start += 20
                    
                    # 找到 manifest 后就可以返回了
                    if version_code or version_name:
                        return version_code, version_name
            
            offset += chunk_size
        
        return version_code, version_name
    
    def _parse_axml(self, xml_data):
        """解析二进制 AXML 格式获取版本信息"""
        try:
            # 方法 1: 尝试作为普通文本 XML 解析 (某些 APK 是明文的)
            try:
                xml_text = xml_data.decode('utf-8', errors='ignore')
                # 查找 versionCode
                code_match = re.search(r'android:versionCode="(\d+)"', xml_text)
                version_code = int(code_match.group(1)) if code_match else None
                # 查找 versionName
                name_match = re.search(r'android:versionName="([\d.]+)"', xml_text)
                version_name = name_match.group(1) if name_match else None
                if version_code or version_name:
                    return version_code, version_name
            except:
                pass
            
            # 方法 2: 在二进制数据中搜索版本字符串
            # APK 文件中通常包含可读的版本信息字符串
            version_code = None
            version_name = None
            
            # 搜索常见的版本模式 (如 1.0.0, 2.3.1 等)
            text_parts = xml_data.split(b'\x00')
            for part in text_parts:
                try:
                    decoded = part.decode('utf-8', errors='ignore').strip()
                    # 检查是否是 versionName 格式
                    if re.match(r'^[\d.]+$', decoded) and '.' in decoded:
                        if not version_name:
                            version_name = decoded
                    # 检查是否是纯数字 versionCode
                    elif decoded.isdigit() and len(decoded) <= 10:
                        if not version_code:
                            version_code = int(decoded)
                except:
                    continue
            
            # 方法 3: 使用 ANDR 资源 ID 解析 (简化版)
            if len(xml_data) >= 12:
                # 查找 manifest 标签后的属性
                for i in range(len(xml_data) - 20):
                    # 查找 versionCode 的资源 ID (0x0101021b)
                    if xml_data[i:i+4] == b'\x1b\x02\x01\x01':
                        if i + 8 < len(xml_data):
                            val = struct.unpack('<I', xml_data[i+4:i+8])[0]
                            if val > 0 and val < 1000000000:
                                version_code = val
                                break
                    
                    # 查找 versionName 的资源 ID (0x0101021c)
                    if xml_data[i:i+4] == b'\x1c\x02\x01\x01':
                        if i + 8 < len(xml_data):
                            str_idx = struct.unpack('<I', xml_data[i+4:i+8])[0]
                            # 从字符串池中提取
                            if str_idx < len(xml_data):
                                # 简化的字符串提取
                                for j in range(str_idx, min(str_idx + 50, len(xml_data))):
                                    if xml_data[j] == 0:
                                        candidate = xml_data[str_idx:j].decode('utf-8', errors='ignore')
                                        if re.match(r'^[\d.]+$', candidate):
                                            version_name = candidate
                                            break
                                break
            
            return version_code, version_name
        except Exception as e:
            return None, None
    
    def install(self, device_id, apk_path, replace=False, timeout=300):
        """安装 APK"""
        args = ["install"]
        if replace:
            args.extend(["-r", "-d"])  # -r 覆盖，-d 允许降级
        args.append(apk_path)
        success, stdout, stderr = self._run_adb(device_id, *args, timeout=timeout)
        
        if success and "Success" in stdout:
            return True, "安装成功"
        error_msg = stderr or stdout or "安装失败"
        return False, error_msg
    
    def uninstall(self, device_id, package_name, timeout=60):
        """卸载应用"""
        success, stdout, stderr = self._run_adb(
            device_id, "uninstall", package_name, timeout=timeout
        )
        if success and "Success" in stdout:
            return True, "卸载成功"
        return False, stderr or stdout or "卸载失败"


class ScanThread(QThread):
    """设备扫描线程"""
    device_found = pyqtSignal(dict)
    scan_progress = pyqtSignal(int, int)
    scan_finished = pyqtSignal()
    log_message = pyqtSignal(str)
    
    def __init__(self, ip_list, port, max_threads=50):
        super().__init__()
        self.ip_list = ip_list  # IP 地址列表
        self.port = port
        self.max_threads = max_threads
        self.adb = ADBWorker()
        self.stop_flag = False
    
    def run(self):
        total = len(self.ip_list)
        completed = 0
        found_devices = set()
        
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = {
                executor.submit(self.scan_device, ip): ip
                for ip in self.ip_list
            }
            
            for future in as_completed(futures):
                if self.stop_flag:
                    break
                
                ip = futures[future]
                try:
                    success, device_id, info = future.result()
                    if success and device_id not in found_devices:
                        found_devices.add(device_id)
                        self.device_found.emit({
                            "id": device_id, "ip": ip, "port": self.port,
                            "state": info.get("state", "unknown"),
                            "model": info.get("model", "unknown"),
                            "version": info.get("version", "unknown")
                        })
                        self.log_message.emit(f"✓ 发现设备：{ip}:{self.port} - {info.get('model', 'Unknown')}")
                except Exception as e:
                    pass
                
                completed += 1
                self.scan_progress.emit(completed, total)
        
        self.scan_finished.emit()
    
    def scan_device(self, ip):
        """扫描单个设备，带重试机制"""
        # 尝试连接 3 次，每次检查停止信号
        for attempt in range(3):
            if self.stop_flag:  # 检查停止信号
                return False, None, {}
            
            success, msg = self.adb.connect(ip, self.port, timeout=2)
            if success:
                # 连接成功后等待一下
                import time
                time.sleep(0.2)
                info = self.adb.get_device_info(f"{ip}:{self.port}")
                return True, f"{ip}:{self.port}", info
            # 失败后等待一下再试
            import time
            time.sleep(0.1)
        return False, None, {}
    
    def stop(self):
        self.stop_flag = True



class UninstallThread(QThread):
    """批量卸载线程"""
    uninstall_progress = pyqtSignal(str, str, str)  # device, status, message
    task_finished = pyqtSignal(str, bool, str, str)  # device, success, message, status
    all_finished = pyqtSignal()
    
    def __init__(self, devices, package_name, max_threads=10):
        super().__init__()
        self.devices = devices
        self.package_name = package_name
        self.max_threads = max_threads
        self.adb = ADBWorker()
        self.stop_flag = False
    
    def run(self):
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = {
                executor.submit(self.uninstall_from_device, device): device
                for device in self.devices
            }
            
            for future in as_completed(futures):
                if self.stop_flag:
                    break
                device = futures[future]
                try:
                    device_id, success, message, status = future.result()
                    self.task_finished.emit(device_id, success, message, status)
                except Exception as e:
                    self.task_finished.emit(device["id"], False, str(e), "error")
        
        self.all_finished.emit()
    
    def uninstall_from_device(self, device):
        device_id = device["id"]
        
        try:
            # 检查是否已安装
            self.uninstall_progress.emit(device_id, "checking", "检查安装状态...")
            is_installed = self.adb.is_installed(device_id, self.package_name)
            
            if not is_installed:
                self.uninstall_progress.emit(device_id, "skipped", "未安装，跳过")
                return device_id, True, "未安装，跳过", "skipped"
            
            # 执行卸载
            self.uninstall_progress.emit(device_id, "uninstalling", "正在卸载...")
            success, msg = self.adb.uninstall(device_id, self.package_name)
            
            if success:
                self.uninstall_progress.emit(device_id, "success", "卸载成功")
                return device_id, True, "卸载成功", "success"
            else:
                self.uninstall_progress.emit(device_id, "error", msg)
                return device_id, False, msg, "error"
                
        except Exception as e:
            error_msg = f"卸载异常：{str(e)}"
            self.uninstall_progress.emit(device_id, "error", error_msg)
            return device_id, False, error_msg, "error"
    
    def stop(self):
        self.stop_flag = True


class CheckVersionThread(QThread):
    """检查已安装版本的线程"""
    version_checked = pyqtSignal(str, str)  # device_id, version
    finished = pyqtSignal()
    
    def __init__(self, devices, package_name, adb):
        super().__init__()
        self.devices = devices
        self.package_name = package_name
        self.adb = adb
        self.stop_flag = False
    
    def run(self):
        import sys
        for i, device in enumerate(self.devices):
            if self.stop_flag:
                break
            device_id = device["id"]
            version = self.adb.get_installed_version(device_id, self.package_name)
            version_str = f"v{version}" if version else "未安装"
            # 使用 print 输出调试信息（会显示在控制台）
            print(f"[DEBUG] 检查设备 {i+1}/{len(self.devices)}: {device_id} = {version_str}", file=sys.stderr)
            self.version_checked.emit(device_id, version_str)
        print(f"[DEBUG] CheckVersionThread 完成", file=sys.stderr)
        self.finished.emit()
    
    def stop(self):
        self.stop_flag = True


class ADBBatchManager(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.adb = ADBWorker()
        self.devices = []
        self.failed_devices = []  # 安装失败的设备
        self.scan_thread = None
        self.install_thread = None
        self.retry_thread = None
        self.install_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.retry_stats = {"success": 0, "failure": 0}
        self.init_ui()
        self.log("=" * 50)
        self.log("adb 批量设备安装工具 已启动")
        self.log("增强功能：版本检测 | 失败重试 | 自定义端口")
        self.log("=" * 50)
        self.check_adb()
        
        # 加载上次扫描的设备
        self.load_devices()
    
    def init_ui(self):
        self.setWindowTitle("adb 批量设备安装工具")
        self.setMinimumSize(1400, 900)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        tabs = QTabWidget()
        tabs.addTab(self.create_scan_tab(), "📱 设备发现")
        tabs.addTab(self.create_install_tab(), "📦 应用安装")
        tabs.addTab(self.create_retry_tab(), "⚠️ 失败重试")
        tabs.addTab(self.create_uninstall_tab(), "🗑️ 应用卸载")
        tabs.addTab(self.create_log_tab(), "📋 日志")
        
        main_layout.addWidget(tabs)
        self.statusBar().showMessage("就绪")
    
    def create_scan_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        scan_group = QGroupBox("扫描设置")
        scan_layout = QHBoxLayout(scan_group)
        
        # IP 范围 - 完整 IP 地址
        ip_layout = QVBoxLayout()
        ip_layout.addWidget(QLabel("起始 IP (完整地址):"))
        self.ip_start_edit = QLineEdit()
        self.ip_start_edit.setPlaceholderText("例如：192.168.1.100")
        self.ip_start_edit.setText("192.168.1.100")
        ip_layout.addWidget(self.ip_start_edit)
        
        ip_layout.addWidget(QLabel("结束 IP (完整地址):"))
        self.ip_end_edit = QLineEdit()
        self.ip_end_edit.setPlaceholderText("例如：192.168.1.200")
        self.ip_end_edit.setText("192.168.1.200")
        ip_layout.addWidget(self.ip_end_edit)
        
        # 端口设置 - 单个端口
        port_layout = QVBoxLayout()
        port_layout.addWidget(QLabel("ADB 端口:"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(5555)
        port_layout.addWidget(self.port_input)
        port_layout.addWidget(QLabel("默认 5555\n可自定义"))
        
        # 并发数
        thread_layout = QVBoxLayout()
        thread_layout.addWidget(QLabel("最大并发数:"))
        self.scan_threads = QSpinBox()
        self.scan_threads.setRange(1, 200)
        self.scan_threads.setValue(20)  # 降低默认值，避免网络拥塞
        thread_layout.addWidget(self.scan_threads)
        
        scan_layout.addLayout(ip_layout)
        scan_layout.addLayout(port_layout)
        scan_layout.addLayout(thread_layout)
        scan_layout.addStretch()
        
        self.scan_btn = QPushButton("🔍 开始扫描")
        self.scan_btn.clicked.connect(self.start_scan)
        self.scan_btn.setFixedWidth(150)
        self.scan_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; }")
        scan_layout.addWidget(self.scan_btn)
        
        self.stop_scan_btn = QPushButton("⏹️ 停止")
        self.stop_scan_btn.clicked.connect(self.stop_scan)
        self.stop_scan_btn.setEnabled(False)
        self.stop_scan_btn.setFixedWidth(100)
        scan_layout.addWidget(self.stop_scan_btn)
        
        layout.addWidget(scan_group)
        
        self.scan_progress = QProgressBar()
        self.scan_progress.setVisible(False)
        layout.addWidget(self.scan_progress)
        
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(6)
        self.device_table.setHorizontalHeaderLabels(["选择", "IP:端口", "状态", "型号", "Android 版本", "操作"])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.device_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.device_table)
        
        btn_layout = QHBoxLayout()
        self.device_count_label = QLabel("已发现 0 台设备")
        self.device_count_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        btn_layout.addWidget(self.device_count_label)
        btn_layout.addStretch()
        
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.select_all_devices)
        btn_layout.addWidget(self.select_all_btn)
        
        self.disconnect_btn = QPushButton("断开选中")
        self.disconnect_btn.clicked.connect(self.disconnect_selected)
        btn_layout.addWidget(self.disconnect_btn)
        
        self.clear_devices_btn = QPushButton("清除保存")
        self.clear_devices_btn.clicked.connect(self.clear_saved_devices)
        self.clear_devices_btn.setStyleSheet("QPushButton { color: #cc0000; }")
        btn_layout.addWidget(self.clear_devices_btn)
        
        layout.addLayout(btn_layout)
        return widget
    
    def create_install_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # APK 选择
        apk_group = QGroupBox("APK 文件")
        apk_layout = QHBoxLayout(apk_group)
        self.apk_path_edit = QLineEdit()
        self.apk_path_edit.setPlaceholderText("选择要安装的 APK 文件...")
        apk_layout.addWidget(self.apk_path_edit)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_apk)
        apk_layout.addWidget(browse_btn)
        layout.addWidget(apk_group)
        
        # 包名和版本信息
        pkg_group = QGroupBox("应用信息")
        pkg_layout = QVBoxLayout(pkg_group)
        
        pkg_row = QHBoxLayout()
        pkg_row.addWidget(QLabel("包名:"))
        self.package_name_edit = QLineEdit()
        self.package_name_edit.setPlaceholderText("例如：com.example.app")
        pkg_row.addWidget(self.package_name_edit)
        pkg_layout.addLayout(pkg_row)
        
        # 包名改变时自动检查已安装版本
        self.package_name_edit.textChanged.connect(self.on_package_name_changed)
        
        self.version_info_label = QLabel("APK 版本信息：未选择文件")
        self.version_info_label.setStyleSheet("color: #666; font-style: italic;")
        pkg_layout.addWidget(self.version_info_label)
        layout.addWidget(pkg_group)
        
        # 安装设置
        install_group = QGroupBox("安装设置")
        install_layout = QVBoxLayout(install_group)
        
        # 第一行：并发数和全局策略
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("最大并发数:"))
        self.install_threads = QSpinBox()
        self.install_threads.setRange(1, 50)
        self.install_threads.setValue(10)
        row1.addWidget(self.install_threads)
        
        row1.addSpacing(30)
        row1.addWidget(QLabel("全局策略:"))
        self.version_policy = QComboBox()
        self.version_policy.addItems([
            "智能对比 (版本一致或更高则跳过)",
            "跳过已安装 (不检查版本)",
            "强制覆盖 (始终安装)"
        ])
        self.version_policy.setCurrentIndex(0)
        row1.addWidget(self.version_policy)
        row1.addStretch()
        install_layout.addLayout(row1)
        
        # 版本策略说明
        self.version_policy_tip = QLabel("💡 智能对比：自动检测已安装版本，只有新版本才会安装")
        self.version_policy_tip.setStyleSheet("color: #0066cc; font-size: 11px;")
        install_layout.addWidget(self.version_policy_tip)
        self.version_policy.currentIndexChanged.connect(self.on_version_policy_changed)
        
        layout.addWidget(install_group)
        
        # 设备选择和版本对比
        device_group = QGroupBox("设备列表与版本对比")
        device_layout = QVBoxLayout(device_group)
        
        # 刷新按钮行
        refresh_row = QHBoxLayout()
        refresh_row.addStretch()
        self.refresh_version_btn = QPushButton("🔄 刷新版本")
        self.refresh_version_btn.clicked.connect(self.on_refresh_version_clicked)
        self.refresh_version_btn.setFixedWidth(120)
        self.refresh_version_btn.setStyleSheet("QPushButton { font-size: 12px; background-color: #2196F3; color: white; padding: 5px; }")
        refresh_row.addWidget(self.refresh_version_btn)
        device_layout.addLayout(refresh_row)
        
        self.install_device_table = QTableWidget()
        self.install_device_table.setColumnCount(5)
        self.install_device_table.setHorizontalHeaderLabels([
            "选择", "设备", "已安装版本", "APK 版本", "策略"
        ])
        self.install_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # 策略列使用下拉框
        self.install_device_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        device_layout.addWidget(self.install_device_table)
        
        # 策略说明
        strategy_tip = QLabel("💡 可在表格中为每台设备单独设置策略，也可点击'刷新版本'按钮手动刷新")
        strategy_tip.setStyleSheet("color: #999; font-size: 10px;")
        device_layout.addWidget(strategy_tip)
        
        layout.addWidget(device_group)
        
        # 安装按钮和进度
        btn_layout = QHBoxLayout()
        self.install_btn = QPushButton("📦 开始安装")
        self.install_btn.clicked.connect(self.start_install)
        self.install_btn.setFixedWidth(150)
        self.install_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #4CAF50; color: white; padding: 8px; }")
        btn_layout.addWidget(self.install_btn)
        
        self.stop_install_btn = QPushButton("⏹️ 停止")
        self.stop_install_btn.clicked.connect(self.stop_install)
        self.stop_install_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_install_btn)
        btn_layout.addStretch()
        
        self.install_progress_label = QLabel("准备就绪")
        self.install_progress_label.setStyleSheet("font-size: 12px;")
        btn_layout.addWidget(self.install_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.install_progress_bar = QProgressBar()
        layout.addWidget(self.install_progress_bar)
        
        self.install_result_label = QLabel("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        self.install_result_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self.install_result_label)
        
        self.retry_tip_label = QLabel("💡 安装失败的设备会自动出现在「失败重试」标签页，可以单独重试")
        self.retry_tip_label.setStyleSheet("color: #ff6600; font-size: 11px;")
        layout.addWidget(self.retry_tip_label)
        
        return widget
    
    def create_retry_tab(self):
        """创建失败重试标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 说明
        tip_group = QGroupBox("使用说明")
        tip_layout = QVBoxLayout(tip_group)
        tip1 = QLabel("⚠️ 此页面显示上次安装失败的设备")
        tip1.setStyleSheet("color: #cc0000; font-weight: bold;")
        tip_layout.addWidget(tip1)
        tip2 = QLabel("• 可以选择部分或全部失败设备重新尝试安装")
        tip2.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip2)
        tip3 = QLabel("• 重试前会自动卸载旧版本，然后重新安装")
        tip3.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip3)
        layout.addWidget(tip_group)
        
        # 失败设备列表
        device_group = QGroupBox("失败设备列表")
        device_layout = QVBoxLayout(device_group)
        
        self.retry_device_table = QTableWidget()
        self.retry_device_table.setColumnCount(4)
        self.retry_device_table.setHorizontalHeaderLabels(["选择", "设备", "失败原因", "重试次数"])
        self.retry_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        device_layout.addWidget(self.retry_device_table)
        
        layout.addWidget(device_group)
        
        # 重试按钮
        btn_layout = QHBoxLayout()
        self.retry_btn = QPushButton("🔄 重试选中设备")
        self.retry_btn.clicked.connect(self.start_retry)
        self.retry_btn.setFixedWidth(180)
        self.retry_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #ff9800; color: white; padding: 8px; }")
        btn_layout.addWidget(self.retry_btn)
        
        self.stop_retry_btn = QPushButton("⏹️ 停止")
        self.stop_retry_btn.clicked.connect(self.stop_retry)
        self.stop_retry_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_retry_btn)
        
        btn_layout.addStretch()
        
        self.retry_progress_label = QLabel("准备就绪")
        btn_layout.addWidget(self.retry_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.retry_progress_bar = QProgressBar()
        layout.addWidget(self.retry_progress_bar)
        
        self.retry_result_label = QLabel("✅ 成功：0 | ❌ 失败：0")
        self.retry_result_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self.retry_result_label)
        
        return widget
    
    def create_uninstall_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 包名输入
        pkg_group = QGroupBox("要卸载的应用")
        pkg_layout = QVBoxLayout(pkg_group)
        
        pkg_row1 = QHBoxLayout()
        pkg_row1.addWidget(QLabel("应用包名:"))
        self.uninstall_package_edit = QLineEdit()
        self.uninstall_package_edit.setPlaceholderText("例如：com.example.app")
        pkg_row1.addWidget(self.uninstall_package_edit)
        pkg_layout.addLayout(pkg_row1)
        
        pkg_tip = QLabel("💡 提示：请输入完整的应用包名")
        pkg_tip.setStyleSheet("color: #666; font-size: 11px;")
        pkg_layout.addWidget(pkg_tip)
        
        layout.addWidget(pkg_group)
        
        # 卸载设置
        uninstall_group = QGroupBox("卸载设置")
        uninstall_layout = QHBoxLayout(uninstall_group)
        uninstall_layout.addWidget(QLabel("最大并发数:"))
        self.uninstall_threads = QSpinBox()
        self.uninstall_threads.setRange(1, 50)
        self.uninstall_threads.setValue(10)
        uninstall_layout.addWidget(self.uninstall_threads)
        uninstall_layout.addStretch()
        layout.addWidget(uninstall_group)
        
        # 设备选择
        device_group = QGroupBox("选择设备")
        device_layout = QVBoxLayout(device_group)
        self.uninstall_device_table = QTableWidget()
        self.uninstall_device_table.setColumnCount(2)
        self.uninstall_device_table.setHorizontalHeaderLabels(["选择", "设备"])
        self.uninstall_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        device_layout.addWidget(self.uninstall_device_table)
        layout.addWidget(device_group)
        
        # 卸载按钮和进度
        btn_layout = QHBoxLayout()
        self.uninstall_btn = QPushButton("🗑️ 开始卸载")
        self.uninstall_btn.clicked.connect(self.start_uninstall)
        self.uninstall_btn.setFixedWidth(150)
        self.uninstall_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #f44336; color: white; padding: 8px; }")
        btn_layout.addWidget(self.uninstall_btn)
        
        self.stop_uninstall_btn = QPushButton("⏹️ 停止")
        self.stop_uninstall_btn.clicked.connect(self.stop_uninstall)
        self.stop_uninstall_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_uninstall_btn)
        btn_layout.addStretch()
        
        self.uninstall_progress_label = QLabel("准备就绪")
        self.uninstall_progress_label.setStyleSheet("font-size: 12px;")
        btn_layout.addWidget(self.uninstall_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.uninstall_progress_bar = QProgressBar()
        layout.addWidget(self.uninstall_progress_bar)
        
        self.uninstall_result_label = QLabel("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        self.uninstall_result_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #0066cc;")
        layout.addWidget(self.uninstall_result_label)
        
        return widget
    
    def create_log_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self.log_text)
        
        btn_layout = QHBoxLayout()
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self.log_text.clear)
        btn_layout.addWidget(clear_btn)
        
        export_btn = QPushButton("导出日志")
        export_btn.clicked.connect(self.export_log)
        btn_layout.addWidget(export_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        return widget
    
    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        self.log_text.append(log_line)
        self.log_text.moveCursor(QTextCursor.End)
    
    def check_adb(self):
        try:
            result = subprocess.run([self.adb.adb_path, "version"], capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode == 0:
                version_line = result.stdout.splitlines()[0]
                self.log(f"✓ ADB 已就绪：{version_line}")
            else:
                self.log("✗ ADB 未找到")
                QMessageBox.warning(self, "警告", "ADB 未找到，请安装 Android SDK Platform-Tools 并添加到 PATH")
        except FileNotFoundError:
            self.log("✗ ADB 未找到")
            QMessageBox.warning(self, "警告", "ADB 未找到，请安装 Android SDK Platform-Tools 并添加到 PATH")
    
    # ========== 扫描功能 ==========
    
    def _parse_ip(self, ip_str):
        """解析 IP 地址，返回四段整数列表"""
        try:
            parts = ip_str.strip().split('.')
            if len(parts) != 4:
                return None
            return [int(p) for p in parts]
        except:
            return None
    
    def _ip_to_str(self, ip_parts):
        """将 IP 地址列表转换为字符串"""
        return '.'.join(str(p) for p in ip_parts)
    
    def _generate_ip_list(self, start_ip_str, end_ip_str):
        """生成 IP 地址列表"""
        start_parts = self._parse_ip(start_ip_str)
        end_parts = self._parse_ip(end_ip_str)
        
        if not start_parts or not end_parts:
            return []
        
        # 检查是否在同一网段（前两段相同）
        if start_parts[:2] != end_parts[:2]:
            return []
        
        ip_list = []
        # 遍历第三段和第四段
        for third in range(start_parts[2], end_parts[2] + 1):
            start_fourth = start_parts[3] if third == start_parts[2] else 0
            end_fourth = end_parts[3] if third == end_parts[2] else 255
            
            for fourth in range(start_fourth, end_fourth + 1):
                ip = f"{start_parts[0]}.{start_parts[1]}.{third}.{fourth}"
                ip_list.append(ip)
        
        return ip_list
    
    def start_scan(self):
        ip_start_str = self.ip_start_edit.text().strip()
        ip_end_str = self.ip_end_edit.text().strip()
        port = self.port_input.value()
        max_threads = self.scan_threads.value()
        
        # 生成 IP 列表
        ip_list = self._generate_ip_list(ip_start_str, ip_end_str)
        
        if not ip_list:
            QMessageBox.warning(self, "错误", 
                "IP 地址格式不正确或不在同一网段\n\n"
                "示例：\n"
                "起始 IP: 192.168.1.100\n"
                "结束 IP: 192.168.1.200\n\n"
                "或跨网段：\n"
                "起始 IP: 192.168.1.1\n"
                "结束 IP: 192.168.2.255")
            return
        
        self.devices = []
        self.failed_devices = []
        self.device_table.setRowCount(0)
        self.scan_btn.setEnabled(False)
        self.stop_scan_btn.setEnabled(True)
        self.scan_progress.setVisible(True)
        self.scan_progress.setValue(0)
        
        self.log(f"开始扫描 {ip_start_str} - {ip_end_str} 端口 {port} (共 {len(ip_list)} 个 IP)")
        
        self.scan_thread = ScanThread(ip_list, port, max_threads)
        self.scan_thread.device_found.connect(self.on_device_found)
        self.scan_thread.scan_progress.connect(self.on_scan_progress)
        self.scan_thread.scan_finished.connect(self.on_scan_finished)
        self.scan_thread.log_message.connect(self.log)
        self.scan_thread.start()
    
    def stop_scan(self):
        if self.scan_thread:
            self.scan_thread.stop()
            self.log("扫描已停止")
    
    def on_device_found(self, device):
        self.devices.append(device)
        row = self.device_table.rowCount()
        self.device_table.insertRow(row)
        
        checkbox = QTableWidgetItem("✓")
        checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        checkbox.setCheckState(Qt.Checked)
        self.device_table.setItem(row, 0, checkbox)
        self.device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']}"))
        self.device_table.setItem(row, 2, QTableWidgetItem(device['state']))
        self.device_table.setItem(row, 3, QTableWidgetItem(device['model']))
        self.device_table.setItem(row, 4, QTableWidgetItem(device['version']))
        
        disconnect_btn = QPushButton("断开")
        disconnect_btn.clicked.connect(lambda checked, d=device: self.disconnect_device(d))
        self.device_table.setCellWidget(row, 5, disconnect_btn)
        
        self.device_count_label.setText(f"已发现 {len(self.devices)} 台设备")
    
    def on_scan_progress(self, current, total):
        self.scan_progress.setMaximum(total)
        self.scan_progress.setValue(current)
        self.statusBar().showMessage(f"扫描进度：{current}/{total}")
    
    def on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.scan_progress.setVisible(False)
        self.log(f"✓ 扫描完成，发现 {len(self.devices)} 台设备")
        self.statusBar().showMessage(f"扫描完成，发现 {len(self.devices)} 台设备")
        self.update_device_tables()
        
        # 保存扫描结果
        self.save_devices()
    
    def save_devices(self):
        """保存设备列表到文件"""
        import json
        try:
            # 使用当前工作目录（exe 运行目录）
            if getattr(sys, 'frozen', False):
                # 打包后的 exe，使用 exe 所在目录
                save_dir = os.path.dirname(sys.executable)
            else:
                # 开发时，使用脚本所在目录
                save_dir = os.path.dirname(os.path.abspath(__file__))
            
            save_file = os.path.join(save_dir, "devices.json")
            with open(save_file, 'w', encoding='utf-8') as f:
                json.dump(self.devices, f, ensure_ascii=False, indent=2)
            self.log(f"✓ 设备列表已保存到：{save_file}")
            self.log(f"  共 {len(self.devices)} 台设备")
        except Exception as e:
            self.log(f"⚠ 保存设备列表失败：{e}")
    
    def load_devices(self):
        """从文件加载设备列表"""
        import json
        try:
            # 使用当前工作目录（exe 运行目录）
            if getattr(sys, 'frozen', False):
                save_dir = os.path.dirname(sys.executable)
            else:
                save_dir = os.path.dirname(os.path.abspath(__file__))
            
            save_file = os.path.join(save_dir, "devices.json")
            
            if os.path.exists(save_file):
                with open(save_file, 'r', encoding='utf-8') as f:
                    self.devices = json.load(f)
                
                if self.devices:
                    self.log(f"✓ 加载上次扫描的设备：{len(self.devices)} 台")
                    self.log(f"  文件：{save_file}")
                    self.update_device_tables()
                    self.device_count_label.setText(f"已发现 {len(self.devices)} 台设备 (已保存)")
                else:
                    self.log("ℹ 保存的设备列表为空")
            else:
                self.log("ℹ 未找到保存的设备列表，请先扫描设备")
        except Exception as e:
            self.log(f"⚠ 加载设备列表失败：{e}")
    
    def disconnect_device(self, device):
        success, msg = self.adb.disconnect(device['ip'], device['port'])
        self.log(f"断开 {device['ip']}:{device['port']}: {msg}")
    
    def disconnect_selected(self):
        for row in range(self.device_table.rowCount()):
            checkbox = self.device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                self.disconnect_device(self.devices[row])
    
    def select_all_devices(self):
        for row in range(self.device_table.rowCount()):
            checkbox = self.device_table.item(row, 0)
            if checkbox:
                checkbox.setCheckState(Qt.Checked)
    
    def clear_saved_devices(self):
        """清除保存的设备列表"""
        import json
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            save_file = os.path.join(script_dir, "devices.json")
            if os.path.exists(save_file):
                os.remove(save_file)
                self.log("✓ 已清除保存的设备列表")
                self.devices = []
                self.device_table.setRowCount(0)
                self.device_count_label.setText("已发现 0 台设备")
                self.update_device_tables()
            else:
                self.log("ℹ 没有保存的设备列表")
        except Exception as e:
            self.log(f"⚠ 清除失败：{e}")
    
    def update_device_tables(self):
        # 获取 APK 版本信息
        apk_path = self.apk_path_edit.text().strip()
        apk_version = "-"
        apk_code = None
        apk_name = None
        if apk_path and os.path.exists(apk_path):
            code, name = self.adb.get_apk_version(apk_path)
            if code or name:
                apk_name = name or str(code)
                apk_version = f"v{apk_name}"
                apk_code = code
        
        # 安装页面 - 带版本对比
        self.install_device_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            # 选择列
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked)
            self.install_device_table.setItem(row, 0, checkbox)
            
            # 设备列
            self.install_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
            
            # 已安装版本列 - 需要查询
            version_item = QTableWidgetItem("检测中...")
            version_item.setForeground(QColor("#999"))
            self.install_device_table.setItem(row, 2, version_item)
            
            # APK 版本列 - 统一显示格式 v1.5.0
            apk_version_item = QTableWidgetItem(apk_version)
            if apk_code:
                apk_version_item.setForeground(QColor("#006600"))
            self.install_device_table.setItem(row, 3, apk_version_item)
            
            # 策略列 - 使用下拉框，根据版本自动选择
            policy_combo = QComboBox()
            policy_combo.addItems([
                "智能对比",
                "跳过已安装",
                "强制覆盖"
            ])
            # 默认选择全局策略
            policy_combo.setCurrentIndex(self.version_policy.currentIndex())
            self.install_device_table.setCellWidget(row, 4, policy_combo)
        
        # 卸载页面
        self.uninstall_device_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked)
            self.uninstall_device_table.setItem(row, 0, checkbox)
            self.uninstall_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
        
        # 重试页面清空
        self.retry_device_table.setRowCount(0)
        self.failed_devices = []
    
    # ========== 安装功能 ==========
    
    def on_package_name_changed(self, text):
        """包名改变时自动检查已安装版本"""
        if text and self.devices:
            # 延迟 500ms 检查，避免频繁查询
            if hasattr(self, 'check_timer'):
                self.check_timer.stop()
            else:
                from PyQt5.QtCore import QTimer
                self.check_timer = QTimer()
                self.check_timer.setSingleShot(True)
                self.check_timer.timeout.connect(self.check_installed_versions)
            self.check_timer.start(500)
    
    def on_refresh_version_clicked(self):
        """手动刷新版本按钮点击事件"""
        package_name = self.package_name_edit.text().strip()
        if not package_name:
            QMessageBox.warning(self, "提示", "请先输入应用包名")
            return
        
        if not self.devices:
            QMessageBox.warning(self, "提示", "没有设备，请先扫描设备")
            return
        
        self.log("🔄 手动刷新版本状态...")
        self.check_installed_versions(package_name)
    
    def on_version_policy_changed(self, index):
        tips = [
            "💡 智能对比：自动检测已安装版本，只有新版本才会安装",
            "💡 跳过已安装：只要已安装就跳过，不检查版本",
            "💡 强制覆盖：无论是否安装都覆盖安装"
        ]
        self.version_policy_tip.setText(tips[index])
        
        # 自动更新所有设备的策略
        for row in range(self.install_device_table.rowCount()):
            policy_combo = self.install_device_table.cellWidget(row, 4)
            if policy_combo:
                policy_combo.setCurrentIndex(index)
    
    def browse_apk(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择 APK 文件", "", "APK Files (*.apk)")
        if file_path:
            self.apk_path_edit.setText(file_path)
            self.log(f"已选择 APK: {file_path}")
            
            # 获取版本信息
            try:
                version_code, version_name = self.adb.get_apk_version(file_path)
                self.log(f"APK 解析结果：code={version_code}, name={version_name}")
                if version_code or version_name:
                    version_str = f"APK 版本：v{version_name or ''} (code: {version_code or 'N/A'})"
                    self.version_info_label.setText(version_str)
                    self.version_info_label.setStyleSheet("color: #006600; font-weight: bold;")
                    
                    # 更新表格中的 APK 版本列
                    apk_version = f"v{version_name or version_code}"
                    for row in range(self.install_device_table.rowCount()):
                        item = QTableWidgetItem(apk_version)
                        item.setForeground(QColor("#006600"))
                        self.install_device_table.setItem(row, 3, item)
                else:
                    self.version_info_label.setText("APK 版本信息：无法读取")
                    self.log("⚠ APK 版本解析失败")
            except Exception as e:
                self.version_info_label.setText(f"APK 版本信息：解析错误")
                self.log(f"✗ APK 版本解析错误：{e}")
    
    def check_installed_versions(self, package_name=None):
        """异步检查所有设备的已安装版本"""
        # 如果没有传入包名，从安装标签页获取
        if package_name is None:
            package_name = self.package_name_edit.text().strip()
        
        if not package_name:
            self.log("⚠ 未输入包名，跳过版本检测")
            return
        
        if not self.devices:
            self.log("ℹ 没有设备，跳过版本检测")
            return
        
        self.log(f"🔄 开始检测 {len(self.devices)} 台设备的已安装版本 (包名：{package_name})...")
        
        # 取消之前的检查线程
        if hasattr(self, 'check_version_thread') and self.check_version_thread.isRunning():
            self.check_version_thread.stop()
            self.check_version_thread.wait()
        
        # 启动新线程
        self.check_version_thread = CheckVersionThread(self.devices, package_name, self.adb)
        self.check_version_thread.version_checked.connect(self.update_installed_version)
        self.check_version_thread.finished.connect(self.on_check_versions_finished)
        self.check_version_thread.start()
    
    def update_installed_version(self, device_id, version):
        """更新已安装版本显示，并自动调整策略"""
        self.log(f"📝 更新设备 {device_id} 的版本：{version}")
        
        found = False
        for row in range(self.install_device_table.rowCount()):
            if row < len(self.devices):
                current_id = self.devices[row]["id"]
                self.log(f"  检查行 {row}: {current_id} == {device_id}? {current_id == device_id}")
                
                if current_id == device_id:
                    found = True
                    # 更新版本显示
                    item = QTableWidgetItem(version)
                    if version == "未安装":
                        item.setForeground(QColor("#999"))
                    else:
                        item.setForeground(QColor("#0066cc"))
                    self.install_device_table.setItem(row, 2, item)
                    self.log(f"  ✓ 已更新行 {row} 的版本列为：{version}")
                    
                    # 自动调整策略
                    policy_combo = self.install_device_table.cellWidget(row, 4)
                    if policy_combo:
                        # 获取 APK 版本信息
                        apk_path = self.apk_path_edit.text().strip()
                        apk_code = None
                        apk_name = None
                        if apk_path and os.path.exists(apk_path):
                            apk_code, apk_name = self.adb.get_apk_version(apk_path)
                        
                        # 获取已安装版本的 versionCode
                        installed_code = None
                        if version != "未安装":
                            # 重新查询 versionCode
                            package_name = self.package_name_edit.text().strip()
                            if package_name:
                                success, stdout, _ = self.adb._run_adb(
                                    device_id, "shell", "dumpsys", "package", package_name, timeout=30
                                )
                                if success and stdout:
                                    match = re.search(r'versionCode=(\d+)', stdout)
                                    if match:
                                        installed_code = int(match.group(1))
                        
                        # 自动选择策略
                        if version == "未安装":
                            policy_combo.setCurrentIndex(0)
                            self.log(f"  ✓ 策略设置为：智能对比 (未安装)")
                        elif apk_code and installed_code:
                            if apk_code > installed_code:
                                policy_combo.setCurrentIndex(0)
                                self.log(f"  ✓ 策略设置为：智能对比 (APK 版本更高)")
                            elif apk_code == installed_code:
                                policy_combo.setCurrentIndex(1)
                                self.log(f"  ✓ 策略设置为：跳过已安装 (版本相同)")
                            else:
                                policy_combo.setCurrentIndex(1)
                                self.log(f"  ✓ 策略设置为：跳过已安装 (APK 版本更低)")
                        else:
                            policy_combo.setCurrentIndex(0)
                            self.log(f"  ✓ 策略设置为：智能对比 (默认)")
                    
                    break
        
        if not found:
            self.log(f"  ⚠ 未找到设备 {device_id} 在表格中")
    
    def on_check_versions_finished(self):
        """版本检查完成"""
        self.log("✓ 已安装版本检测完成")
        self.log(f"  表格行数：{self.install_device_table.rowCount()}")
        self.log(f"  设备数量：{len(self.devices)}")
    
    def start_install(self):
        apk_path = self.apk_path_edit.text().strip()
        package_name = self.package_name_edit.text().strip()
        
        if not apk_path:
            QMessageBox.warning(self, "错误", "请选择 APK 文件")
            return
        if not package_name:
            QMessageBox.warning(self, "错误", "请输入应用包名")
            return
        if not os.path.exists(apk_path):
            QMessageBox.warning(self, "错误", "APK 文件不存在")
            return
        
        selected_devices = []
        for row in range(self.install_device_table.rowCount()):
            checkbox = self.install_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                selected_devices.append(self.devices[row])
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "请至少选择一台设备")
            return
        
        # 重置统计
        self.install_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.failed_devices = []
        self.install_result_label.setText("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        
        max_threads = self.install_threads.value()
        policy_map = {0: "compare", 1: "skip", 2: "force"}
        version_policy = policy_map[self.version_policy.currentIndex()]
        
        self.install_btn.setEnabled(False)
        self.stop_install_btn.setEnabled(True)
        self.install_progress_label.setText("正在安装...")
        self.log(f"📦 开始安装到 {len(selected_devices)} 台设备")
        self.log(f"   APK: {os.path.basename(apk_path)}")
        self.log(f"   包名：{package_name}")
        self.log(f"   策略：{self.version_policy.currentText()}")
        
        self.install_thread = InstallThread(
            selected_devices, apk_path, package_name, max_threads, version_policy
        )
        self.install_thread.install_progress.connect(self.on_install_progress)
        self.install_thread.task_finished.connect(self.on_install_task_finished)
        self.install_thread.all_finished.connect(self.on_install_all_finished)
        self.install_thread.start()
    
    def stop_install(self):
        if self.install_thread:
            self.install_thread.stop()
            self.log("安装已停止")
    
    def on_install_progress(self, device_id, status, message, device_info):
        icons = {
            "installing": "🔄", "success": "✅", "error": "❌", 
            "skipped": "⏭️", "uninstalling": "🗑️", "comparing": "📊"
        }
        icon = icons.get(status, "")
        self.install_progress_label.setText(f"{icon} {device_id}: {message}")
        self.log(f"[{status.upper()}] {device_id}: {message}")
    
    def on_install_task_finished(self, device_id, success, message, device_info):
        if success:
            if "跳过" in message or "skipped" in message.lower():
                self.install_stats["skipped"] += 1
            else:
                self.install_stats["success"] += 1
        else:
            self.install_stats["failure"] += 1
            # 记录失败设备
            for device in self.devices:
                if device["id"] == device_id:
                    self.failed_devices.append({
                        **device,
                        "error": message,
                        "retry_count": 0
                    })
                    break
        
        self.install_result_label.setText(
            f"✅ 成功：{self.install_stats['success']} | "
            f"❌ 失败：{self.install_stats['failure']} | "
            f"⏭️ 跳过：{self.install_stats['skipped']}")
        
        # 更新设备表格中的版本信息
        if success and device_info:
            for row in range(self.install_device_table.rowCount()):
                if self.devices[row]["id"] == device_id:
                    if device_info.get("apk_version_code"):
                        version_item = QTableWidgetItem(f"v{device_info['apk_version_code']}")
                        version_item.setForeground(QColor("#006600"))
                        self.install_device_table.setItem(row, 2, version_item)
                    break
    
    def on_install_all_finished(self):
        self.install_btn.setEnabled(True)
        self.stop_install_btn.setEnabled(False)
        
        if self.install_stats["failure"] > 0:
            self.install_progress_label.setText(f"安装完成 - {self.install_stats['failure']} 台设备失败，请查看「失败重试」标签")
            self.log(f"⚠️ 安装完成 - {self.install_stats['failure']} 台设备失败")
            self.update_retry_table()
        else:
            self.install_progress_label.setText("✓ 安装完成 - 全部成功!")
            self.log(f"✓ 安装完成 - 全部成功!")
        
        total = sum(self.install_stats.values())
        self.log(f"统计 - 成功：{self.install_stats['success']}/{total} | 跳过：{self.install_stats['skipped']}")
    
    # ========== 重试功能 ==========
    
    def update_retry_table(self):
        """更新重试设备表格"""
        self.retry_device_table.setRowCount(len(self.failed_devices))
        for row, device in enumerate(self.failed_devices):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked)
            self.retry_device_table.setItem(row, 0, checkbox)
            self.retry_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
            
            error_item = QTableWidgetItem(device.get("error", "未知错误")[:50])
            error_item.setForeground(QColor("#cc0000"))
            self.retry_device_table.setItem(row, 2, error_item)
            
            retry_count_item = QTableWidgetItem(str(device.get("retry_count", 0)))
            self.retry_device_table.setItem(row, 3, retry_count_item)
    
    def create_retry_tab(self):
        """创建失败重试标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        tip_group = QGroupBox("使用说明")
        tip_layout = QVBoxLayout(tip_group)
        tip1 = QLabel("⚠️ 此页面显示上次安装失败的设备")
        tip1.setStyleSheet("color: #cc0000; font-weight: bold;")
        tip_layout.addWidget(tip1)
        tip2 = QLabel("• 可以选择部分或全部失败设备重新尝试安装")
        tip2.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip2)
        tip3 = QLabel("• 重试前会自动卸载旧版本，然后重新安装")
        tip3.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip3)
        layout.addWidget(tip_group)
        
        device_group = QGroupBox("失败设备列表")
        device_layout = QVBoxLayout(device_group)
        
        self.retry_device_table = QTableWidget()
        self.retry_device_table.setColumnCount(4)
        self.retry_device_table.setHorizontalHeaderLabels(["选择", "设备", "失败原因", "重试次数"])
        self.retry_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        device_layout.addWidget(self.retry_device_table)
        
        layout.addWidget(device_group)
        
        btn_layout = QHBoxLayout()
        self.retry_btn = QPushButton("🔄 重试选中设备")
        self.retry_btn.clicked.connect(self.start_retry)
        self.retry_btn.setFixedWidth(180)
        self.retry_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #ff9800; color: white; padding: 8px; }")
        btn_layout.addWidget(self.retry_btn)
        
        self.stop_retry_btn = QPushButton("⏹️ 停止")
        self.stop_retry_btn.clicked.connect(self.stop_retry)
        self.stop_retry_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_retry_btn)
        
        btn_layout.addStretch()
        
        self.retry_progress_label = QLabel("准备就绪")
        btn_layout.addWidget(self.retry_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.retry_progress_bar = QProgressBar()
        layout.addWidget(self.retry_progress_bar)
        
        self.retry_result_label = QLabel("✅ 成功：0 | ❌ 失败：0")
        self.retry_result_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self.retry_result_label)
        
        return widget
    
    def start_retry(self):
        apk_path = self.apk_path_edit.text().strip()
        package_name = self.package_name_edit.text().strip()
        
        if not apk_path:
            QMessageBox.warning(self, "错误", "请先在「应用安装」标签选择 APK 文件")
            return
        if not package_name:
            QMessageBox.warning(self, "错误", "请输入应用包名")
            return
        
        selected_devices = []
        for row in range(self.retry_device_table.rowCount()):
            checkbox = self.retry_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                selected_devices.append(self.failed_devices[row])
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "请至少选择一台设备")
            return
        
        self.retry_stats = {"success": 0, "failure": 0}
        self.retry_result_label.setText("✅ 成功：0 | ❌ 失败：0")
        
        self.retry_btn.setEnabled(False)
        self.stop_retry_btn.setEnabled(True)
        self.retry_progress_label.setText("正在重试...")
        self.log(f"🔄 开始重试 {len(selected_devices)} 台设备")
        
        self.retry_thread = RetryInstallThread(selected_devices, apk_path, package_name, max_threads=5)
        self.retry_thread.retry_progress.connect(self.on_retry_progress)
        self.retry_thread.retry_finished.connect(self.on_retry_finished)
        self.retry_thread.all_finished.connect(self.on_retry_all_finished)
        self.retry_thread.start()
    
    def stop_retry(self):
        if self.retry_thread:
            self.retry_thread.stop()
            self.log("重试已停止")
    
    def on_retry_progress(self, device_id, status, message):
        icons = {"retrying": "🔄", "success": "✅", "error": "❌", "uninstalling": "🗑️"}
        icon = icons.get(status, "")
        self.retry_progress_label.setText(f"{icon} {device_id}: {message}")
        self.log(f"[{status.upper()}] {device_id}: {message}")
    
    def on_retry_finished(self, device_id, success, message):
        if success:
            self.retry_stats["success"] += 1
            # 从失败列表移除
            self.failed_devices = [d for d in self.failed_devices if d["id"] != device_id]
        else:
            self.retry_stats["failure"] += 1
            # 增加重试次数
            for device in self.failed_devices:
                if device["id"] == device_id:
                    device["retry_count"] = device.get("retry_count", 0) + 1
                    break
        
        self.retry_result_label.setText(f"✅ 成功：{self.retry_stats['success']} | ❌ 失败：{self.retry_stats['failure']}")
        self.update_retry_table()
    
    def on_retry_all_finished(self):
        self.retry_btn.setEnabled(True)
        self.stop_retry_btn.setEnabled(False)
        
        if self.retry_stats["failure"] == 0:
            self.retry_progress_label.setText("✓ 重试完成 - 全部成功!")
            self.log("✓ 重试完成 - 全部成功!")
        else:
            self.retry_progress_label.setText(f"重试完成 - {self.retry_stats['failure']} 台设备仍然失败")
            self.log(f"⚠️ 重试完成 - {self.retry_stats['failure']} 台设备仍然失败")
        
        # 刷新版本状态 - 直接使用安装包名
        package_name = self.package_name_edit.text().strip()
        if package_name:
            self.log(f"🔄 刷新设备版本状态...")
            self.check_installed_versions(package_name)
        else:
            self.log("⚠ 包名为空，跳过版本刷新")
    
    # ========== 卸载功能 ==========
    
    def start_uninstall(self):
        package_name = self.uninstall_package_edit.text().strip()
        
        if not package_name:
            QMessageBox.warning(self, "错误", "请输入应用包名")
            return
        
        selected_devices = []
        for row in range(self.uninstall_device_table.rowCount()):
            checkbox = self.uninstall_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                selected_devices.append(self.devices[row])
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "请至少选择一台设备")
            return
        
        self.uninstall_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.uninstall_result_label.setText("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        max_threads = self.uninstall_threads.value()
        
        self.uninstall_btn.setEnabled(False)
        self.stop_uninstall_btn.setEnabled(True)
        self.uninstall_progress_label.setText("正在卸载...")
        self.uninstall_progress_bar.setValue(0)
        self.log(f"🗑️ 开始卸载 {package_name} 从 {len(selected_devices)} 台设备")
        
        # 使用异步线程卸载
        self.uninstall_thread = UninstallThread(selected_devices, package_name, max_threads)
        self.uninstall_thread.uninstall_progress.connect(self.on_uninstall_progress)
        self.uninstall_thread.task_finished.connect(self.on_uninstall_task_finished)
        self.uninstall_thread.all_finished.connect(self.on_uninstall_all_finished)
        self.uninstall_thread.start()
    
    def stop_uninstall(self):
        if self.uninstall_thread:
            self.uninstall_thread.stop()
            self.log("卸载已停止")
        self.uninstall_btn.setEnabled(True)
        self.stop_uninstall_btn.setEnabled(False)
    
    def on_uninstall_progress(self, device_id, status, message):
        icons = {
            "checking": "🔍", "uninstalling": "🗑️", "success": "✅", 
            "error": "❌", "skipped": "⏭️"
        }
        icon = icons.get(status, "")
        self.uninstall_progress_label.setText(f"{icon} {device_id}: {message}")
        self.log(f"[{status.upper()}] {device_id}: {message}")
    
    def on_uninstall_task_finished(self, device_id, success, message, status):
        if status == "skipped":
            self.uninstall_stats["skipped"] += 1
        elif success:
            self.uninstall_stats["success"] += 1
        else:
            self.uninstall_stats["failure"] += 1
        
        total = sum(self.uninstall_stats.values())
        self.uninstall_result_label.setText(
            f"✅ 成功：{self.uninstall_stats['success']} | "
            f"❌ 失败：{self.uninstall_stats['failure']} | "
            f"⏭️ 跳过：{self.uninstall_stats['skipped']}")
        
        if total > 0:
            progress = int((total / len(self.devices)) * 100)
            self.uninstall_progress_bar.setValue(progress)
    
    def on_uninstall_all_finished(self):
        self.uninstall_btn.setEnabled(True)
        self.stop_uninstall_btn.setEnabled(False)
        
        total = sum(self.uninstall_stats.values())
        if self.uninstall_stats["failure"] == 0:
            self.uninstall_progress_label.setText(f"✓ 卸载完成 - 成功 {self.uninstall_stats['success']}/{total}")
            self.log(f"✓ 卸载完成 - 成功：{self.uninstall_stats['success']}/{total}")
        else:
            self.uninstall_progress_label.setText(f"卸载完成 - {self.uninstall_stats['failure']} 台失败")
            self.log(f"⚠️ 卸载完成 - 失败：{self.uninstall_stats['failure']}/{total}")
        
        # 刷新版本状态 - 直接使用卸载包名
        package_name = self.uninstall_package_edit.text().strip()
        if package_name:
            self.log(f"🔄 刷新设备版本状态...")
            # 同步包名到安装标签页
            self.package_name_edit.setText(package_name)
            # 检查版本
            self.check_installed_versions(package_name)
        else:
            self.log("⚠ 卸载包名为空，跳过版本刷新")

    def stop_uninstall(self):
        self.log("卸载已停止")
        self.uninstall_btn.setEnabled(True)
        self.stop_uninstall_btn.setEnabled(False)
    
    def export_log(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "导出日志", "adb_manager_log.txt", "Text Files (*.txt)")
        if file_path:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.log_text.toPlainText())
            self.log(f"✓ 日志已导出：{file_path}")




class InstallThread(QThread):
    """批量安装线程"""
    install_progress = pyqtSignal(str, str, str, object)  # device, status, message, device_info
    task_finished = pyqtSignal(str, bool, str, object)  # device, success, message, device_info
    all_finished = pyqtSignal()
    
    def __init__(self, devices, apk_path, package_name, max_threads=10, 
                 version_policy="compare", force_reinstall=False):
        super().__init__()
        self.devices = devices
        self.apk_path = apk_path
        self.package_name = package_name
        self.max_threads = max_threads
        self.version_policy = version_policy  # compare, skip, force, reinstall
        self.force_reinstall = force_reinstall
        self.adb = ADBWorker()
        self.stop_flag = False
        
        # 获取 APK 版本
        self.apk_version_code, self.apk_version_name = self.adb.get_apk_version(apk_path)
    
    def run(self):
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = {
                executor.submit(self.install_to_device, device): device
                for device in self.devices
            }
            
            for future in as_completed(futures):
                if self.stop_flag:
                    break
                device = futures[future]
                try:
                    device_id, success, message, device_info = future.result()
                    self.task_finished.emit(device_id, success, message, device_info)
                except Exception as e:
                    self.task_finished.emit(device["id"], False, str(e), device)
        
        self.all_finished.emit()
    
    def install_to_device(self, device):
        device_id = device["id"]
        device_info = {
            "installed_version": None,
            "apk_version_code": self.apk_version_code,
            "apk_version_name": self.apk_version_name
        }
        
        try:
            # 检查是否已安装
            is_installed = self.adb.is_installed(device_id, self.package_name)
            
            if is_installed:
                # 获取已安装的 versionCode（整数）
                success, stdout, _ = self.adb._run_adb(
                    device_id, "shell", "dumpsys", "package", self.package_name, timeout=30
                )
                installed_code = None
                installed_name = None
                if success and stdout:
                    match = re.search(r'versionCode=(\d+)', stdout)
                    if match:
                        installed_code = int(match.group(1))
                    match = re.search(r'versionName=([\d.]+)', stdout)
                    if match:
                        installed_name = match.group(1)
                
                device_info["installed_version"] = installed_name or installed_code
                
                if self.version_policy == "skip":
                    self.install_progress.emit(device_id, "skipped", f"已安装 (v{installed_name or installed_code})，跳过", device_info)
                    return device_id, True, f"已安装，跳过", device_info
                
                elif self.version_policy == "compare" and installed_code:
                    if self.apk_version_code and installed_code >= self.apk_version_code:
                        self.install_progress.emit(device_id, "skipped", f"已是最新版本 (v{installed_name})，跳过", device_info)
                        return device_id, True, f"已是最新版本，跳过", device_info
                    else:
                        self.install_progress.emit(device_id, "comparing", 
                            f"版本对比：已安装 v{installed_name} → 新版本 v{self.apk_version_name}", device_info)
                
                elif self.version_policy == "reinstall" or self.force_reinstall:
                    self.install_progress.emit(device_id, "uninstalling", "正在卸载旧版本...", device_info)
                    success, msg = self.adb.uninstall(device_id, self.package_name)
                    if not success:
                        self.install_progress.emit(device_id, "error", f"卸载失败：{msg}", device_info)
                        return device_id, False, f"卸载失败：{msg}", device_info
            
            # 安装
            self.install_progress.emit(device_id, "installing", 
                f"正在安装 v{self.apk_version_name or self.apk_version_code}...", device_info)
            success, msg = self.adb.install(device_id, self.apk_path, replace=True)
            
            if success:
                self.install_progress.emit(device_id, "success", "安装成功", device_info)
            else:
                self.install_progress.emit(device_id, "error", msg, device_info)
            
            return device_id, success, msg, device_info
            
        except Exception as e:
            error_msg = f"安装异常：{str(e)}"
            self.install_progress.emit(device_id, "error", error_msg, device_info)
            return device_id, False, error_msg, device_info
    
    def stop(self):
        self.stop_flag = True


class CheckVersionThread(QThread):
    """检查已安装版本的线程"""
    version_checked = pyqtSignal(str, str)  # device_id, version
    finished = pyqtSignal()
    
    def __init__(self, devices, package_name, adb):
        super().__init__()
        self.devices = devices
        self.package_name = package_name
        self.adb = adb
        self.stop_flag = False
    
    def run(self):
        import sys
        for i, device in enumerate(self.devices):
            if self.stop_flag:
                break
            device_id = device["id"]
            version = self.adb.get_installed_version(device_id, self.package_name)
            version_str = f"v{version}" if version else "未安装"
            # 使用 print 输出调试信息（会显示在控制台）
            print(f"[DEBUG] 检查设备 {i+1}/{len(self.devices)}: {device_id} = {version_str}", file=sys.stderr)
            self.version_checked.emit(device_id, version_str)
        print(f"[DEBUG] CheckVersionThread 完成", file=sys.stderr)
        self.finished.emit()
    
    def stop(self):
        self.stop_flag = True


class ADBBatchManager(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.adb = ADBWorker()
        self.devices = []
        self.failed_devices = []  # 安装失败的设备
        self.scan_thread = None
        self.install_thread = None
        self.retry_thread = None
        self.install_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.retry_stats = {"success": 0, "failure": 0}
        self.init_ui()
        self.log("=" * 50)
        self.log("adb 批量设备安装工具 已启动")
        self.log("增强功能：版本检测 | 失败重试 | 自定义端口")
        self.log("=" * 50)
        self.check_adb()
        
        # 加载上次扫描的设备
        self.load_devices()
    
    def init_ui(self):
        self.setWindowTitle("adb 批量设备安装工具")
        self.setMinimumSize(1400, 900)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        tabs = QTabWidget()
        tabs.addTab(self.create_scan_tab(), "📱 设备发现")
        tabs.addTab(self.create_install_tab(), "📦 应用安装")
        tabs.addTab(self.create_retry_tab(), "⚠️ 失败重试")
        tabs.addTab(self.create_uninstall_tab(), "🗑️ 应用卸载")
        tabs.addTab(self.create_log_tab(), "📋 日志")
        
        main_layout.addWidget(tabs)
        self.statusBar().showMessage("就绪")
    
    def create_scan_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        scan_group = QGroupBox("扫描设置")
        scan_layout = QHBoxLayout(scan_group)
        
        # IP 范围 - 完整 IP 地址
        ip_layout = QVBoxLayout()
        ip_layout.addWidget(QLabel("起始 IP (完整地址):"))
        self.ip_start_edit = QLineEdit()
        self.ip_start_edit.setPlaceholderText("例如：192.168.1.100")
        self.ip_start_edit.setText("192.168.1.100")
        ip_layout.addWidget(self.ip_start_edit)
        
        ip_layout.addWidget(QLabel("结束 IP (完整地址):"))
        self.ip_end_edit = QLineEdit()
        self.ip_end_edit.setPlaceholderText("例如：192.168.1.200")
        self.ip_end_edit.setText("192.168.1.200")
        ip_layout.addWidget(self.ip_end_edit)
        
        # 端口设置 - 单个端口
        port_layout = QVBoxLayout()
        port_layout.addWidget(QLabel("ADB 端口:"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(5555)
        port_layout.addWidget(self.port_input)
        port_layout.addWidget(QLabel("默认 5555\n可自定义"))
        
        # 并发数
        thread_layout = QVBoxLayout()
        thread_layout.addWidget(QLabel("最大并发数:"))
        self.scan_threads = QSpinBox()
        self.scan_threads.setRange(1, 200)
        self.scan_threads.setValue(20)  # 降低默认值，避免网络拥塞
        thread_layout.addWidget(self.scan_threads)
        
        scan_layout.addLayout(ip_layout)
        scan_layout.addLayout(port_layout)
        scan_layout.addLayout(thread_layout)
        scan_layout.addStretch()
        
        self.scan_btn = QPushButton("🔍 开始扫描")
        self.scan_btn.clicked.connect(self.start_scan)
        self.scan_btn.setFixedWidth(150)
        self.scan_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; }")
        scan_layout.addWidget(self.scan_btn)
        
        self.stop_scan_btn = QPushButton("⏹️ 停止")
        self.stop_scan_btn.clicked.connect(self.stop_scan)
        self.stop_scan_btn.setEnabled(False)
        self.stop_scan_btn.setFixedWidth(100)
        scan_layout.addWidget(self.stop_scan_btn)
        
        layout.addWidget(scan_group)
        
        self.scan_progress = QProgressBar()
        self.scan_progress.setVisible(False)
        layout.addWidget(self.scan_progress)
        
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(6)
        self.device_table.setHorizontalHeaderLabels(["选择", "IP:端口", "状态", "型号", "Android 版本", "操作"])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.device_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.device_table)
        
        btn_layout = QHBoxLayout()
        self.device_count_label = QLabel("已发现 0 台设备")
        self.device_count_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        btn_layout.addWidget(self.device_count_label)
        btn_layout.addStretch()
        
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.select_all_devices)
        btn_layout.addWidget(self.select_all_btn)
        
        self.disconnect_btn = QPushButton("断开选中")
        self.disconnect_btn.clicked.connect(self.disconnect_selected)
        btn_layout.addWidget(self.disconnect_btn)
        
        self.clear_devices_btn = QPushButton("清除保存")
        self.clear_devices_btn.clicked.connect(self.clear_saved_devices)
        self.clear_devices_btn.setStyleSheet("QPushButton { color: #cc0000; }")
        btn_layout.addWidget(self.clear_devices_btn)
        
        layout.addLayout(btn_layout)
        return widget
    
    def create_install_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # APK 选择
        apk_group = QGroupBox("APK 文件")
        apk_layout = QHBoxLayout(apk_group)
        self.apk_path_edit = QLineEdit()
        self.apk_path_edit.setPlaceholderText("选择要安装的 APK 文件...")
        apk_layout.addWidget(self.apk_path_edit)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_apk)
        apk_layout.addWidget(browse_btn)
        layout.addWidget(apk_group)
        
        # 包名和版本信息
        pkg_group = QGroupBox("应用信息")
        pkg_layout = QVBoxLayout(pkg_group)
        
        pkg_row = QHBoxLayout()
        pkg_row.addWidget(QLabel("包名:"))
        self.package_name_edit = QLineEdit()
        self.package_name_edit.setPlaceholderText("例如：com.example.app")
        pkg_row.addWidget(self.package_name_edit)
        pkg_layout.addLayout(pkg_row)
        
        # 包名改变时自动检查已安装版本
        self.package_name_edit.textChanged.connect(self.on_package_name_changed)
        
        self.version_info_label = QLabel("APK 版本信息：未选择文件")
        self.version_info_label.setStyleSheet("color: #666; font-style: italic;")
        pkg_layout.addWidget(self.version_info_label)
        layout.addWidget(pkg_group)
        
        # 安装设置
        install_group = QGroupBox("安装设置")
        install_layout = QVBoxLayout(install_group)
        
        # 第一行：并发数和全局策略
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("最大并发数:"))
        self.install_threads = QSpinBox()
        self.install_threads.setRange(1, 50)
        self.install_threads.setValue(10)
        row1.addWidget(self.install_threads)
        
        row1.addSpacing(30)
        row1.addWidget(QLabel("全局策略:"))
        self.version_policy = QComboBox()
        self.version_policy.addItems([
            "智能对比 (版本一致或更高则跳过)",
            "跳过已安装 (不检查版本)",
            "强制覆盖 (始终安装)"
        ])
        self.version_policy.setCurrentIndex(0)
        row1.addWidget(self.version_policy)
        row1.addStretch()
        install_layout.addLayout(row1)
        
        # 版本策略说明
        self.version_policy_tip = QLabel("💡 智能对比：自动检测已安装版本，只有新版本才会安装")
        self.version_policy_tip.setStyleSheet("color: #0066cc; font-size: 11px;")
        install_layout.addWidget(self.version_policy_tip)
        self.version_policy.currentIndexChanged.connect(self.on_version_policy_changed)
        
        layout.addWidget(install_group)
        
        # 设备选择和版本对比
        device_group = QGroupBox("设备列表与版本对比")
        device_layout = QVBoxLayout(device_group)
        
        # 刷新按钮行
        refresh_row = QHBoxLayout()
        refresh_row.addStretch()
        self.refresh_version_btn = QPushButton("🔄 刷新版本")
        self.refresh_version_btn.clicked.connect(self.on_refresh_version_clicked)
        self.refresh_version_btn.setFixedWidth(120)
        self.refresh_version_btn.setStyleSheet("QPushButton { font-size: 12px; background-color: #2196F3; color: white; padding: 5px; }")
        refresh_row.addWidget(self.refresh_version_btn)
        device_layout.addLayout(refresh_row)
        
        self.install_device_table = QTableWidget()
        self.install_device_table.setColumnCount(5)
        self.install_device_table.setHorizontalHeaderLabels([
            "选择", "设备", "已安装版本", "APK 版本", "策略"
        ])
        self.install_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # 策略列使用下拉框
        self.install_device_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        device_layout.addWidget(self.install_device_table)
        
        # 策略说明
        strategy_tip = QLabel("💡 可在表格中为每台设备单独设置策略，也可点击'刷新版本'按钮手动刷新")
        strategy_tip.setStyleSheet("color: #999; font-size: 10px;")
        device_layout.addWidget(strategy_tip)
        
        layout.addWidget(device_group)
        
        # 安装按钮和进度
        btn_layout = QHBoxLayout()
        self.install_btn = QPushButton("📦 开始安装")
        self.install_btn.clicked.connect(self.start_install)
        self.install_btn.setFixedWidth(150)
        self.install_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #4CAF50; color: white; padding: 8px; }")
        btn_layout.addWidget(self.install_btn)
        
        self.stop_install_btn = QPushButton("⏹️ 停止")
        self.stop_install_btn.clicked.connect(self.stop_install)
        self.stop_install_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_install_btn)
        btn_layout.addStretch()
        
        self.install_progress_label = QLabel("准备就绪")
        self.install_progress_label.setStyleSheet("font-size: 12px;")
        btn_layout.addWidget(self.install_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.install_progress_bar = QProgressBar()
        layout.addWidget(self.install_progress_bar)
        
        self.install_result_label = QLabel("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        self.install_result_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self.install_result_label)
        
        self.retry_tip_label = QLabel("💡 安装失败的设备会自动出现在「失败重试」标签页，可以单独重试")
        self.retry_tip_label.setStyleSheet("color: #ff6600; font-size: 11px;")
        layout.addWidget(self.retry_tip_label)
        
        return widget
    
    def create_retry_tab(self):
        """创建失败重试标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 说明
        tip_group = QGroupBox("使用说明")
        tip_layout = QVBoxLayout(tip_group)
        tip1 = QLabel("⚠️ 此页面显示上次安装失败的设备")
        tip1.setStyleSheet("color: #cc0000; font-weight: bold;")
        tip_layout.addWidget(tip1)
        tip2 = QLabel("• 可以选择部分或全部失败设备重新尝试安装")
        tip2.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip2)
        tip3 = QLabel("• 重试前会自动卸载旧版本，然后重新安装")
        tip3.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip3)
        layout.addWidget(tip_group)
        
        # 失败设备列表
        device_group = QGroupBox("失败设备列表")
        device_layout = QVBoxLayout(device_group)
        
        self.retry_device_table = QTableWidget()
        self.retry_device_table.setColumnCount(4)
        self.retry_device_table.setHorizontalHeaderLabels(["选择", "设备", "失败原因", "重试次数"])
        self.retry_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        device_layout.addWidget(self.retry_device_table)
        
        layout.addWidget(device_group)
        
        # 重试按钮
        btn_layout = QHBoxLayout()
        self.retry_btn = QPushButton("🔄 重试选中设备")
        self.retry_btn.clicked.connect(self.start_retry)
        self.retry_btn.setFixedWidth(180)
        self.retry_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #ff9800; color: white; padding: 8px; }")
        btn_layout.addWidget(self.retry_btn)
        
        self.stop_retry_btn = QPushButton("⏹️ 停止")
        self.stop_retry_btn.clicked.connect(self.stop_retry)
        self.stop_retry_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_retry_btn)
        
        btn_layout.addStretch()
        
        self.retry_progress_label = QLabel("准备就绪")
        btn_layout.addWidget(self.retry_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.retry_progress_bar = QProgressBar()
        layout.addWidget(self.retry_progress_bar)
        
        self.retry_result_label = QLabel("✅ 成功：0 | ❌ 失败：0")
        self.retry_result_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self.retry_result_label)
        
        return widget
    
    def create_uninstall_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 包名输入
        pkg_group = QGroupBox("要卸载的应用")
        pkg_layout = QVBoxLayout(pkg_group)
        
        pkg_row1 = QHBoxLayout()
        pkg_row1.addWidget(QLabel("应用包名:"))
        self.uninstall_package_edit = QLineEdit()
        self.uninstall_package_edit.setPlaceholderText("例如：com.example.app")
        pkg_row1.addWidget(self.uninstall_package_edit)
        pkg_layout.addLayout(pkg_row1)
        
        pkg_tip = QLabel("💡 提示：请输入完整的应用包名")
        pkg_tip.setStyleSheet("color: #666; font-size: 11px;")
        pkg_layout.addWidget(pkg_tip)
        
        layout.addWidget(pkg_group)
        
        # 卸载设置
        uninstall_group = QGroupBox("卸载设置")
        uninstall_layout = QHBoxLayout(uninstall_group)
        uninstall_layout.addWidget(QLabel("最大并发数:"))
        self.uninstall_threads = QSpinBox()
        self.uninstall_threads.setRange(1, 50)
        self.uninstall_threads.setValue(10)
        uninstall_layout.addWidget(self.uninstall_threads)
        uninstall_layout.addStretch()
        layout.addWidget(uninstall_group)
        
        # 设备选择
        device_group = QGroupBox("选择设备")
        device_layout = QVBoxLayout(device_group)
        self.uninstall_device_table = QTableWidget()
        self.uninstall_device_table.setColumnCount(2)
        self.uninstall_device_table.setHorizontalHeaderLabels(["选择", "设备"])
        self.uninstall_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        device_layout.addWidget(self.uninstall_device_table)
        layout.addWidget(device_group)
        
        # 卸载按钮和进度
        btn_layout = QHBoxLayout()
        self.uninstall_btn = QPushButton("🗑️ 开始卸载")
        self.uninstall_btn.clicked.connect(self.start_uninstall)
        self.uninstall_btn.setFixedWidth(150)
        self.uninstall_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #f44336; color: white; padding: 8px; }")
        btn_layout.addWidget(self.uninstall_btn)
        
        self.stop_uninstall_btn = QPushButton("⏹️ 停止")
        self.stop_uninstall_btn.clicked.connect(self.stop_uninstall)
        self.stop_uninstall_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_uninstall_btn)
        btn_layout.addStretch()
        
        self.uninstall_progress_label = QLabel("准备就绪")
        self.uninstall_progress_label.setStyleSheet("font-size: 12px;")
        btn_layout.addWidget(self.uninstall_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.uninstall_progress_bar = QProgressBar()
        layout.addWidget(self.uninstall_progress_bar)
        
        self.uninstall_result_label = QLabel("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        self.uninstall_result_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #0066cc;")
        layout.addWidget(self.uninstall_result_label)
        
        return widget
    
    def create_log_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self.log_text)
        
        btn_layout = QHBoxLayout()
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self.log_text.clear)
        btn_layout.addWidget(clear_btn)
        
        export_btn = QPushButton("导出日志")
        export_btn.clicked.connect(self.export_log)
        btn_layout.addWidget(export_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        return widget
    
    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        self.log_text.append(log_line)
        self.log_text.moveCursor(QTextCursor.End)
    
    def check_adb(self):
        try:
            result = subprocess.run([self.adb.adb_path, "version"], capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode == 0:
                version_line = result.stdout.splitlines()[0]
                self.log(f"✓ ADB 已就绪：{version_line}")
            else:
                self.log("✗ ADB 未找到")
                QMessageBox.warning(self, "警告", "ADB 未找到，请安装 Android SDK Platform-Tools 并添加到 PATH")
        except FileNotFoundError:
            self.log("✗ ADB 未找到")
            QMessageBox.warning(self, "警告", "ADB 未找到，请安装 Android SDK Platform-Tools 并添加到 PATH")
    
    # ========== 扫描功能 ==========
    
    def _parse_ip(self, ip_str):
        """解析 IP 地址，返回四段整数列表"""
        try:
            parts = ip_str.strip().split('.')
            if len(parts) != 4:
                return None
            return [int(p) for p in parts]
        except:
            return None
    
    def _ip_to_str(self, ip_parts):
        """将 IP 地址列表转换为字符串"""
        return '.'.join(str(p) for p in ip_parts)
    
    def _generate_ip_list(self, start_ip_str, end_ip_str):
        """生成 IP 地址列表"""
        start_parts = self._parse_ip(start_ip_str)
        end_parts = self._parse_ip(end_ip_str)
        
        if not start_parts or not end_parts:
            return []
        
        # 检查是否在同一网段（前两段相同）
        if start_parts[:2] != end_parts[:2]:
            return []
        
        ip_list = []
        # 遍历第三段和第四段
        for third in range(start_parts[2], end_parts[2] + 1):
            start_fourth = start_parts[3] if third == start_parts[2] else 0
            end_fourth = end_parts[3] if third == end_parts[2] else 255
            
            for fourth in range(start_fourth, end_fourth + 1):
                ip = f"{start_parts[0]}.{start_parts[1]}.{third}.{fourth}"
                ip_list.append(ip)
        
        return ip_list
    
    def start_scan(self):
        ip_start_str = self.ip_start_edit.text().strip()
        ip_end_str = self.ip_end_edit.text().strip()
        port = self.port_input.value()
        max_threads = self.scan_threads.value()
        
        # 生成 IP 列表
        ip_list = self._generate_ip_list(ip_start_str, ip_end_str)
        
        if not ip_list:
            QMessageBox.warning(self, "错误", 
                "IP 地址格式不正确或不在同一网段\n\n"
                "示例：\n"
                "起始 IP: 192.168.1.100\n"
                "结束 IP: 192.168.1.200\n\n"
                "或跨网段：\n"
                "起始 IP: 192.168.1.1\n"
                "结束 IP: 192.168.2.255")
            return
        
        self.devices = []
        self.failed_devices = []
        self.device_table.setRowCount(0)
        self.scan_btn.setEnabled(False)
        self.stop_scan_btn.setEnabled(True)
        self.scan_progress.setVisible(True)
        self.scan_progress.setValue(0)
        
        self.log(f"开始扫描 {ip_start_str} - {ip_end_str} 端口 {port} (共 {len(ip_list)} 个 IP)")
        
        self.scan_thread = ScanThread(ip_list, port, max_threads)
        self.scan_thread.device_found.connect(self.on_device_found)
        self.scan_thread.scan_progress.connect(self.on_scan_progress)
        self.scan_thread.scan_finished.connect(self.on_scan_finished)
        self.scan_thread.log_message.connect(self.log)
        self.scan_thread.start()
    
    def stop_scan(self):
        if self.scan_thread:
            self.scan_thread.stop()
            self.log("扫描已停止")
    
    def on_device_found(self, device):
        self.devices.append(device)
        row = self.device_table.rowCount()
        self.device_table.insertRow(row)
        
        checkbox = QTableWidgetItem("✓")
        checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        checkbox.setCheckState(Qt.Checked)
        self.device_table.setItem(row, 0, checkbox)
        self.device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']}"))
        self.device_table.setItem(row, 2, QTableWidgetItem(device['state']))
        self.device_table.setItem(row, 3, QTableWidgetItem(device['model']))
        self.device_table.setItem(row, 4, QTableWidgetItem(device['version']))
        
        disconnect_btn = QPushButton("断开")
        disconnect_btn.clicked.connect(lambda checked, d=device: self.disconnect_device(d))
        self.device_table.setCellWidget(row, 5, disconnect_btn)
        
        self.device_count_label.setText(f"已发现 {len(self.devices)} 台设备")
    
    def on_scan_progress(self, current, total):
        self.scan_progress.setMaximum(total)
        self.scan_progress.setValue(current)
        self.statusBar().showMessage(f"扫描进度：{current}/{total}")
    
    def on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.scan_progress.setVisible(False)
        self.log(f"✓ 扫描完成，发现 {len(self.devices)} 台设备")
        self.statusBar().showMessage(f"扫描完成，发现 {len(self.devices)} 台设备")
        self.update_device_tables()
        
        # 保存扫描结果
        self.save_devices()
    
    def save_devices(self):
        """保存设备列表到文件"""
        import json
        try:
            # 使用当前工作目录（exe 运行目录）
            if getattr(sys, 'frozen', False):
                # 打包后的 exe，使用 exe 所在目录
                save_dir = os.path.dirname(sys.executable)
            else:
                # 开发时，使用脚本所在目录
                save_dir = os.path.dirname(os.path.abspath(__file__))
            
            save_file = os.path.join(save_dir, "devices.json")
            with open(save_file, 'w', encoding='utf-8') as f:
                json.dump(self.devices, f, ensure_ascii=False, indent=2)
            self.log(f"✓ 设备列表已保存到：{save_file}")
            self.log(f"  共 {len(self.devices)} 台设备")
        except Exception as e:
            self.log(f"⚠ 保存设备列表失败：{e}")
    
    def load_devices(self):
        """从文件加载设备列表"""
        import json
        try:
            # 使用当前工作目录（exe 运行目录）
            if getattr(sys, 'frozen', False):
                save_dir = os.path.dirname(sys.executable)
            else:
                save_dir = os.path.dirname(os.path.abspath(__file__))
            
            save_file = os.path.join(save_dir, "devices.json")
            
            if os.path.exists(save_file):
                with open(save_file, 'r', encoding='utf-8') as f:
                    self.devices = json.load(f)
                
                if self.devices:
                    self.log(f"✓ 加载上次扫描的设备：{len(self.devices)} 台")
                    self.log(f"  文件：{save_file}")
                    self.update_device_tables()
                    self.device_count_label.setText(f"已发现 {len(self.devices)} 台设备 (已保存)")
                else:
                    self.log("ℹ 保存的设备列表为空")
            else:
                self.log("ℹ 未找到保存的设备列表，请先扫描设备")
        except Exception as e:
            self.log(f"⚠ 加载设备列表失败：{e}")
    
    def disconnect_device(self, device):
        success, msg = self.adb.disconnect(device['ip'], device['port'])
        self.log(f"断开 {device['ip']}:{device['port']}: {msg}")
    
    def disconnect_selected(self):
        for row in range(self.device_table.rowCount()):
            checkbox = self.device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                self.disconnect_device(self.devices[row])
    
    def select_all_devices(self):
        for row in range(self.device_table.rowCount()):
            checkbox = self.device_table.item(row, 0)
            if checkbox:
                checkbox.setCheckState(Qt.Checked)
    
    def clear_saved_devices(self):
        """清除保存的设备列表"""
        import json
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            save_file = os.path.join(script_dir, "devices.json")
            if os.path.exists(save_file):
                os.remove(save_file)
                self.log("✓ 已清除保存的设备列表")
                self.devices = []
                self.device_table.setRowCount(0)
                self.device_count_label.setText("已发现 0 台设备")
                self.update_device_tables()
            else:
                self.log("ℹ 没有保存的设备列表")
        except Exception as e:
            self.log(f"⚠ 清除失败：{e}")
    
    def update_device_tables(self):
        # 获取 APK 版本信息
        apk_path = self.apk_path_edit.text().strip()
        apk_version = "-"
        apk_code = None
        apk_name = None
        if apk_path and os.path.exists(apk_path):
            code, name = self.adb.get_apk_version(apk_path)
            if code or name:
                apk_name = name or str(code)
                apk_version = f"v{apk_name}"
                apk_code = code
        
        # 安装页面 - 带版本对比
        self.install_device_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            # 选择列
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked)
            self.install_device_table.setItem(row, 0, checkbox)
            
            # 设备列
            self.install_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
            
            # 已安装版本列 - 需要查询
            version_item = QTableWidgetItem("检测中...")
            version_item.setForeground(QColor("#999"))
            self.install_device_table.setItem(row, 2, version_item)
            
            # APK 版本列 - 统一显示格式 v1.5.0
            apk_version_item = QTableWidgetItem(apk_version)
            if apk_code:
                apk_version_item.setForeground(QColor("#006600"))
            self.install_device_table.setItem(row, 3, apk_version_item)
            
            # 策略列 - 使用下拉框，根据版本自动选择
            policy_combo = QComboBox()
            policy_combo.addItems([
                "智能对比",
                "跳过已安装",
                "强制覆盖"
            ])
            # 默认选择全局策略
            policy_combo.setCurrentIndex(self.version_policy.currentIndex())
            self.install_device_table.setCellWidget(row, 4, policy_combo)
        
        # 卸载页面
        self.uninstall_device_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked)
            self.uninstall_device_table.setItem(row, 0, checkbox)
            self.uninstall_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
        
        # 重试页面清空
        self.retry_device_table.setRowCount(0)
        self.failed_devices = []
    
    # ========== 安装功能 ==========
    
    def on_package_name_changed(self, text):
        """包名改变时自动检查已安装版本"""
        if text and self.devices:
            # 延迟 500ms 检查，避免频繁查询
            if hasattr(self, 'check_timer'):
                self.check_timer.stop()
            else:
                from PyQt5.QtCore import QTimer
                self.check_timer = QTimer()
                self.check_timer.setSingleShot(True)
                self.check_timer.timeout.connect(self.check_installed_versions)
            self.check_timer.start(500)
    
    def on_refresh_version_clicked(self):
        """手动刷新版本按钮点击事件"""
        package_name = self.package_name_edit.text().strip()
        if not package_name:
            QMessageBox.warning(self, "提示", "请先输入应用包名")
            return
        
        if not self.devices:
            QMessageBox.warning(self, "提示", "没有设备，请先扫描设备")
            return
        
        self.log("🔄 手动刷新版本状态...")
        self.check_installed_versions(package_name)
    
    def on_version_policy_changed(self, index):
        tips = [
            "💡 智能对比：自动检测已安装版本，只有新版本才会安装",
            "💡 跳过已安装：只要已安装就跳过，不检查版本",
            "💡 强制覆盖：无论是否安装都覆盖安装"
        ]
        self.version_policy_tip.setText(tips[index])
        
        # 自动更新所有设备的策略
        for row in range(self.install_device_table.rowCount()):
            policy_combo = self.install_device_table.cellWidget(row, 4)
            if policy_combo:
                policy_combo.setCurrentIndex(index)
    
    def browse_apk(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择 APK 文件", "", "APK Files (*.apk)")
        if file_path:
            self.apk_path_edit.setText(file_path)
            self.log(f"已选择 APK: {file_path}")
            
            # 获取版本信息
            try:
                version_code, version_name = self.adb.get_apk_version(file_path)
                self.log(f"APK 解析结果：code={version_code}, name={version_name}")
                if version_code or version_name:
                    version_str = f"APK 版本：v{version_name or ''} (code: {version_code or 'N/A'})"
                    self.version_info_label.setText(version_str)
                    self.version_info_label.setStyleSheet("color: #006600; font-weight: bold;")
                    
                    # 更新表格中的 APK 版本列
                    apk_version = f"v{version_name or version_code}"
                    for row in range(self.install_device_table.rowCount()):
                        item = QTableWidgetItem(apk_version)
                        item.setForeground(QColor("#006600"))
                        self.install_device_table.setItem(row, 3, item)
                else:
                    self.version_info_label.setText("APK 版本信息：无法读取")
                    self.log("⚠ APK 版本解析失败")
            except Exception as e:
                self.version_info_label.setText(f"APK 版本信息：解析错误")
                self.log(f"✗ APK 版本解析错误：{e}")
    
    def check_installed_versions(self, package_name=None):
        """异步检查所有设备的已安装版本"""
        # 如果没有传入包名，从安装标签页获取
        if package_name is None:
            package_name = self.package_name_edit.text().strip()
        
        if not package_name:
            self.log("⚠ 未输入包名，跳过版本检测")
            return
        
        if not self.devices:
            self.log("ℹ 没有设备，跳过版本检测")
            return
        
        self.log(f"🔄 开始检测 {len(self.devices)} 台设备的已安装版本 (包名：{package_name})...")
        
        # 取消之前的检查线程
        if hasattr(self, 'check_version_thread') and self.check_version_thread.isRunning():
            self.check_version_thread.stop()
            self.check_version_thread.wait()
        
        # 启动新线程
        self.check_version_thread = CheckVersionThread(self.devices, package_name, self.adb)
        self.check_version_thread.version_checked.connect(self.update_installed_version)
        self.check_version_thread.finished.connect(self.on_check_versions_finished)
        self.check_version_thread.start()
    
    def update_installed_version(self, device_id, version):
        """更新已安装版本显示，并自动调整策略"""
        self.log(f"📝 更新设备 {device_id} 的版本：{version}")
        
        found = False
        for row in range(self.install_device_table.rowCount()):
            if row < len(self.devices):
                current_id = self.devices[row]["id"]
                self.log(f"  检查行 {row}: {current_id} == {device_id}? {current_id == device_id}")
                
                if current_id == device_id:
                    found = True
                    # 更新版本显示
                    item = QTableWidgetItem(version)
                    if version == "未安装":
                        item.setForeground(QColor("#999"))
                    else:
                        item.setForeground(QColor("#0066cc"))
                    self.install_device_table.setItem(row, 2, item)
                    self.log(f"  ✓ 已更新行 {row} 的版本列为：{version}")
                    
                    # 自动调整策略
                    policy_combo = self.install_device_table.cellWidget(row, 4)
                    if policy_combo:
                        # 获取 APK 版本信息
                        apk_path = self.apk_path_edit.text().strip()
                        apk_code = None
                        apk_name = None
                        if apk_path and os.path.exists(apk_path):
                            apk_code, apk_name = self.adb.get_apk_version(apk_path)
                        
                        # 获取已安装版本的 versionCode
                        installed_code = None
                        if version != "未安装":
                            # 重新查询 versionCode
                            package_name = self.package_name_edit.text().strip()
                            if package_name:
                                success, stdout, _ = self.adb._run_adb(
                                    device_id, "shell", "dumpsys", "package", package_name, timeout=30
                                )
                                if success and stdout:
                                    match = re.search(r'versionCode=(\d+)', stdout)
                                    if match:
                                        installed_code = int(match.group(1))
                        
                        # 自动选择策略
                        if version == "未安装":
                            policy_combo.setCurrentIndex(0)
                            self.log(f"  ✓ 策略设置为：智能对比 (未安装)")
                        elif apk_code and installed_code:
                            if apk_code > installed_code:
                                policy_combo.setCurrentIndex(0)
                                self.log(f"  ✓ 策略设置为：智能对比 (APK 版本更高)")
                            elif apk_code == installed_code:
                                policy_combo.setCurrentIndex(1)
                                self.log(f"  ✓ 策略设置为：跳过已安装 (版本相同)")
                            else:
                                policy_combo.setCurrentIndex(1)
                                self.log(f"  ✓ 策略设置为：跳过已安装 (APK 版本更低)")
                        else:
                            policy_combo.setCurrentIndex(0)
                            self.log(f"  ✓ 策略设置为：智能对比 (默认)")
                    
                    break
        
        if not found:
            self.log(f"  ⚠ 未找到设备 {device_id} 在表格中")
    
    def on_check_versions_finished(self):
        """版本检查完成"""
        self.log("✓ 已安装版本检测完成")
        self.log(f"  表格行数：{self.install_device_table.rowCount()}")
        self.log(f"  设备数量：{len(self.devices)}")
    
    def start_install(self):
        apk_path = self.apk_path_edit.text().strip()
        package_name = self.package_name_edit.text().strip()
        
        if not apk_path:
            QMessageBox.warning(self, "错误", "请选择 APK 文件")
            return
        if not package_name:
            QMessageBox.warning(self, "错误", "请输入应用包名")
            return
        if not os.path.exists(apk_path):
            QMessageBox.warning(self, "错误", "APK 文件不存在")
            return
        
        selected_devices = []
        for row in range(self.install_device_table.rowCount()):
            checkbox = self.install_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                selected_devices.append(self.devices[row])
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "请至少选择一台设备")
            return
        
        # 重置统计
        self.install_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.failed_devices = []
        self.install_result_label.setText("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        
        max_threads = self.install_threads.value()
        policy_map = {0: "compare", 1: "skip", 2: "force"}
        version_policy = policy_map[self.version_policy.currentIndex()]
        
        self.install_btn.setEnabled(False)
        self.stop_install_btn.setEnabled(True)
        self.install_progress_label.setText("正在安装...")
        self.log(f"📦 开始安装到 {len(selected_devices)} 台设备")
        self.log(f"   APK: {os.path.basename(apk_path)}")
        self.log(f"   包名：{package_name}")
        self.log(f"   策略：{self.version_policy.currentText()}")
        
        self.install_thread = InstallThread(
            selected_devices, apk_path, package_name, max_threads, version_policy
        )
        self.install_thread.install_progress.connect(self.on_install_progress)
        self.install_thread.task_finished.connect(self.on_install_task_finished)
        self.install_thread.all_finished.connect(self.on_install_all_finished)
        self.install_thread.start()
    
    def stop_install(self):
        if self.install_thread:
            self.install_thread.stop()
            self.log("安装已停止")
    
    def on_install_progress(self, device_id, status, message, device_info):
        icons = {
            "installing": "🔄", "success": "✅", "error": "❌", 
            "skipped": "⏭️", "uninstalling": "🗑️", "comparing": "📊"
        }
        icon = icons.get(status, "")
        self.install_progress_label.setText(f"{icon} {device_id}: {message}")
        self.log(f"[{status.upper()}] {device_id}: {message}")
    
    def on_install_task_finished(self, device_id, success, message, device_info):
        if success:
            if "跳过" in message or "skipped" in message.lower():
                self.install_stats["skipped"] += 1
            else:
                self.install_stats["success"] += 1
        else:
            self.install_stats["failure"] += 1
            # 记录失败设备
            for device in self.devices:
                if device["id"] == device_id:
                    self.failed_devices.append({
                        **device,
                        "error": message,
                        "retry_count": 0
                    })
                    break
        
        self.install_result_label.setText(
            f"✅ 成功：{self.install_stats['success']} | "
            f"❌ 失败：{self.install_stats['failure']} | "
            f"⏭️ 跳过：{self.install_stats['skipped']}")
        
        # 更新设备表格中的版本信息
        if success and device_info:
            for row in range(self.install_device_table.rowCount()):
                if self.devices[row]["id"] == device_id:
                    if device_info.get("apk_version_code"):
                        version_item = QTableWidgetItem(f"v{device_info['apk_version_code']}")
                        version_item.setForeground(QColor("#006600"))
                        self.install_device_table.setItem(row, 2, version_item)
                    break
    
    def on_install_all_finished(self):
        self.install_btn.setEnabled(True)
        self.stop_install_btn.setEnabled(False)
        
        if self.install_stats["failure"] > 0:
            self.install_progress_label.setText(f"安装完成 - {self.install_stats['failure']} 台设备失败，请查看「失败重试」标签")
            self.log(f"⚠️ 安装完成 - {self.install_stats['failure']} 台设备失败")
            self.update_retry_table()
        else:
            self.install_progress_label.setText("✓ 安装完成 - 全部成功!")
            self.log(f"✓ 安装完成 - 全部成功!")
        
        total = sum(self.install_stats.values())
        self.log(f"统计 - 成功：{self.install_stats['success']}/{total} | 跳过：{self.install_stats['skipped']}")
    
    # ========== 重试功能 ==========
    
    def update_retry_table(self):
        """更新重试设备表格"""
        self.retry_device_table.setRowCount(len(self.failed_devices))
        for row, device in enumerate(self.failed_devices):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked)
            self.retry_device_table.setItem(row, 0, checkbox)
            self.retry_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
            
            error_item = QTableWidgetItem(device.get("error", "未知错误")[:50])
            error_item.setForeground(QColor("#cc0000"))
            self.retry_device_table.setItem(row, 2, error_item)
            
            retry_count_item = QTableWidgetItem(str(device.get("retry_count", 0)))
            self.retry_device_table.setItem(row, 3, retry_count_item)
    
    def create_retry_tab(self):
        """创建失败重试标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        tip_group = QGroupBox("使用说明")
        tip_layout = QVBoxLayout(tip_group)
        tip1 = QLabel("⚠️ 此页面显示上次安装失败的设备")
        tip1.setStyleSheet("color: #cc0000; font-weight: bold;")
        tip_layout.addWidget(tip1)
        tip2 = QLabel("• 可以选择部分或全部失败设备重新尝试安装")
        tip2.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip2)
        tip3 = QLabel("• 重试前会自动卸载旧版本，然后重新安装")
        tip3.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip3)
        layout.addWidget(tip_group)
        
        device_group = QGroupBox("失败设备列表")
        device_layout = QVBoxLayout(device_group)
        
        self.retry_device_table = QTableWidget()
        self.retry_device_table.setColumnCount(4)
        self.retry_device_table.setHorizontalHeaderLabels(["选择", "设备", "失败原因", "重试次数"])
        self.retry_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        device_layout.addWidget(self.retry_device_table)
        
        layout.addWidget(device_group)
        
        btn_layout = QHBoxLayout()
        self.retry_btn = QPushButton("🔄 重试选中设备")
        self.retry_btn.clicked.connect(self.start_retry)
        self.retry_btn.setFixedWidth(180)
        self.retry_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #ff9800; color: white; padding: 8px; }")
        btn_layout.addWidget(self.retry_btn)
        
        self.stop_retry_btn = QPushButton("⏹️ 停止")
        self.stop_retry_btn.clicked.connect(self.stop_retry)
        self.stop_retry_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_retry_btn)
        
        btn_layout.addStretch()
        
        self.retry_progress_label = QLabel("准备就绪")
        btn_layout.addWidget(self.retry_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.retry_progress_bar = QProgressBar()
        layout.addWidget(self.retry_progress_bar)
        
        self.retry_result_label = QLabel("✅ 成功：0 | ❌ 失败：0")
        self.retry_result_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self.retry_result_label)
        
        return widget
    
    def start_retry(self):
        apk_path = self.apk_path_edit.text().strip()
        package_name = self.package_name_edit.text().strip()
        
        if not apk_path:
            QMessageBox.warning(self, "错误", "请先在「应用安装」标签选择 APK 文件")
            return
        if not package_name:
            QMessageBox.warning(self, "错误", "请输入应用包名")
            return
        
        selected_devices = []
        for row in range(self.retry_device_table.rowCount()):
            checkbox = self.retry_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                selected_devices.append(self.failed_devices[row])
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "请至少选择一台设备")
            return
        
        self.retry_stats = {"success": 0, "failure": 0}
        self.retry_result_label.setText("✅ 成功：0 | ❌ 失败：0")
        
        self.retry_btn.setEnabled(False)
        self.stop_retry_btn.setEnabled(True)
        self.retry_progress_label.setText("正在重试...")
        self.log(f"🔄 开始重试 {len(selected_devices)} 台设备")
        
        self.retry_thread = RetryInstallThread(selected_devices, apk_path, package_name, max_threads=5)
        self.retry_thread.retry_progress.connect(self.on_retry_progress)
        self.retry_thread.retry_finished.connect(self.on_retry_finished)
        self.retry_thread.all_finished.connect(self.on_retry_all_finished)
        self.retry_thread.start()
    
    def stop_retry(self):
        if self.retry_thread:
            self.retry_thread.stop()
            self.log("重试已停止")
    
    def on_retry_progress(self, device_id, status, message):
        icons = {"retrying": "🔄", "success": "✅", "error": "❌", "uninstalling": "🗑️"}
        icon = icons.get(status, "")
        self.retry_progress_label.setText(f"{icon} {device_id}: {message}")
        self.log(f"[{status.upper()}] {device_id}: {message}")
    
    def on_retry_finished(self, device_id, success, message):
        if success:
            self.retry_stats["success"] += 1
            # 从失败列表移除
            self.failed_devices = [d for d in self.failed_devices if d["id"] != device_id]
        else:
            self.retry_stats["failure"] += 1
            # 增加重试次数
            for device in self.failed_devices:
                if device["id"] == device_id:
                    device["retry_count"] = device.get("retry_count", 0) + 1
                    break
        
        self.retry_result_label.setText(f"✅ 成功：{self.retry_stats['success']} | ❌ 失败：{self.retry_stats['failure']}")
        self.update_retry_table()
    
    def on_retry_all_finished(self):
        self.retry_btn.setEnabled(True)
        self.stop_retry_btn.setEnabled(False)
        
        if self.retry_stats["failure"] == 0:
            self.retry_progress_label.setText("✓ 重试完成 - 全部成功!")
            self.log("✓ 重试完成 - 全部成功!")
        else:
            self.retry_progress_label.setText(f"重试完成 - {self.retry_stats['failure']} 台设备仍然失败")
            self.log(f"⚠️ 重试完成 - {self.retry_stats['failure']} 台设备仍然失败")
        
        # 刷新版本状态 - 直接使用安装包名
        package_name = self.package_name_edit.text().strip()
        if package_name:
            self.log(f"🔄 刷新设备版本状态...")
            self.check_installed_versions(package_name)
        else:
            self.log("⚠ 包名为空，跳过版本刷新")
    
    # ========== 卸载功能 ==========
    
    def start_uninstall(self):
        package_name = self.uninstall_package_edit.text().strip()
        
        if not package_name:
            QMessageBox.warning(self, "错误", "请输入应用包名")
            return
        
        selected_devices = []
        for row in range(self.uninstall_device_table.rowCount()):
            checkbox = self.uninstall_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                selected_devices.append(self.devices[row])
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "请至少选择一台设备")
            return
        
        self.uninstall_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.uninstall_result_label.setText("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        max_threads = self.uninstall_threads.value()
        
        self.uninstall_btn.setEnabled(False)
        self.stop_uninstall_btn.setEnabled(True)
        self.uninstall_progress_label.setText("正在卸载...")
        self.log(f"🗑️ 开始卸载 {package_name} 从 {len(selected_devices)} 台设备")
        
        # 使用 InstallThread 的卸载逻辑 (简化版)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        def uninstall_device(device):
            device_id = device["id"]
            is_installed = self.adb.is_installed(device_id, package_name)
            if not is_installed:
                return device_id, True, "未安装，跳过", "skipped"
            
            success, msg = self.adb.uninstall(device_id, package_name)
            status = "success" if success else "error"
            return device_id, success, msg, status
        
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = {executor.submit(uninstall_device, d): d for d in selected_devices}
            for future in as_completed(futures):
                device_id, success, message, status = future.result()
                
                if status == "skipped":
                    self.uninstall_stats["skipped"] += 1
                elif success:
                    self.uninstall_stats["success"] += 1
                else:
                    self.uninstall_stats["failure"] += 1
                
                self.uninstall_result_label.setText(
                    f"✅ 成功：{self.uninstall_stats['success']} | "
                    f"❌ 失败：{self.uninstall_stats['failure']} | "
                    f"⏭️ 跳过：{self.uninstall_stats['skipped']}")
                self.log(f"[{status.upper()}] {device_id}: {message}")
        
        self.uninstall_btn.setEnabled(True)
        self.stop_uninstall_btn.setEnabled(False)
        self.uninstall_progress_label.setText("卸载完成")
        total = sum(self.uninstall_stats.values())
        self.log(f"✓ 卸载完成 - 成功：{self.uninstall_stats['success']}/{total}")
    
    def stop_uninstall(self):
        self.log("卸载已停止")
        self.uninstall_btn.setEnabled(True)
        self.stop_uninstall_btn.setEnabled(False)
    
    def export_log(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "导出日志", "adb_manager_log.txt", "Text Files (*.txt)")
        if file_path:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.log_text.toPlainText())
            self.log(f"✓ 日志已导出：{file_path}")




class RetryInstallThread(QThread):
    """失败重试安装线程"""
    retry_progress = pyqtSignal(str, str, str)
    retry_finished = pyqtSignal(str, bool, str)
    all_finished = pyqtSignal()
    
    def __init__(self, failed_devices, apk_path, package_name, max_threads=5):
        super().__init__()
        self.failed_devices = failed_devices
        self.apk_path = apk_path
        self.package_name = package_name
        self.max_threads = max_threads
        self.adb = ADBWorker()
        self.stop_flag = False
    
    def run(self):
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = {
                executor.submit(self.retry_device, device): device
                for device in self.failed_devices
            }
            
            for future in as_completed(futures):
                if self.stop_flag:
                    break
                device = futures[future]
                try:
                    device_id, success, message = future.result()
                    self.retry_finished.emit(device_id, success, message)
                except Exception as e:
                    self.retry_finished.emit(device["id"], False, str(e))
        
        self.all_finished.emit()
    
    def retry_device(self, device):
        device_id = device["id"]
        self.retry_progress.emit(device_id, "retrying", "正在重试安装...")
        
        # 先尝试卸载
        self.retry_progress.emit(device_id, "uninstalling", "正在清理旧版本...")
        self.adb.uninstall(device_id, self.package_name, timeout=30)
        
        # 再安装
        success, msg = self.adb.install(device_id, self.apk_path, replace=True, timeout=300)
        
        if success:
            self.retry_progress.emit(device_id, "success", "重试成功 ✓")
        else:
            self.retry_progress.emit(device_id, "error", f"重试失败：{msg}")
        
        return device_id, success, msg
    
    def stop(self):
        self.stop_flag = True


class CheckVersionThread(QThread):
    """检查已安装版本的线程"""
    version_checked = pyqtSignal(str, str)  # device_id, version
    finished = pyqtSignal()
    
    def __init__(self, devices, package_name, adb):
        super().__init__()
        self.devices = devices
        self.package_name = package_name
        self.adb = adb
        self.stop_flag = False
    
    def run(self):
        import sys
        for i, device in enumerate(self.devices):
            if self.stop_flag:
                break
            device_id = device["id"]
            version = self.adb.get_installed_version(device_id, self.package_name)
            version_str = f"v{version}" if version else "未安装"
            # 使用 print 输出调试信息（会显示在控制台）
            print(f"[DEBUG] 检查设备 {i+1}/{len(self.devices)}: {device_id} = {version_str}", file=sys.stderr)
            self.version_checked.emit(device_id, version_str)
        print(f"[DEBUG] CheckVersionThread 完成", file=sys.stderr)
        self.finished.emit()
    
    def stop(self):
        self.stop_flag = True


class ADBBatchManager(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.adb = ADBWorker()
        self.devices = []
        self.failed_devices = []  # 安装失败的设备
        self.scan_thread = None
        self.install_thread = None
        self.retry_thread = None
        self.install_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.retry_stats = {"success": 0, "failure": 0}
        self.init_ui()
        self.log("=" * 50)
        self.log("adb 批量设备安装工具 已启动")
        self.log("增强功能：版本检测 | 失败重试 | 自定义端口")
        self.log("=" * 50)
        self.check_adb()
        
        # 加载上次扫描的设备
        self.load_devices()
    
    def init_ui(self):
        self.setWindowTitle("adb 批量设备安装工具")
        self.setMinimumSize(1400, 900)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        tabs = QTabWidget()
        tabs.addTab(self.create_scan_tab(), "📱 设备发现")
        tabs.addTab(self.create_install_tab(), "📦 应用安装")
        tabs.addTab(self.create_retry_tab(), "⚠️ 失败重试")
        tabs.addTab(self.create_uninstall_tab(), "🗑️ 应用卸载")
        tabs.addTab(self.create_log_tab(), "📋 日志")
        
        main_layout.addWidget(tabs)
        self.statusBar().showMessage("就绪")
    
    def create_scan_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        scan_group = QGroupBox("扫描设置")
        scan_layout = QHBoxLayout(scan_group)
        
        # IP 范围 - 完整 IP 地址
        ip_layout = QVBoxLayout()
        ip_layout.addWidget(QLabel("起始 IP (完整地址):"))
        self.ip_start_edit = QLineEdit()
        self.ip_start_edit.setPlaceholderText("例如：192.168.1.100")
        self.ip_start_edit.setText("192.168.1.100")
        ip_layout.addWidget(self.ip_start_edit)
        
        ip_layout.addWidget(QLabel("结束 IP (完整地址):"))
        self.ip_end_edit = QLineEdit()
        self.ip_end_edit.setPlaceholderText("例如：192.168.1.200")
        self.ip_end_edit.setText("192.168.1.200")
        ip_layout.addWidget(self.ip_end_edit)
        
        # 端口设置 - 单个端口
        port_layout = QVBoxLayout()
        port_layout.addWidget(QLabel("ADB 端口:"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(5555)
        port_layout.addWidget(self.port_input)
        port_layout.addWidget(QLabel("默认 5555\n可自定义"))
        
        # 并发数
        thread_layout = QVBoxLayout()
        thread_layout.addWidget(QLabel("最大并发数:"))
        self.scan_threads = QSpinBox()
        self.scan_threads.setRange(1, 200)
        self.scan_threads.setValue(20)  # 降低默认值，避免网络拥塞
        thread_layout.addWidget(self.scan_threads)
        
        scan_layout.addLayout(ip_layout)
        scan_layout.addLayout(port_layout)
        scan_layout.addLayout(thread_layout)
        scan_layout.addStretch()
        
        self.scan_btn = QPushButton("🔍 开始扫描")
        self.scan_btn.clicked.connect(self.start_scan)
        self.scan_btn.setFixedWidth(150)
        self.scan_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; }")
        scan_layout.addWidget(self.scan_btn)
        
        self.stop_scan_btn = QPushButton("⏹️ 停止")
        self.stop_scan_btn.clicked.connect(self.stop_scan)
        self.stop_scan_btn.setEnabled(False)
        self.stop_scan_btn.setFixedWidth(100)
        scan_layout.addWidget(self.stop_scan_btn)
        
        layout.addWidget(scan_group)
        
        self.scan_progress = QProgressBar()
        self.scan_progress.setVisible(False)
        layout.addWidget(self.scan_progress)
        
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(6)
        self.device_table.setHorizontalHeaderLabels(["选择", "IP:端口", "状态", "型号", "Android 版本", "操作"])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.device_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.device_table)
        
        btn_layout = QHBoxLayout()
        self.device_count_label = QLabel("已发现 0 台设备")
        self.device_count_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        btn_layout.addWidget(self.device_count_label)
        btn_layout.addStretch()
        
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.select_all_devices)
        btn_layout.addWidget(self.select_all_btn)
        
        self.disconnect_btn = QPushButton("断开选中")
        self.disconnect_btn.clicked.connect(self.disconnect_selected)
        btn_layout.addWidget(self.disconnect_btn)
        
        self.clear_devices_btn = QPushButton("清除保存")
        self.clear_devices_btn.clicked.connect(self.clear_saved_devices)
        self.clear_devices_btn.setStyleSheet("QPushButton { color: #cc0000; }")
        btn_layout.addWidget(self.clear_devices_btn)
        
        layout.addLayout(btn_layout)
        return widget
    
    def create_install_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # APK 选择
        apk_group = QGroupBox("APK 文件")
        apk_layout = QHBoxLayout(apk_group)
        self.apk_path_edit = QLineEdit()
        self.apk_path_edit.setPlaceholderText("选择要安装的 APK 文件...")
        apk_layout.addWidget(self.apk_path_edit)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_apk)
        apk_layout.addWidget(browse_btn)
        layout.addWidget(apk_group)
        
        # 包名和版本信息
        pkg_group = QGroupBox("应用信息")
        pkg_layout = QVBoxLayout(pkg_group)
        
        pkg_row = QHBoxLayout()
        pkg_row.addWidget(QLabel("包名:"))
        self.package_name_edit = QLineEdit()
        self.package_name_edit.setPlaceholderText("例如：com.example.app")
        pkg_row.addWidget(self.package_name_edit)
        pkg_layout.addLayout(pkg_row)
        
        # 包名改变时自动检查已安装版本
        self.package_name_edit.textChanged.connect(self.on_package_name_changed)
        
        self.version_info_label = QLabel("APK 版本信息：未选择文件")
        self.version_info_label.setStyleSheet("color: #666; font-style: italic;")
        pkg_layout.addWidget(self.version_info_label)
        layout.addWidget(pkg_group)
        
        # 安装设置
        install_group = QGroupBox("安装设置")
        install_layout = QVBoxLayout(install_group)
        
        # 第一行：并发数和全局策略
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("最大并发数:"))
        self.install_threads = QSpinBox()
        self.install_threads.setRange(1, 50)
        self.install_threads.setValue(10)
        row1.addWidget(self.install_threads)
        
        row1.addSpacing(30)
        row1.addWidget(QLabel("全局策略:"))
        self.version_policy = QComboBox()
        self.version_policy.addItems([
            "智能对比 (版本一致或更高则跳过)",
            "跳过已安装 (不检查版本)",
            "强制覆盖 (始终安装)"
        ])
        self.version_policy.setCurrentIndex(0)
        row1.addWidget(self.version_policy)
        row1.addStretch()
        install_layout.addLayout(row1)
        
        # 版本策略说明
        self.version_policy_tip = QLabel("💡 智能对比：自动检测已安装版本，只有新版本才会安装")
        self.version_policy_tip.setStyleSheet("color: #0066cc; font-size: 11px;")
        install_layout.addWidget(self.version_policy_tip)
        self.version_policy.currentIndexChanged.connect(self.on_version_policy_changed)
        
        layout.addWidget(install_group)
        
        # 设备选择和版本对比
        device_group = QGroupBox("设备列表与版本对比")
        device_layout = QVBoxLayout(device_group)
        
        # 刷新按钮行
        refresh_row = QHBoxLayout()
        refresh_row.addStretch()
        self.refresh_version_btn = QPushButton("🔄 刷新版本")
        self.refresh_version_btn.clicked.connect(self.on_refresh_version_clicked)
        self.refresh_version_btn.setFixedWidth(120)
        self.refresh_version_btn.setStyleSheet("QPushButton { font-size: 12px; background-color: #2196F3; color: white; padding: 5px; }")
        refresh_row.addWidget(self.refresh_version_btn)
        device_layout.addLayout(refresh_row)
        
        self.install_device_table = QTableWidget()
        self.install_device_table.setColumnCount(5)
        self.install_device_table.setHorizontalHeaderLabels([
            "选择", "设备", "已安装版本", "APK 版本", "策略"
        ])
        self.install_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # 策略列使用下拉框
        self.install_device_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        device_layout.addWidget(self.install_device_table)
        
        # 策略说明
        strategy_tip = QLabel("💡 可在表格中为每台设备单独设置策略，也可点击'刷新版本'按钮手动刷新")
        strategy_tip.setStyleSheet("color: #999; font-size: 10px;")
        device_layout.addWidget(strategy_tip)
        
        layout.addWidget(device_group)
        
        # 安装按钮和进度
        btn_layout = QHBoxLayout()
        self.install_btn = QPushButton("📦 开始安装")
        self.install_btn.clicked.connect(self.start_install)
        self.install_btn.setFixedWidth(150)
        self.install_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #4CAF50; color: white; padding: 8px; }")
        btn_layout.addWidget(self.install_btn)
        
        self.stop_install_btn = QPushButton("⏹️ 停止")
        self.stop_install_btn.clicked.connect(self.stop_install)
        self.stop_install_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_install_btn)
        btn_layout.addStretch()
        
        self.install_progress_label = QLabel("准备就绪")
        self.install_progress_label.setStyleSheet("font-size: 12px;")
        btn_layout.addWidget(self.install_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.install_progress_bar = QProgressBar()
        layout.addWidget(self.install_progress_bar)
        
        self.install_result_label = QLabel("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        self.install_result_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self.install_result_label)
        
        self.retry_tip_label = QLabel("💡 安装失败的设备会自动出现在「失败重试」标签页，可以单独重试")
        self.retry_tip_label.setStyleSheet("color: #ff6600; font-size: 11px;")
        layout.addWidget(self.retry_tip_label)
        
        return widget
    
    def create_retry_tab(self):
        """创建失败重试标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 说明
        tip_group = QGroupBox("使用说明")
        tip_layout = QVBoxLayout(tip_group)
        tip1 = QLabel("⚠️ 此页面显示上次安装失败的设备")
        tip1.setStyleSheet("color: #cc0000; font-weight: bold;")
        tip_layout.addWidget(tip1)
        tip2 = QLabel("• 可以选择部分或全部失败设备重新尝试安装")
        tip2.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip2)
        tip3 = QLabel("• 重试前会自动卸载旧版本，然后重新安装")
        tip3.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip3)
        layout.addWidget(tip_group)
        
        # 失败设备列表
        device_group = QGroupBox("失败设备列表")
        device_layout = QVBoxLayout(device_group)
        
        self.retry_device_table = QTableWidget()
        self.retry_device_table.setColumnCount(4)
        self.retry_device_table.setHorizontalHeaderLabels(["选择", "设备", "失败原因", "重试次数"])
        self.retry_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        device_layout.addWidget(self.retry_device_table)
        
        layout.addWidget(device_group)
        
        # 重试按钮
        btn_layout = QHBoxLayout()
        self.retry_btn = QPushButton("🔄 重试选中设备")
        self.retry_btn.clicked.connect(self.start_retry)
        self.retry_btn.setFixedWidth(180)
        self.retry_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #ff9800; color: white; padding: 8px; }")
        btn_layout.addWidget(self.retry_btn)
        
        self.stop_retry_btn = QPushButton("⏹️ 停止")
        self.stop_retry_btn.clicked.connect(self.stop_retry)
        self.stop_retry_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_retry_btn)
        
        btn_layout.addStretch()
        
        self.retry_progress_label = QLabel("准备就绪")
        btn_layout.addWidget(self.retry_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.retry_progress_bar = QProgressBar()
        layout.addWidget(self.retry_progress_bar)
        
        self.retry_result_label = QLabel("✅ 成功：0 | ❌ 失败：0")
        self.retry_result_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self.retry_result_label)
        
        return widget
    
    def create_uninstall_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 包名输入
        pkg_group = QGroupBox("要卸载的应用")
        pkg_layout = QVBoxLayout(pkg_group)
        
        pkg_row1 = QHBoxLayout()
        pkg_row1.addWidget(QLabel("应用包名:"))
        self.uninstall_package_edit = QLineEdit()
        self.uninstall_package_edit.setPlaceholderText("例如：com.example.app")
        pkg_row1.addWidget(self.uninstall_package_edit)
        pkg_layout.addLayout(pkg_row1)
        
        pkg_tip = QLabel("💡 提示：请输入完整的应用包名")
        pkg_tip.setStyleSheet("color: #666; font-size: 11px;")
        pkg_layout.addWidget(pkg_tip)
        
        layout.addWidget(pkg_group)
        
        # 卸载设置
        uninstall_group = QGroupBox("卸载设置")
        uninstall_layout = QHBoxLayout(uninstall_group)
        uninstall_layout.addWidget(QLabel("最大并发数:"))
        self.uninstall_threads = QSpinBox()
        self.uninstall_threads.setRange(1, 50)
        self.uninstall_threads.setValue(10)
        uninstall_layout.addWidget(self.uninstall_threads)
        uninstall_layout.addStretch()
        layout.addWidget(uninstall_group)
        
        # 设备选择
        device_group = QGroupBox("选择设备")
        device_layout = QVBoxLayout(device_group)
        self.uninstall_device_table = QTableWidget()
        self.uninstall_device_table.setColumnCount(2)
        self.uninstall_device_table.setHorizontalHeaderLabels(["选择", "设备"])
        self.uninstall_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        device_layout.addWidget(self.uninstall_device_table)
        layout.addWidget(device_group)
        
        # 卸载按钮和进度
        btn_layout = QHBoxLayout()
        self.uninstall_btn = QPushButton("🗑️ 开始卸载")
        self.uninstall_btn.clicked.connect(self.start_uninstall)
        self.uninstall_btn.setFixedWidth(150)
        self.uninstall_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #f44336; color: white; padding: 8px; }")
        btn_layout.addWidget(self.uninstall_btn)
        
        self.stop_uninstall_btn = QPushButton("⏹️ 停止")
        self.stop_uninstall_btn.clicked.connect(self.stop_uninstall)
        self.stop_uninstall_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_uninstall_btn)
        btn_layout.addStretch()
        
        self.uninstall_progress_label = QLabel("准备就绪")
        self.uninstall_progress_label.setStyleSheet("font-size: 12px;")
        btn_layout.addWidget(self.uninstall_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.uninstall_progress_bar = QProgressBar()
        layout.addWidget(self.uninstall_progress_bar)
        
        self.uninstall_result_label = QLabel("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        self.uninstall_result_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #0066cc;")
        layout.addWidget(self.uninstall_result_label)
        
        return widget
    
    def create_log_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self.log_text)
        
        btn_layout = QHBoxLayout()
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self.log_text.clear)
        btn_layout.addWidget(clear_btn)
        
        export_btn = QPushButton("导出日志")
        export_btn.clicked.connect(self.export_log)
        btn_layout.addWidget(export_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        return widget
    
    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        self.log_text.append(log_line)
        self.log_text.moveCursor(QTextCursor.End)
    
    def check_adb(self):
        try:
            result = subprocess.run([self.adb.adb_path, "version"], capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode == 0:
                version_line = result.stdout.splitlines()[0]
                self.log(f"✓ ADB 已就绪：{version_line}")
            else:
                self.log("✗ ADB 未找到")
                QMessageBox.warning(self, "警告", "ADB 未找到，请安装 Android SDK Platform-Tools 并添加到 PATH")
        except FileNotFoundError:
            self.log("✗ ADB 未找到")
            QMessageBox.warning(self, "警告", "ADB 未找到，请安装 Android SDK Platform-Tools 并添加到 PATH")
    
    # ========== 扫描功能 ==========
    
    def _parse_ip(self, ip_str):
        """解析 IP 地址，返回四段整数列表"""
        try:
            parts = ip_str.strip().split('.')
            if len(parts) != 4:
                return None
            return [int(p) for p in parts]
        except:
            return None
    
    def _ip_to_str(self, ip_parts):
        """将 IP 地址列表转换为字符串"""
        return '.'.join(str(p) for p in ip_parts)
    
    def _generate_ip_list(self, start_ip_str, end_ip_str):
        """生成 IP 地址列表"""
        start_parts = self._parse_ip(start_ip_str)
        end_parts = self._parse_ip(end_ip_str)
        
        if not start_parts or not end_parts:
            return []
        
        # 检查是否在同一网段（前两段相同）
        if start_parts[:2] != end_parts[:2]:
            return []
        
        ip_list = []
        # 遍历第三段和第四段
        for third in range(start_parts[2], end_parts[2] + 1):
            start_fourth = start_parts[3] if third == start_parts[2] else 0
            end_fourth = end_parts[3] if third == end_parts[2] else 255
            
            for fourth in range(start_fourth, end_fourth + 1):
                ip = f"{start_parts[0]}.{start_parts[1]}.{third}.{fourth}"
                ip_list.append(ip)
        
        return ip_list
    
    def start_scan(self):
        ip_start_str = self.ip_start_edit.text().strip()
        ip_end_str = self.ip_end_edit.text().strip()
        port = self.port_input.value()
        max_threads = self.scan_threads.value()
        
        # 生成 IP 列表
        ip_list = self._generate_ip_list(ip_start_str, ip_end_str)
        
        if not ip_list:
            QMessageBox.warning(self, "错误", 
                "IP 地址格式不正确或不在同一网段\n\n"
                "示例：\n"
                "起始 IP: 192.168.1.100\n"
                "结束 IP: 192.168.1.200\n\n"
                "或跨网段：\n"
                "起始 IP: 192.168.1.1\n"
                "结束 IP: 192.168.2.255")
            return
        
        self.devices = []
        self.failed_devices = []
        self.device_table.setRowCount(0)
        self.scan_btn.setEnabled(False)
        self.stop_scan_btn.setEnabled(True)
        self.scan_progress.setVisible(True)
        self.scan_progress.setValue(0)
        
        self.log(f"开始扫描 {ip_start_str} - {ip_end_str} 端口 {port} (共 {len(ip_list)} 个 IP)")
        
        self.scan_thread = ScanThread(ip_list, port, max_threads)
        self.scan_thread.device_found.connect(self.on_device_found)
        self.scan_thread.scan_progress.connect(self.on_scan_progress)
        self.scan_thread.scan_finished.connect(self.on_scan_finished)
        self.scan_thread.log_message.connect(self.log)
        self.scan_thread.start()
    
    def stop_scan(self):
        if self.scan_thread:
            self.scan_thread.stop()
            self.log("扫描已停止")
    
    def on_device_found(self, device):
        self.devices.append(device)
        row = self.device_table.rowCount()
        self.device_table.insertRow(row)
        
        checkbox = QTableWidgetItem("✓")
        checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        checkbox.setCheckState(Qt.Checked)
        self.device_table.setItem(row, 0, checkbox)
        self.device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']}"))
        self.device_table.setItem(row, 2, QTableWidgetItem(device['state']))
        self.device_table.setItem(row, 3, QTableWidgetItem(device['model']))
        self.device_table.setItem(row, 4, QTableWidgetItem(device['version']))
        
        disconnect_btn = QPushButton("断开")
        disconnect_btn.clicked.connect(lambda checked, d=device: self.disconnect_device(d))
        self.device_table.setCellWidget(row, 5, disconnect_btn)
        
        self.device_count_label.setText(f"已发现 {len(self.devices)} 台设备")
    
    def on_scan_progress(self, current, total):
        self.scan_progress.setMaximum(total)
        self.scan_progress.setValue(current)
        self.statusBar().showMessage(f"扫描进度：{current}/{total}")
    
    def on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.scan_progress.setVisible(False)
        self.log(f"✓ 扫描完成，发现 {len(self.devices)} 台设备")
        self.statusBar().showMessage(f"扫描完成，发现 {len(self.devices)} 台设备")
        self.update_device_tables()
        
        # 保存扫描结果
        self.save_devices()
    
    def save_devices(self):
        """保存设备列表到文件"""
        import json
        try:
            # 使用当前工作目录（exe 运行目录）
            if getattr(sys, 'frozen', False):
                # 打包后的 exe，使用 exe 所在目录
                save_dir = os.path.dirname(sys.executable)
            else:
                # 开发时，使用脚本所在目录
                save_dir = os.path.dirname(os.path.abspath(__file__))
            
            save_file = os.path.join(save_dir, "devices.json")
            with open(save_file, 'w', encoding='utf-8') as f:
                json.dump(self.devices, f, ensure_ascii=False, indent=2)
            self.log(f"✓ 设备列表已保存到：{save_file}")
            self.log(f"  共 {len(self.devices)} 台设备")
        except Exception as e:
            self.log(f"⚠ 保存设备列表失败：{e}")
    
    def load_devices(self):
        """从文件加载设备列表"""
        import json
        try:
            # 使用当前工作目录（exe 运行目录）
            if getattr(sys, 'frozen', False):
                save_dir = os.path.dirname(sys.executable)
            else:
                save_dir = os.path.dirname(os.path.abspath(__file__))
            
            save_file = os.path.join(save_dir, "devices.json")
            
            if os.path.exists(save_file):
                with open(save_file, 'r', encoding='utf-8') as f:
                    self.devices = json.load(f)
                
                if self.devices:
                    self.log(f"✓ 加载上次扫描的设备：{len(self.devices)} 台")
                    self.log(f"  文件：{save_file}")
                    self.update_device_tables()
                    self.device_count_label.setText(f"已发现 {len(self.devices)} 台设备 (已保存)")
                else:
                    self.log("ℹ 保存的设备列表为空")
            else:
                self.log("ℹ 未找到保存的设备列表，请先扫描设备")
        except Exception as e:
            self.log(f"⚠ 加载设备列表失败：{e}")
    
    def disconnect_device(self, device):
        success, msg = self.adb.disconnect(device['ip'], device['port'])
        self.log(f"断开 {device['ip']}:{device['port']}: {msg}")
    
    def disconnect_selected(self):
        for row in range(self.device_table.rowCount()):
            checkbox = self.device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                self.disconnect_device(self.devices[row])
    
    def select_all_devices(self):
        for row in range(self.device_table.rowCount()):
            checkbox = self.device_table.item(row, 0)
            if checkbox:
                checkbox.setCheckState(Qt.Checked)
    
    def clear_saved_devices(self):
        """清除保存的设备列表"""
        import json
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            save_file = os.path.join(script_dir, "devices.json")
            if os.path.exists(save_file):
                os.remove(save_file)
                self.log("✓ 已清除保存的设备列表")
                self.devices = []
                self.device_table.setRowCount(0)
                self.device_count_label.setText("已发现 0 台设备")
                self.update_device_tables()
            else:
                self.log("ℹ 没有保存的设备列表")
        except Exception as e:
            self.log(f"⚠ 清除失败：{e}")
    
    def update_device_tables(self):
        # 获取 APK 版本信息
        apk_path = self.apk_path_edit.text().strip()
        apk_version = "-"
        apk_code = None
        apk_name = None
        if apk_path and os.path.exists(apk_path):
            code, name = self.adb.get_apk_version(apk_path)
            if code or name:
                apk_name = name or str(code)
                apk_version = f"v{apk_name}"
                apk_code = code
        
        # 安装页面 - 带版本对比
        self.install_device_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            # 选择列
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked)
            self.install_device_table.setItem(row, 0, checkbox)
            
            # 设备列
            self.install_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
            
            # 已安装版本列 - 需要查询
            version_item = QTableWidgetItem("检测中...")
            version_item.setForeground(QColor("#999"))
            self.install_device_table.setItem(row, 2, version_item)
            
            # APK 版本列 - 统一显示格式 v1.5.0
            apk_version_item = QTableWidgetItem(apk_version)
            if apk_code:
                apk_version_item.setForeground(QColor("#006600"))
            self.install_device_table.setItem(row, 3, apk_version_item)
            
            # 策略列 - 使用下拉框，根据版本自动选择
            policy_combo = QComboBox()
            policy_combo.addItems([
                "智能对比",
                "跳过已安装",
                "强制覆盖"
            ])
            # 默认选择全局策略
            policy_combo.setCurrentIndex(self.version_policy.currentIndex())
            self.install_device_table.setCellWidget(row, 4, policy_combo)
        
        # 卸载页面
        self.uninstall_device_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked)
            self.uninstall_device_table.setItem(row, 0, checkbox)
            self.uninstall_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
        
        # 重试页面清空
        self.retry_device_table.setRowCount(0)
        self.failed_devices = []
    
    # ========== 安装功能 ==========
    
    def on_package_name_changed(self, text):
        """包名改变时自动检查已安装版本"""
        if text and self.devices:
            # 延迟 500ms 检查，避免频繁查询
            if hasattr(self, 'check_timer'):
                self.check_timer.stop()
            else:
                from PyQt5.QtCore import QTimer
                self.check_timer = QTimer()
                self.check_timer.setSingleShot(True)
                self.check_timer.timeout.connect(self.check_installed_versions)
            self.check_timer.start(500)
    
    def on_refresh_version_clicked(self):
        """手动刷新版本按钮点击事件"""
        package_name = self.package_name_edit.text().strip()
        if not package_name:
            QMessageBox.warning(self, "提示", "请先输入应用包名")
            return
        
        if not self.devices:
            QMessageBox.warning(self, "提示", "没有设备，请先扫描设备")
            return
        
        self.log("🔄 手动刷新版本状态...")
        self.check_installed_versions(package_name)
    
    def on_version_policy_changed(self, index):
        tips = [
            "💡 智能对比：自动检测已安装版本，只有新版本才会安装",
            "💡 跳过已安装：只要已安装就跳过，不检查版本",
            "💡 强制覆盖：无论是否安装都覆盖安装"
        ]
        self.version_policy_tip.setText(tips[index])
        
        # 自动更新所有设备的策略
        for row in range(self.install_device_table.rowCount()):
            policy_combo = self.install_device_table.cellWidget(row, 4)
            if policy_combo:
                policy_combo.setCurrentIndex(index)
    
    def browse_apk(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择 APK 文件", "", "APK Files (*.apk)")
        if file_path:
            self.apk_path_edit.setText(file_path)
            self.log(f"已选择 APK: {file_path}")
            
            # 获取版本信息
            try:
                version_code, version_name = self.adb.get_apk_version(file_path)
                self.log(f"APK 解析结果：code={version_code}, name={version_name}")
                if version_code or version_name:
                    version_str = f"APK 版本：v{version_name or ''} (code: {version_code or 'N/A'})"
                    self.version_info_label.setText(version_str)
                    self.version_info_label.setStyleSheet("color: #006600; font-weight: bold;")
                    
                    # 更新表格中的 APK 版本列
                    apk_version = f"v{version_name or version_code}"
                    for row in range(self.install_device_table.rowCount()):
                        item = QTableWidgetItem(apk_version)
                        item.setForeground(QColor("#006600"))
                        self.install_device_table.setItem(row, 3, item)
                else:
                    self.version_info_label.setText("APK 版本信息：无法读取")
                    self.log("⚠ APK 版本解析失败")
            except Exception as e:
                self.version_info_label.setText(f"APK 版本信息：解析错误")
                self.log(f"✗ APK 版本解析错误：{e}")
    
    def check_installed_versions(self, package_name=None):
        """异步检查所有设备的已安装版本"""
        # 如果没有传入包名，从安装标签页获取
        if package_name is None:
            package_name = self.package_name_edit.text().strip()
        
        if not package_name:
            self.log("⚠ 未输入包名，跳过版本检测")
            return
        
        if not self.devices:
            self.log("ℹ 没有设备，跳过版本检测")
            return
        
        self.log(f"🔄 开始检测 {len(self.devices)} 台设备的已安装版本 (包名：{package_name})...")
        
        # 取消之前的检查线程
        if hasattr(self, 'check_version_thread') and self.check_version_thread.isRunning():
            self.check_version_thread.stop()
            self.check_version_thread.wait()
        
        # 启动新线程
        self.check_version_thread = CheckVersionThread(self.devices, package_name, self.adb)
        self.check_version_thread.version_checked.connect(self.update_installed_version)
        self.check_version_thread.finished.connect(self.on_check_versions_finished)
        self.check_version_thread.start()
    
    def update_installed_version(self, device_id, version):
        """更新已安装版本显示，并自动调整策略"""
        self.log(f"📝 更新设备 {device_id} 的版本：{version}")
        
        found = False
        for row in range(self.install_device_table.rowCount()):
            if row < len(self.devices):
                current_id = self.devices[row]["id"]
                self.log(f"  检查行 {row}: {current_id} == {device_id}? {current_id == device_id}")
                
                if current_id == device_id:
                    found = True
                    # 更新版本显示
                    item = QTableWidgetItem(version)
                    if version == "未安装":
                        item.setForeground(QColor("#999"))
                    else:
                        item.setForeground(QColor("#0066cc"))
                    self.install_device_table.setItem(row, 2, item)
                    self.log(f"  ✓ 已更新行 {row} 的版本列为：{version}")
                    
                    # 自动调整策略
                    policy_combo = self.install_device_table.cellWidget(row, 4)
                    if policy_combo:
                        # 获取 APK 版本信息
                        apk_path = self.apk_path_edit.text().strip()
                        apk_code = None
                        apk_name = None
                        if apk_path and os.path.exists(apk_path):
                            apk_code, apk_name = self.adb.get_apk_version(apk_path)
                        
                        # 获取已安装版本的 versionCode
                        installed_code = None
                        if version != "未安装":
                            # 重新查询 versionCode
                            package_name = self.package_name_edit.text().strip()
                            if package_name:
                                success, stdout, _ = self.adb._run_adb(
                                    device_id, "shell", "dumpsys", "package", package_name, timeout=30
                                )
                                if success and stdout:
                                    match = re.search(r'versionCode=(\d+)', stdout)
                                    if match:
                                        installed_code = int(match.group(1))
                        
                        # 自动选择策略
                        if version == "未安装":
                            policy_combo.setCurrentIndex(0)
                            self.log(f"  ✓ 策略设置为：智能对比 (未安装)")
                        elif apk_code and installed_code:
                            if apk_code > installed_code:
                                policy_combo.setCurrentIndex(0)
                                self.log(f"  ✓ 策略设置为：智能对比 (APK 版本更高)")
                            elif apk_code == installed_code:
                                policy_combo.setCurrentIndex(1)
                                self.log(f"  ✓ 策略设置为：跳过已安装 (版本相同)")
                            else:
                                policy_combo.setCurrentIndex(1)
                                self.log(f"  ✓ 策略设置为：跳过已安装 (APK 版本更低)")
                        else:
                            policy_combo.setCurrentIndex(0)
                            self.log(f"  ✓ 策略设置为：智能对比 (默认)")
                    
                    break
        
        if not found:
            self.log(f"  ⚠ 未找到设备 {device_id} 在表格中")
    
    def on_check_versions_finished(self):
        """版本检查完成"""
        self.log("✓ 已安装版本检测完成")
        self.log(f"  表格行数：{self.install_device_table.rowCount()}")
        self.log(f"  设备数量：{len(self.devices)}")
    
    def start_install(self):
        apk_path = self.apk_path_edit.text().strip()
        package_name = self.package_name_edit.text().strip()
        
        if not apk_path:
            QMessageBox.warning(self, "错误", "请选择 APK 文件")
            return
        if not package_name:
            QMessageBox.warning(self, "错误", "请输入应用包名")
            return
        if not os.path.exists(apk_path):
            QMessageBox.warning(self, "错误", "APK 文件不存在")
            return
        
        selected_devices = []
        for row in range(self.install_device_table.rowCount()):
            checkbox = self.install_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                selected_devices.append(self.devices[row])
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "请至少选择一台设备")
            return
        
        # 重置统计
        self.install_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.failed_devices = []
        self.install_result_label.setText("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        
        max_threads = self.install_threads.value()
        policy_map = {0: "compare", 1: "skip", 2: "force"}
        version_policy = policy_map[self.version_policy.currentIndex()]
        
        self.install_btn.setEnabled(False)
        self.stop_install_btn.setEnabled(True)
        self.install_progress_label.setText("正在安装...")
        self.log(f"📦 开始安装到 {len(selected_devices)} 台设备")
        self.log(f"   APK: {os.path.basename(apk_path)}")
        self.log(f"   包名：{package_name}")
        self.log(f"   策略：{self.version_policy.currentText()}")
        
        self.install_thread = InstallThread(
            selected_devices, apk_path, package_name, max_threads, version_policy
        )
        self.install_thread.install_progress.connect(self.on_install_progress)
        self.install_thread.task_finished.connect(self.on_install_task_finished)
        self.install_thread.all_finished.connect(self.on_install_all_finished)
        self.install_thread.start()
    
    def stop_install(self):
        if self.install_thread:
            self.install_thread.stop()
            self.log("安装已停止")
    
    def on_install_progress(self, device_id, status, message, device_info):
        icons = {
            "installing": "🔄", "success": "✅", "error": "❌", 
            "skipped": "⏭️", "uninstalling": "🗑️", "comparing": "📊"
        }
        icon = icons.get(status, "")
        self.install_progress_label.setText(f"{icon} {device_id}: {message}")
        self.log(f"[{status.upper()}] {device_id}: {message}")
    
    def on_install_task_finished(self, device_id, success, message, device_info):
        if success:
            if "跳过" in message or "skipped" in message.lower():
                self.install_stats["skipped"] += 1
            else:
                self.install_stats["success"] += 1
        else:
            self.install_stats["failure"] += 1
            # 记录失败设备
            for device in self.devices:
                if device["id"] == device_id:
                    self.failed_devices.append({
                        **device,
                        "error": message,
                        "retry_count": 0
                    })
                    break
        
        self.install_result_label.setText(
            f"✅ 成功：{self.install_stats['success']} | "
            f"❌ 失败：{self.install_stats['failure']} | "
            f"⏭️ 跳过：{self.install_stats['skipped']}")
        
        # 更新设备表格中的版本信息
        if success and device_info:
            for row in range(self.install_device_table.rowCount()):
                if self.devices[row]["id"] == device_id:
                    if device_info.get("apk_version_code"):
                        version_item = QTableWidgetItem(f"v{device_info['apk_version_code']}")
                        version_item.setForeground(QColor("#006600"))
                        self.install_device_table.setItem(row, 2, version_item)
                    break
    
    def on_install_all_finished(self):
        self.install_btn.setEnabled(True)
        self.stop_install_btn.setEnabled(False)
        
        if self.install_stats["failure"] > 0:
            self.install_progress_label.setText(f"安装完成 - {self.install_stats['failure']} 台设备失败，请查看「失败重试」标签")
            self.log(f"⚠️ 安装完成 - {self.install_stats['failure']} 台设备失败")
            self.update_retry_table()
        else:
            self.install_progress_label.setText("✓ 安装完成 - 全部成功!")
            self.log(f"✓ 安装完成 - 全部成功!")
        
        total = sum(self.install_stats.values())
        self.log(f"统计 - 成功：{self.install_stats['success']}/{total} | 跳过：{self.install_stats['skipped']}")
    
    # ========== 重试功能 ==========
    
    def update_retry_table(self):
        """更新重试设备表格"""
        self.retry_device_table.setRowCount(len(self.failed_devices))
        for row, device in enumerate(self.failed_devices):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked)
            self.retry_device_table.setItem(row, 0, checkbox)
            self.retry_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
            
            error_item = QTableWidgetItem(device.get("error", "未知错误")[:50])
            error_item.setForeground(QColor("#cc0000"))
            self.retry_device_table.setItem(row, 2, error_item)
            
            retry_count_item = QTableWidgetItem(str(device.get("retry_count", 0)))
            self.retry_device_table.setItem(row, 3, retry_count_item)
    
    def create_retry_tab(self):
        """创建失败重试标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        tip_group = QGroupBox("使用说明")
        tip_layout = QVBoxLayout(tip_group)
        tip1 = QLabel("⚠️ 此页面显示上次安装失败的设备")
        tip1.setStyleSheet("color: #cc0000; font-weight: bold;")
        tip_layout.addWidget(tip1)
        tip2 = QLabel("• 可以选择部分或全部失败设备重新尝试安装")
        tip2.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip2)
        tip3 = QLabel("• 重试前会自动卸载旧版本，然后重新安装")
        tip3.setStyleSheet("color: #666;")
        tip_layout.addWidget(tip3)
        layout.addWidget(tip_group)
        
        device_group = QGroupBox("失败设备列表")
        device_layout = QVBoxLayout(device_group)
        
        self.retry_device_table = QTableWidget()
        self.retry_device_table.setColumnCount(4)
        self.retry_device_table.setHorizontalHeaderLabels(["选择", "设备", "失败原因", "重试次数"])
        self.retry_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        device_layout.addWidget(self.retry_device_table)
        
        layout.addWidget(device_group)
        
        btn_layout = QHBoxLayout()
        self.retry_btn = QPushButton("🔄 重试选中设备")
        self.retry_btn.clicked.connect(self.start_retry)
        self.retry_btn.setFixedWidth(180)
        self.retry_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; background-color: #ff9800; color: white; padding: 8px; }")
        btn_layout.addWidget(self.retry_btn)
        
        self.stop_retry_btn = QPushButton("⏹️ 停止")
        self.stop_retry_btn.clicked.connect(self.stop_retry)
        self.stop_retry_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_retry_btn)
        
        btn_layout.addStretch()
        
        self.retry_progress_label = QLabel("准备就绪")
        btn_layout.addWidget(self.retry_progress_label)
        
        layout.addLayout(btn_layout)
        
        self.retry_progress_bar = QProgressBar()
        layout.addWidget(self.retry_progress_bar)
        
        self.retry_result_label = QLabel("✅ 成功：0 | ❌ 失败：0")
        self.retry_result_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self.retry_result_label)
        
        return widget
    
    def start_retry(self):
        apk_path = self.apk_path_edit.text().strip()
        package_name = self.package_name_edit.text().strip()
        
        if not apk_path:
            QMessageBox.warning(self, "错误", "请先在「应用安装」标签选择 APK 文件")
            return
        if not package_name:
            QMessageBox.warning(self, "错误", "请输入应用包名")
            return
        
        selected_devices = []
        for row in range(self.retry_device_table.rowCount()):
            checkbox = self.retry_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                selected_devices.append(self.failed_devices[row])
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "请至少选择一台设备")
            return
        
        self.retry_stats = {"success": 0, "failure": 0}
        self.retry_result_label.setText("✅ 成功：0 | ❌ 失败：0")
        
        self.retry_btn.setEnabled(False)
        self.stop_retry_btn.setEnabled(True)
        self.retry_progress_label.setText("正在重试...")
        self.log(f"🔄 开始重试 {len(selected_devices)} 台设备")
        
        self.retry_thread = RetryInstallThread(selected_devices, apk_path, package_name, max_threads=5)
        self.retry_thread.retry_progress.connect(self.on_retry_progress)
        self.retry_thread.retry_finished.connect(self.on_retry_finished)
        self.retry_thread.all_finished.connect(self.on_retry_all_finished)
        self.retry_thread.start()
    
    def stop_retry(self):
        if self.retry_thread:
            self.retry_thread.stop()
            self.log("重试已停止")
    
    def on_retry_progress(self, device_id, status, message):
        icons = {"retrying": "🔄", "success": "✅", "error": "❌", "uninstalling": "🗑️"}
        icon = icons.get(status, "")
        self.retry_progress_label.setText(f"{icon} {device_id}: {message}")
        self.log(f"[{status.upper()}] {device_id}: {message}")
    
    def on_retry_finished(self, device_id, success, message):
        if success:
            self.retry_stats["success"] += 1
            # 从失败列表移除
            self.failed_devices = [d for d in self.failed_devices if d["id"] != device_id]
        else:
            self.retry_stats["failure"] += 1
            # 增加重试次数
            for device in self.failed_devices:
                if device["id"] == device_id:
                    device["retry_count"] = device.get("retry_count", 0) + 1
                    break
        
        self.retry_result_label.setText(f"✅ 成功：{self.retry_stats['success']} | ❌ 失败：{self.retry_stats['failure']}")
        self.update_retry_table()
    
    def on_retry_all_finished(self):
        self.retry_btn.setEnabled(True)
        self.stop_retry_btn.setEnabled(False)
        
        if self.retry_stats["failure"] == 0:
            self.retry_progress_label.setText("✓ 重试完成 - 全部成功!")
            self.log("✓ 重试完成 - 全部成功!")
        else:
            self.retry_progress_label.setText(f"重试完成 - {self.retry_stats['failure']} 台设备仍然失败")
            self.log(f"⚠️ 重试完成 - {self.retry_stats['failure']} 台设备仍然失败")
        
        # 刷新版本状态 - 直接使用安装包名
        package_name = self.package_name_edit.text().strip()
        if package_name:
            self.log(f"🔄 刷新设备版本状态...")
            self.check_installed_versions(package_name)
        else:
            self.log("⚠ 包名为空，跳过版本刷新")
    
    # ========== 卸载功能 ==========
    
    def start_uninstall(self):
        package_name = self.uninstall_package_edit.text().strip()
        
        if not package_name:
            QMessageBox.warning(self, "错误", "请输入应用包名")
            return
        
        selected_devices = []
        for row in range(self.uninstall_device_table.rowCount()):
            checkbox = self.uninstall_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                selected_devices.append(self.devices[row])
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "请至少选择一台设备")
            return
        
        self.uninstall_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.uninstall_result_label.setText("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        max_threads = self.uninstall_threads.value()
        
        self.uninstall_btn.setEnabled(False)
        self.stop_uninstall_btn.setEnabled(True)
        self.uninstall_progress_label.setText("正在卸载...")
        self.log(f"🗑️ 开始卸载 {package_name} 从 {len(selected_devices)} 台设备")
        
        # 使用 InstallThread 的卸载逻辑 (简化版)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        def uninstall_device(device):
            device_id = device["id"]
            is_installed = self.adb.is_installed(device_id, package_name)
            if not is_installed:
                return device_id, True, "未安装，跳过", "skipped"
            
            success, msg = self.adb.uninstall(device_id, package_name)
            status = "success" if success else "error"
            return device_id, success, msg, status
        
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = {executor.submit(uninstall_device, d): d for d in selected_devices}
            for future in as_completed(futures):
                device_id, success, message, status = future.result()
                
                if status == "skipped":
                    self.uninstall_stats["skipped"] += 1
                elif success:
                    self.uninstall_stats["success"] += 1
                else:
                    self.uninstall_stats["failure"] += 1
                
                self.uninstall_result_label.setText(
                    f"✅ 成功：{self.uninstall_stats['success']} | "
                    f"❌ 失败：{self.uninstall_stats['failure']} | "
                    f"⏭️ 跳过：{self.uninstall_stats['skipped']}")
                self.log(f"[{status.upper()}] {device_id}: {message}")
        
        self.uninstall_btn.setEnabled(True)
        self.stop_uninstall_btn.setEnabled(False)
        self.uninstall_progress_label.setText("卸载完成")
        total = sum(self.uninstall_stats.values())
        self.log(f"✓ 卸载完成 - 成功：{self.uninstall_stats['success']}/{total}")
    
    def stop_uninstall(self):
        self.log("卸载已停止")
        self.uninstall_btn.setEnabled(True)
        self.stop_uninstall_btn.setEnabled(False)
    
    def export_log(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "导出日志", "adb_manager_log.txt", "Text Files (*.txt)")
        if file_path:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.log_text.toPlainText())
            self.log(f"✓ 日志已导出：{file_path}")




def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = ADBBatchManager()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
