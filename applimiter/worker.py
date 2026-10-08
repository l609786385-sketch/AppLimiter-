from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .appearance import app_icon
from .engine import Engine
from .runtime import launch
from .storage import Store
from .windows import WindowsAdapter


class Worker:
    def __init__(self, app: QApplication, data_dir: Path, no_tray: bool = False):
        self.app, self.data_dir = app, data_dir
        self.store = Store(data_dir / "applimiter.db")
        self.adapter = WindowsAdapter()
        self.engine = Engine(self.store)
        self.last_event = self.store.latest_event_id()
        self.reported: dict[tuple, float] = {}
        self.tray = None
        if not no_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(app_icon())
            self.tray.setToolTip("AppLimiter · 后台监测中")
            menu = QMenu()
            menu.addAction("打开应用时间管家", lambda: launch(data_dir))
            menu.addSeparator()
            menu.addAction("退出后台监测…", self.quit_monitor)
            self.tray.setContextMenu(menu)
            self.menu = menu
            self.tray.activated.connect(self.activate)
            self.tray.show()
        self.timer = QTimer()
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        app.aboutToQuit.connect(self.close)
        self.tick()

    def activate(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            launch(self.data_dir)

    def quit_monitor(self):
        if QMessageBox.question(None, "退出后台监测", "退出后不再计时或拦截。确定退出？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.app.quit()

    def report(self, rule_id, kind, message, token):
        now = time.monotonic()
        key = (rule_id, kind, token)
        if now - self.reported.get(key, -1e9) >= 30:
            self.store.event(datetime.now().isoformat(), rule_id, kind, message)
            self.reported[key] = now

    def tick(self):
        try:
            rules = self.store.rules()
            snapshot = self.adapter.snapshot({p for r in rules for p in r.paths})
            actions = self.engine.tick(time.monotonic(), datetime.now(), snapshot)
            for action in actions:
                # Re-read after commit: a rule may have been paused/edited/deleted
                # by the separate GUI before its termination action executes.
                current = next((r for r in self.store.rules() if r.id == action.rule_id), None)
                if not current or not current.enabled:
                    continue
                exhausted = (self.store.used(current.id, datetime.now().date().isoformat()) >= current.daily_seconds
                             if action.reason == "daily" else self.store.session(current.id).seconds >= current.single_seconds)
                if not exhausted:
                    continue
                for target in action.targets:
                    ok, message = self.adapter.terminate(target, set(current.paths))
                    label = "今日额度已用完" if action.reason == "daily" else "单次时长已用完"
                    self.report(action.rule_id, "limit" if ok else "error",
                                f"{action.name}：{label}；{message}", target.token)
            messages = []
            for event in self.store.events_after(self.last_event):
                self.last_event = event["id"]
                if self.tray and event["kind"] in {"warning", "limit", "error"}:
                    messages.append(event["message"])
            if self.tray and messages:
                self.tray.showMessage("AppLimiter 应用时间管家", "\n".join(messages),
                                      QSystemTrayIcon.MessageIcon.Warning, 8000)
            # Remove stale retry dedup keys in long-running workers.
            if len(self.reported) > 1000:
                cutoff = time.monotonic() - 120
                self.reported = {k: v for k, v in self.reported.items() if v > cutoff}
            if self.tray:
                self.tray.setToolTip("AppLimiter · 后台监测中")
        except Exception as exc:
            logging.exception("Monitor tick failed; no unverified process is terminated")
            if self.tray:
                self.tray.setToolTip("AppLimiter · 监测异常，请打开查看日志")
            try:
                self.report(None, "error", f"监测异常：{exc}", "worker")
            except Exception:
                logging.exception("Cannot persist monitor error")

    def close(self):
        self.timer.stop()
        if self.tray:
            self.tray.hide()
        self.store.close()


def run_worker(app: QApplication, data_dir: Path, no_tray: bool = False) -> int:
    lock = QLockFile(str(data_dir / "worker.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        return 0
    app.setQuitOnLastWindowClosed(False)
    # Keep the Python controller alive for the entire Qt event loop.
    _worker = Worker(app, data_dir, no_tray)
    try:
        return app.exec()
    finally:
        lock.unlock()
