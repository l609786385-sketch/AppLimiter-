"""Opt-in native tests. These NEVER target installed user apps or normal data."""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

from applimiter.model import ProcessRef
from applimiter.storage import Store


NATIVE = sys.platform == "win32" and os.environ.get("APPLIMITER_WINDOWS_TESTS") == "1"


@unittest.skipUnless(NATIVE, "需要 Windows 交互桌面及 APPLIMITER_WINDOWS_TESTS=1")
class WindowsNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from applimiter.windows import WindowsAdapter
        cls.adapter = WindowsAdapter()
        cls.temp = tempfile.TemporaryDirectory(prefix="AppLimiterNative-")
        cls.directory = Path(cls.temp.name)
        cls.exe = cls.directory / "AppLimiterTestTarget.exe"
        compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        if not compiler.exists():
            cls.temp.cleanup()
            raise RuntimeError("缺少 .NET Framework C# 编译器，Windows 验证未完成")
        source = Path(__file__).resolve().parents[1] / "scripts/TestApp.cs"
        subprocess.run([str(compiler), "/nologo", "/target:winexe", f"/out:{cls.exe}",
                        "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll", str(source)], check=True)
        cls.path = cls.adapter.validate_selection(str(cls.exe))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.children = []
        self.child_data = {}
        self.store = None
        self.gui_data = None

    def tearDown(self):
        if self.gui_data:
            lock = self.gui_data / "worker.lock"
            if lock.exists():
                import psutil
                try:
                    worker_pid = int(lock.read_text(encoding="utf-8").splitlines()[0])
                    worker = psutil.Process(worker_pid)
                    args = worker.cmdline()
                    if str(self.gui_data) in args and "--worker" in args:
                        worker.terminate()
                        worker.wait(timeout=10)
                except (psutil.Error, ValueError, OSError):
                    pass
        for child in reversed(self.children):
            self.stop_child(child)
        if self.store:
            self.store.close()

    def stop_child(self, child):
        if child.poll() is not None:
            return
        import psutil
        data = self.child_data.get(child.pid)
        if data:
            # Windows venv's Popen PID is a redirector, not the Qt process.
            for process in reversed(psutil.Process(child.pid).children(recursive=True)):
                try:
                    if str(data) in process.cmdline():
                        process.terminate()
                        process.wait(timeout=10)
                except psutil.NoSuchProcess:
                    pass
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)

    def launch_target(self):
        child = subprocess.Popen([str(self.exe)])
        self.children.append(child)
        return child

    def target(self):
        child = self.launch_target()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            snapshot = self.adapter.snapshot({self.path})
            found = next((p for p in snapshot.processes if p.pid == child.pid), None)
            if found:
                return child, found
            time.sleep(.1)
        self.fail("未找到临时测试目标")

    def bring_front(self, pid, child=None):
        user = self.adapter.u
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        user.SetForegroundWindow.restype = wintypes.BOOL
        user.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user.AttachThreadInput.restype = wintypes.BOOL
        user.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        user.SwitchToThisWindow.restype = None
        self.adapter.k.GetCurrentThreadId.restype = wintypes.DWORD
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if child is not None and child.poll() is not None:
                return
            windows = []

            @self.adapter.enum_callback
            def visit(hwnd, _, current_windows=windows):
                p = wintypes.DWORD()
                user.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
                if p.value == pid and user.IsWindowVisible(hwnd):
                    current_windows.append(hwnd)
                return True

            user.EnumWindows(visit, 0)
            for hwnd in windows:
                # Share input with the current foreground thread only during
                # this focus request; always detach and still verify the PID.
                foreground_thread = user.GetWindowThreadProcessId(user.GetForegroundWindow(), None)
                thread = self.adapter.k.GetCurrentThreadId()
                attached = foreground_thread != thread and user.AttachThreadInput(thread, foreground_thread, True)
                try:
                    user.SetForegroundWindow(hwnd)
                    if self.adapter.foreground() != pid:
                        user.SwitchToThisWindow(hwnd, True)
                finally:
                    if attached:
                        user.AttachThreadInput(thread, foreground_thread, False)
            if self.adapter.foreground() == pid:
                return
            time.sleep(.1)
        self.fail(f"Windows 未允许测试窗口成为前台：target={pid}, foreground={self.adapter.foreground()}, "
                  f"windows={windows}。请在解锁的本地桌面运行并点击测试窗口，然后重试")

    def wait_until(self, predicate, timeout=15, focus=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            if focus is not None and focus.poll() is None and self.adapter.foreground() != focus.pid:
                self.bring_front(focus.pid, child=focus)
            time.sleep(.1)
        self.fail("等待原生行为超时")

    def hold_front(self, child, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.assertIsNone(child.poll(), "测试窗口意外退出")
            if self.adapter.foreground() != child.pid:
                self.bring_front(child.pid)
            time.sleep(.05)

    def start_worker(self, data):
        root = Path(__file__).resolve().parents[1]
        entry = ([os.environ["APPLIMITER_TEST_EXE"]] if os.environ.get("APPLIMITER_TEST_EXE")
                 else [sys.executable, str(root / "main.py")])
        monitor = subprocess.Popen([*entry, "--worker", "--no-tray", "--data-dir", str(data)],
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        self.children.append(monitor)
        self.child_data[monitor.pid] = data
        return monitor

    def test_exact_snapshot_foreground_and_handle_termination(self):
        child, ref = self.target()
        self.bring_front(child.pid)
        self.assertEqual(self.adapter.snapshot({self.path}).foreground_pid, child.pid)
        ok, message = self.adapter.terminate(ref, {self.path})
        self.assertTrue(ok, message)
        child.wait(timeout=10)

    def test_creation_identity_and_rule_path_prevent_wrong_kill(self):
        child, ref = self.target()
        stale = ProcessRef(ref.pid, ref.created - 100, ref.path)
        self.assertFalse(self.adapter.terminate(stale, {self.path})[0])
        self.assertIsNone(child.poll())
        self.assertFalse(self.adapter.terminate(ref, set())[0])
        self.assertIsNone(child.poll())

    def test_actual_interpreter_and_venv_launchers_are_protected(self):
        import psutil
        for path in {sys.executable, sys._base_executable, psutil.Process().exe()}:
            with self.assertRaises(ValueError, msg=path):
                self.adapter.allowed_path(path)

    def test_same_filename_in_other_directory_is_not_targeted(self):
        child, ref = self.target()
        other_dir = self.directory / "other-application"
        other_dir.mkdir(exist_ok=True)
        other_exe = other_dir / self.exe.name
        shutil.copy2(self.exe, other_exe)
        other = subprocess.Popen([str(other_exe)])
        self.children.append(other)
        snapshot = self.adapter.snapshot({self.path})
        self.assertNotIn(other.pid, {p.pid for p in snapshot.processes})
        ok, message = self.adapter.terminate(ref, {self.path})
        self.assertTrue(ok, message)
        child.wait(timeout=10)
        self.assertIsNone(other.poll())

    def test_running_app_selection_and_background_pause(self):
        from datetime import datetime
        from PySide6.QtWidgets import QApplication, QDialog
        from applimiter.gui import RuleDialog

        app = QApplication.instance() or QApplication([])
        child, _ = self.target()
        self.bring_front(child.pid)
        self.wait_until(lambda: self.path in {path for _, path in self.adapter.running_apps()})
        data = self.directory / "selection-isolated-data"
        self.store = Store(data / "applimiter.db")
        dialog = RuleDialog(self.store, self.adapter)
        try:
            dialog.add_path(str(self.exe), "原生选择测试")
            dialog.save()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()
        rule = self.store.rules()[0]
        self.assertEqual(rule.paths, (self.path,))
        self.assertEqual(rule.name, "原生选择测试")
        day = datetime.now().date().isoformat()
        self.start_worker(data)
        self.bring_front(child.pid)
        self.wait_until(lambda: self.store.used(rule.id, day) >= 1, focus=child)

        other_dir = self.directory / "pause-control"
        other_dir.mkdir()
        other_exe = other_dir / self.exe.name
        shutil.copy2(self.exe, other_exe)
        other = subprocess.Popen([str(other_exe)])
        self.children.append(other)
        self.bring_front(other.pid)
        self.hold_front(other, .8)  # Allow the first background sample to settle.
        paused = self.store.used(rule.id, day)
        self.hold_front(other, 1.2)
        self.assertEqual(self.adapter.foreground(), other.pid)
        self.assertEqual(self.store.used(rule.id, day), paused)
        self.bring_front(child.pid)
        self.wait_until(lambda: self.store.used(rule.id, day) > paused, focus=child)
        reader = Store(data / "applimiter.db")
        try:
            self.assertEqual(reader.rules()[0], rule)
            self.assertGreater(reader.used(rule.id, day), paused)
        finally:
            reader.close()
        self.assertIsNone(other.poll())

    def test_single_limit_closes_all_matching_instances_keeps_daily(self):
        from datetime import datetime
        data = self.directory / "single-isolated-data"
        self.store = Store(data / "applimiter.db")
        rule = self.store.save_rule("临时测试目标", [self.path], 3, 30)
        child, _ = self.target()
        companion, _ = self.target()
        self.bring_front(child.pid)
        self.start_worker(data)
        self.wait_until(lambda: child.poll() is not None and companion.poll() is not None, focus=child)
        day = datetime.now().date().isoformat()
        self.assertAlmostEqual(self.store.used(rule, day), 3)
        # Let a no-process observation occur before the next explicit session.
        time.sleep(.7)
        again, _ = self.target()
        self.bring_front(again.pid)
        self.wait_until(lambda: again.poll() is not None, focus=again)
        self.assertAlmostEqual(self.store.used(rule, day), 6)

    def test_worker_daily_accounting_relaunch_and_worker_restart(self):
        data = self.directory / "isolated-data"
        self.store = Store(data / "applimiter.db")
        rule = self.store.save_rule("临时测试目标", [self.path], 30, 3)
        child, _ = self.target()
        self.bring_front(child.pid)
        worker = self.start_worker(data)
        self.wait_until(lambda: child.poll() is not None, focus=child)
        from datetime import datetime
        day = datetime.now().date().isoformat()
        self.assertAlmostEqual(self.store.used(rule, day), 3)
        relaunched = self.launch_target()
        self.wait_until(lambda: relaunched.poll() is not None)
        self.stop_child(worker)
        again, _ = self.target()
        self.start_worker(data)
        self.wait_until(lambda: again.poll() is not None)
        self.assertAlmostEqual(self.store.used(rule, day), 3)

    def test_gui_window_starts_with_isolated_data(self):
        root = Path(__file__).resolve().parents[1]
        data = self.directory / "gui-isolated-data"
        self.gui_data = data
        entry = ([os.environ["APPLIMITER_TEST_EXE"]] if os.environ.get("APPLIMITER_TEST_EXE")
                 else [sys.executable, str(root / "main.py")])
        child = subprocess.Popen([*entry, "--data-dir", str(data)], creationflags=subprocess.CREATE_NO_WINDOW)
        self.children.append(child)
        self.child_data[child.pid] = data
        store_path = data / "applimiter.db"
        self.wait_until(store_path.exists)
        self.store = Store(store_path)
        self.wait_until(lambda: self.store.status("heartbeat") is not None)
        self.assertIsNone(child.poll())
        found = []

        @self.adapter.enum_callback
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            self.adapter.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in gui_pids and self.adapter.u.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        def window_visible():
            import psutil
            gui_pids.clear()
            gui_pids.add(child.pid)
            for process in psutil.Process(child.pid).children(recursive=True):
                try:
                    args = process.cmdline()
                    if str(data) in args and "--worker" not in args:
                        gui_pids.add(process.pid)
                except psutil.NoSuchProcess:
                    pass
            found.clear()
            self.adapter.u.EnumWindows(visit, 0)
            return bool(found)

        gui_pids = set()
        self.wait_until(window_visible)


if __name__ == "__main__":
    unittest.main()
