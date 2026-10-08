# AppLimiter 0.1.0 本机 Windows 验收记录

日期：2026-10-08（中国标准时间）。平台：Windows 11 x64，版本 10.0.26200。Git 2.53.0.windows.3；项目虚拟环境 Python 3.12.14 x64；PySide6 6.8.3、psutil 7.0.0、PyInstaller 6.12.0。

系统默认 Python 为 3.7.7，Python Launcher 没有注册的 Python 3.12。本次使用本机已有的 Codex Python 3.12 创建项目 `.venv`，没有升级系统 Python、改 PATH 或安装系统服务。依赖全部安装到该独立虚拟环境，`pip check` 通过。精确的已安装版本保存在 `verification-artifacts/installed-dependencies.txt`。

## 最终结果

| 执行 | 结果 |
| --- | --- |
| `python scripts/verify_windows.py` | 54 项全部通过，0 失败、0 跳过 |
| `scripts/build_windows.ps1 -SkipInstall` 构建前验证 | 54 项全部通过，0 失败、0 跳过 |
| PyInstaller 原生 x64 目录包构建 | 成功 |
| `python scripts/verify_windows.py --exe dist/AppLimiter/AppLimiter.exe` | 54 项全部通过，0 失败、0 跳过 |
| 真实 Qt 窗口截图检查 | 中文主窗口、规则编辑器正常，后台心跳正常，系统托盘 API 可用 |
| Python 语法、PowerShell 脚本解析、`git diff --check` | 通过 |

54 项包括：计时/SQLite 核心 32 项、Qt 数据联动 3 项、模拟终止安全边界 7 项、后台事务集成 4 项、Windows 原生 8 项。打包验收中，原生后台和主窗口使用生成的 EXE；纯核心、模拟和控件测试仍由项目 Python 执行。此前 Linux 记录为 46 项通过、6 项跳过，已由本轮 Windows 记录更新。

## 已通过 Windows 实测

- 完整 EXE 路径识别、真实前台窗口 PID 查询、有窗口应用列表，以及真实适配器校验后在规则编辑器保存 EXE。
- 真实前台使用累计；切到另一个专用窗口暂停；切回来继续；规则与用量通过另一 SQLite 连接重新读取一致。
- 单次上限使用 3 秒的加速测试，达到上限后关闭同路径的两个测试实例；再次启动开始新单次，累计从 3 秒增加到 6 秒。
- 每日上限使用 3 秒的加速测试，耗尽后结束目标；再次启动即被结束；结束并重新启动独立后台后仍然拦截，累计保留为 3 秒。
- 相同文件名、不同目录的测试 EXE 保持运行；创建时间伪造和规则路径移除均拒绝终止；实际终止使用已经复核的同一个 Windows 句柄。
- 源码模式下，虚拟环境启动器、底层 Python 解释器及当前实际解释器镜像都被拒绝加入限制。
- 源码和 EXE 均能显示真实主窗口并启动独立后台，SQLite 中出现后台心跳。截图检查时使用空规则的隔离数据库；没有限制用户已有应用。

跨午夜、休眠间隔、时钟跳变、锁屏无前台、暂停/编辑/删除、提醒去重、PID 复用及事务回滚等核心算法测试通过；这些不等于真实系统午夜、锁屏、休眠或重启已经实测。

## 修复与脚本审查

源码模式原先只保护 `.venv/Scripts/python*.exe`。Windows 虚拟环境会启动底层解释器，进程镜像路径可能位于公共运行时目录；现同时保护这两个目录内的 Python/Pythonw，避免将公共解释器加入限制后影响其他 Python 应用。新增原生回归测试。

原生测试原先将 `Popen.pid` 当成窗口 PID；Windows venv 的实际窗口位于启动器子进程，现按本次隔离数据参数识别实际 GUI 进程。清理和后台重启也覆盖本次创建的解释器子进程。测试仅对专用窗口处理前台切换，并处理窗口在切换期间被正常结束的竞态，仍要求实际前台查询和累计结果正确。

`run_windows.bat` 已审查：切到项目目录、创建项目虚拟环境、安装项目运行依赖、使用 pythonw 启动；路径均带引号，没有全局安装、注册表修改、管理员提权或结束其他应用的命令。依赖安装会联网；没有 `.venv` 时依赖已注册的 `py -3.12`，本机已预先创建好 `.venv`。本轮真实界面使用 Python 入口启动，未双击该 BAT。

`build_windows.ps1` 已审查并实际成功执行：依赖写入项目虚拟环境；源码测试失败/跳过则停止；使用 PyInstaller onedir；再验证冻结后的 EXE；输出完整目录 ZIP。`--clean/--noconfirm` 可覆盖旧构建目录，脚本只删除其固定的输出 ZIP，没有通配进程关闭或系统设置写入。此轮使用 `-SkipInstall`，避免重复联网安装。

验证脚本的源码指纹排除本轮本地 `verification-artifacts`，避免诊断脚本、截图等影响源码凭据。运行脚本及构建脚本无需重写，应用功能没有新增。

## 产物与运行

EXE 实际路径：`D:\codex project\AppLimiter-\dist\AppLimiter\AppLimiter.exe`。

完整分发包：`D:\codex project\AppLimiter-\dist\AppLimiter-Windows-x64.zip`。

打开上述 `dist\AppLimiter` 文件夹，双击 `AppLimiter.exe` 即可。无需 Python；必须保留 `_internal` 和整个目录。默认数据写入 `%LOCALAPPDATA%\AppLimiter`。本次测试使用隔离数据目录，没有写入正常使用数据或变更自启动注册表。

源码原生凭据：`.windows-verification.json`；EXE 凭据：`.windows-package-verification.json`，并复制到分发目录 `Windows-verification.json`。源代码测试全文见 `TEST_RESULTS.txt`，完整构建及 EXE 测试日志见 `verification-artifacts/build-results.txt`；界面截图见 `verification-artifacts/main-window.png` 与 `rule-dialog.png`。

## 仍需人工验证

- Windows 10、另一台无 Python 的 Windows x64 电脑、用户实际播放器及其辅助进程。
- 真实注销/登录、开机自启动勾选/取消、重启电脑后的恢复；此轮未改注册表、未重启或锁定电脑。
- 真实锁屏、UAC、休眠恢复、跨系统午夜；提升权限/受保护目标及损坏/只读数据库的原生行为。
- 托盘菜单、双击恢复、通知实际送达，以及 100%/150%/200% DPI 全套调整。当前桌面的中文布局已截图检查，尚未主动切换 DPI。
- SmartScreen/杀毒兼容性与代码签名。本包未签名。

没有提交或推送 GitHub；代码变更保留在本地供确认。
