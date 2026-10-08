from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler

from .runtime import data_directory


def main() -> int:
    parser = argparse.ArgumentParser(description="AppLimiter · 应用时间管家")
    parser.add_argument("--worker", action="store_true", help="独立后台监测")
    parser.add_argument("--data-dir", help="数据目录（默认 %%LOCALAPPDATA%%\\AppLimiter）")
    parser.add_argument("--no-tray", action="store_true", help="后台无托盘模式，仅用于自动化测试")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("AppLimiter 的桌面界面与原生监测需要 Windows 10/11。跨平台核心测试：python -m unittest discover -s tests -v", file=sys.stderr)
        return 2
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv[:1])
    app.setApplicationName("AppLimiter")
    app.setOrganizationName("AppLimiter")
    directory = args.data_dir or r"%LOCALAPPDATA%\AppLimiter"
    try:
        directory = data_directory(args.data_dir)
        handler = RotatingFileHandler(directory / ("worker.log" if args.worker else "gui.log"),
                                     maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
        if args.worker:
            from .worker import run_worker
            return run_worker(app, directory, args.no_tray)
        from .gui import run_gui
        return run_gui(app, directory)
    except Exception as exc:
        logging.exception("Startup failed")
        if not (args.worker and args.no_tray):
            QMessageBox.critical(None, "AppLimiter 启动失败", f"{exc}\n数据及日志目录：{directory}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
