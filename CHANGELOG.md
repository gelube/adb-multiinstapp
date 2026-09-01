# ADB 批量管理工具 - 更新日志

## v3.4.1 (2026-09-01) - 代码审查修复

### 🔴 严重修复

- **修复"范围过大"提示不可达**: start_scan 中 None 判断提前，超 65536 地址时弹正确提示
- **删除 debug_install.log 调试残留**: 5 处硬编码写日志已移除（只读目录下会炸回调槽）
- **修复 crash.log 路径**: 打包后写到 exe 所在目录而非 PyInstaller 临时目录
- **修复重试线程信号断连顺序**: start_retry 先断旧线程再建新线程，避免回调叠加
- **修复 install() 潜在死锁**: stdout 改由后台线程排空，防止管道写满阻塞子进程；读取循环加 sleep 消除忙等
- **修复"停止"不生效**: 安装/重试循环检查 stop_flag；多包名卸载停止时清空队列

### 🟡 Bug 修复

- **修复安装后版本列不刷新**: device_info 补上 package 键
- **IP 末段范围校验 0-255**: 100-999 不再生成非法 IP，倒序范围自动翻转
- **修复扫描 socket 泄漏**: 探测 socket 改用 try/finally 关闭
- **修复设备详情对话框线程隐患**: 关闭时停止加载线程并断开信号

### 🧹 清理

- 版本号统一为 APP_VERSION 常量（原 docstring v3.0 / 标题 v3.4 不一致）
- 线程信号断开样板抽为 _disconnect_thread_signals()
- 新增 tests/test_parsers.py（21 个用例：IP/端口解析、AXML 解析）
- 清理本地 check*.py / *.bak / 临时日志

## v3.4 (2026-08) - 按设备策略 + 稳定性

- 修复信号重复连接导致卸载死循环
- 每行设备策略下拉框生效（支持单台设备独立策略）
- 修复补扫阶段闪退
- 安装/卸载计数改为按设备
- 版本信息不再被重置为"待检测"
- 去掉补扫逻辑，加设备ID去重
- IP输入改为范围格式（如 192.168.1.100-200）
- 拖放APK后自动保存配置
- CSV导出apk_name不再为空
- 强制覆盖改为保留数据安装
- 全局crash handler写crash.log

## v3.0 - 多APK与界面增强

- 多APK批量安装、设备详情面板、多端口扫描、搜索过滤、CSV导出、配置持久化、断线重连


## v2.2 (2026-05-14) - 代码审计修复 + 性能优化

### 🔴 严重修复

- **删除重复代码**: 主文件从 4466 行缩减至 1828 行，3 份重复的类定义只保留最后一份
- **修复 `stop_uninstall` 丢失线程检查**: 点击停止按钮不会真正停止卸载线程
- **修复 README.md 未解决的 git 合并冲突标记**

### 🟡 Bug 修复

- **修复 `clear_saved_devices` 路径不一致**: 打包 exe 后删除设备列表会删错位置
- **修复卸载操作阻塞 UI**: 改用异步 `UninstallThread` 替代主线程阻塞的 `ThreadPoolExecutor`
- **删除 `_parse_axml` 死代码**: 被 `_parse_axml_v2` 替代但未清理

### ⚡ 性能优化

- **消除 UI 线程 ADB 调用**: `update_installed_version` 不再在主线程查询 versionCode，改由后台线程 `CheckVersionThread` 一并返回
- **优化扫描重试逻辑**: 先 socket 探测端口，再 adb connect，失败最多重试 1 次（原 3 次），减少 50%+ 网络请求
- **精简日志输出**: 移除冗余调试日志，减少日志窗口信息量

### 🧹 清理

- **删除多余依赖**: `requirements.txt` 移除未使用的 `pure-python-adb`
- **修复 `release/启动.bat`**: 引用名从 `adb_manager.exe` 改为 `adb-multiinstapp.exe`
- **删除临时生成文件**: 移除 `publish*.py`、`generate_*.py`、公众号文章 HTML 等

---

## v2.1 (2026-03-21) - APK 版本解析增强

### 🎯 问题修复

修复了选择 APK 文件后无法获取版本号的问题。

### ✨ 改进内容

**纯 Python APK 解析方案** - 不依赖任何第三方工具：

- 使用 Python 内置的 `zipfile` 和 `struct` 模块
- 直接解析 AXML (Android XML) 二进制格式
- 无需安装 Android SDK Build-Tools
- 零额外依赖，方便打包成 exe

---

## v2.0 (2026-03-20)

- ✅ 新增自定义 ADB 端口支持
- ✅ 新增 APK 版本信息读取
- ✅ 新增已安装版本检测
- ✅ 新增智能版本对比策略
- ✅ 新增失败重试功能
- ✅ 增强日志显示（深色主题）
- ✅ 优化界面布局和样式

## v1.0 (2026-03-20)

- ✅ 初始版本发布
