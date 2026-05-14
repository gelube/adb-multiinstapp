# ADB 批量管理工具 - 更新日志

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
