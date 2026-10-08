"""Independent worker + real SQLite integration, with OS termination mocked."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from applimiter.model import ProcessRef, Snapshot, canonical_path
from applimiter.storage import Store

HAS_QT = importlib.util.find_spec("PySide6") is not None
if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(HAS_QT, "请安装 requirements.txt 后运行后台集成测试")
class WorkerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from applimiter.worker import Worker
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        store = Store(self.directory / "applimiter.db")
        self.path = canonical_path(r"C:\Apps\video.exe")
        self.ref = ProcessRef(100, 50, self.path)
        self.rule_id = store.save_rule("视频", [self.path], 30, 3)
        store.close()
        self.patch_adapter = patch("applimiter.worker.WindowsAdapter")
        self.adapter = self.patch_adapter.start().return_value
        self.adapter.snapshot.return_value = Snapshot((self.ref,), 100)
        self.adapter.terminate.return_value = (True, "已结束")
        self.worker = Worker(self.app, self.directory, no_tray=True)
        self.worker.timer.stop()
        self.today = datetime.now().date().isoformat()
        with self.worker.store.transaction():
            self.worker.store.add_usage(self.rule_id, self.today, 3)

    def tearDown(self):
        self.worker.close()
        self.patch_adapter.stop()
        self.temp.cleanup()

    def test_usage_is_committed_before_termination(self):
        def terminate(ref, paths):
            reader = Store(self.directory / "applimiter.db")
            try:
                self.assertEqual(reader.used(self.rule_id, self.today), 3)
            finally:
                reader.close()
            self.assertEqual(ref, self.ref)
            self.assertEqual(paths, {self.path})
            return True, "已结束"
        self.adapter.terminate.side_effect = terminate
        self.worker.tick()
        self.adapter.terminate.assert_called_once()

    def test_pause_between_accounting_and_enforcement_cancels_kill(self):
        original = self.worker.engine.tick
        def pause(*args):
            actions = original(*args)
            self.worker.store.enable(self.rule_id, False)
            return actions
        self.worker.engine.tick = pause
        self.worker.tick()
        self.adapter.terminate.assert_not_called()

    def test_deleted_rule_cancels_pending_kill(self):
        original = self.worker.engine.tick
        def delete(*args):
            actions = original(*args)
            self.worker.store.delete(self.rule_id)
            return actions
        self.worker.engine.tick = delete
        self.worker.tick()
        self.adapter.terminate.assert_not_called()

    def test_termination_failure_is_logged_and_does_not_refund_usage(self):
        self.adapter.terminate.return_value = (False, "测试：访问被拒绝")
        self.worker.tick()
        errors = [e for e in self.worker.store.events_after(0) if e["kind"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("访问被拒绝", errors[0]["message"])
        self.assertEqual(self.worker.store.used(self.rule_id, self.today), 3)


if __name__ == "__main__":
    unittest.main()
