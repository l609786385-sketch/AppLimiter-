# AppLimiter 0.1.0 验证记录

验证日期：2026-10-08。执行环境：Linux x86_64、Python 3.12.14、PySide6 6.8.3、psutil 7.0.0。

**Windows 实机验证：未执行。Windows EXE 构建：未执行。没有附带可用 EXE，也不宣称原生 Windows 功能测试成功。**

## 已执行

```text
python -m unittest discover -s tests -v
Ran 52 tests
OK (skipped=6)
```

实际使用项目依赖的虚拟环境运行。46 项通过，6 项 Windows 原生测试明确跳过。

| 类别 | 通过 | 说明 |
| --- | ---: | --- |
| 计时与持久化核心 | 32 | 前台累计、后台暂停、单次和每日上限、重开、后台重建、数据库重开、多应用/多进程、辅助 EXE、PID 复用、跨午夜、休眠/时钟跳变、暂停编辑删除、提醒去重、事务回滚及双连接 |
| Qt 界面与数据库联动 | 3 | Linux offscreen：保存规则、显示用量及历史、选中规则后暂停；WindowsAdapter/自启动查询使用 mock |
| 进程结束安全边界 | 7 | Win32 与 psutil 使用 mock：同句柄结束、创建时间变化、路径变化、关键进程、其他用户/会话、规则路径移除、系统目录及自身拒绝 |
| 独立后台与 SQLite 集成 | 4 | OS 采样及终止使用 mock：提交后结束、动作前暂停/删除、终止失败不退额度并写日志 |
| Windows 原生 | 0 | 6 项全部跳过：真实前台与终止、安全拒绝、同名不同目录隔离、单次超限/多实例关闭/每日保留、独立后台每日计时/再次启动/后台重启、主窗口与后台启动 |

另外已进行 Python 源码语法编译检查及项目配置下的 Ruff 静态检查。主入口在 Linux 明确返回“需要 Windows”的错误，不假装提供可工作的 Linux 原生监测；Windows 验证脚本在 Linux 返回错误码 2，拒绝生成成功凭据。

## 尚未验证

- `GetForegroundWindow`、输入桌面查询、Windows 会话与所有者过滤、`QueryFullProcessImageNameW` / `GetProcessTimes` / `IsProcessCritical` / `TerminateProcess` 的真实行为。
- Windows 中文字体、可调整窗口、DPI、托盘操作、系统通知，以及登录自启动注册表的真实行为。
- 真实注销/重启、锁屏、UAC 与休眠恢复场景；每日午夜算法已测试，系统真实午夜场景尚未执行。
- PyInstaller Windows 构建、打包后运行、SmartScreen/杀毒软件兼容性、真实播放器的进程结构。
- Windows 10 和 Windows 11 的分别验收。

Windows 验证及打包脚本已提供。脚本拒绝在非 Windows 上生成验证凭据；测试失败或跳过会中止正式打包流程。测试生成的 JSON 凭据与本记录不是同一件事，本次未生成任何 Windows 成功凭据。
