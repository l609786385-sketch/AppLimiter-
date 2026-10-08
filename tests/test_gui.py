"""Widget/database integration tests. Native Windows APIs are explicitly mocked."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

HAS_QT = importlib.util.find_spec("PySide6") is not None
if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(HAS_QT, "请安装 requirements.txt 后运行 Qt 集成测试")
class GuiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from applimiter.gui import MainWindow
        self.temp = tempfile.TemporaryDirectory()
        self.patch_adapter = patch("applimiter.gui.WindowsAdapter")
        self.patch_auto = patch("applimiter.gui.autostart_enabled", return_value=False)
        self.patch_adapter.start()
        self.patch_auto.start()
        self.window = MainWindow(Path(self.temp.name))

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.patch_auto.stop()
        self.patch_adapter.stop()
        self.temp.cleanup()

    def test_dashboard_and_records_show_persisted_usage(self):
        rule = self.window.store.save_rule("测试视频", [r"C:\Apps\video.exe"], 1800, 3600)
        with self.window.store.transaction():
            self.window.store.add_usage(rule, datetime.now().date().isoformat(), 120)
        self.window.refresh()
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertEqual(self.window.table.item(0, 0).text(), "测试视频")
        self.assertEqual(self.window.table.item(0, 2).text(), "00:58:00")
        self.assertEqual(self.window.history.rowCount(), 1)
        self.assertEqual(self.window.history.item(0, 2).text(), "00:02:00")

    def test_selected_rule_can_pause_from_dashboard(self):
        rule = self.window.store.save_rule("测试视频", [r"C:\Apps\video.exe"], 1800, 3600)
        self.window.refresh()
        self.window.table.selectRow(0)
        self.window.toggle()
        self.assertFalse(self.window.store.rules()[0].enabled)
        self.assertEqual(self.window.table.item(0, 6).text(), "已暂停")
        self.assertEqual(self.window.selected().id, rule)

    def test_rule_editor_save_integrates_with_dashboard(self):
        from applimiter.gui import RuleDialog
        from PySide6.QtWidgets import QDialog
        dialog = RuleDialog(self.window.store, self.window.adapter, parent=self.window)
        dialog.name.setText("新应用")
        dialog.paths.addItem(r"C:\Apps\new.exe")
        dialog.single.setValue(30)
        dialog.daily.setValue(60)
        dialog.save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.window.refresh()
        self.assertEqual(self.window.table.item(0, 0).text(), "新应用")
        self.assertEqual(self.window.store.rules()[0].daily_seconds, 3600)


if __name__ == "__main__":
    unittest.main()
