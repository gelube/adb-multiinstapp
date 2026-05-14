#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ADB 批量管理工具 v3.0
用于局域网内批量发现 ADB 设备并进行应用安装/卸载管理
增强版：版本检测、失败重试、自定义端口、多端口扫描、配置持久化、
        断线重连、设备搜索、多APK安装、深色主题、设备详情、CSV导出
"""

import sys
import os
import subprocess
import re
import socket
import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QTableWidget, QTableWidgetItem,
    QGroupBox, QSpinBox, QFileDialog, QProgressBar, QTabWidget,
    QMessageBox, QHeaderView, QComboBox, QRadioButton, QButtonGroup,
    QDialog, QListWidget, QCheckBox, QSplitter, QAction, QStyleFactory
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings, QTimer
from PyQt5.QtGui import QFont, QColor, QIcon, QTextCursor


# ========== 深色主题 QSS ==========
DARK_STYLE = """
QMainWindow, QDialog { background-color: #2b2b2b; color: #d4d4d4; }
QGroupBox { border: 1px solid #555; border-radius: 4px; margin-top: 8px; padding-top: 16px; color: #d4d4d4; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #d4d4d4; }
QLabel { color: #d4d4d4; }
QLineEdit { background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #555; border-radius: 3px; padding: 4px; }
QLineEdit:focus { border: 1px solid #007acc; }
QPushButton { background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #555; border-radius: 3px; padding: 5px 12px; }
QPushButton:hover { background-color: #4a4a4a; }
QPushButton:pressed { background-color: #555; }
QPushButton:disabled { color: #666; background-color: #333; }
QTableWidget { background-color: #2b2b2b; color: #d4d4d4; gridline-color: #555; border: 1px solid #555; }
QTableWidget::item { padding: 2px; }
QTableWidget::item:selected { background-color: #094771; }
QHeaderView::section { background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #555; padding: 4px; }
QTabWidget::pane { border: 1px solid #555; background-color: #2b2b2b; }
QTabBar::tab { background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #555; padding: 6px 12px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background-color: #2b2b2b; border-bottom-color: #2b2b2b; }
QComboBox { background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #555; border-radius: 3px; padding: 4px; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background-color: #3c3c3c; color: #d4d4d4; selection-background-color: #094771; }
QSpinBox { background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #555; border-radius: 3px; padding: 4px; }
QProgressBar { border: 1px solid #555; border-radius: 3px; text-align: center; background-color: #3c3c3c; color: #d4d4d4; }
QProgressBar::chunk { background-color: #007acc; }
QTextEdit { background-color: #1e1e1e; color: #d4d4d4; border: 1px solid #555; }
QScrollBar:vertical { background-color: #2b2b2b; width: 10px; }
QScrollBar::handle:vertical { background-color: #555; border-radius: 5px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QCheckBox { color: #d4d4d4; }
QCheckBox::indicator { width: 14px; height: 14px; }
QStatusBar { background-color: #3c3c3c; color: #d4d4d4; }
QToolTip { background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #666; padding: 4px; }
QListWidget { background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #555; }
QListWidget::item:selected { background-color: #094771; }
QSplitter::handle { background-color: #555; }
"""


class ADBWorker:
    """ADB 操作工具类"""
    
    @staticmethod
    def _get_app_dir():
        """获取应用程序所在目录（兼容 PyInstaller 打包）"""
        if getattr(sys, 'frozen', False):
            # PyInstaller 打包后，sys.executable 是 exe 路径
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(os.path.abspath(__file__))

    def __init__(self, adb_path=None):
        if adb_path is None:
            app_dir = self._get_app_dir()
            adb_paths = [
                os.path.join(app_dir, "adb", "adb.exe"),
                os.path.join(app_dir, "adb.exe"),
            ]
            for path in adb_paths:
                if os.path.exists(path):
                    self.adb_path = path
                    return
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
    
    def get_device_detail(self, device_id):
        """获取设备详细信息（电量、分辨率、存储、SDK等）"""
        detail = {}
        
        # 电量
        success, stdout, _ = self._run_adb(device_id, "shell", "dumpsys", "battery", timeout=10)
        if success and stdout:
            level_match = re.search(r'level:\s*(\d+)', stdout)
            status_match = re.search(r'status:\s*(\d+)', stdout)
            if level_match:
                detail['battery'] = level_match.group(1) + '%'
                if status_match:
                    status_map = {'2': '充电中', '3': '放电中', '4': '未充电', '5': '已充满'}
                    detail['battery_status'] = status_map.get(status_match.group(1), '未知')
        
        # 分辨率
        success, stdout, _ = self._run_adb(device_id, "shell", "wm", "size", timeout=10)
        if success and stdout:
            size_match = re.search(r'(\d+x\d+)', stdout)
            if size_match:
                detail['screen'] = size_match.group(1)
        
        # 存储空间
        success, stdout, _ = self._run_adb(device_id, "shell", "df", "/data", timeout=10)
        if success and stdout:
            lines = stdout.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 4:
                    try:
                        total_kb = int(parts[1])
                        used_kb = int(parts[2])
                        free_kb = int(parts[3])
                        detail['storage_total'] = f"{total_kb/1024/1024:.1f}GB"
                        detail['storage_used'] = f"{used_kb/1024/1024:.1f}GB"
                        detail['storage_free'] = f"{free_kb/1024/1024:.1f}GB"
                    except (ValueError, IndexError):
                        detail['storage_total'] = parts[1]
                        detail['storage_used'] = parts[2]
                        detail['storage_free'] = parts[3]
        
        # SDK版本
        success, stdout, _ = self._run_adb(device_id, "shell", "getprop", "ro.build.version.sdk", timeout=10)
        if success and stdout:
            detail['sdk'] = stdout
        
        # CPU架构
        success, stdout, _ = self._run_adb(device_id, "shell", "getprop", "ro.product.cpu.abi", timeout=10)
        if success and stdout:
            detail['cpu_abi'] = stdout
        
        # Android安全补丁
        success, stdout, _ = self._run_adb(device_id, "shell", "getprop", "ro.build.version.security_patch", timeout=10)
        if success and stdout:
            detail['security_patch'] = stdout
        
        return detail
    
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
            match = re.search(r'versionName=([\d.]+)', stdout)
            if match:
                return match.group(1)
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
                manifest_names = [n for n in zip_ref.namelist() 
                                  if n.endswith('AndroidManifest.xml')]
                if not manifest_names:
                    return None, None, None
                
                xml_data = zip_ref.read(manifest_names[0])
                return self._parse_axml_v2(xml_data)
        except Exception as e:
            return None, None, None
    
    def _parse_axml_v2(self, xml_data):
        """增强版 AXML 解析器 - 支持标准格式的 APK"""
        import struct
        
        if len(xml_data) < 8:
            return None, None, None
        
        version_code = None
        version_name = None
        package_name = None
        
        is_binary = xml_data[:4].hex() == '03000800'
        
        if not is_binary:
            try:
                xml_text = xml_data.decode('utf-8', errors='ignore')
                code_match = re.search(r'android:versionCode="(\d+)"', xml_text)
                version_code = int(code_match.group(1)) if code_match else None
                name_match = re.search(r'android:versionName="([\d.]+)"', xml_text)
                version_name = name_match.group(1) if name_match else None
                pkg_match = re.search(r'package="([^"]+)"', xml_text)
                package_name = pkg_match.group(1) if pkg_match else None
                if version_code or version_name or package_name:
                    return version_code, version_name, package_name
            except:
                pass
            return None, None, None
        
        # 解析二进制 AXML
        pool_offset = 8
        header_size = struct.unpack('<H', xml_data[pool_offset+2:pool_offset+4])[0]
        string_count = struct.unpack('<I', xml_data[pool_offset+8:pool_offset+12])[0]
        strings_start = struct.unpack('<I', xml_data[pool_offset+20:pool_offset+24])[0]
        
        str_table_start = pool_offset + header_size
        pool_data_start = pool_offset + strings_start
        
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
        
        chunk_size = struct.unpack('<I', xml_data[pool_offset+4:pool_offset+8])[0]
        offset = pool_offset + chunk_size
        
        while offset < len(xml_data) - 8:
            chunk_type = struct.unpack('<H', xml_data[offset:offset+2])[0]
            chunk_size = struct.unpack('<I', xml_data[offset+4:offset+8])[0]
            
            if chunk_type == 0x0102:
                break
            offset += chunk_size
        
        while offset < len(xml_data) - 24:
            chunk_type = struct.unpack('<H', xml_data[offset:offset+2])[0]
            header_size = struct.unpack('<H', xml_data[offset+2:offset+4])[0]
            chunk_size = struct.unpack('<I', xml_data[offset+4:offset+8])[0]
            
            if chunk_type == 0x0102:
                name_idx = struct.unpack('<I', xml_data[offset+12:offset+16])[0]
                attr_count = struct.unpack('<H', xml_data[offset+28:offset+30])[0]
                
                elem_name = strings[name_idx] if name_idx < len(strings) else ''
                is_manifest = (elem_name == 'manifest')
                is_obfuscated = (name_idx == 0xFFFFFFFF)
                
                if is_manifest or is_obfuscated:
                    attr_start = offset + header_size
                    for i in range(attr_count):
                        if attr_start + 20 > len(xml_data):
                            break
                        
                        attr_name_idx = struct.unpack('<I', xml_data[attr_start+4:attr_start+8])[0]
                        attr_type = xml_data[attr_start + 13]
                        attr_value = struct.unpack('<I', xml_data[attr_start+16:attr_start+20])[0]
                        
                        attr_name = strings[attr_name_idx] if attr_name_idx < len(strings) else ''
                        
                        is_version_code = (attr_name == 'versionCode' or attr_name_idx == 0x0101021b)
                        is_version_name = (attr_name == 'versionName' or attr_name_idx == 0x0101021c)
                        is_package = (attr_name == 'package')
                        
                        if is_version_code:
                            if attr_type in [0x10, 0x00]:
                                version_code = attr_value
                        elif is_version_name:
                            if attr_type == 0x03:
                                str_idx = attr_value & 0xFFFF
                                if str_idx < len(strings):
                                    version_name = strings[str_idx]
                            elif attr_type == 0x00:
                                str_idx = attr_value
                                if str_idx < len(strings):
                                    version_name = strings[str_idx]
                        elif is_package:
                            if attr_type == 0x03:
                                str_idx = attr_value & 0xFFFF
                                if str_idx < len(strings):
                                    package_name = strings[str_idx]
                        
                        attr_start += 20
                    
                    if version_code or version_name or package_name:
                        return version_code, version_name, package_name
            
            offset += chunk_size
        
        return version_code, version_name, package_name
    
    def install(self, device_id, apk_path, replace=False, timeout=300):
        """安装 APK，返回 (success, message, phase_info)
        phase_info: 'transferring' | 'installing' | None
        """
        args = ["install"]
        if replace:
            args.extend(["-r", "-d"])
        args.append(apk_path)
        
        cmd = [self.adb_path, "-s", device_id] + args
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # 读取 stderr 实时检测阶段
            phase = None
            while True:
                line = proc.stderr.readline()
                if not line:
                    break
                line = line.strip()
                if 'copying' in line.lower() or 'push' in line.lower():
                    phase = 'transferring'
                elif 'Performing Streamed Install' in line or 'installing' in line.lower():
                    phase = 'installing'
            
            proc.wait(timeout=30)
            stdout = proc.stdout.read().strip()
            stderr = proc.stderr.read().strip()
            
            if proc.returncode == 0 and "Success" in stdout:
                return True, "安装成功", phase
            error_msg = stderr or stdout or "安装失败"
            return False, error_msg, phase
            
        except subprocess.TimeoutExpired:
            proc.kill()
            return False, "安装超时", None
        except Exception as e:
            return False, str(e), None
    
    def uninstall(self, device_id, package_name, timeout=60):
        """卸载应用"""
        success, stdout, stderr = self._run_adb(
            device_id, "uninstall", package_name, timeout=timeout
        )
        if success and "Success" in stdout:
            return True, "卸载成功"
        return False, stderr or stdout or "卸载失败"
    
    def list_packages(self, device_id, third_party_only=True, timeout=30):
        """获取已安装应用包名列表"""
        args = ["shell", "pm", "list", "packages"]
        if third_party_only:
            args.append("-3")
        success, stdout, stderr = self._run_adb(device_id, *args, timeout=timeout)
        if not success:
            return []
        packages = []
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line[8:])
        return packages


def parse_ports(port_str):
    """解析端口字符串，支持 5555,5556-5558 格式
    返回端口列表，如 [5555, 5556, 5557, 5558]
    """
    ports = set()
    for part in port_str.split(','):
        part = part.strip()
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                for p in range(int(start.strip()), int(end.strip()) + 1):
                    if 1 <= p <= 65535:
                        ports.add(p)
            except ValueError:
                continue
        else:
            try:
                p = int(part)
                if 1 <= p <= 65535:
                    ports.add(p)
            except ValueError:
                continue
    return sorted(ports)


class ScanThread(QThread):
    """设备扫描线程"""
    device_found = pyqtSignal(dict)
    scan_progress = pyqtSignal(int, int)
    scan_finished = pyqtSignal()
    log_message = pyqtSignal(str)
    
    def __init__(self, ip_list, ports, max_threads=50):
        super().__init__()
        self.ip_list = ip_list
        self.ports = ports if isinstance(ports, list) else [ports]
        self.max_threads = max_threads
        self.adb = ADBWorker()
        self.stop_flag = False
    
    def run(self):
        total = len(self.ip_list) * len(self.ports)
        completed = 0
        found_devices = set()
        
        # 构建 (ip, port) 任务列表
        tasks = []
        for ip in self.ip_list:
            for port in self.ports:
                tasks.append((ip, port))
        
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = {
                executor.submit(self.scan_device, ip, port): (ip, port)
                for ip, port in tasks
            }
            
            for future in as_completed(futures):
                if self.stop_flag:
                    break
                
                ip, port = futures[future]
                try:
                    success, device_id, info = future.result()
                    if success and device_id not in found_devices:
                        found_devices.add(device_id)
                        self.device_found.emit({
                            "id": device_id, "ip": ip, "port": port,
                            "state": info.get("state", "unknown"),
                            "model": info.get("model", "unknown"),
                            "version": info.get("version", "unknown")
                        })
                        self.log_message.emit(f"✓ 发现设备：{ip}:{port} - {info.get('model', 'Unknown')}")
                except Exception:
                    pass
                
                completed += 1
                self.scan_progress.emit(completed, total)
        
        self.scan_finished.emit()
    
    def scan_device(self, ip, port):
        """扫描单个设备的单个端口"""
        if self.stop_flag:
            return False, None, {}
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((ip, port))
            sock.close()
            if result != 0:
                return False, None, {}
        except Exception:
            return False, None, {}
        
        if self.stop_flag:
            return False, None, {}
        
        success, msg = self.adb.connect(ip, port, timeout=5)
        if success:
            import time
            time.sleep(0.2)
            info = self.adb.get_device_info(f"{ip}:{port}")
            return True, f"{ip}:{port}", info
        
        return False, None, {}
    
    def stop(self):
        self.stop_flag = True


class UninstallThread(QThread):
    """批量卸载线程"""
    uninstall_progress = pyqtSignal(str, str, str)
    task_finished = pyqtSignal(str, bool, str, str)
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
            # 断线重连 #15
            ip = device.get("ip", device_id.split(":")[0] if ":" in device_id else device_id)
            port = device.get("port", int(device_id.split(":")[1]) if ":" in device_id else 5555)
            self.adb.connect(ip, port, timeout=3)
            
            self.uninstall_progress.emit(device_id, "checking", "检查安装状态...")
            is_installed = self.adb.is_installed(device_id, self.package_name)
            
            if not is_installed:
                self.uninstall_progress.emit(device_id, "skipped", "未安装，跳过")
                return device_id, True, "未安装，跳过", "skipped"
            
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


class QueryInstalledThread(QThread):
    """查询已安装应用线程"""
    result_ready = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, devices, adb):
        super().__init__()
        self.devices = devices
        self.adb = adb
    
    def run(self):
        all_packages = set()
        for device in self.devices:
            try:
                packages = self.adb.list_packages(device["id"], third_party_only=True)
                all_packages.update(packages)
            except Exception:
                continue
        if all_packages:
            self.result_ready.emit(sorted(all_packages))
        else:
            self.error.emit("未查询到任何已安装应用")


class InstallThread(QThread):
    """批量安装线程"""
    install_progress = pyqtSignal(str, str, str, object)
    task_finished = pyqtSignal(str, bool, str, object)
    all_finished = pyqtSignal()
    
    def __init__(self, devices, apk_info_list, max_threads=10,
                 version_policy="compare", force_reinstall=False):
        super().__init__()
        self.devices = devices
        self.apk_info_list = apk_info_list  # [{path, package, version_code, version_name}, ...]
        self.max_threads = max_threads
        self.version_policy = version_policy
        self.force_reinstall = force_reinstall
        self.adb = ADBWorker()
        self.stop_flag = False
    
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
            "apk_version_code": None,
            "apk_version_name": None
        }
        
        try:
            # 断线重连 #15
            ip = device.get("ip", device_id.split(":")[0] if ":" in device_id else device_id)
            port = device.get("port", int(device_id.split(":")[1]) if ":" in device_id else 5555)
            self.install_progress.emit(device_id, "reconnecting", "正在重连设备...", device_info)
            self.adb.connect(ip, port, timeout=3)
            
            all_success = True
            last_msg = ""
            
            # 逐个安装APK，每个APK用自己的包名做版本对比
            for idx, apk_info in enumerate(self.apk_info_list):
                apk_path = apk_info["path"]
                package_name = apk_info["package"]
                apk_version_code = apk_info["version_code"]
                apk_version_name = apk_info["version_name"]
                apk_name = os.path.basename(apk_path)
                
                # 更新device_info用于结果记录
                device_info["apk_version_code"] = apk_version_code
                device_info["apk_version_name"] = apk_version_name
                
                # 如果没有包名，跳过版本对比，直接安装
                if not package_name:
                    self.install_progress.emit(device_id, "installing",
                        f"正在安装 ({idx+1}/{len(self.apk_info_list)}) {apk_name} (无包名，跳过对比)...", device_info)
                    success, msg, phase = self.adb.install(device_id, apk_path, replace=True)
                    if not success:
                        all_success = False
                        last_msg = f"{apk_name}: {msg}"
                        self.install_progress.emit(device_id, "error", last_msg, device_info)
                        break
                    last_msg = f"{apk_name}: 安装成功"
                    continue
                
                # 版本对比检查
                is_installed = self.adb.is_installed(device_id, package_name)
                skip_this = False
                need_uninstall = False
                
                if is_installed:
                    success, stdout, _ = self.adb._run_adb(
                        device_id, "shell", "dumpsys", "package", package_name, timeout=30
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
                        self.install_progress.emit(device_id, "skipped",
                            f"{apk_name} 已安装 (v{installed_name or installed_code})，跳过", device_info)
                        last_msg = f"{apk_name}: 已安装，跳过"
                        skip_this = True
                    
                    elif self.version_policy == "compare" and installed_code and apk_version_code:
                        if installed_code >= apk_version_code:
                            self.install_progress.emit(device_id, "skipped",
                                f"{apk_name} 已是最新版本 (v{installed_name})，跳过", device_info)
                            last_msg = f"{apk_name}: 已是最新版本，跳过"
                            skip_this = True
                        else:
                            self.install_progress.emit(device_id, "comparing",
                                f"{apk_name} 版本对比：已安装 v{installed_name} → 新版本 v{apk_version_name}", device_info)
                    
                    elif self.version_policy == "force":
                        need_uninstall = True
                
                if skip_this:
                    continue
                
                # 卸载旧版本
                if need_uninstall:
                    self.install_progress.emit(device_id, "uninstalling",
                        f"正在卸载 {apk_name} 旧版本...", device_info)
                    success, msg = self.adb.uninstall(device_id, package_name)
                    if not success:
                        self.install_progress.emit(device_id, "error",
                            f"{apk_name} 卸载失败：{msg}", device_info)
                        all_success = False
                        last_msg = f"{apk_name}: 卸载失败 - {msg}"
                        break
                
                # 安装APK
                if len(self.apk_info_list) > 1:
                    self.install_progress.emit(device_id, "installing",
                        f"正在安装 ({idx+1}/{len(self.apk_info_list)}) {apk_name}...", device_info)
                else:
                    self.install_progress.emit(device_id, "installing",
                        f"正在安装 v{apk_version_name or apk_version_code}...", device_info)
                
                success, msg, phase = self.adb.install(device_id, apk_path, replace=True)
                
                if not success:
                    all_success = False
                    last_msg = f"{apk_name}: {msg}"
                    self.install_progress.emit(device_id, "error", last_msg, device_info)
                    break
                else:
                    last_msg = f"{apk_name}: 安装成功"
                    if phase == 'transferring':
                        self.install_progress.emit(device_id, "installing", "传输完成，正在安装...", device_info)
            
            if all_success and not last_msg:
                # 全部跳过的情况
                last_msg = "全部已安装，跳过"
            
            if all_success:
                self.install_progress.emit(device_id, "success", last_msg, device_info)
            
            return device_id, all_success, last_msg, device_info
            
        except Exception as e:
            error_msg = f"安装异常：{str(e)}"
            self.install_progress.emit(device_id, "error", error_msg, device_info)
            return device_id, False, error_msg, device_info
    
    def stop(self):
        self.stop_flag = True


class RetryInstallThread(QThread):
    """失败重试安装线程"""
    retry_progress = pyqtSignal(str, str, str)
    retry_finished = pyqtSignal(str, bool, str)
    all_finished = pyqtSignal()
    
    def __init__(self, failed_devices, apk_info_list, max_threads=10):
        super().__init__()
        self.failed_devices = failed_devices
        self.apk_info_list = apk_info_list  # [{path, package, ...}, ...]
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
        
        # 断线重连 #15
        ip = device.get("ip", device_id.split(":")[0] if ":" in device_id else device_id)
        port = device.get("port", int(device_id.split(":")[1]) if ":" in device_id else 5555)
        self.adb.connect(ip, port, timeout=3)
        
        # 逐个APK处理
        for idx, apk_info in enumerate(self.apk_info_list):
            apk_path = apk_info["path"]
            package_name = apk_info.get("package", "")
            apk_name = os.path.basename(apk_path)
            
            # 先尝试卸载旧版本
            if package_name:
                self.retry_progress.emit(device_id, "uninstalling", f"正在卸载 {apk_name} 旧版本...")
                self.adb.uninstall(device_id, package_name, timeout=30)
            
            # 安装
            success, msg, phase = self.adb.install(device_id, apk_path, replace=True, timeout=300)
            if not success:
                self.retry_progress.emit(device_id, "error", f"{apk_name} 重试失败：{msg}")
                return device_id, False, f"{apk_name}: {msg}"
        
        self.retry_progress.emit(device_id, "success", "重试成功 ✓")
        return device_id, True, "重试成功"
    
    def stop(self):
        self.stop_flag = True


class CheckVersionThread(QThread):
    """检查已安装版本的线程 — 支持多包名"""
    version_checked = pyqtSignal(str, str, int)
    finished = pyqtSignal()
    
    def __init__(self, devices, package_names, adb):
        super().__init__()
        self.devices = devices
        self.package_names = package_names if isinstance(package_names, list) else [package_names]
        self.adb = adb
        self.stop_flag = False
    
    def run(self):
        for i, device in enumerate(self.devices):
            if self.stop_flag:
                break
            device_id = device["id"]
            # 对每个包名检查版本，显示最后一个包名的结果
            all_versions = []
            last_version_code = 0
            for pkg in self.package_names:
                if not pkg:
                    continue
                version = self.adb.get_installed_version(device_id, pkg)
                version_code = 0
                success, stdout, _ = self.adb._run_adb(
                    device_id, "shell", "dumpsys", "package", pkg, timeout=30
                )
                if success and stdout:
                    match = re.search(r'versionCode=(\d+)', stdout)
                    if match:
                        version_code = int(match.group(1))
                if version:
                    all_versions.append(f"{pkg}: v{version}")
                    last_version_code = version_code
                else:
                    all_versions.append(f"{pkg}: 未安装")
            
            if len(self.package_names) == 1:
                # 单包名：保持原有格式
                pkg = self.package_names[0]
                version = self.adb.get_installed_version(device_id, pkg)
                version_str = f"v{version}" if version else "未安装"
                version_code = 0
                success, stdout, _ = self.adb._run_adb(
                    device_id, "shell", "dumpsys", "package", pkg, timeout=30
                )
                if success and stdout:
                    match = re.search(r'versionCode=(\d+)', stdout)
                    if match:
                        version_code = int(match.group(1))
                self.version_checked.emit(device_id, version_str, version_code)
            else:
                # 多包名：显示汇总
                version_str = " | ".join(all_versions) if all_versions else "未安装"
                self.version_checked.emit(device_id, version_str, last_version_code)
        self.finished.emit()
    
    def stop(self):
        self.stop_flag = True


class DeviceDetailDialog(QDialog):
    """设备详情对话框 #21 — 异步加载"""
    
    def __init__(self, device_id, adb, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"设备详情 - {device_id}")
        self.setMinimumSize(400, 350)
        self.device_id = device_id
        self.adb = adb
        
        layout = QVBoxLayout(self)
        
        # 基本信息
        info_group = QGroupBox("基本信息")
        info_layout = QVBoxLayout(info_group)
        self.info_labels = {}
        
        basic_items = [
            ("设备ID", device_id),
            ("型号", "加载中..."),
            ("Android版本", "加载中..."),
        ]
        for label, default in basic_items:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{label}:"))
            val_label = QLabel(default)
            val_label.setStyleSheet("font-weight: bold;")
            row.addWidget(val_label)
            row.addStretch()
            info_layout.addLayout(row)
            self.info_labels[label] = val_label
        
        layout.addWidget(info_group)
        
        # 详细信息
        detail_group = QGroupBox("详细信息")
        detail_layout = QVBoxLayout(detail_group)
        
        detail_items = ["电量", "分辨率", "存储(总计)", "存储(可用)", "SDK版本", "CPU架构", "安全补丁"]
        for item in detail_items:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{item}:"))
            val_label = QLabel("加载中...")
            val_label.setStyleSheet("font-weight: bold;")
            row.addWidget(val_label)
            row.addStretch()
            detail_layout.addLayout(row)
            self.info_labels[item] = val_label
        
        layout.addWidget(detail_group)
        
        # 关闭按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        
        # 异步加载详细信息（不阻塞UI）
        self._load_thread = None
        QTimer.singleShot(50, self._async_load_details)
    
    def _async_load_details(self):
        """在后台线程加载设备详细信息"""
        import threading
        
        class DetailLoader(QThread):
            loaded = pyqtSignal(dict, dict)
            
            def __init__(self, device_id, adb):
                super().__init__()
                self.device_id = device_id
                self.adb = adb
            
            def run(self):
                info = self.adb.get_device_info(self.device_id)
                detail = self.adb.get_device_detail(self.device_id)
                self.loaded.emit(info, detail)
        
        self._loader = DetailLoader(self.device_id, self.adb)
        self._loader.loaded.connect(self._update_ui)
        self._loader.start()
    
    def _update_ui(self, info, detail):
        """在主线程更新UI"""
        self.info_labels["型号"].setText(info.get("model", "未知"))
        self.info_labels["Android版本"].setText(info.get("version", "未知"))
        
        self.info_labels["电量"].setText(
            detail.get('battery', '未知') + 
            (f" ({detail.get('battery_status', '')})" if 'battery_status' in detail else '')
        )
        self.info_labels["分辨率"].setText(detail.get('screen', '未知'))
        self.info_labels["存储(总计)"].setText(detail.get('storage_total', '未知'))
        self.info_labels["存储(可用)"].setText(detail.get('storage_free', '未知'))
        self.info_labels["SDK版本"].setText(detail.get('sdk', '未知'))
        self.info_labels["CPU架构"].setText(detail.get('cpu_abi', '未知'))
        self.info_labels["安全补丁"].setText(detail.get('security_patch', '未知'))


class ADBBatchManager(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.adb = ADBWorker()
        self.devices = []
        self.failed_devices = []
        self.scan_thread = None
        self.install_thread = None
        self.retry_thread = None
        self.install_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.retry_stats = {"success": 0, "failure": 0}
        self.install_results = []  # 用于导出CSV #22
        self.apk_paths = []  # 多APK支持 #17
        self.apk_info_list = []  # 多APK详情 [{path, package, version_code, version_name}, ...]
        self.dark_mode = False  # 深色主题 #23
        
        # 配置持久化 #16
        self.settings = QSettings("ADB-Batch-Manager", "ADB-Batch-Manager")
        
        self.init_ui()
        self.load_settings()  # #16 加载保存的配置
        
        self.log("=" * 50)
        self.log("ADB 批量管理工具 v3.0 已启动")
        self.log("新功能：多端口 | 配置持久化 | 断线重连 | 搜索 | 多APK | 深色主题 | 详情 | 导出")
        self.log("=" * 50)
        self.check_adb()
        
        self.load_devices()
    
    def init_ui(self):
        self.setWindowTitle("ADB 批量管理工具 v3.0")
        self.setMinimumSize(1400, 900)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # 顶部工具栏：深色主题切换
        toolbar_layout = QHBoxLayout()
        toolbar_layout.addStretch()
        self.dark_mode_btn = QPushButton("🌙 深色主题")
        self.dark_mode_btn.setCheckable(True)
        self.dark_mode_btn.setFixedWidth(110)
        self.dark_mode_btn.clicked.connect(self.toggle_dark_mode)
        toolbar_layout.addWidget(self.dark_mode_btn)
        main_layout.addLayout(toolbar_layout)
        
        tabs = QTabWidget()
        tabs.addTab(self.create_scan_tab(), "📱 设备发现")
        tabs.addTab(self.create_install_tab(), "📦 应用安装")
        tabs.addTab(self.create_retry_tab(), "⚠️ 失败重试")
        tabs.addTab(self.create_uninstall_tab(), "🗑️ 应用卸载")
        tabs.addTab(self.create_log_tab(), "📋 日志")
        
        main_layout.addWidget(tabs)
        self.statusBar().showMessage("就绪")
    
    # ========== 深色主题 #23 ==========
    
    def toggle_dark_mode(self, checked):
        self.dark_mode = checked
        if checked:
            self.setStyleSheet(DARK_STYLE)
            self.dark_mode_btn.setText("☀️ 浅色主题")
        else:
            self.setStyleSheet("")
            self.dark_mode_btn.setText("🌙 深色主题")
        self.settings.setValue("dark_mode", checked)
    
    # ========== 配置持久化 #16 ==========
    
    def load_settings(self):
        """加载保存的配置"""
        self.ip_start_edit.setText(self.settings.value("ip_start", "192.168.1.100"))
        self.ip_end_edit.setText(self.settings.value("ip_end", "192.168.1.200"))
        self.port_edit.setText(self.settings.value("port", "5555"))
        self.scan_threads.setValue(int(self.settings.value("scan_threads", 20)))
        self.install_threads.setValue(int(self.settings.value("install_threads", 30)))
        self.version_policy.setCurrentIndex(int(self.settings.value("version_policy", 0)))
        self.uninstall_threads.setValue(int(self.settings.value("uninstall_threads", 30)))
        
        # 深色主题
        dark = self.settings.value("dark_mode", False, type=bool)
        if dark:
            self.dark_mode_btn.setChecked(True)
            self.toggle_dark_mode(True)
    
    def save_settings(self):
        """保存当前配置"""
        self.settings.setValue("ip_start", self.ip_start_edit.text())
        self.settings.setValue("ip_end", self.ip_end_edit.text())
        self.settings.setValue("port", self.port_edit.text())
        self.settings.setValue("scan_threads", self.scan_threads.value())
        self.settings.setValue("install_threads", self.install_threads.value())
        self.settings.setValue("version_policy", self.version_policy.currentIndex())
        self.settings.setValue("uninstall_threads", self.uninstall_threads.value())
    
    def closeEvent(self, event):
        """窗口关闭时保存配置"""
        self.save_settings()
        super().closeEvent(event)
    

    def create_scan_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(6)
        
        # ── 扫描设置：两行布局 ──
        scan_group = QGroupBox("扫描设置")
        scan_grid = QVBoxLayout(scan_group)
        scan_grid.setSpacing(8)
        
        # 第一行：IP 范围
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        row1.addWidget(QLabel("起始 IP:"))
        self.ip_start_edit = QLineEdit()
        self.ip_start_edit.setPlaceholderText("例如：192.168.1.100")
        self.ip_start_edit.setToolTip("扫描的起始IP地址，支持跨网段扫描\n例如：192.168.1.100")
        row1.addWidget(self.ip_start_edit, 3)
        
        row1.addWidget(QLabel("结束 IP:"))
        self.ip_end_edit = QLineEdit()
        self.ip_end_edit.setPlaceholderText("例如：192.168.2.255")
        self.ip_end_edit.setToolTip("扫描的结束IP地址\n可跨网段，如 192.168.2.255\n单IP时起始和结束填一样")
        row1.addWidget(self.ip_end_edit, 3)
        scan_grid.addLayout(row1)
        
        # 第二行：端口 + 并发 + 按钮
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addWidget(QLabel("ADB 端口:"))
        self.port_edit = QLineEdit()
        self.port_edit.setPlaceholderText("5555 或 5555,5556-5558")
        self.port_edit.setText("5555")
        self.port_edit.setToolTip("ADB连接端口，支持以下格式：\n• 单端口：5555\n• 多端口（逗号分隔）：5555,5556,5557\n• 端口范围（连字符）：5555-5558\n• 混合格式：5555,5556-5558")
        row2.addWidget(self.port_edit, 3)
        
        row2.addWidget(QLabel("并发数:"))
        self.scan_threads = QSpinBox()
        self.scan_threads.setRange(1, 200)
        self.scan_threads.setValue(20)
        self.scan_threads.setFixedWidth(80)
        self.scan_threads.setToolTip("同时扫描的最大线程数\n• 局域网建议：20-50\n• 跨网段/大量IP建议：50-100\n• 数值越大扫描越快，但占用资源越多")
        row2.addWidget(self.scan_threads)
        
        row2.addSpacing(16)
        self.scan_btn = QPushButton("🔍 开始扫描")
        self.scan_btn.clicked.connect(self.start_scan)
        self.scan_btn.setMinimumWidth(130)
        self.scan_btn.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; padding: 6px 16px; }")
        row2.addWidget(self.scan_btn)
        
        self.stop_scan_btn = QPushButton("⏹️ 停止")
        self.stop_scan_btn.clicked.connect(self.stop_scan)
        self.stop_scan_btn.setEnabled(False)
        self.stop_scan_btn.setMinimumWidth(90)
        row2.addWidget(self.stop_scan_btn)
        
        scan_grid.addLayout(row2)
        
        # 端口格式提示（单独一行，靠左）
        port_tip = QLabel("💡 端口格式：5555 | 5555,5557 | 5555-5558 | 5555,5557-5560")
        port_tip.setStyleSheet("color: #888; font-size: 11px;")
        port_tip.setWordWrap(True)
        scan_grid.addWidget(port_tip)
        
        layout.addWidget(scan_group)
        
        # ── 扫描进度 ──
        self.scan_progress = QProgressBar()
        self.scan_progress.setVisible(False)
        layout.addWidget(self.scan_progress)
        
        # ── 设备搜索 #14 ──
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍 搜索:"))
        self.device_search_edit = QLineEdit()
        self.device_search_edit.setPlaceholderText("输入 IP、型号或版本号筛选设备...")
        self.device_search_edit.textChanged.connect(self.filter_device_table)
        search_layout.addWidget(self.device_search_edit)
        layout.addLayout(search_layout)
        
        # ── 设备列表 ──
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(6)
        self.device_table.setHorizontalHeaderLabels(["选择", "IP:端口", "状态", "型号", "Android 版本", "操作"])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.device_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.device_table.doubleClicked.connect(self.on_device_double_clicked)  # #21 设备详情
        layout.addWidget(self.device_table)
        
        # ── 底部按钮行 ──
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
        layout.setSpacing(6)
        
        # ── 上半部分：设置区域（左右分栏） ──
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)
        
        # 左侧：APK选择 + 应用信息
        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        
        # APK 选择
        apk_group = QGroupBox("APK 文件（支持多选）")
        apk_layout = QVBoxLayout(apk_group)
        apk_layout.setSpacing(4)
        
        apk_row = QHBoxLayout()
        self.apk_path_edit = QLineEdit()
        self.apk_path_edit.setPlaceholderText("点击「浏览」选择 APK 文件...")
        self.apk_path_edit.setToolTip("支持选择多个APK文件同时安装\n按住Ctrl多选，按住Shift范围选\n多APK将按顺序依次安装到每台设备")
        apk_row.addWidget(self.apk_path_edit, 1)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(self.browse_apk)
        apk_row.addWidget(browse_btn)
        apk_layout.addLayout(apk_row)
        
        self.apk_list_label = QLabel("")
        self.apk_list_label.setStyleSheet("color: #888; font-size: 11px;")
        self.apk_list_label.setWordWrap(True)
        apk_layout.addWidget(self.apk_list_label)
        
        left_col.addWidget(apk_group)
        
        # 应用信息
        pkg_group = QGroupBox("应用信息")
        pkg_layout = QVBoxLayout(pkg_group)
        pkg_layout.setSpacing(4)
        
        pkg_row = QHBoxLayout()
        pkg_row.addWidget(QLabel("包名:"))
        self.package_name_edit = QLineEdit()
        self.package_name_edit.setPlaceholderText("选APK后自动识别，或手动输入")
        self.package_name_edit.setToolTip("应用的包名（Package Name）\n• 选择APK文件后会自动识别\n• 也可手动输入，用于版本对比检测\n• 格式如：com.company.appname")
        pkg_row.addWidget(self.package_name_edit, 1)
        pkg_layout.addLayout(pkg_row)
        
        self.package_name_edit.textChanged.connect(self.on_package_name_changed)
        
        self.version_info_label = QLabel("APK 版本信息：未选择文件")
        self.version_info_label.setStyleSheet("color: #888; font-size: 11px;")
        pkg_layout.addWidget(self.version_info_label)
        
        left_col.addWidget(pkg_group)
        left_col.addStretch()
        
        top_layout.addLayout(left_col, 2)
        
        # 右侧：安装设置
        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        
        install_group = QGroupBox("安装设置")
        install_layout = QVBoxLayout(install_group)
        install_layout.setSpacing(8)
        
        # 并发数
        row_threads = QHBoxLayout()
        row_threads.addWidget(QLabel("安装并发数:"))
        self.install_threads = QSpinBox()
        self.install_threads.setRange(1, 100)
        self.install_threads.setValue(30)
        self.install_threads.setFixedWidth(80)
        self.install_threads.setToolTip("同时安装的最大设备数\n• 建议：5-30\n• 数值过大可能导致设备卡顿")
        row_threads.addWidget(self.install_threads)
        row_threads.addStretch()
        install_layout.addLayout(row_threads)
        
        # 策略
        row_policy = QHBoxLayout()
        row_policy.addWidget(QLabel("安装策略:"))
        self.version_policy = QComboBox()
        self.version_policy.addItems([
            "智能对比 (版本一致或更高则跳过)",
            "跳过已安装 (不检查版本)",
            "强制覆盖 (始终安装)"
        ])
        self.version_policy.setCurrentIndex(0)
        self.version_policy.setToolTip("全局安装策略，可在设备列表中单独覆盖\n• 智能对比：检测已安装版本，新版本才装\n• 跳过已安装：只要有就跳过\n• 强制覆盖：不管有没有都装")
        row_policy.addWidget(self.version_policy, 1)
        install_layout.addLayout(row_policy)
        
        self.version_policy_tip = QLabel("💡 智能对比：自动检测已安装版本，只有新版本才会安装")
        self.version_policy_tip.setStyleSheet("color: #0066cc; font-size: 11px;")
        self.version_policy_tip.setWordWrap(True)
        install_layout.addWidget(self.version_policy_tip)
        self.version_policy.currentIndexChanged.connect(self.on_version_policy_changed)
        
        right_col.addWidget(install_group)
        right_col.addStretch()
        
        top_layout.addLayout(right_col, 3)
        
        layout.addLayout(top_layout)
        
        # ── 设备列表与版本对比 ──
        device_group = QGroupBox("设备列表与版本对比")
        device_layout = QVBoxLayout(device_group)
        device_layout.setSpacing(4)
        
        refresh_row = QHBoxLayout()
        refresh_row.addStretch()
        self.refresh_version_btn = QPushButton("🔄 刷新版本")
        self.refresh_version_btn.clicked.connect(self.on_refresh_version_clicked)
        self.refresh_version_btn.setFixedWidth(110)
        self.refresh_version_btn.setStyleSheet("QPushButton { font-size: 12px; background-color: #2196F3; color: white; padding: 5px; }")
        refresh_row.addWidget(self.refresh_version_btn)
        device_layout.addLayout(refresh_row)
        
        self.install_device_table = QTableWidget()
        self.install_device_table.setColumnCount(5)
        self.install_device_table.setHorizontalHeaderLabels([
            "选择", "设备", "已安装版本", "APK 版本", "策略"
        ])
        self.install_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.install_device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.install_device_table.setColumnWidth(0, 50)
        self.install_device_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        device_layout.addWidget(self.install_device_table)
        
        strategy_tip = QLabel("💡 可在表格中为每台设备单独设置策略")
        strategy_tip.setStyleSheet("color: #888; font-size: 11px;")
        device_layout.addWidget(strategy_tip)
        
        layout.addWidget(device_group, 1)
        
        # ── 安装按钮和进度 ──
        btn_layout = QHBoxLayout()
        self.install_btn = QPushButton("📦 开始安装")
        self.install_btn.clicked.connect(self.start_install)
        self.install_btn.setMinimumWidth(140)
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
        
        # 结果 + 导出
        result_row = QHBoxLayout()
        self.install_result_label = QLabel("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        self.install_result_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        result_row.addWidget(self.install_result_label)
        result_row.addStretch()
        
        self.export_csv_btn = QPushButton("📊 导出CSV报告")
        self.export_csv_btn.clicked.connect(self.export_install_csv)
        self.export_csv_btn.setEnabled(False)
        self.export_csv_btn.setStyleSheet("QPushButton { padding: 5px 15px; }")
        result_row.addWidget(self.export_csv_btn)
        
        self.retry_tip_label = QLabel("💡 安装失败的设备会自动出现在「失败重试」标签页")
        self.retry_tip_label.setStyleSheet("color: #ff6600; font-size: 11px;")
        result_row.addWidget(self.retry_tip_label)
        
        layout.addLayout(result_row)
        
        return widget
    
    def create_retry_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(6)
        
        # 简洁提示（不占太多空间）
        tip_row = QHBoxLayout()
        tip_label = QLabel("⚠️ 此页面显示上次安装失败的设备，重试前会自动卸载旧版本")
        tip_label.setStyleSheet("color: #cc6600; font-size: 12px; font-weight: bold;")
        tip_label.setWordWrap(True)
        tip_row.addWidget(tip_label)
        tip_row.addStretch()
        layout.addLayout(tip_row)
        
        # 失败设备列表
        device_group = QGroupBox("失败设备列表")
        device_layout = QVBoxLayout(device_group)
        
        self.retry_device_table = QTableWidget()
        self.retry_device_table.setColumnCount(4)
        self.retry_device_table.setHorizontalHeaderLabels(["选择", "设备", "失败原因", "重试次数"])
        self.retry_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        device_layout.addWidget(self.retry_device_table)
        
        layout.addWidget(device_group, 1)
        
        # 按钮和进度
        btn_layout = QHBoxLayout()
        self.retry_btn = QPushButton("🔄 重试选中设备")
        self.retry_btn.clicked.connect(self.start_retry)
        self.retry_btn.setMinimumWidth(160)
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
        layout.setSpacing(6)
        
        # ── 上部：卸载设置 ──
        settings_group = QGroupBox("卸载设置")
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setSpacing(8)
        
        # 包名输入行
        pkg_row = QHBoxLayout()
        pkg_row.addWidget(QLabel("应用包名:"))
        self.uninstall_package_edit = QLineEdit()
        self.uninstall_package_edit.setPlaceholderText("例如：com.example.app")
        self.uninstall_package_edit.setToolTip("要卸载的应用包名\n• 可点击「查询已安装」获取包名列表\n• 格式如：com.company.appname")
        pkg_row.addWidget(self.uninstall_package_edit, 1)
        
        query_installed_btn = QPushButton("📋 查询已安装")
        query_installed_btn.setFixedWidth(110)
        query_installed_btn.setToolTip("从选中设备查询已安装的第三方应用列表")
        query_installed_btn.clicked.connect(self.query_installed_apps)
        pkg_row.addWidget(query_installed_btn)
        settings_layout.addLayout(pkg_row)
        
        pkg_tip = QLabel("💡 可点击「查询已安装」从设备获取包名")
        pkg_tip.setStyleSheet("color: #888; font-size: 11px;")
        settings_layout.addWidget(pkg_tip)
        
        # 并发数
        thread_row = QHBoxLayout()
        thread_row.addWidget(QLabel("卸载并发数:"))
        self.uninstall_threads = QSpinBox()
        self.uninstall_threads.setRange(1, 100)
        self.uninstall_threads.setValue(30)
        self.uninstall_threads.setFixedWidth(80)
        self.uninstall_threads.setToolTip("同时卸载的最大设备数\n• 建议：5-30")
        thread_row.addWidget(self.uninstall_threads)
        thread_row.addStretch()
        settings_layout.addLayout(thread_row)
        
        layout.addWidget(settings_group)
        
        # ── 设备列表 ──
        device_group = QGroupBox("选择设备")
        device_layout = QVBoxLayout(device_group)
        self.uninstall_device_table = QTableWidget()
        self.uninstall_device_table.setColumnCount(2)
        self.uninstall_device_table.setHorizontalHeaderLabels(["选择", "设备"])
        self.uninstall_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        device_layout.addWidget(self.uninstall_device_table)
        layout.addWidget(device_group, 1)
        
        # ── 按钮和进度 ──
        btn_layout = QHBoxLayout()
        self.uninstall_btn = QPushButton("🗑️ 开始卸载")
        self.uninstall_btn.clicked.connect(self.start_uninstall)
        self.uninstall_btn.setMinimumWidth(140)
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
    
    # ========== 设备搜索 #14 ==========
    
    def filter_device_table(self, text):
        """根据搜索文本过滤设备表格"""
        text = text.lower()
        for row in range(self.device_table.rowCount()):
            match = False
            for col in range(self.device_table.columnCount() - 1):  # 排除操作列
                item = self.device_table.item(row, col)
                if item and text in item.text().lower():
                    match = True
                    break
            self.device_table.setRowHidden(row, not match)
    
    # ========== 设备详情 #21 ==========
    
    def on_device_double_clicked(self, index):
        """双击设备行显示详情"""
        row = index.row()
        if row < len(self.devices):
            device = self.devices[row]
            dialog = DeviceDetailDialog(device["id"], self.adb, self)
            dialog.exec_()
    
    # ========== 扫描功能 ==========
    
    def _parse_ip(self, ip_str):
        try:
            parts = ip_str.strip().split('.')
            if len(parts) != 4:
                return None
            return [int(p) for p in parts]
        except:
            return None
    
    def _ip_to_int(self, ip_parts):
        """IP地址转整数，方便比较"""
        return (ip_parts[0] << 24) + (ip_parts[1] << 16) + (ip_parts[2] << 8) + ip_parts[3]
    
    def _int_to_ip(self, num):
        """整数转IP地址"""
        return f"{(num >> 24) & 0xFF}.{(num >> 16) & 0xFF}.{(num >> 8) & 0xFF}.{num & 0xFF}"
    
    def _generate_ip_list(self, start_ip_str, end_ip_str):
        """生成 IP 地址列表 #18 — 已放宽限制"""
        start_parts = self._parse_ip(start_ip_str)
        end_parts = self._parse_ip(end_ip_str)
        
        if not start_parts or not end_parts:
            return []
        
        start_int = self._ip_to_int(start_parts)
        end_int = self._ip_to_int(end_parts)
        
        if start_int > end_int:
            return []
        
        # 限制最大IP数量，防止误操作
        MAX_IPS = 65536
        count = end_int - start_int + 1
        if count > MAX_IPS:
            QMessageBox.warning(self, "范围过大", 
                f"IP 范围包含 {count} 个地址（上限 {MAX_IPS}）\n"
                "请缩小范围或使用更精确的起止IP")
            return []
        
        ip_list = []
        for i in range(start_int, end_int + 1):
            ip_list.append(self._int_to_ip(i))
        
        return ip_list
    
    def start_scan(self):
        ip_start_str = self.ip_start_edit.text().strip()
        ip_end_str = self.ip_end_edit.text().strip()
        port_str = self.port_edit.text().strip()
        max_threads = self.scan_threads.value()
        
        # 解析端口 #20
        ports = parse_ports(port_str)
        if not ports:
            QMessageBox.warning(self, "错误", "端口格式不正确\n示例：5555 或 5555,5556-5558")
            return
        
        # 生成 IP 列表
        ip_list = self._generate_ip_list(ip_start_str, ip_end_str)
        
        if not ip_list:
            QMessageBox.warning(self, "错误", 
                "IP 地址格式不正确\n\n"
                "示例：\n"
                "起始 IP: 192.168.1.100\n"
                "结束 IP: 192.168.1.200\n\n"
                "支持跨网段：\n"
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
        
        port_display = port_str if len(ports) == 1 else f"{port_str} ({len(ports)}个端口)"
        self.log(f"开始扫描 {ip_start_str} - {ip_end_str} 端口 {port_display} (共 {len(ip_list)} 个 IP)")
        
        self.scan_thread = ScanThread(ip_list, ports, max_threads)
        self.scan_thread.device_found.connect(self.on_device_found)
        self.scan_thread.scan_progress.connect(self.on_scan_progress)
        self.scan_thread.scan_finished.connect(self.on_scan_finished)
        self.scan_thread.log_message.connect(self.log)
        self.scan_thread.start()
        
        self.save_settings()
    
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
        self.save_devices()
    
    def save_devices(self):
        import json
        try:
            if getattr(sys, 'frozen', False):
                save_dir = os.path.dirname(sys.executable)
            else:
                save_dir = os.path.dirname(os.path.abspath(__file__))
            
            save_file = os.path.join(save_dir, "devices.json")
            with open(save_file, 'w', encoding='utf-8') as f:
                json.dump(self.devices, f, ensure_ascii=False, indent=2)
            self.log(f"✓ 设备列表已保存（{len(self.devices)} 台）")
        except Exception as e:
            self.log(f"⚠ 保存设备列表失败：{e}")
    
    def load_devices(self):
        import json
        try:
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
                if row < len(self.devices):
                    self.disconnect_device(self.devices[row])
    
    def select_all_devices(self):
        for row in range(self.device_table.rowCount()):
            checkbox = self.device_table.item(row, 0)
            if checkbox:
                checkbox.setCheckState(Qt.Checked)
    
    def clear_saved_devices(self):
        try:
            if getattr(sys, 'frozen', False):
                save_dir = os.path.dirname(sys.executable)
            else:
                save_dir = os.path.dirname(os.path.abspath(__file__))
            save_file = os.path.join(save_dir, "devices.json")
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
        apk_path = self.apk_path_edit.text().strip()
        apk_version = "-"
        apk_code = None
        apk_name = None
        if apk_path and os.path.exists(apk_path):
            code, name, _ = self.adb.get_apk_version(apk_path)
            if code or name:
                apk_name = name or str(code)
                apk_version = f"v{apk_name}"
                apk_code = code
        
        self.install_device_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked)
            self.install_device_table.setItem(row, 0, checkbox)
            
            self.install_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
            
            version_item = QTableWidgetItem("检测中...")
            version_item.setForeground(QColor("#999"))
            self.install_device_table.setItem(row, 2, version_item)
            
            apk_version_item = QTableWidgetItem(apk_version)
            if apk_code:
                apk_version_item.setForeground(QColor("#006600"))
            self.install_device_table.setItem(row, 3, apk_version_item)
            
            policy_combo = QComboBox()
            policy_combo.addItems(["智能对比", "跳过已安装", "强制覆盖"])
            policy_combo.setCurrentIndex(self.version_policy.currentIndex())
            self.install_device_table.setCellWidget(row, 4, policy_combo)
        
        self.uninstall_device_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked)
            self.uninstall_device_table.setItem(row, 0, checkbox)
            self.uninstall_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
        
        self.retry_device_table.setRowCount(0)
        self.failed_devices = []
    
    # ========== 安装功能 ==========
    
    def on_package_name_changed(self, text):
        if text and self.devices:
            if hasattr(self, 'check_timer'):
                self.check_timer.stop()
            else:
                self.check_timer = QTimer()
                self.check_timer.setSingleShot(True)
                self.check_timer.timeout.connect(self.check_installed_versions)
            self.check_timer.start(500)
    
    def on_refresh_version_clicked(self):
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
        for row in range(self.install_device_table.rowCount()):
            policy_combo = self.install_device_table.cellWidget(row, 4)
            if policy_combo:
                policy_combo.setCurrentIndex(index)
    
    def browse_apk(self):
        """选择APK文件 #17 — 支持多选"""
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择 APK 文件", "", "APK Files (*.apk)")
        if file_paths:
            self.apk_paths = file_paths
            self.apk_path_edit.setText(file_paths[0])
            
            # 解析所有APK的包名和版本
            self._parse_all_apk_info(file_paths)
            
            self.save_settings()
    
    def _parse_all_apk_info(self, file_paths):
        """解析所有APK的版本和包名信息"""
        self.apk_info_list = []
        all_success = True
        
        for file_path in file_paths:
            self.log(f"已选择 APK: {file_path}")
            try:
                version_code, version_name, pkg_name = self.adb.get_apk_version(file_path)
                self.log(f"APK 解析结果：code={version_code}, name={version_name}, package={pkg_name}")
                
                if not pkg_name:
                    all_success = False
                    self.log(f"⚠ 无法识别包名：{os.path.basename(file_path)}")
                
                self.apk_info_list.append({
                    "path": file_path,
                    "package": pkg_name or "",
                    "version_code": version_code,
                    "version_name": version_name or ""
                })
            except Exception as e:
                all_success = False
                self.apk_info_list.append({
                    "path": file_path,
                    "package": "",
                    "version_code": None,
                    "version_name": ""
                })
                self.log(f"✗ APK 解析错误：{e}")
        
        # 更新UI
        if len(file_paths) == 1:
            # 单APK：回填包名到输入框
            info = self.apk_info_list[0]
            if info["package"] and not self.package_name_edit.text().strip():
                self.package_name_edit.setText(info["package"])
                self.log(f"✓ 已自动填入包名：{info['package']}")
            
            if info["version_code"] or info["version_name"]:
                version_str = f"APK 版本：v{info['version_name']} (code: {info['version_code'] or 'N/A'})"
                if info["package"]:
                    version_str += f"  包名：{info['package']}"
                self.version_info_label.setText(version_str)
                self.version_info_label.setStyleSheet("color: #006600; font-weight: bold;")
                apk_version = f"v{info['version_name'] or info['version_code']}"
                for row in range(self.install_device_table.rowCount()):
                    item = QTableWidgetItem(apk_version)
                    item.setForeground(QColor("#006600"))
                    self.install_device_table.setItem(row, 3, item)
            else:
                self.version_info_label.setText("APK 版本信息：无法读取")
            self.apk_list_label.setText("")
        else:
            # 多APK：显示列表
            lines = []
            for i, info in enumerate(self.apk_info_list):
                name = os.path.basename(info["path"])
                pkg = info["package"] or "未知包名"
                ver = f"v{info['version_name']}" if info["version_name"] else "未知版本"
                lines.append(f"{i+1}. {name} — {pkg} ({ver})")
            
            self.apk_list_label.setText("📦 已选择 " + str(len(file_paths)) + " 个APK：\n" + "\n".join(lines))
            self.apk_list_label.setStyleSheet("color: #888; font-size: 11px;")
            
            # 多APK时包名输入框显示提示
            packages = [info["package"] for info in self.apk_info_list if info["package"]]
            if packages:
                self.package_name_edit.setPlaceholderText(f"自动识别：{', '.join(packages[:3])}{'...' if len(packages) > 3 else ''}")
            
            # 版本信息区显示摘要
            self.version_info_label.setText(f"共 {len(file_paths)} 个APK，包名/版本已自动识别")
            self.version_info_label.setStyleSheet("color: #006600; font-weight: bold;")
            
            self.log(f"已选择 {len(file_paths)} 个 APK")
            
            if not all_success:
                self.log("⚠ 部分APK解析失败，版本对比可能不准确")
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(url.toLocalFile().lower().endswith('.apk') for url in urls):
                event.acceptProposedAction()
    
    def dropEvent(self, event):
        """拖放 APK 文件 #17 — 支持多文件"""
        apk_files = []
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith('.apk'):
                apk_files.append(file_path)
        
        if apk_files:
            self.apk_paths = apk_files
            self.apk_path_edit.setText(apk_files[0])
            
            # 解析所有APK
            self._parse_all_apk_info(apk_files)
    
    def check_installed_versions(self, package_names=None):
        # 获取要检查的包名列表
        if package_names is None:
            # 从apk_info_list获取包名，或从输入框获取
            if self.apk_info_list:
                package_names = [info["package"] for info in self.apk_info_list if info["package"]]
            else:
                pkg = self.package_name_edit.text().strip()
                package_names = [pkg] if pkg else []
        elif isinstance(package_names, str):
            package_names = [package_names]
        
        # 过滤空包名
        package_names = [p for p in package_names if p]
        if not package_names or not self.devices:
            return
        
        pkg_display = ', '.join(package_names[:3]) + ('...' if len(package_names) > 3 else '')
        self.log(f"🔄 开始检测 {len(self.devices)} 台设备的已安装版本 (包名：{pkg_display})...")
        
        if hasattr(self, 'check_version_thread') and self.check_version_thread.isRunning():
            self.check_version_thread.stop()
            self.check_version_thread.wait()
        
        self.check_version_thread = CheckVersionThread(self.devices, package_names, self.adb)
        self.check_version_thread.version_checked.connect(self.update_installed_version)
        self.check_version_thread.finished.connect(self.on_check_versions_finished)
        self.check_version_thread.start()
    
    def update_installed_version(self, device_id, version, installed_code=0):
        for row in range(self.install_device_table.rowCount()):
            if row < len(self.devices):
                current_id = self.devices[row]["id"]
                if current_id == device_id:
                    item = QTableWidgetItem(version)
                    if version == "未安装":
                        item.setForeground(QColor("#999"))
                    else:
                        item.setForeground(QColor("#0066cc"))
                    self.install_device_table.setItem(row, 2, item)
                    
                    # 单APK时自动设置策略
                    if self.apk_info_list and len(self.apk_info_list) == 1:
                        policy_combo = self.install_device_table.cellWidget(row, 4)
                        if policy_combo:
                            apk_code = self.apk_info_list[0].get("version_code")
                            if version == "未安装":
                                policy_combo.setCurrentIndex(0)
                            elif apk_code and installed_code:
                                if apk_code > installed_code:
                                    policy_combo.setCurrentIndex(0)
                                else:
                                    policy_combo.setCurrentIndex(1)
                            else:
                                policy_combo.setCurrentIndex(0)
                    break
    
    def on_check_versions_finished(self):
        self.log("✓ 已安装版本检测完成")
    
    def start_install(self):
        apk_path = self.apk_path_edit.text().strip()
        
        if not apk_path:
            QMessageBox.warning(self, "错误", "请选择 APK 文件")
            return
        
        # 检查APK信息
        if not self.apk_info_list:
            # 没有解析过（可能是旧数据），尝试解析
            if self.apk_paths:
                self._parse_all_apk_info(self.apk_paths)
            else:
                self.apk_info_list = [{
                    "path": apk_path,
                    "package": self.package_name_edit.text().strip(),
                    "version_code": None,
                    "version_name": ""
                }]
        
        # 验证APK文件存在
        for info in self.apk_info_list:
            if not os.path.exists(info["path"]):
                QMessageBox.warning(self, "错误", f"APK 文件不存在：{info['path']}")
                return
        
        # 单APK时检查包名
        if len(self.apk_info_list) == 1 and not self.apk_info_list[0]["package"]:
            pkg = self.package_name_edit.text().strip()
            if not pkg:
                QMessageBox.warning(self, "错误", "请输入应用包名")
                return
            self.apk_info_list[0]["package"] = pkg
        
        selected_devices = []
        for row in range(self.install_device_table.rowCount()):
            checkbox = self.install_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                selected_devices.append(self.devices[row])
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "请至少选择一台设备")
            return
        
        self.install_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.install_results = []  # 清空导出数据 #22
        self.failed_devices = []
        self.install_selected_count = len(selected_devices)  # 用于进度条 #5
        self.install_result_label.setText("✅ 成功：0 | ❌ 失败：0 | ⏭️ 跳过：0")
        
        max_threads = self.install_threads.value()
        policy_map = {0: "compare", 1: "skip", 2: "force"}
        version_policy = policy_map[self.version_policy.currentIndex()]
        
        self.install_btn.setEnabled(False)
        self.stop_install_btn.setEnabled(True)
        self.export_csv_btn.setEnabled(False)
        self.install_progress_label.setText("正在安装...")
        self.install_progress_bar.setValue(0)
        
        apk_names = [os.path.basename(info["path"]) for info in self.apk_info_list]
        packages = [info["package"] for info in self.apk_info_list if info["package"]]
        self.log(f"📦 开始安装到 {len(selected_devices)} 台设备")
        self.log(f"   APK: {', '.join(apk_names)}")
        self.log(f"   包名：{', '.join(packages) if packages else '未识别'}")
        self.log(f"   策略：{self.version_policy.currentText()}")
        
        self.install_thread = InstallThread(
            selected_devices, self.apk_info_list, max_threads, version_policy
        )
        self.install_thread.install_progress.connect(self.on_install_progress)
        self.install_thread.task_finished.connect(self.on_install_task_finished)
        self.install_thread.all_finished.connect(self.on_install_all_finished)
        self.install_thread.start()
        
        self.save_settings()
    
    def stop_install(self):
        if self.install_thread:
            self.install_thread.stop()
            self.log("安装已停止")
    
    def on_install_progress(self, device_id, status, message, device_info):
        icons = {
            "installing": "🔄", "success": "✅", "error": "❌", 
            "skipped": "⏭️", "uninstalling": "🗑️", "comparing": "📊",
            "reconnecting": "🔗", "transferring": "📤"
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
            for device in self.devices:
                if device["id"] == device_id:
                    self.failed_devices.append({
                        **device,
                        "error": message,
                        "retry_count": 0
                    })
                    break
        
        # 更新进度条 #5
        total = sum(self.install_stats.values())
        if hasattr(self, 'install_selected_count') and self.install_selected_count > 0:
            progress = int((total / self.install_selected_count) * 100)
            self.install_progress_bar.setValue(min(progress, 100))
        
        # 记录安装结果用于导出 #22
        installed_ver = device_info.get("installed_version", "") if device_info else ""
        apk_ver = device_info.get("apk_version_name", "") if device_info else ""
        device_model = ""
        for d in self.devices:
            if d["id"] == device_id:
                device_model = d.get("model", "")
                break
        self.install_results.append({
            "device_id": device_id,
            "model": device_model,
            "installed_version": installed_ver or "未安装",
            "apk_version": apk_ver or "未知",
            "result": "成功" if success and "跳过" not in message else ("跳过" if "跳过" in message else "失败"),
            "error": "" if success else message
        })
        
        self.install_result_label.setText(
            f"✅ 成功：{self.install_stats['success']} | "
            f"❌ 失败：{self.install_stats['failure']} | "
            f"⏭️ 跳过：{self.install_stats['skipped']}")
        
        if success and device_info:
            for row in range(self.install_device_table.rowCount()):
                if row < len(self.devices) and self.devices[row]["id"] == device_id:
                    if device_info.get("apk_version_code"):
                        version_item = QTableWidgetItem(f"v{device_info['apk_version_code']}")
                        version_item.setForeground(QColor("#006600"))
                        self.install_device_table.setItem(row, 2, version_item)
                    break
    
    def on_install_all_finished(self):
        self.install_btn.setEnabled(True)
        self.stop_install_btn.setEnabled(False)
        self.export_csv_btn.setEnabled(True)  # #22 允许导出
        
        if self.install_stats["failure"] > 0:
            self.install_progress_label.setText(f"安装完成 - {self.install_stats['failure']} 台设备失败，请查看「失败重试」标签")
            self.log(f"⚠️ 安装完成 - {self.install_stats['failure']} 台设备失败")
            self.update_retry_table()
        else:
            self.install_progress_label.setText("✓ 安装完成 - 全部成功!")
            self.log("✓ 安装完成 - 全部成功!")
        
        total = sum(self.install_stats.values())
        self.log(f"统计 - 成功：{self.install_stats['success']}/{total} | 跳过：{self.install_stats['skipped']}")
    
    # ========== 导出CSV #22 ==========
    
    def export_install_csv(self):
        """导出安装结果为CSV"""
        if not self.install_results:
            QMessageBox.warning(self, "提示", "没有安装结果可导出")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出安装报告", 
            f"install_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV 文件 (*.csv)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=["device_id", "model", "installed_version", "apk_version", "result", "error"])
                    writer.writeheader()
                    writer.writerows(self.install_results)
                self.log(f"✓ 安装报告已导出：{file_path}")
                QMessageBox.information(self, "导出成功", f"安装报告已导出到：\n{file_path}")
            except Exception as e:
                QMessageBox.warning(self, "导出失败", f"导出失败：{e}")
    
    # ========== 重试功能 ==========
    
    def update_retry_table(self):
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
    
    def start_retry(self):
        # 使用安装时保存的APK路径，而非UI输入框
        if not self.apk_paths:
            QMessageBox.warning(self, "错误", "请先在「应用安装」标签选择 APK 文件")
            return
        if not self.apk_info_list:
            QMessageBox.warning(self, "错误", "APK 信息缺失，请重新选择 APK 文件")
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
        
        self.retry_thread = RetryInstallThread(selected_devices, self.apk_info_list, max_threads=self.install_threads.value())
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
            self.failed_devices = [d for d in self.failed_devices if d["id"] != device_id]
        else:
            self.retry_stats["failure"] += 1
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
        
        package_name = self.package_name_edit.text().strip()
        if package_name:
            self.log("🔄 刷新设备版本状态...")
            self.check_installed_versions(package_name)
    
    # ========== 卸载功能 ==========
    
    def query_installed_apps(self):
        selected_devices = []
        for row in range(self.uninstall_device_table.rowCount()):
            checkbox = self.uninstall_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                if row < len(self.devices):
                    selected_devices.append(self.devices[row])
        
        if not selected_devices:
            QMessageBox.warning(self, "提示", "请先在卸载页面选择至少一台设备")
            return
        
        self.log(f"📋 正在查询 {len(selected_devices)} 台设备的已安装应用...")
        self.query_thread = QueryInstalledThread(selected_devices, self.adb)
        self.query_thread.result_ready.connect(self.show_installed_apps)
        self.query_thread.error.connect(lambda msg: self.log(f"⚠ {msg}"))
        self.query_thread.start()
    
    def show_installed_apps(self, packages):
        if not packages:
            self.log("⚠ 未查询到任何已安装应用")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"已安装应用 ({len(packages)} 个)")
        dialog.setMinimumSize(450, 500)
        layout = QVBoxLayout(dialog)
        
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("🔍 搜索包名...")
        layout.addWidget(search_edit)
        
        list_widget = QListWidget()
        list_widget.addItems(packages)
        layout.addWidget(list_widget)
        
        def filter_list(text):
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                item.setHidden(text.lower() not in item.text().lower())
        search_edit.textChanged.connect(filter_list)
        
        def on_double_click(item):
            self.uninstall_package_edit.setText(item.text())
            self.log(f"✓ 已选择包名：{item.text()}")
            dialog.accept()
        list_widget.itemDoubleClicked.connect(on_double_click)
        
        btn_layout = QHBoxLayout()
        select_btn = QPushButton("选择")
        select_btn.clicked.connect(lambda: (
            self.uninstall_package_edit.setText(list_widget.currentItem().text()) if list_widget.currentItem() else None,
            self.log(f"✓ 已选择包名：{list_widget.currentItem().text()}") if list_widget.currentItem() else None,
            dialog.accept()
        ))
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(select_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        self.log(f"📋 查询到 {len(packages)} 个第三方应用，请在弹窗中选择")
        dialog.exec_()
    
    def start_uninstall(self):
        package_name = self.uninstall_package_edit.text().strip()
        
        if not package_name:
            QMessageBox.warning(self, "错误", "请输入应用包名")
            return
        
        selected_devices = []
        for row in range(self.uninstall_device_table.rowCount()):
            checkbox = self.uninstall_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                if row < len(self.devices):
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
        
        self.uninstall_selected_count = len(selected_devices)
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
            progress = int((total / self.uninstall_selected_count) * 100)
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
        
        package_name = self.uninstall_package_edit.text().strip()
        if package_name:
            self.log("🔄 刷新设备版本状态...")
            self.package_name_edit.setText(package_name)
            self.check_installed_versions(package_name)
    
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
