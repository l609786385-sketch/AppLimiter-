from __future__ import annotations

import ctypes
import ntpath
import os
import sys
from ctypes import wintypes
from pathlib import Path

import psutil

from .model import ProcessRef, Snapshot, canonical_path


class WindowsAdapter:
    """Exact executable matching, same user/session, handle-based termination."""

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Windows 原生监测仅支持 Windows 10/11")
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        self._bind()
        self.pid = os.getpid()
        self.username = psutil.Process().username().casefold()
        self.session = self.session_id(self.pid)
        self.windows_dir = canonical_path(str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "placeholder.exe"))
        self.windows_dir = ntpath.dirname(self.windows_dir)
        self.self_exe = canonical_path(sys.executable)
        self.protected_exes = {self.self_exe}
        if not getattr(sys, "frozen", False):
            # Windows venv executables redirect to a base interpreter. psutil
            # reports that real image, which may also be used by other apps.
            interpreters = {self.self_exe, canonical_path(psutil.Process().exe()),
                            canonical_path(getattr(sys, "_base_executable", sys.executable))}
            self.protected_exes.update(interpreters)
            for interpreter in interpreters:
                parent = ntpath.dirname(interpreter)
                self.protected_exes.update({ntpath.join(parent, "python.exe"), ntpath.join(parent, "pythonw.exe")})

    def _bind(self):
        k, u = self.k, self.u
        k.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        k.ProcessIdToSessionId.restype = wintypes.BOOL
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k.GetProcessTimes.restype = wintypes.BOOL
        k.IsProcessCritical.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        k.IsProcessCritical.restype = wintypes.BOOL
        k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.TerminateProcess.restype = wintypes.BOOL
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        u.OpenInputDesktop.restype = wintypes.HANDLE
        u.CloseDesktop.argtypes = [wintypes.HANDLE]
        u.CloseDesktop.restype = wintypes.BOOL
        u.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                                               wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        u.GetUserObjectInformationW.restype = wintypes.BOOL
        self.enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = [self.enum_callback, wintypes.LPARAM]
        u.EnumWindows.restype = wintypes.BOOL
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindowVisible.restype = wintypes.BOOL
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.restype = ctypes.c_int

    def session_id(self, pid: int) -> int:
        value = wintypes.DWORD()
        if not self.k.ProcessIdToSessionId(pid, ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.value

    def allowed_path(self, path: str) -> str:
        path = canonical_path(path)
        if path in self.protected_exes or path == self.windows_dir or path.startswith(self.windows_dir + "\\"):
            raise ValueError("为避免误关，不能限制 AppLimiter 自身、运行解释器或 Windows 系统目录内的 EXE")
        return path

    def validate_selection(self, path: str) -> str:
        resolved = str(Path(path).resolve(strict=True))
        if not Path(resolved).is_file():
            raise ValueError("请选择 EXE 文件")
        return self.allowed_path(resolved)

    def belongs(self, process: psutil.Process) -> bool:
        return (process.pid != self.pid and self.session_id(process.pid) == self.session
                and process.username().casefold() == self.username)

    def foreground(self) -> int | None:
        # Only sample the ordinary interactive desktop. Lock/UAC desktops do not
        # count; querying its name never switches or unlocks a desktop.
        desktop = self.u.OpenInputDesktop(0, False, 0x0001)
        if not desktop:
            return None
        try:
            name = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            if not self.u.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)):
                return None
            if name.value.casefold() != "default":
                return None
        finally:
            self.u.CloseDesktop(desktop)
        hwnd = self.u.GetForegroundWindow()
        pid = wintypes.DWORD()
        if hwnd:
            self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value or None

    def snapshot(self, target_paths: set[str]) -> Snapshot:
        processes = []
        complete = True
        # Snapshot every configured executable, not every same-name process.
        for process in psutil.process_iter():
            try:
                path = canonical_path(process.exe())
                if path not in target_paths:
                    continue
                self.allowed_path(path)
                if self.belongs(process):
                    processes.append(ProcessRef(process.pid, process.create_time(), path))
            except (psutil.NoSuchProcess, psutil.ZombieProcess, ValueError):
                continue
            except (psutil.AccessDenied, OSError):
                # Inaccessible unrelated system processes are normal. Only an
                # already-seen target's disappearance is treated conservatively
                # by the worker's target name check below.
                try:
                    if process.name().casefold() in {ntpath.basename(p) for p in target_paths}:
                        complete = False
                except (psutil.Error, OSError):
                    pass
        return Snapshot(tuple(processes), self.foreground(), complete)

    def running_apps(self) -> list[tuple[str, str]]:
        visible: dict[int, str] = {}

        @self.enum_callback
        def visit(hwnd, _):
            if self.u.IsWindowVisible(hwnd):
                title = ctypes.create_unicode_buffer(512)
                self.u.GetWindowTextW(hwnd, title, len(title))
                pid = wintypes.DWORD()
                self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if title.value:
                    visible[pid.value] = title.value
            return True

        self.u.EnumWindows(visit, 0)
        result: dict[str, str] = {}
        for pid, title in visible.items():
            try:
                process = psutil.Process(pid)
                if self.belongs(process):
                    path = self.allowed_path(process.exe())
                    result.setdefault(path, title)
            except (psutil.Error, OSError, ValueError):
                continue
        return sorted([(title, path) for path, title in result.items()])

    def terminate(self, ref: ProcessRef, configured_paths: set[str]) -> tuple[bool, str]:
        """Check creation time and image on the *same* handle used to terminate.

        A recycled PID, unrelated child, other user's process, system image,
        critical process or inaccessible process is never terminated.
        """
        handle = None
        try:
            expected = self.allowed_path(ref.path)
            if expected not in configured_paths:
                return False, "目标路径已不属于规则"
            process = psutil.Process(ref.pid)
            if not self.belongs(process):
                return False, "目标不属于当前用户会话"
            handle = self.k.OpenProcess(0x1000 | 0x0001, False, ref.pid)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if not self.k.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            if canonical_path(buffer.value) != expected:
                return False, "进程路径已改变，取消结束"
            times = [wintypes.FILETIME() for _ in range(4)]
            if not self.k.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                raise ctypes.WinError(ctypes.get_last_error())
            ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            created = ticks / 10_000_000 - 11644473600
            if abs(created - ref.created) > 0.00001:
                return False, "PID 已被复用，取消结束"
            critical = wintypes.BOOL()
            if not self.k.IsProcessCritical(handle, ctypes.byref(critical)):
                raise ctypes.WinError(ctypes.get_last_error())
            if critical.value:
                return False, "目标是系统关键进程，取消结束"
            if not self.k.TerminateProcess(handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            return True, "已结束"
        except psutil.NoSuchProcess:
            return True, "目标已退出"
        except (psutil.Error, OSError, ValueError) as exc:
            return False, f"结束失败：{exc}（可能需要与目标相同权限）"
        finally:
            if handle:
                self.k.CloseHandle(handle)
