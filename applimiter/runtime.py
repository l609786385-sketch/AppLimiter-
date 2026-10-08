from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def data_directory(override: str | None = None) -> Path:
    path = Path(override) if override else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AppLimiter"
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def command(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "applimiter", *args]


def launch(data_dir: Path, worker: bool = False):
    args = ["--data-dir", str(data_dir)]
    if worker:
        args.append("--worker")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    return subprocess.Popen(command(*args), cwd=Path(__file__).resolve().parent.parent, **kwargs)


def autostart_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            winreg.QueryValueEx(key, "AppLimiter")
        return True
    except FileNotFoundError:
        return False


def set_autostart(enabled: bool, data_dir: Path):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            args = command("--worker", "--data-dir", str(data_dir))
            if not getattr(sys, "frozen", False):
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                if pythonw.exists():
                    args[0] = str(pythonw)
                # -m depends on cwd; absolute bootstrap works at login.
                args[1:3] = [str(Path(__file__).resolve().parent.parent / "main.py")]
            winreg.SetValueEx(key, "AppLimiter", 0, winreg.REG_SZ, subprocess.list2cmdline(args))
        else:
            try:
                winreg.DeleteValue(key, "AppLimiter")
            except FileNotFoundError:
                pass
