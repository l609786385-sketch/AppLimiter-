# Build this spec on Windows only; Linux cannot cross-compile a native Windows EXE.
import sys

if sys.platform != 'win32':
    raise RuntimeError('AppLimiter must be packaged and verified on Windows 10/11')

a = Analysis(
    ['main.py'], pathex=[], binaries=[], datas=[],
    hiddenimports=['PySide6.QtNetwork'], hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=['tkinter'], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='AppLimiter',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AppLimiter')
