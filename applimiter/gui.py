from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QLockFile, QSettings, Qt, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDateEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .appearance import STYLE, app_icon, duration
from .model import Rule
from .runtime import autostart_enabled, launch, set_autostart
from .storage import Store
from .windows import WindowsAdapter


class RunningDialog(QDialog):
    def __init__(self, adapter: WindowsAdapter, parent=None):
        super().__init__(parent)
        self.adapter = adapter
        self.setWindowTitle("选择正在运行的应用")
        self.resize(650, 400)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("显示当前用户会话中有窗口的应用；系统程序及 AppLimiter 已过滤。"))
        self.items = QListWidget()
        layout.addWidget(self.items)
        refresh = QPushButton("刷新列表")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("选择")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.choose)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.items.itemDoubleClicked.connect(lambda _: self.choose())
        self.selected: tuple[str, str] | None = None
        self.refresh()

    def refresh(self):
        self.items.clear()
        for title, path in self.adapter.running_apps():
            item = QListWidgetItem(f"{title}\n{path}")
            item.setData(Qt.ItemDataRole.UserRole, (title, path))
            self.items.addItem(item)

    def choose(self):
        if self.items.currentItem():
            self.selected = self.items.currentItem().data(Qt.ItemDataRole.UserRole)
            self.accept()


class RuleDialog(QDialog):
    def __init__(self, store: Store, adapter: WindowsAdapter, rule: Rule | None = None, parent=None):
        super().__init__(parent)
        self.store, self.adapter, self.rule = store, adapter, rule
        self.setWindowTitle("编辑应用规则" if rule else "添加应用")
        self.resize(650, 480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(rule.name if rule else "")
        self.name.setMaxLength(80)
        form.addRow("应用名称", self.name)
        self.single = QSpinBox()
        self.daily = QSpinBox()
        for spin, initial in ((self.single, rule.single_seconds // 60 if rule else 30),
                              (self.daily, rule.daily_seconds // 60 if rule else 60)):
            spin.setRange(1, 1440)
            spin.setSuffix(" 分钟")
            spin.setValue(max(1, initial))
        form.addRow("单次使用上限", self.single)
        form.addRow("每日累计上限", self.daily)
        layout.addLayout(form)
        layout.addWidget(QLabel("精确匹配以下 EXE；如应用有独立辅助进程，可添加到同一规则。"))
        self.paths = QListWidget()
        if rule:
            self.paths.addItems(rule.paths)
        layout.addWidget(self.paths)
        row = QHBoxLayout()
        for text, handler in (("选择 EXE", self.file), ("从运行列表选择", self.running), ("移除选中路径", self.remove_path)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        note = QLabel("仅前台计时，切到后台暂停；关闭所有匹配进程后重新启动开始新的一次。\n"
                      "到达限制会强制结束匹配进程，请先保存内容。当天累计不会因重开应用而清零。")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存规则")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_path(self, path, title=""):
        try:
            path = self.adapter.validate_selection(path)
            if not any(self.paths.item(i).text() == path for i in range(self.paths.count())):
                self.paths.addItem(path)
            if not self.name.text():
                self.name.setText(title or Path(path).stem)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "无法添加", str(exc))

    def file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择应用 EXE", "", "Windows 应用 (*.exe)")
        if path:
            self.add_path(path)

    def running(self):
        dialog = RunningDialog(self.adapter, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected:
            title, path = dialog.selected
            self.add_path(path, title)

    def remove_path(self):
        row = self.paths.currentRow()
        if row >= 0:
            self.paths.takeItem(row)

    def save(self):
        try:
            paths = [self.paths.item(i).text() for i in range(self.paths.count())]
            # Existing missing/uninstalled paths can remain; path safety still applies.
            for path in paths:
                self.adapter.allowed_path(path)
            self.store.save_rule(self.name.text(), paths, self.single.value() * 60,
                                 self.daily.value() * 60, self.rule.id if self.rule else None)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.accept()


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


class MainWindow(QMainWindow):
    def __init__(self, data_dir: Path):
        super().__init__()
        self.data_dir = data_dir
        self.store = Store(data_dir / "applimiter.db")
        self.adapter = WindowsAdapter()
        self.settings = QSettings(str(data_dir / "window.ini"), QSettings.Format.IniFormat)
        self.setWindowTitle("AppLimiter · 应用时间管家")
        self.setWindowIcon(app_icon())
        self.resize(1150, 680)
        self.setMinimumSize(620, 400)
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel("应用时间管家")
        title.setObjectName("title")
        layout.addWidget(title)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        layout.addWidget(self.summary)
        self.health = QLabel("正在启动后台监测…")
        layout.addWidget(self.health)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        home = QWidget()
        home_layout = QVBoxLayout(home)
        row = QHBoxLayout()
        for text, handler in (("＋ 添加应用", self.add), ("编辑限制", self.edit),
                              ("启用 / 暂停", self.toggle), ("删除规则", self.delete)):
            button = QPushButton(text)
            if handler == self.add:
                button.setObjectName("primary")
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch()
        home_layout.addLayout(row)
        self.table = table(["应用", "今日用量 / 上限", "今日剩余", "本次用量 / 上限", "本次剩余", "今日进度", "状态"])
        self.table.itemDoubleClicked.connect(lambda _: self.edit())
        home_layout.addWidget(self.table)
        self.empty = QLabel("还没有管理的应用。点击“添加应用”，设置单次和每日使用上限。")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        home_layout.addWidget(self.empty)
        self.tabs.addTab(home, "应用管理")
        history = QWidget()
        history_layout = QVBoxLayout(history)
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("查看日期"))
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.dateChanged.connect(self.refresh_history)
        date_row.addWidget(self.date)
        date_row.addStretch()
        history_layout.addLayout(date_row)
        self.history = table(["应用", "日期", "实际前台用量"])
        history_layout.addWidget(self.history)
        self.tabs.addTab(history, "每日使用记录")
        self.events = table(["时间", "类型", "提醒与异常"])
        self.tabs.addTab(self.events, "监测日志")
        bottom = QHBoxLayout()
        self.autostart = QCheckBox("登录 Windows 后自动启动后台监测")
        self.autostart.setChecked(autostart_enabled())
        self.autostart.toggled.connect(self.change_autostart)
        bottom.addWidget(self.autostart)
        bottom.addStretch()
        restart = QPushButton("启动后台")
        restart.clicked.connect(lambda: launch(self.data_dir, worker=True))
        bottom.addWidget(restart)
        hide = QPushButton("收起到托盘")
        hide.clicked.connect(self.hide_to_tray)
        bottom.addWidget(hide)
        layout.addLayout(bottom)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.last_event = -1
        self.refresh()

    def selected(self) -> Rule | None:
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 0) is None:
            return None
        rule_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        return next((r for r in self.store.rules() if r.id == rule_id), None)

    def add(self):
        RuleDialog(self.store, self.adapter, parent=self).exec()
        self.refresh()

    def edit(self):
        rule = self.selected()
        if rule:
            RuleDialog(self.store, self.adapter, rule, self).exec()
            self.refresh()

    def toggle(self):
        rule = self.selected()
        if rule:
            self.store.enable(rule.id, not rule.enabled)
            self.refresh()

    def delete(self):
        rule = self.selected()
        if rule and QMessageBox.question(self, "删除规则", f"删除“{rule.name}”的限制规则？历史记录仍会保留。",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.store.delete(rule.id)
            self.refresh()

    def change_autostart(self, checked):
        try:
            set_autostart(checked, self.data_dir)
        except OSError as exc:
            self.autostart.blockSignals(True)
            self.autostart.setChecked(not checked)
            self.autostart.blockSignals(False)
            QMessageBox.warning(self, "自启动设置失败", str(exc))

    def hide_to_tray(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
        else:
            self.showMinimized()

    def show_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event):
        from PySide6.QtCore import QEvent
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized() and QSystemTrayIcon.isSystemTrayAvailable():
            QTimer.singleShot(0, self.hide)

    def refresh(self):
        try:
            rules = self.store.rules()
            selected = self.selected()
            today = datetime.now().date().isoformat()
            total = sum(self.store.used(r.id, today) for r in rules)
            self.summary.setText(f"今日 {today}  ·  已管理 {len(rules)} 个应用  ·  前台累计 {duration(total)}")
            beat = self.store.status("heartbeat")
            stale = not beat or abs((datetime.now() - datetime.fromisoformat(beat)).total_seconds()) > 5
            self.health.setText("⚠ 后台未响应，计时与拦截可能已停止。请点击“启动后台”或查看日志。" if stale else
                                "● 后台监测中 · 仅前台计时 · 关闭窗口后继续监测")
            self.health.setStyleSheet("color: #b45309" if stale else "color: #16815a")
            self.empty.setVisible(not rules)
            self.table.setRowCount(len(rules))
            for row, rule in enumerate(rules):
                used = self.store.used(rule.id, today)
                single = self.store.session(rule.id).seconds
                state = "已暂停" if not rule.enabled else self.store.status(f"rule:{rule.id}") or "等待监测"
                values = [rule.name, f"{duration(used)} / {duration(rule.daily_seconds)}",
                          duration(rule.daily_seconds - used), f"{duration(single)} / {duration(rule.single_seconds)}",
                          duration(rule.single_seconds - single), "", state]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, rule.id)
                        item.setToolTip("\n".join(rule.paths))
                    self.table.setItem(row, col, item)
                progress = QProgressBar()
                progress.setRange(0, 1000)
                progress.setValue(min(1000, int(used / rule.daily_seconds * 1000)))
                progress.setFormat(f"{min(100, int(used / rule.daily_seconds * 100))}%")
                self.table.setCellWidget(row, 5, progress)
                if selected and selected.id == rule.id:
                    self.table.selectRow(row)
            self.refresh_history()
            latest = self.store.latest_event_id()
            if latest != self.last_event:
                rows = self.store.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 200").fetchall()
                self.events.setRowCount(len(rows))
                labels = {"warning": "提醒", "limit": "超限关闭", "error": "异常"}
                for row, event in enumerate(rows):
                    for col, value in enumerate((event["at"][:19].replace("T", " "), labels.get(event["kind"], event["kind"]), event["message"])):
                        self.events.setItem(row, col, QTableWidgetItem(value))
                self.last_event = latest
        except Exception as exc:
            self.health.setText(f"读取状态失败：{exc}")

    def refresh_history(self, *_):
        day = self.date.date().toString("yyyy-MM-dd")
        rows = self.store.records(day)
        self.history.setRowCount(len(rows))
        for row, entry in enumerate(rows):
            for col, value in enumerate((entry["name"] + ("（已删除）" if entry["deleted"] else ""), day, duration(entry["seconds"]))):
                self.history.setItem(row, col, QTableWidgetItem(value))

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.timer.stop()
        self.store.close()
        event.accept()


def run_gui(app: QApplication, data_dir: Path) -> int:
    channel = "AppLimiter-" + hashlib.sha256(str(data_dir).encode()).hexdigest()[:20]
    client = QLocalSocket()
    client.connectToServer(channel)
    if client.waitForConnected(400):
        client.write(b"show")
        client.waitForBytesWritten(400)
        client.disconnectFromServer()
        return 0
    lock = QLockFile(str(data_dir / "gui.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        return 0
    QLocalServer.removeServer(channel)
    server = QLocalServer()
    if not server.listen(channel):
        lock.unlock()
        raise RuntimeError(f"无法创建窗口通信端点：{server.errorString()}")
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(True)
    window = MainWindow(data_dir)

    def connection():
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            window.show_front()
            socket.disconnectFromServer()
            socket.deleteLater()

    server.newConnection.connect(connection)
    launch(data_dir, worker=True)
    window.show()
    try:
        return app.exec()
    finally:
        server.close()
        lock.unlock()
