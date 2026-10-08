"""Run real native tests; never turn skipped tests into a successful release gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fingerprint() -> str:
    digest = hashlib.sha256()
    files = [p for p in ROOT.rglob("*") if p.is_file() and
             not any(part in {".venv", "__pycache__", "build", "dist", ".git", "verification-artifacts"}
                     for part in p.relative_to(ROOT).parts)
             and (p.suffix in {".py", ".cs", ".ps1", ".bat", ".spec"} or p.name.startswith("requirements"))]
    for path in sorted(files):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="AppLimiter Windows 原生验证")
    parser.add_argument("--exe", type=Path, help="同时验证打包后的后台和窗口启动")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("拒绝生成 Windows 验证凭据：当前系统不是 Windows。", file=sys.stderr)
        return 2
    os.environ["APPLIMITER_WINDOWS_TESTS"] = "1"
    if args.exe:
        if not args.exe.is_file():
            parser.error("EXE 不存在")
        os.environ["APPLIMITER_TEST_EXE"] = str(args.exe.resolve())
    print("请在已解锁的本地 Windows 桌面运行。测试将打开并关闭专用临时窗口。", flush=True)
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped:
        print("Windows 验证未完成：存在失败或跳过项。不会生成可用验证凭据。", file=sys.stderr)
        return 1
    report = {"tested_at_local": datetime.now().isoformat(), "platform": platform.platform(),
              "python": sys.version, "tests": result.testsRun, "skipped": 0,
              "source_sha256": fingerprint(), "native_tested": True,
              "packaged_exe": str(args.exe.resolve()) if args.exe else None,
              "manual_checks": "NOT_PERFORMED_BY_THIS_SCRIPT"}
    output = ROOT / (".windows-package-verification.json" if args.exe else ".windows-verification.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"验证通过：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
