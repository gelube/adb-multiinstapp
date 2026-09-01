# -*- coding: utf-8 -*-
"""纯逻辑函数的单元测试：IP/端口解析、AXML 解析。不依赖 ADB 设备。"""
import importlib.util
import os
import sys
import struct
import zipfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "adb_multiinstapp", os.path.join(_ROOT, "adb-multiinstapp.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
parse_ports = _mod.parse_ports
parse_ip_ranges = _mod.parse_ip_ranges
ADBWorker = _mod.ADBWorker


class TestParsePorts:
    def test_single(self):
        assert parse_ports("5555") == [5555]

    def test_comma(self):
        assert parse_ports("5555,5557") == [5555, 5557]

    def test_range(self):
        assert parse_ports("5555-5558") == [5555, 5556, 5557, 5558]

    def test_mixed(self):
        assert parse_ports("5555,5557-5560") == [5555, 5557, 5558, 5559, 5560]

    def test_dedup_and_sort(self):
        assert parse_ports("5557,5555,5555") == [5555, 5557]

    def test_invalid_ignored(self):
        assert parse_ports("abc,5555,,") == [5555]

    def test_out_of_range_ignored(self):
        assert parse_ports("0,65536,5555") == [5555]

    def test_empty(self):
        assert parse_ports("") == []


class TestParseIpRanges:
    def test_single_ip(self):
        assert parse_ip_ranges("192.168.1.100") == ["192.168.1.100"]

    def test_last_octet_range(self):
        assert parse_ip_ranges("192.168.1.100-102") == [
            "192.168.1.100", "192.168.1.101", "192.168.1.102"]

    def test_last_octet_reversed_flips(self):
        assert parse_ip_ranges("192.168.1.102-100") == [
            "192.168.1.100", "192.168.1.101", "192.168.1.102"]

    def test_last_octet_above_255_rejected(self):
        # 修复：末段 >255 不再生成非法 IP
        assert parse_ip_ranges("192.168.1.100-999") == []

    def test_full_range(self):
        ips = parse_ip_ranges("192.168.1.1-192.168.1.3")
        assert ips == ["192.168.1.1", "192.168.1.2", "192.168.1.3"]

    def test_comma_multi(self):
        ips = parse_ip_ranges("192.168.1.100,192.168.2.50-51")
        assert ips == ["192.168.1.100", "192.168.2.50", "192.168.2.51"]

    def test_dedup(self):
        assert parse_ip_ranges("192.168.1.100,192.168.1.100") == ["192.168.1.100"]

    def test_invalid(self):
        assert parse_ip_ranges("abc") == []
        assert parse_ip_ranges("") == []
        assert parse_ip_ranges("999.999.999.999") == []

    def test_too_large_returns_none(self):
        assert parse_ip_ranges("1.0.0.0-2.0.0.0") is None

    def test_boundary_255_ok(self):
        ips = parse_ip_ranges("192.168.1.254-255")
        assert ips == ["192.168.1.254", "192.168.1.255"]


REAL_APKS = [
    r"Z:\org.zwanoo.android.speedtest.apk",
    r"Z:\tronlink-pro-5-11-6.apk",
    r"Z:\miniapp_debug_v1.0-debug_20260219_1627_arm64-v8a_debug.apk",
]


class TestApkVersionParsing:
    def test_plain_xml(self):
        xml = (b'<?xml version="1.0"?><manifest xmlns:android="http://schemas.android.com/apk/res/android"'
               b' package="com.foo.bar" android:versionCode="15" android:versionName="1.2.3">')
        worker = ADBWorker(adb_path="adb")
        code, name, pkg = worker._parse_axml_v2(xml)
        assert code == 15
        assert name == "1.2.3"
        assert pkg == "com.foo.bar"

    def test_real_apks(self):
        """二进制 AXML 路径用真实 APK 验证；本机没有这些文件则跳过。"""
        existing = [p for p in REAL_APKS if os.path.exists(p)]
        if not existing:
            import pytest
            pytest.skip("本机无真实 APK 可用")
        worker = ADBWorker(adb_path="adb")
        for apk in existing:
            code, name, pkg = worker.get_apk_version(apk)
            assert pkg and "." in pkg, f"{apk}: 包名解析失败"
            assert code and int(code) > 0, f"{apk}: versionCode 解析失败"

    def test_truncated_input(self):
        worker = ADBWorker(adb_path="adb")
        assert worker._parse_axml_v2(b"\x03\x00") == (None, None, None)
        assert worker._parse_axml_v2(b"") == (None, None, None)
