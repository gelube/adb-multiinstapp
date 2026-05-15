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
import time
import struct
import zipfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QTableWidget, QTableWidgetItem,
    QGroupBox, QSpinBox, QFileDialog, QProgressBar, QTabWidget,
    QMessageBox, QHeaderView, QComboBox, QRadioButton, QButtonGroup,
    QDialog, QListWidget, QListWidgetItem, QCheckBox, QSplitter, QAction, QStyleFactory, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings, QTimer, QRect
from PyQt5.QtGui import QFont, QColor, QIcon, QTextCursor, QCursor




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
                            elif attr_type == 0x00:
                                if attr_value < len(strings):
                                    package_name = strings[attr_value]
                        
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
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # 读取 stderr 实时检测阶段
            phase = None
            start_time = time.time()
            while True:
                # 检查超时
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    proc.kill()
                    return False, f"安装超时({timeout}秒)", phase
                
                line = proc.stderr.readline()
                if not line:
                    # 检查进程是否结束
                    if proc.poll() is not None:
                        break
                    continue
                line = line.strip()
                if 'copying' in line.lower() or 'push' in line.lower():
                    phase = 'transferring'
                elif 'Performing Streamed Install' in line or 'installing' in line.lower():
                    phase = 'installing'
            
            # 进程已结束，读取剩余输出
            remaining_time = max(5, timeout - (time.time() - start_time))
            proc.wait(timeout=remaining_time)
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


def parse_ip_ranges(ip_str):
    """解析IP地址字符串，支持多种格式：
    单IP: 192.168.1.100
    末段范围: 192.168.1.100-200
    完整范围: 192.168.1.100-192.168.1.200
    逗号分隔: 192.168.1.100,192.168.2.50-60
    返回IP列表
    """
    MAX_IPS = 65536
    ip_list = []
    seen = set()
    
    for part in ip_str.split(','):
        part = part.strip()
        if not part:
            continue
        
        if '-' in part:
            left, right = part.split('-', 1)
            left = left.strip()
            right = right.strip()
            
            # 判断是末段范围还是完整IP范围
            if '.' not in right:
                # 末段范围: 192.168.1.100-200
                prefix = left.rsplit('.', 1)[0]
                start_last = int(left.rsplit('.', 1)[1])
                end_last = int(right)
                for i in range(start_last, end_last + 1):
                    ip = f"{prefix}.{i}"
                    if ip not in seen:
                        seen.add(ip)
                        ip_list.append(ip)
            else:
                # 完整IP范围: 192.168.1.100-192.168.2.200
                start_parts = left.split('.')
                end_parts = right.split('.')
                if len(start_parts) == 4 and len(end_parts) == 4:
                    try:
                        start_int = (int(start_parts[0]) << 24) | (int(start_parts[1]) << 16) | (int(start_parts[2]) << 8) | int(start_parts[3])
                        end_int = (int(end_parts[0]) << 24) | (int(end_parts[1]) << 16) | (int(end_parts[2]) << 8) | int(end_parts[3])
                        count = end_int - start_int + 1
                        if count > MAX_IPS:
                            return None  # 范围过大
                        for i in range(start_int, end_int + 1):
                            ip = f"{(i >> 24) & 255}.{(i >> 16) & 255}.{(i >> 8) & 255}.{i & 255}"
                            if ip not in seen:
                                seen.add(ip)
                                ip_list.append(ip)
                    except ValueError:
                        continue
        else:
            # 单IP
            parts = part.split('.')
            if len(parts) == 4:
                try:
                    nums = [int(p) for p in parts]
                    if all(0 <= n <= 255 for n in nums):
                        if part not in seen:
                            seen.add(part)
                            ip_list.append(part)
                except ValueError:
                    pass
    
    return ip_list


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
            connected, conn_msg = self.adb.connect(ip, port, timeout=3)
            if not connected:
                self.uninstall_progress.emit(device_id, "error", f"设备连接失败: {conn_msg}")
                return device_id, False, f"连接失败: {conn_msg}", "error"
            
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
    task_finished = pyqtSignal(str, bool, str, object, list)
    all_finished = pyqtSignal()
    
    def __init__(self, devices, apk_info_list, max_threads=10,
                 version_policy="compare", force_reinstall=False):
        super().__init__()
        self.devices = devices
        self.apk_info_list = apk_info_list  # [{path, package, version_code, version_name}, ...]
        self.max_threads = max_threads
        self.version_policy = version_policy  # 全局默认策略
        self.force_reinstall = force_reinstall
        self.adb = ADBWorker()
        self.stop_flag = False
    
    def _get_device_policy(self, device):
        """获取设备级别的策略，优先用设备自带的，否则用全局默认"""
        return device.get("version_policy", self.version_policy)
    
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
                    device_id, success, message, device_info, apk_results = future.result()
                    self.task_finished.emit(device_id, success, message, device_info, apk_results)
                except Exception as e:
                    self.task_finished.emit(device["id"], False, str(e), {}, [])
        
        self.all_finished.emit()
    
    def install_to_device(self, device):
        device_id = device["id"]
        device_info = {
            "installed_version": None,
            "apk_version_code": None,
            "apk_version_name": None
        }
        apk_results = []  # [{apk_name, success, skipped, message}, ...]
        
        try:
            # 断线重连 #15
            ip = device.get("ip", device_id.split(":")[0] if ":" in device_id else device_id)
            port = device.get("port", int(device_id.split(":")[1]) if ":" in device_id else 5555)
            self.install_progress.emit(device_id, "reconnecting", "正在重连设备...", device_info)
            connected, conn_msg = self.adb.connect(ip, port, timeout=3)
            if not connected:
                self.install_progress.emit(device_id, "error", f"设备连接失败: {conn_msg}", device_info)
                return device_id, False, f"连接失败: {conn_msg}", device_info, []
            
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
                        apk_results.append({"apk_name": apk_name, "success": False, "skipped": False, "message": last_msg})
                        self.install_progress.emit(device_id, "error", last_msg, device_info)
                        break
                    last_msg = f"{apk_name}: 安装成功"
                    apk_results.append({"apk_name": apk_name, "success": True, "skipped": False, "message": last_msg})
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
                    
                    device_policy = self._get_device_policy(device)
                    
                    if device_policy == "skip":
                        self.install_progress.emit(device_id, "skipped",
                            f"{apk_name} 已安装 (v{installed_name or installed_code})，跳过", device_info)
                        last_msg = f"{apk_name}: 已安装，跳过"
                        skip_this = True
                    
                    elif device_policy == "compare" and installed_code and apk_version_code:
                        if installed_code >= apk_version_code:
                            self.install_progress.emit(device_id, "skipped",
                                f"{apk_name} 已是最新版本 (v{installed_name})，跳过", device_info)
                            last_msg = f"{apk_name}: 已是最新版本，跳过"
                            skip_this = True
                        else:
                            self.install_progress.emit(device_id, "comparing",
                                f"{apk_name} 版本对比：已安装 v{installed_name} → 新版本 v{apk_version_name}", device_info)
                    
                    elif device_policy == "force":
                        # 强制覆盖：直接覆盖安装，不卸载（保留数据）
                        self.install_progress.emit(device_id, "comparing",
                            f"{apk_name} 强制覆盖安装 (已安装 v{installed_name})", device_info)
                        import datetime; open('debug_install.log','a').write(f"{datetime.datetime.now():%H:%M:%S} [force] {device_id} {apk_name} is_installed={is_installed} skip={skip_this}\n")
                
                if skip_this:
                    apk_results.append({"apk_name": apk_name, "success": True, "skipped": True, "message": last_msg})
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
                import datetime; open('debug_install.log','a').write(f"{datetime.datetime.now():%H:%M:%S} [install] {device_id} {apk_name} success={success} msg={msg} policy={self.version_policy}\n")
                
                if not success:
                    all_success = False
                    last_msg = f"{apk_name}: {msg}"
                    self.install_progress.emit(device_id, "error", last_msg, device_info)
                    break
                else:
                    last_msg = f"{apk_name}: 安装成功"
                    apk_results.append({"apk_name": apk_name, "success": True, "skipped": False, "message": last_msg})
                    if phase == 'transferring':
                        self.install_progress.emit(device_id, "installing", "传输完成，正在安装...", device_info)
            
            if all_success and not last_msg:
                # 全部跳过的情况
                last_msg = "全部已安装，跳过"
            
            if all_success:
                self.install_progress.emit(device_id, "success", last_msg, device_info)
            
            return device_id, all_success, last_msg, device_info, apk_results
            
        except Exception as e:
            error_msg = f"安装异常：{str(e)}\n{traceback.format_exc()}"
            self.install_progress.emit(device_id, "error", error_msg, device_info)
            return device_id, False, error_msg, device_info, []
    
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
        connected, conn_msg = self.adb.connect(ip, port, timeout=3)
        if not connected:
            self.retry_progress.emit(device_id, "error", f"设备连接失败: {conn_msg}")
            return device_id, False, f"连接失败: {conn_msg}"
        
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
    """检查已安装版本的线程 — 支持多包名，逐包名发射信号"""
    version_checked = pyqtSignal(str, str, int)  # device_id, version_str, installed_code
    pkg_version_checked = pyqtSignal(str, str, str, int)  # device_id, package, version_or_"未安装", version_code
    
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
            all_versions = []
            last_version_code = 0
            last_version = None
            
            for pkg in self.package_names:
                if not pkg:
                    continue
                # 只调用一次 dumpsys，同时提取 versionName 和 versionCode
                version = None
                version_code = 0
                success, stdout, _ = self.adb._run_adb(
                    device_id, "shell", "dumpsys", "package", pkg, timeout=30
                )
                if success and stdout:
                    match_name = re.search(r'versionName=([\d.]+)', stdout)
                    if match_name:
                        version = match_name.group(1)
                    match_code = re.search(r'versionCode=(\d+)', stdout)
                    if match_code:
                        version_code = int(match_code.group(1))
                
                # 逐包名发射精确信号
                self.pkg_version_checked.emit(device_id, pkg, version or "未安装", version_code)
                
                if version:
                    all_versions.append(f"{pkg}: v{version}")
                    last_version_code = version_code
                    last_version = version
                else:
                    all_versions.append(f"{pkg}: 未安装")
            
            # 兼容旧信号
            if len(self.package_names) == 1:
                version_str = f"v{last_version}" if last_version else "未安装"
                self.version_checked.emit(device_id, version_str, last_version_code)
            else:
                version_str = " | ".join(all_versions) if all_versions else "未安装"
                self.version_checked.emit(device_id, version_str, last_version_code)
    
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


class VersionComparePopup(QDialog):
    """多APK版本对比弹窗"""
    def __init__(self, device_id, apk_info_list, installed_versions, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setWindowTitle("版本对比")
        
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        
        title = QLabel(f"📱 {device_id}")
        title.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        layout.addWidget(title)
        
        for apk_info in apk_info_list:
            pkg = apk_info.get("package", "")
            apk_ver = apk_info.get("version_name", "")
            apk_code = apk_info.get("version_code", 0)
            apk_name = os.path.basename(apk_info.get("path", ""))
            
            if pkg:
                installed = installed_versions.get(pkg, (None, 0))
                inst_ver, inst_code = installed
            else:
                inst_ver, inst_code = None, 0
            
            # 确定箭头标记
            if not pkg:
                arrow = "? 未知包名"
                color = "#999"
            elif inst_ver is None:
                arrow = "⬇ 需安装"
                color = "#cc0000"
            elif inst_code and apk_code and inst_code < apk_code:
                arrow = "⬇ 有更新"
                color = "#ff6600"
            elif inst_code and apk_code and inst_code > apk_code:
                arrow = "⬆ 已装更新版"
                color = "#0066cc"
            else:
                arrow = "＝ 相同"
                color = "#006600"
            
            row_layout = QHBoxLayout()
            pkg_display = pkg if pkg else apk_name
            pkg_label = QLabel(f"📦 {pkg_display}")
            pkg_label.setStyleSheet("font-size: 12px;")
            pkg_label.setToolTip(apk_name)
            row_layout.addWidget(pkg_label)
            
            if pkg:
                ver_text = f"已安装: {inst_ver or '无'}  vs  APK: v{apk_ver}"
            else:
                ver_text = f"APK: v{apk_ver} (包名未知)"
            ver_label = QLabel(ver_text)
            ver_label.setStyleSheet(f"font-size: 11px; color: #666;")
            row_layout.addWidget(ver_label, 1)
            
            arrow_label = QLabel(arrow)
            arrow_label.setStyleSheet(f"font-weight: bold; color: {color}; font-size: 12px;")
            row_layout.addWidget(arrow_label)
            
            layout.addLayout(row_layout)
        
        # 屏幕边界修正
        pos = QCursor.pos()
        try:
            screen = QApplication.screenAt(pos)
            if screen:
                screen_geo = screen.availableGeometry()
            else:
                screen_geo = QApplication.primaryScreen().availableGeometry()
        except Exception:
            screen_geo = QRect(0, 0, 1920, 1080)
        x = pos.x() + 10
        y = pos.y() + 10
        if x + self.sizeHint().width() > screen_geo.right():
            x = screen_geo.right() - self.sizeHint().width() - 10
        if y + self.sizeHint().height() > screen_geo.bottom():
            y = screen_geo.bottom() - self.sizeHint().height() - 10
        self.move(x, y)

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
        self.device_installed_versions = {}  # {device_id: {package: (version_name, version_code)}}
        self._device_list_changed = False  # Tab切换覆盖标记
        
        # 配置持久化 #16
        self.settings = QSettings("ADB-Batch-Manager", "ADB-Batch-Manager")
        
        self.init_ui()
        self.load_settings()  # #16 加载保存的配置
        
        self.log("=" * 50)
        self.log("ADB 批量管理工具 v3.4 已启动")
        self.log("新功能：多端口 | 补扫 | 版本对比弹窗 | 搜索过滤 | 多APK | 详情 | 导出")
        self.log("=" * 50)
        self.check_adb()
        
        self.load_devices()
    
    def init_ui(self):
        self.setWindowTitle("ADB 批量管理工具 v3.4")
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
    
    # ========== 配置持久化 #16 ==========
    
    def load_settings(self):
        """加载保存的配置"""
        self.ip_edit.setText(self.settings.value("ip_range", "192.168.1.100-200"))
        self.port_edit.setText(self.settings.value("port", "5555"))
        self.scan_threads.setValue(int(self.settings.value("scan_threads", 20)))
        self.install_threads.setValue(int(self.settings.value("install_threads", 30)))
        saved_policy = int(self.settings.value("version_policy", 0))
        self.version_policy.setCurrentIndex(saved_policy)
        import datetime; open('debug_install.log','a').write(f"{datetime.datetime.now():%H:%M:%S} [load_settings] policy={saved_policy}\n")
        self.uninstall_threads.setValue(int(self.settings.value("uninstall_threads", 30)))
        
    
    def save_settings(self):
        """保存当前配置"""
        self.settings.setValue("ip_range", self.ip_edit.text())
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
        
        # 第一行：IP 地址
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        row1.addWidget(QLabel("IP 地址:"))
        self.ip_edit = QLineEdit()
        self.ip_edit.setPlaceholderText("192.168.1.100-200")
        self.ip_edit.setToolTip("支持逗号分隔和范围")
        row1.addWidget(self.ip_edit, 1)
        
        scan_grid.addLayout(row1)
        
        # IP格式提示
        ip_tip = QLabel("💡 IP格式：192.168.1.100 | 192.168.1.100-200 | 192.168.1.100,192.168.2.50-60")
        ip_tip.setStyleSheet("color: #888; font-size: 11px;")
        ip_tip.setWordWrap(True)
        scan_grid.addWidget(ip_tip)
        
        # 第二行：端口 + 并发 + 按钮
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addWidget(QLabel("ADB 端口:"))
        self.port_edit = QLineEdit()
        self.port_edit.setPlaceholderText("5555")
        self.port_edit.setText("5555")
        self.port_edit.setToolTip("支持：5555 / 5555,5556-5558")
        row2.addWidget(self.port_edit, 3)
        
        row2.addWidget(QLabel("并发数:"))
        self.scan_threads = QSpinBox()
        self.scan_threads.setRange(1, 200)
        self.scan_threads.setValue(20)
        self.scan_threads.setFixedWidth(80)
        self.scan_threads.setToolTip("局域网20-50，跨网段50-100")
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
        self.device_search_edit.setPlaceholderText("搜索设备...")
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
        
        # ── 上半部分：APK文件(左) + 应用信息+安装设置(右) ──
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)
        
        # 左侧：APK文件列表
        apk_group = QGroupBox("APK 文件")
        apk_layout = QVBoxLayout(apk_group)
        apk_layout.setSpacing(4)
        
        self.apk_list_widget = QListWidget()
        self.apk_list_widget.setToolTip("Ctrl多选添加，选中后可删除")
        apk_layout.addWidget(self.apk_list_widget)
        
        apk_btn_row = QHBoxLayout()
        browse_btn = QPushButton("📂 浏览...")
        browse_btn.clicked.connect(self.browse_apk)
        apk_btn_row.addWidget(browse_btn)
        self.remove_apk_btn = QPushButton("🗑 删除")
        self.remove_apk_btn.clicked.connect(self.remove_apk)
        self.remove_apk_btn.setEnabled(False)
        apk_btn_row.addWidget(self.remove_apk_btn)
        self.clear_apk_btn = QPushButton("清空")
        self.clear_apk_btn.clicked.connect(self.clear_apk)
        self.clear_apk_btn.setEnabled(False)
        apk_btn_row.addWidget(self.clear_apk_btn)
        apk_btn_row.addStretch()
        apk_layout.addLayout(apk_btn_row)
        
        top_layout.addWidget(apk_group, 3)
        
        # 右侧：应用信息
        pkg_group = QGroupBox("应用信息")
        pkg_layout = QVBoxLayout(pkg_group)
        pkg_layout.setSpacing(4)
        
        self.app_info_list = QListWidget()
        self.app_info_list.setToolTip("APK包名和版本信息")
        pkg_layout.addWidget(self.app_info_list)
        
        self.version_info_label = QLabel("未选择APK文件")
        self.version_info_label.setStyleSheet("color: #888; font-size: 11px;")
        pkg_layout.addWidget(self.version_info_label)
        
        top_layout.addWidget(pkg_group, 3)
        
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
        self.install_threads.setToolTip("建议5-30，过大可能设备卡顿")
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
        self.version_policy.setToolTip("可在设备列表中单独覆盖")
        row_policy.addWidget(self.version_policy, 1)
        install_layout.addLayout(row_policy)
        
        self.version_policy_tip = QLabel("💡 智能对比：自动检测已安装版本，只有新版本才会安装")
        self.version_policy_tip.setStyleSheet("color: #0066cc; font-size: 11px;")
        self.version_policy_tip.setWordWrap(True)
        install_layout.addWidget(self.version_policy_tip)
        self.version_policy.currentIndexChanged.connect(self.on_version_policy_changed)
        
        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        right_col.addWidget(install_group)
        right_col.addStretch()
        
        top_layout.addLayout(right_col, 2)
        
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
        self.install_device_table.setColumnCount(4)
        self.install_device_table.setHorizontalHeaderLabels([
            "选择", "设备", "版本对比", "策略"
        ])
        self.install_device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.install_device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.install_device_table.setColumnWidth(0, 50)
        self.install_device_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
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
        self.uninstall_package_edit.setPlaceholderText("com.example.app")
        self.uninstall_package_edit.setToolTip("可点「查询已安装」获取")
        pkg_row.addWidget(self.uninstall_package_edit, 1)
        
        self.query_installed_btn = QPushButton("📋 查询已安装")
        self.query_installed_btn.setFixedWidth(110)
        self.query_installed_btn.setToolTip("从选中设备查询第三方应用")
        self.query_installed_btn.clicked.connect(self.query_installed_apps)
        pkg_row.addWidget(self.query_installed_btn)
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
        self.uninstall_threads.setToolTip("建议5-30")
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
        self.log_text.setStyleSheet("")
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
            for col in range(1, self.device_table.columnCount() - 1):  # 跳过勾选列(0)和操作列
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
        ip_str = self.ip_edit.text().strip()
        port_str = self.port_edit.text().strip()
        max_threads = self.scan_threads.value()
        
        # 解析端口
        ports = parse_ports(port_str)
        if not ports:
            QMessageBox.warning(self, "错误", "端口格式不正确\n示例：5555 或 5555,5556-5558")
            return
        
        # 解析 IP
        ip_list = parse_ip_ranges(ip_str)
        
        if not ip_list:
            QMessageBox.warning(self, "错误", 
                "IP 地址格式不正确\n\n"
                "示例：\n"
                "单IP: 192.168.1.100\n"
                "范围: 192.168.1.100-200\n"
                "多段: 192.168.1.100,192.168.2.50-60")
            return
        
        if ip_list is None:
            QMessageBox.warning(self, "范围过大", 
                f"IP 范围超过 65536 个地址\n请缩小范围")
            return
        
        self.devices = []
        self.failed_devices = []
        self.device_table.setRowCount(0)
        self.scan_btn.setEnabled(False)
        self.stop_scan_btn.setEnabled(True)
        self.scan_progress.setVisible(True)
        self.scan_progress.setValue(0)
        
        port_display = port_str if len(ports) == 1 else f"{port_str} ({len(ports)}个端口)"
        self.log(f"开始扫描 {ip_str} 端口 {port_display} (共 {len(ip_list)} 个 IP)")
        
        # ADB预热
        try:
            subprocess.run([self.adb.adb_path, "start-server"], capture_output=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.log("✓ ADB 服务已预热")
        except:
            pass

        # 断开旧扫描线程信号连接
        if hasattr(self, 'scan_thread') and self.scan_thread:
            try:
                self.scan_thread.device_found.disconnect()
                self.scan_thread.scan_progress.disconnect()
                self.scan_thread.scan_finished.disconnect()
                self.scan_thread.log_message.disconnect()
            except Exception:
                pass
        
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
        # 去重：同ID设备不重复添加
        if any(d['id'] == device['id'] for d in self.devices):
            return
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
        try:
            self._do_update_device_tables()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.log(f"✗ 更新设备表异常：{e}")
    
    def _do_update_device_tables(self):
        apk_version = "-"
        apk_code = None
        apk_name = None
        if self.apk_info_list:
            # 从已解析的APK信息获取版本
            if len(self.apk_info_list) == 1:
                info = self.apk_info_list[0]
                if info.get('version_name'):
                    apk_version = f"v{info['version_name']}"
                    apk_name = info['version_name']
                elif info.get('version_code'):
                    apk_version = f"v{info['version_code']}"
                    apk_name = str(info['version_code'])
                apk_code = info.get('version_code')
            else:
                apk_version = f"{len(self.apk_info_list)}个APK"
                apk_name = apk_version
        
        self._device_list_changed = True
        
        # 保存当前勾选状态
        saved_install_checks = {}
        for row in range(self.install_device_table.rowCount()):
            item = self.install_device_table.item(row, 0)
            if item and row < len(self.devices):
                saved_install_checks[self.devices[row]['id']] = item.checkState()
        saved_uninstall_checks = {}
        for row in range(self.uninstall_device_table.rowCount()):
            item = self.uninstall_device_table.item(row, 0)
            if item and row < len(self.devices):
                saved_uninstall_checks[self.devices[row]['id']] = item.checkState()
        
        self.install_device_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            # 恢复勾选状态，如果有的话
            if device['id'] in saved_install_checks:
                checkbox.setCheckState(saved_install_checks[device['id']])
            else:
                checkbox.setCheckState(Qt.Checked)
            self.install_device_table.setItem(row, 0, checkbox)
            
            self.install_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
            
            # 版本对比列 — 读取已有版本数据
            device_id = device['id']
            installed_dict = self.device_installed_versions.get(device_id, {})
            apk_count = len(self.apk_info_list) if self.apk_info_list else 0
            if apk_count > 0 and installed_dict:
                installed_count = 0
                update_count = 0
                for ai in (self.apk_info_list or []):
                    p = ai.get("package", "")
                    if p and p in installed_dict:
                        iv, ic = installed_dict[p]
                        if iv is not None:
                            installed_count += 1
                            ac = ai.get("version_code", 0) or 0
                            if ac > (ic or 0):
                                update_count += 1
                if installed_count == 0:
                    ver_text = "0/{}已安装".format(apk_count)
                    ver_color = "#cc0000"
                elif installed_count < apk_count:
                    ver_text = "{}/{}已安装".format(installed_count, apk_count)
                    ver_color = "#ff6600"
                elif update_count > 0:
                    ver_text = "{}/{}已安装 {}可更新".format(apk_count, apk_count, update_count)
                    ver_color = "#ff6600"
                else:
                    ver_text = "{}/{}已安装".format(apk_count, apk_count)
                    ver_color = "#006600"
            elif not installed_dict:
                ver_text = "待检测"
                ver_color = "#999"
            else:
                ver_text = "待检测"
                ver_color = "#999"
            self.install_device_table.setCellWidget(row, 2, self._create_version_widget(row, device_id, ver_text, ver_color))
            
            policy_combo = QComboBox()
            policy_combo.addItems(["智能对比", "跳过已安装", "强制覆盖"])
            policy_combo.setCurrentIndex(self.version_policy.currentIndex())
            self.install_device_table.setCellWidget(row, 3, policy_combo)
        
        self.uninstall_device_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            if device['id'] in saved_uninstall_checks:
                checkbox.setCheckState(saved_uninstall_checks[device['id']])
            else:
                checkbox.setCheckState(Qt.Checked)
            self.uninstall_device_table.setItem(row, 0, checkbox)
            self.uninstall_device_table.setItem(row, 1, QTableWidgetItem(f"{device['ip']}:{device['port']} - {device['model']}"))
        
        # 保留 failed_devices 和重试表，不清空
        # 只更新重试表中设备信息（IP/型号可能更新）
        if self.failed_devices:
            self.update_retry_table()
        self._device_list_changed = False
    
    def _create_version_widget(self, row, device_id, text, color="#0066cc"):
        """创建版本列按钮 - 点击弹出详情"""
        btn = QPushButton(f"{text}  详情 ▸")
        btn.setFlat(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                color: {color}; font-size: 12px; text-align: left;
                border: none; padding: 2px 4px; background: transparent;
            }}
            QPushButton:hover {{
                background: #e8f0fe; border-radius: 3px;
            }}
        """)
        btn.setToolTip("点击查看版本对比详情")
        btn.clicked.connect(lambda checked, r=row, d=device_id: self._show_version_popup(r, d))
        return btn
    
    def _show_version_popup(self, row, device_id):
        """显示版本对比详情弹窗 - 每行APK左右箭头对比"""
        try:
            if not self.apk_info_list:
                QMessageBox.information(self, "版本对比", "请先选择APK文件")
                return
            
            installed = self.device_installed_versions.get(device_id, {})
            
            # 构建每行对比信息
            lines = []
            for apk_info in self.apk_info_list:
                pkg = apk_info.get("package", "")
                apk_ver = apk_info.get("version_name", "")
                apk_code = apk_info.get("version_code", 0) or 0
                apk_name = os.path.basename(apk_info.get("path", ""))
                
                if pkg:
                    inst_ver, inst_code = installed.get(pkg, (None, 0))
                    inst_code = inst_code or 0
                    
                    if inst_ver is None:
                        status = "需安装"
                        arrow = "→"
                        line = f"  未安装  {arrow}  v{apk_ver}  【{status}】"
                        color_tag = "red"
                    elif inst_code < apk_code:
                        status = "有更新"
                        arrow = "→"
                        line = f"  v{inst_ver}  {arrow}  v{apk_ver}  【{status}】"
                        color_tag = "orange"
                    elif inst_code > apk_code:
                        status = "已装更新版"
                        arrow = "←"
                        line = f"  v{inst_ver}  {arrow}  v{apk_ver}  【{status}】"
                        color_tag = "blue"
                    else:
                        status = "相同"
                        arrow = "＝"
                        line = f"  v{inst_ver}  {arrow}  v{apk_ver}  【{status}】"
                        color_tag = "green"
                    pkg_line = f"📦 {pkg}"
                else:
                    arrow = "→"
                    line = f"  ???  {arrow}  v{apk_ver}  【未知包名】"
                    pkg_line = f"📦 {apk_name}"
                    color_tag = "gray"
                
                lines.append((pkg_line, line, color_tag))
            
            # 创建弹窗
            popup = QDialog(self)
            popup.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
            popup.setWindowTitle("版本对比详情")
            popup_layout = QVBoxLayout(popup)
            popup_layout.setSpacing(6)
            popup_layout.setContentsMargins(12, 8, 12, 8)
            
            # 标题
            title = QLabel(f"📱 {device_id} - 版本对比详情")
            title.setStyleSheet("font-weight: bold; font-size: 13px; padding-bottom: 4px;")
            popup_layout.addWidget(title)
            
            # 分隔线
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color: #ddd;")
            popup_layout.addWidget(sep)
            
            # 每个APK一行
            color_map = {
                "red": "#cc0000",
                "orange": "#e67e00",
                "blue": "#0066cc",
                "green": "#008800",
                "gray": "#999"
            }
            for pkg_line, ver_line, color_tag in lines:
                row_frame = QFrame()
                row_frame.setStyleSheet("QFrame { background: #f8f8f8; border-radius: 4px; padding: 4px; }")
                row_lay = QVBoxLayout(row_frame)
                row_lay.setContentsMargins(6, 4, 6, 4)
                row_lay.setSpacing(2)
                
                pkg_lbl = QLabel(pkg_line)
                pkg_lbl.setStyleSheet("font-size: 12px; font-weight: bold;")
                row_lay.addWidget(pkg_lbl)
                
                ver_lbl = QLabel(ver_line)
                ver_lbl.setStyleSheet(f"font-size: 12px; color: {color_map.get(color_tag, '#333')};")
                row_lay.addWidget(ver_lbl)
                
                popup_layout.addWidget(row_frame)
            
            # 关闭按钮
            close_btn = QPushButton("关闭")
            close_btn.setStyleSheet("padding: 4px 16px;")
            close_btn.clicked.connect(popup.close)
            popup_layout.addWidget(close_btn, alignment=Qt.AlignRight)
            
            # 定位到鼠标附近
            pos = QCursor.pos()
            try:
                screen = QApplication.screenAt(pos)
                if screen:
                    screen_geo = screen.availableGeometry()
                else:
                    screen_geo = QApplication.primaryScreen().availableGeometry()
            except Exception:
                screen_geo = QRect(0, 0, 1920, 1080)
            
            popup.adjustSize()
            x = pos.x() + 10
            y = pos.y() + 10
            if x + popup.width() > screen_geo.right():
                x = screen_geo.right() - popup.width() - 10
            if y + popup.height() > screen_geo.bottom():
                y = screen_geo.bottom() - popup.height() - 10
            popup.move(x, y)
            
            popup.exec_()
            
        except Exception as e:
            self.log(f"⚠ 版本对比弹窗出错: {e}")
            import traceback
            traceback.print_exc()
    
    # ========== 安装功能 ==========
    
    def on_refresh_version_clicked(self):
        package_names = [info["package"] for info in self.apk_info_list if info["package"]] if self.apk_info_list else []
        if not package_names:
            QMessageBox.warning(self, "提示", "请先选择APK文件")
            return
        if not self.devices:
            QMessageBox.warning(self, "提示", "没有设备，请先扫描设备")
            return
        self.log("🔄 手动刷新版本状态...")
        self.check_installed_versions(package_names)
    
    def on_version_policy_changed(self, index):
        import datetime; open('debug_install.log','a').write(f"{datetime.datetime.now():%H:%M:%S} [policy_changed] index={index}\n")
        tips = [
            "💡 智能对比：自动检测已安装版本，只有新版本才会安装",
            "💡 跳过已安装：只要已安装就跳过，不检查版本",
            "💡 强制覆盖：无论是否安装都覆盖安装"
        ]
        self.version_policy_tip.setText(tips[index])
        for row in range(self.install_device_table.rowCount()):
            policy_combo = self.install_device_table.cellWidget(row, 3)
            if policy_combo:
                policy_combo.setCurrentIndex(index)
    
    def browse_apk(self):
        """选择APK文件 #17 — 支持多选"""
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择 APK 文件", "", "APK Files (*.apk)")
        if file_paths:
            # 追加到已有列表
            existing = list(self.apk_paths) if self.apk_paths else []
            existing.extend(file_paths)
            self.apk_paths = existing
            
            # 解析所有APK的包名和版本
            self._parse_all_apk_info(self.apk_paths)
            
            self.save_settings()
    
    def _parse_all_apk_info(self, file_paths):
        """解析所有APK的版本和包名信息"""
        try:
            self._do_parse_all_apk_info(file_paths)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.log(f"✗ 解析APK异常：{e}")
    
    def _do_parse_all_apk_info(self, file_paths):
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
        
        # 更新APK文件列表
        self.apk_list_widget.clear()
        for info in self.apk_info_list:
            name = os.path.basename(info["path"])
            item = QListWidgetItem(f"📦 {name}")
            item.setData(Qt.UserRole, info["path"])
            item.setToolTip(info["path"])
            self.apk_list_widget.addItem(item)
        
        self.remove_apk_btn.setEnabled(len(self.apk_info_list) > 0)
        self.clear_apk_btn.setEnabled(len(self.apk_info_list) > 0)
        
        # 更新应用信息列表（只读）
        self.app_info_list.clear()
        for i, info in enumerate(self.apk_info_list):
            name = os.path.basename(info["path"])
            pkg = info["package"] or "未知包名"
            ver = f"v{info['version_name']}" if info["version_name"] else "未知版本"
            code = f"(code:{info['version_code']})" if info["version_code"] else ""
            item = QListWidgetItem(f"{pkg}  {ver} {code}")
            item.setToolTip(f"{name} — {pkg} {ver} {code}")
            if info["package"]:
                item.setForeground(QColor("#006600"))
            else:
                item.setForeground(QColor("#cc0000"))
            self.app_info_list.addItem(item)
        
        # 版本摘要
        if self.apk_info_list:
            packages = [info["package"] for info in self.apk_info_list if info["package"]]
            if len(self.apk_info_list) == 1:
                info = self.apk_info_list[0]
                ver_str = f"v{info['version_name']}" if info["version_name"] else "未知版本"
                self.version_info_label.setText(f"📦 {info['package'] or '未知包名'}  {ver_str}")
                self.version_info_label.setStyleSheet("color: #006600; font-weight: bold;")
            else:
                self.version_info_label.setText(f"共 {len(self.apk_info_list)} 个APK，{len(packages)} 个已识别包名")
                self.version_info_label.setStyleSheet("color: #006600; font-weight: bold;")
        
        # 触发版本检测
        if packages:
            self.check_installed_versions(packages)
        
        # 更新设备表版本列
        self.update_device_tables()
        
        if not all_success:
            self.log("⚠ 部分APK解析失败，版本对比可能不准确")
    
    def remove_apk(self):
        """删除选中的APK"""
        current_row = self.apk_list_widget.currentRow()
        if current_row >= 0 and current_row < len(self.apk_paths):
            removed_path = self.apk_paths.pop(current_row)
            self.log(f"已删除 APK: {os.path.basename(removed_path)}")
            if self.apk_paths:
                self._parse_all_apk_info(self.apk_paths)
            else:
                self.apk_list_widget.clear()
                self.app_info_list.clear()
                self.apk_info_list = []
                self.version_info_label.setText("未选择APK文件")
                self.version_info_label.setStyleSheet("color: #888; font-size: 11px;")
                self.remove_apk_btn.setEnabled(False)
                self.clear_apk_btn.setEnabled(False)
                self.update_device_tables()
            self.save_settings()
    
    def clear_apk(self):
        """清空所有APK"""
        self.apk_paths = []
        self.apk_info_list = []
        self.apk_list_widget.clear()
        self.app_info_list.clear()
        self.version_info_label.setText("未选择APK文件")
        self.version_info_label.setStyleSheet("color: #888; font-size: 11px;")
        self.remove_apk_btn.setEnabled(False)
        self.clear_apk_btn.setEnabled(False)
        self.update_device_tables()
        self.save_settings()
    
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
            existing = list(self.apk_paths) if self.apk_paths else []
            existing.extend(apk_files)
            self.apk_paths = existing
            
            # 解析所有APK
            self._parse_all_apk_info(self.apk_paths)
            self.save_settings()
    
    def check_installed_versions(self, package_names=None):
        # 获取要检查的包名列表
        if package_names is None:
            # 从apk_info_list获取包名
            if self.apk_info_list:
                package_names = [info["package"] for info in self.apk_info_list if info["package"]]
            else:
                package_names = []
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
        
        # 断开旧信号连接，避免回调叠加
        if hasattr(self, 'check_version_thread') and self.check_version_thread:
            try:
                self.check_version_thread.pkg_version_checked.disconnect()
                self.check_version_thread.version_checked.disconnect()
                self.check_version_thread.finished.disconnect()
            except Exception:
                pass
        
        self.check_version_thread = CheckVersionThread(self.devices, package_names, self.adb)
        self.check_version_thread.pkg_version_checked.connect(self._on_pkg_version_checked)
        self.check_version_thread.version_checked.connect(self.update_installed_version)
        self.check_version_thread.finished.connect(self.on_check_versions_finished)
        self.check_version_thread.start()
    
    def _on_pkg_version_checked(self, device_id, package, version, version_code):
        """逐包名版本检查回调，精确更新 device_installed_versions"""
        if device_id not in self.device_installed_versions:
            self.device_installed_versions[device_id] = {}
        if package:
            self.device_installed_versions[device_id][package] = (
                version if version != "未安装" else None,
                version_code
            )
    
    def update_installed_version(self, device_id, version, installed_code=0):
        # 存入 device_installed_versions
        if device_id not in self.device_installed_versions:
            self.device_installed_versions[device_id] = {}
        # 获取当前包名
        # device_installed_versions 已由 _on_pkg_version_checked 精确更新
        # 这里只负责UI更新
        
        for row in range(self.install_device_table.rowCount()):
            if row < len(self.devices):
                current_id = self.devices[row]["id"]
                if current_id == device_id:
                    apk_count = len(self.apk_info_list) if self.apk_info_list else 0
                    installed_dict = self.device_installed_versions.get(device_id, {})
                    
                    # 统计已安装数量和更新状态
                    installed_count = 0
                    update_count = 0
                    for ai in (self.apk_info_list or []):
                        p = ai.get("package", "")
                        if p and p in installed_dict:
                            iv, ic = installed_dict[p]
                            if iv is not None:
                                installed_count += 1
                                ac = ai.get("version_code", 0) or 0
                                if ac > (ic or 0):
                                    update_count += 1
                    
                    if apk_count > 0:
                        if installed_count == 0:
                            ver_text = f"0/{apk_count}已安装"
                            ver_color = "#cc0000"
                        elif installed_count < apk_count:
                            ver_text = f"{installed_count}/{apk_count}已安装"
                            ver_color = "#ff6600"
                        elif update_count > 0:
                            ver_text = f"{apk_count}/{apk_count}已安装 {update_count}可更新"
                            ver_color = "#ff6600"
                        else:
                            ver_text = f"{apk_count}/{apk_count}已安装"
                            ver_color = "#006600"
                    else:
                        # 无APK时显示原始版本字符串
                        if version == "未安装":
                            ver_text = "未安装"
                            ver_color = "#cc0000"
                        elif version.startswith("v"):
                            ver_text = version
                            ver_color = "#0066cc"
                        else:
                            ver_text = version
                            ver_color = "#0066cc"
                    
                    self.install_device_table.setCellWidget(row, 2, self._create_version_widget(row, device_id, ver_text, ver_color))
                    
                    # 仅全局策略为“智能对比”时自动调整行策略，不覆盖用户手动选的强制覆盖
                    if self.version_policy.currentIndex() == 0 and self.apk_info_list and len(self.apk_info_list) == 1:
                        policy_combo = self.install_device_table.cellWidget(row, 3)
                        if policy_combo and policy_combo.currentIndex() != 2:  # 不覆盖强制覆盖
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
        # 如果是安装前的版本刷新，现在开始安装
        if getattr(self, '_pending_install', False):
            self._pending_install = False
            self._do_start_install()
    
    def start_install(self):
        if not self.apk_paths:
            QMessageBox.warning(self, "错误", "请选择 APK 文件")
            return
        
        # 检查APK信息
        if not self.apk_info_list:
            # 没有解析过（可能是旧数据），尝试解析
            if self.apk_paths:
                self._parse_all_apk_info(self.apk_paths)
            else:
                self.apk_info_list = [{
                    "path": self.apk_paths[0] if self.apk_paths else "",
                    "package": "",
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
            QMessageBox.warning(self, "错误", "无法识别APK包名，请重新选择")
            return
        
        selected_devices = []
        for row in range(self.install_device_table.rowCount()):
            checkbox = self.install_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                selected_devices.append(self.devices[row])
        
        # 如果未勾选但有设备列表，用全部设备
        if not selected_devices and self.devices:
            selected_devices = list(self.devices)
            self.log(f"📦 未勾选设备，自动使用全部 {len(self.devices)} 台设备安装")
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "没有可用设备，请先去「设备发现」页扫描设备")
            return
        
        # 保存安装参数，先刷新版本再安装
        self._pending_install = True
        self._install_params = {
            'selected_devices': selected_devices,
        }
        
        # 刷新设备版本
        packages = [info["package"] for info in self.apk_info_list if info["package"]]
        if packages and self.devices:
            self.log("🔄 安装前刷新设备版本...")
            self.install_progress_label.setText("🔄 安装前刷新版本...")
            self.check_installed_versions(packages)
        else:
            # 无包名，直接安装
            self._pending_install = False
            self._do_start_install()
    
    def _do_start_install(self):
        """实际执行安装（版本刷新后调用）"""
        params = getattr(self, '_install_params', {})
        selected_devices = params.get('selected_devices', [])
        if not selected_devices:
            # 尝试重新获取
            for row in range(self.install_device_table.rowCount()):
                checkbox = self.install_device_table.item(row, 0)
                if checkbox and checkbox.checkState() == Qt.Checked:
                    selected_devices.append(self.devices[row])
            if not selected_devices and self.devices:
                selected_devices = list(self.devices)
            if not selected_devices:
                return
        
        self.install_stats = {"success": 0, "failure": 0, "skipped": 0}
        self.install_results = []  # 清空导出数据 #22
        self.failed_devices = []
        self.install_selected_count = len(selected_devices)  # 用于进度条 #5
        self.install_result_label.setText("✅ 成功：0台 | ❌ 失败：0台 | ⏭️ 跳过：0台")
        
        max_threads = self.install_threads.value()
        policy_map = {0: "compare", 1: "skip", 2: "force"}
        version_policy = policy_map[self.version_policy.currentIndex()]
        import datetime; open('debug_install.log','a').write(f"{datetime.datetime.now():%H:%M:%S} [_do_start_install] policy_index={self.version_policy.currentIndex()} policy={version_policy} combo_text={self.version_policy.currentText()}\n")
        
        self.install_btn.setEnabled(False)
        self.stop_install_btn.setEnabled(True)
        self._install_finished = False  # 防止重复触发
        self.export_csv_btn.setEnabled(False)
        self.install_progress_label.setText("正在安装...")
        self.install_progress_bar.setValue(0)
        
        # 给每个设备注入行级别的策略
        device_policy_map = {0: "compare", 1: "skip", 2: "force"}
        for row in range(self.install_device_table.rowCount()):
            policy_combo = self.install_device_table.cellWidget(row, 3)
            if policy_combo and row < len(self.devices):
                self.devices[row]["version_policy"] = device_policy_map.get(policy_combo.currentIndex(), version_policy)
        
        apk_names = [os.path.basename(info["path"]) for info in self.apk_info_list]
        packages = [info["package"] for info in self.apk_info_list if info["package"]]
        self.log(f"📦 开始安装到 {len(selected_devices)} 台设备")
        self.log(f"   APK: {', '.join(apk_names)}")
        self.log(f"   包名：{', '.join(packages) if packages else '未识别'}")
        self.log(f"   策略：{self.version_policy.currentText()}")
        
        # 断开旧安装线程信号连接
        if hasattr(self, 'install_thread') and self.install_thread:
            try:
                self.install_thread.install_progress.disconnect()
                self.install_thread.task_finished.disconnect()
                self.install_thread.all_finished.disconnect()
            except Exception:
                pass
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
    
    def on_install_task_finished(self, device_id, success, message, device_info, apk_results=None):
        if apk_results is None:
            apk_results = []
        
        # 按设备计数（不是按APK操作计数）
        import datetime; open('debug_install.log','a').write(f"{datetime.datetime.now():%H:%M:%S} [task_finished] {device_id} success={success} msg={message} apk_results={apk_results}\n")
        if apk_results:
            has_failure = any(not r["success"] for r in apk_results)
            all_skipped = all(r.get("skipped", False) for r in apk_results if r["success"])
            if has_failure:
                self.install_stats["failure"] += 1
            elif all_skipped and apk_results:
                self.install_stats["skipped"] += 1
            else:
                self.install_stats["success"] += 1
        else:
            # fallback：无逐APK结果时用旧逻辑
            if success:
                if "跳过" in message or "skipped" in message.lower():
                    self.install_stats["skipped"] += 1
                else:
                    self.install_stats["success"] += 1
            else:
                self.install_stats["failure"] += 1
        
        # 失败时记录到failed_devices
        if not success:
            for device in self.devices:
                if device["id"] == device_id:
                    self.failed_devices.append({
                        **device,
                        "error": message,
                        "retry_count": 0
                    })
                    break
        
        # 更新进度条（按设备计）
        devices_done = sum(self.install_stats.values())
        if hasattr(self, 'install_selected_count') and self.install_selected_count > 0:
            progress = min(int((devices_done / self.install_selected_count) * 100), 100)
            self.install_progress_bar.setValue(progress)
        
        # 记录安装结果用于导出 #22
        installed_ver = device_info.get("installed_version", "") if device_info else ""
        apk_ver = device_info.get("apk_version_name", "") if device_info else ""
        # APK名称：从apk_info_list获取（device_info不含apk_path）
        apk_names_list = [os.path.basename(info["path"]) for info in self.apk_info_list] if self.apk_info_list else []
        apk_name_str = ", ".join(apk_names_list) if apk_names_list else ""
        # APK版本：多APK时拼接
        if self.apk_info_list and len(self.apk_info_list) > 1:
            apk_ver = ", ".join(
                f"{os.path.basename(info['path'])}: v{info.get('version_name', '?')}" 
                for info in self.apk_info_list
            )
        elif not apk_ver and self.apk_info_list:
            apk_ver = self.apk_info_list[0].get('version_name', '') or '未知'
        device_model = ""
        for d in self.devices:
            if d["id"] == device_id:
                device_model = d.get("model", "")
                break
        self.install_results.append({
            "device_id": device_id,
            "model": device_model,
            "installed_version": installed_ver or "未安装",
            "apk_name": apk_name_str,
            "apk_version": apk_ver or "未知",
            "result": "成功" if success and "跳过" not in message else ("跳过(成功)" if "跳过" in message else "失败"),
            "error": "" if success else message
        })
        
        self.install_result_label.setText(
            f"✅ 成功：{self.install_stats['success']}台 | "
            f"❌ 失败：{self.install_stats['failure']}台 | "
            f"⏭️ 跳过：{self.install_stats['skipped']}台")
        
        # 安装成功后立即刷新版本
        if success and device_info:
            apk_count = len(self.apk_info_list) if self.apk_info_list else 0
            apk_vn = device_info.get("apk_version_name", "")
            for row in range(self.install_device_table.rowCount()):
                if row < len(self.devices) and self.devices[row]["id"] == device_id:
                    # 更新 device_installed_versions
                    if device_id not in self.device_installed_versions:
                        self.device_installed_versions[device_id] = {}
                    pkg = device_info.get("package", "")
                    if pkg:
                        self.device_installed_versions[device_id][pkg] = (apk_vn or None, device_info.get("apk_version_code", 0) or 0)
                    
                    # 统计已安装数量
                    installed_dict = self.device_installed_versions.get(device_id, {})
                    installed_count = 0
                    update_count = 0
                    for ai in (self.apk_info_list or []):
                        p = ai.get("package", "")
                        if p and p in installed_dict:
                            iv, ic = installed_dict[p]
                            if iv is not None:
                                installed_count += 1
                                ac = ai.get("version_code", 0) or 0
                                if ac > (ic or 0):
                                    update_count += 1
                    
                    if apk_count > 0:
                        if installed_count < apk_count:
                            ver_text = f"{installed_count}/{apk_count}已安装"
                            ver_color = "#ff6600"
                        elif update_count > 0:
                            ver_text = f"{apk_count}/{apk_count}已安装 {update_count}可更新"
                            ver_color = "#ff6600"
                        else:
                            ver_text = f"{apk_count}/{apk_count}已安装"
                            ver_color = "#006600"
                    else:
                        ver_text = f"v{apk_vn}" if apk_vn else "已安装"
                        ver_color = "#006600"
                    self.install_device_table.setCellWidget(row, 2, self._create_version_widget(row, device_id, ver_text, ver_color))
                    break
    
    def on_install_all_finished(self):
        if getattr(self, '_install_finished', False):
            return  # 防止重复触发
        self._install_finished = True
        self.install_btn.setEnabled(True)
        self.stop_install_btn.setEnabled(False)
        self.export_csv_btn.setEnabled(True)  # #22 允许导出
        
        s = self.install_stats['success']
        f = self.install_stats['failure']
        k = self.install_stats['skipped']
        total = s + f + k  # 总设备数
        
        if f > 0:
            self.install_progress_label.setText(f"安装完成 - 成功 {s}/{total}台（跳过 {k}） | {f} 台失败，请查看「失败重试」")
            self.log(f"⚠️ 安装完成 - 成功 {s}/{total}台（跳过 {k}） | {f} 台失败")
            self.update_retry_table()
        else:
            self.install_progress_label.setText(f"✓ 安装完成 - 成功 {s}/{total}台（跳过 {k}）")
            self.log(f"✓ 安装完成 - 成功 {s}/{total}台（跳过 {k}）")
        
        self.log(f"统计 - 成功：{s} | 失败：{f} | 跳过：{k} | 总计：{total}台")
        
        # 安装完成后刷新版本信息
        packages = [info["package"] for info in self.apk_info_list if info["package"]]
        if packages:
            self._pending_install = False  # 确保不会触发重复安装
            self.log("🔄 安装完成，刷新设备版本...")
            self.check_installed_versions(packages)
    
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
                    writer = csv.DictWriter(f, fieldnames=["device_id", "model", "installed_version", "apk_name", "apk_version", "result", "error"])
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
        # 断开旧信号
        if hasattr(self, 'retry_thread') and self.retry_thread:
            try:
                self.retry_thread.retry_progress.disconnect()
                self.retry_thread.retry_finished.disconnect()
                self.retry_thread.all_finished.disconnect()
            except Exception:
                pass
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
        
        package_names = [info["package"] for info in self.apk_info_list if info["package"]] if self.apk_info_list else []
        if package_names:
            self.log("🔄 刷新设备版本状态...")
            self.check_installed_versions(package_names)
    
    # ========== 卸载功能 ==========
    
    def query_installed_apps(self):
        selected_devices = []
        for row in range(self.uninstall_device_table.rowCount()):
            checkbox = self.uninstall_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                if row < len(self.devices):
                    selected_devices.append(self.devices[row])
        
        # 如果未勾选但有设备列表，用全部设备
        if not selected_devices and self.devices:
            selected_devices = list(self.devices)
            self.log(f"📋 未勾选设备，自动使用全部 {len(self.devices)} 台设备查询")
        
        if not selected_devices:
            QMessageBox.warning(self, "提示", "没有可用设备，请先去「设备发现」页扫描设备")
            return
        
        self.query_installed_btn.setEnabled(False)
        self.query_installed_btn.setText("⏳ 查询中...")
        self.log(f"📋 正在查询 {len(selected_devices)} 台设备的已安装应用...")
        self.query_thread = QueryInstalledThread(selected_devices, self.adb)
        self.query_thread.result_ready.connect(self.show_installed_apps)
        self.query_thread.error.connect(lambda msg: self.log(f"⚠ {msg}"))
        self.query_thread.finished.connect(self._on_query_finished)
        self.query_thread.start()
    
    def _on_query_finished(self):
        """查询线程完成后恢复按钮状态"""
        self.query_installed_btn.setEnabled(True)
        self.query_installed_btn.setText("📋 查询已安装")
    
    def show_installed_apps(self, packages):
        if not packages:
            QMessageBox.information(self, "查询结果", "未查询到已安装应用\n\n可能原因：\n• 设备未连接或ADB超时\n• 设备上无第三方应用\n• ADB权限不足")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"已安装应用 ({len(packages)} 个)")
        dialog.setMinimumSize(450, 500)
        layout = QVBoxLayout(dialog)
        
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("搜索包名...")
        layout.addWidget(search_edit)
        
        list_widget = QListWidget()
        for pkg in packages:
            item = QListWidgetItem(pkg)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            list_widget.addItem(item)
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
        
        # 全选/取消全选按钮
        toggle_btn = QPushButton("取消全选")
        all_checked = [True]
        def toggle_select():
            new_state = Qt.Unchecked if all_checked[0] else Qt.Checked
            all_checked[0] = not all_checked[0]
            toggle_btn.setText("全选" if not all_checked[0] else "取消全选")
            for i in range(list_widget.count()):
                if not list_widget.item(i).isHidden():
                    list_widget.item(i).setCheckState(new_state)
        toggle_btn.clicked.connect(toggle_select)
        
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(toggle_btn)
        btn_layout.addStretch()
        
        def do_select():
            checked = []
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                if item.checkState() == Qt.Checked and not item.isHidden():
                    checked.append(item.text())
            if not checked:
                return
            if len(checked) == 1:
                self.uninstall_package_edit.setText(checked[0])
            else:
                self.uninstall_package_edit.setText(", ".join(checked))
            self.log(f"✓ 已选择 {len(checked)} 个包名")
            dialog.accept()
        
        select_btn = QPushButton("选择")
        select_btn.clicked.connect(do_select)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(select_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        self.log(f"📋 查询到 {len(packages)} 个第三方应用，请在弹窗中选择")
        dialog.exec_()
    
    def start_uninstall(self):
        package_text = self.uninstall_package_edit.text().strip()
        
        if not package_text:
            QMessageBox.warning(self, "错误", "请输入应用包名")
            return
        
        # 支持多包名（逗号/中文逗号分隔）
        package_names = [p.strip() for p in package_text.replace('，', ',').split(',') if p.strip()]
        
        selected_devices = []
        for row in range(self.uninstall_device_table.rowCount()):
            checkbox = self.uninstall_device_table.item(row, 0)
            if checkbox and checkbox.checkState() == Qt.Checked:
                if row < len(self.devices):
                    selected_devices.append(self.devices[row])
        
        # 如果未勾选但有设备列表，用全部设备
        if not selected_devices and self.devices:
            selected_devices = list(self.devices)
            self.log(f"🗑️ 未勾选设备，自动使用全部 {len(self.devices)} 台设备卸载")
        
        if not selected_devices:
            QMessageBox.warning(self, "错误", "没有可用设备，请先去「设备发现」页扫描设备")
            return
        
        self.uninstall_stats = {"success": 0, "failure": 0, "skipped": 0}
        self._uninstall_device_results = {}  # {device_id: [True/False/"skipped", ...]} 按设备跟踪
        self.uninstall_result_label.setText("✅ 成功：0台 | ❌ 失败：0台 | ⏭️ 跳过：0台")
        max_threads = self.uninstall_threads.value()
        
        self.uninstall_btn.setEnabled(False)
        self.stop_uninstall_btn.setEnabled(True)
        self.uninstall_progress_label.setText("正在卸载...")
        self.uninstall_progress_bar.setValue(0)
        
        if len(package_names) == 1:
            self.log(f"🗑️ 开始卸载 {package_names[0]} 从 {len(selected_devices)} 台设备")
            self.uninstall_selected_count = len(selected_devices)
            # 断开旧线程信号连接
            if hasattr(self, 'uninstall_thread') and self.uninstall_thread:
                try:
                    self.uninstall_thread.uninstall_progress.disconnect()
                    self.uninstall_thread.task_finished.disconnect()
                    self.uninstall_thread.all_finished.disconnect()
                except Exception:
                    pass
            self.uninstall_thread = UninstallThread(selected_devices, package_names[0], max_threads)
            self.uninstall_thread.uninstall_progress.connect(self.on_uninstall_progress)
            self.uninstall_thread.task_finished.connect(self.on_uninstall_task_finished)
            self.uninstall_thread.all_finished.connect(self.on_uninstall_all_finished)
            self.uninstall_thread.start()
        else:
            # 多包名：逐个卸载
            self.log(f"🗑️ 开始卸载 {len(package_names)} 个包名 从 {len(selected_devices)} 台设备")
            self._uninstall_queue = list(package_names)
            self._uninstall_devices = selected_devices
            self._uninstall_max_threads = max_threads
            self._start_next_uninstall()

    def _start_next_uninstall(self):
        """多包名卸载：启动下一个包名的卸载"""
        if not self._uninstall_queue:
            # 全部包名卸载完成
            self.on_uninstall_all_finished()
            return
        
        pkg = self._uninstall_queue.pop(0)
        self.log(f"🗑️ 卸载包名 [{pkg}] (剩余 {len(self._uninstall_queue)} 个)")
        self.uninstall_selected_count = len(self._uninstall_devices)
        self._uninstall_total_packages = len(self._uninstall_queue) + 1  # 当前+剩余
        # 断开旧线程信号连接
        if hasattr(self, 'uninstall_thread') and self.uninstall_thread:
            try:
                self.uninstall_thread.uninstall_progress.disconnect()
                self.uninstall_thread.task_finished.disconnect()
                self.uninstall_thread.all_finished.disconnect()
            except Exception:
                pass
        self.uninstall_thread = UninstallThread(self._uninstall_devices, pkg, self._uninstall_max_threads)
        self.uninstall_thread.uninstall_progress.connect(self.on_uninstall_progress)
        self.uninstall_thread.task_finished.connect(self.on_uninstall_task_finished)
        self.uninstall_thread.all_finished.connect(self._on_single_pkg_uninstall_finished)
        self.uninstall_thread.start()
    
    def _on_single_pkg_uninstall_finished(self):
        """单个包名卸载完成，继续下一个"""
        if not self._uninstall_queue:
            self.on_uninstall_all_finished()
        else:
            self._start_next_uninstall()
    
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
        # 按设备跟踪结果
        if device_id not in self._uninstall_device_results:
            self._uninstall_device_results[device_id] = []
        
        if status == "skipped":
            self._uninstall_device_results[device_id].append("skipped")
        elif success:
            self._uninstall_device_results[device_id].append(True)
        else:
            self._uninstall_device_results[device_id].append(False)
        
        # 实时进度
        done_operations = sum(len(v) for v in self._uninstall_device_results.values())
        if hasattr(self, 'uninstall_selected_count') and self.uninstall_selected_count > 0:
            if hasattr(self, '_uninstall_total_packages') and self._uninstall_total_packages > 1:
                total_expected = self.uninstall_selected_count * self._uninstall_total_packages
            else:
                total_expected = self.uninstall_selected_count
            progress = min(int((done_operations / total_expected) * 100), 100)
            self.uninstall_progress_bar.setValue(progress)
    
    def _compute_uninstall_stats(self):
        """从设备结果计算按设备统计：全成功=1成功，有1个失败=1失败，全跳过=1跳过"""
        stats = {"success": 0, "failure": 0, "skipped": 0}
        for device_id, results in self._uninstall_device_results.items():
            if not results:
                continue
            has_failure = any(r is False for r in results)
            all_skipped = all(r == "skipped" for r in results)
            if has_failure:
                stats["failure"] += 1
            elif all_skipped:
                stats["skipped"] += 1
            else:
                stats["success"] += 1
        return stats
    
    def on_uninstall_all_finished(self):
        self.uninstall_btn.setEnabled(True)
        self.stop_uninstall_btn.setEnabled(False)
        
        # 按设备统计
        stats = self._compute_uninstall_stats()
        s = stats['success']
        f = stats['failure']
        k = stats['skipped']
        total = s + f + k
        
        self.uninstall_result_label.setText(
            f"✅ 成功：{s}台 | "
            f"❌ 失败：{f}台 | "
            f"⏭️ 跳过：{k}台")
        
        if f == 0:
            self.uninstall_progress_label.setText(f"✓ 卸载完成 - 成功 {s}/{total}（跳过 {k}）")
            self.log(f"✓ 卸载完成 - 成功 {s}/{total}（跳过 {k}）")
        else:
            self.uninstall_progress_label.setText(f"卸载完成 - 成功 {s}/{total}（跳过 {k}） | {f} 台失败")
            self.log(f"⚠️ 卸载完成 - 成功 {s}/{total}（跳过 {k}） | {f} 台失败")
        
        package_text = self.uninstall_package_edit.text().strip()
        if package_text:
            package_names = [p.strip() for p in package_text.replace('，', ',').split(',') if p.strip()]
            self.log("🔄 刷新设备版本状态...")
            self.check_installed_versions(package_names)
    
    def export_log(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "导出日志", "adb_manager_log.txt", "Text Files (*.txt)")
        if file_path:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.log_text.toPlainText())
            self.log(f"✓ 日志已导出：{file_path}")


def main():
    import traceback
    def exception_hook(exc_type, exc_value, exc_tb):
        traceback.print_exception(exc_type, exc_value, exc_tb)
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'crash.log'), 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*60}\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except:
            pass
    sys.excepthook = exception_hook
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = ADBBatchManager()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
