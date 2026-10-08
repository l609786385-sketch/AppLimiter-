from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from applimiter.engine import Engine
from applimiter.model import ProcessRef, Snapshot, canonical_path
from applimiter.storage import Store


A = canonical_path(r"C:\Apps\Video\video.exe")
B = canonical_path(r"C:\Apps\Music\music.exe")
H = canonical_path(r"C:\Apps\Video\helper.exe")


def process(pid=100, path=A, created=10.0):
    return ProcessRef(pid, created, path)


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "usage.db"
        self.store = Store(self.path)
        self.a = self.store.save_rule("视频", [A], 30, 60)
        self.engine = Engine(self.store)
        self.wall = datetime(2026, 10, 8, 12)
        self.mono = 0.0

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def tick(self, processes=None, foreground=100, advance=1, complete=True):
        self.wall += timedelta(seconds=advance)
        self.mono += advance
        return self.engine.tick(self.mono, self.wall,
                                Snapshot(tuple([process()] if processes is None else processes), foreground, complete))

    def run_seconds(self, seconds, **kwargs):
        actions = []
        for _ in range(seconds):
            actions = self.tick(**kwargs)
        return actions

    def used(self):
        return self.store.used(self.a, self.wall.date().isoformat())

    def test_initial_sample_does_not_charge_unobserved_time(self):
        self.tick(advance=500)
        self.assertEqual(self.used(), 0)

    def test_foreground_accumulates_once(self):
        self.tick()
        self.run_seconds(10)
        self.assertEqual(self.used(), 10)
        self.assertEqual(self.store.session(self.a).seconds, 10)

    def test_background_pauses_single_and_daily(self):
        self.tick()
        self.run_seconds(8)
        self.run_seconds(10, foreground=999)
        self.assertEqual(self.used(), 8)
        self.assertEqual(self.store.session(self.a).seconds, 8)
        self.tick()
        self.tick()
        self.assertEqual(self.used(), 9)

    def test_locked_or_no_foreground_does_not_count(self):
        self.tick(foreground=None)
        self.run_seconds(5, foreground=None)
        self.assertEqual(self.used(), 0)

    def test_multiple_same_exe_processes_do_not_duplicate(self):
        procs = [process(), process(101), process(102)]
        self.tick(processes=procs)
        self.run_seconds(12, processes=procs)
        self.assertEqual(self.used(), 12)

    def test_configured_helper_is_same_rule(self):
        self.store.save_rule("视频", [A, H], 30, 60, self.a)
        procs = [process(), process(101, H)]
        self.tick(processes=procs, foreground=101)
        self.run_seconds(10, processes=procs, foreground=101)
        self.assertEqual(self.used(), 10)
        self.assertEqual(self.store.session(self.a).seconds, 10)

    def test_non_target_same_filename_is_ignored(self):
        other = process(path=canonical_path(r"C:\Other\video.exe"))
        self.tick(processes=[other])
        self.run_seconds(70, processes=[other])
        self.assertEqual(self.used(), 0)

    def test_single_limit_returns_only_target_refs(self):
        procs = [process(), process(101), process(200, B)]
        self.tick(processes=procs)
        actions = self.run_seconds(30, processes=procs)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].reason, "single")
        self.assertEqual({p.pid for p in actions[0].targets}, {100, 101})
        self.assertEqual(self.used(), 30)

    def test_single_relaunch_keeps_daily_usage(self):
        self.tick()
        self.run_seconds(30)
        self.tick(processes=[], foreground=None)
        new = process(110, created=100.0)
        self.tick(processes=[new], foreground=110)
        self.run_seconds(10, processes=[new], foreground=110)
        self.assertEqual(self.used(), 40)
        self.assertEqual(self.store.session(self.a).seconds, 10)

    def test_daily_limit_blocks_relaunch_even_in_background(self):
        self.store.save_rule("视频", [A], 100, 5, self.a)
        self.tick()
        actions = self.run_seconds(5)
        self.assertEqual(actions[0].reason, "daily")
        self.tick(processes=[], foreground=None)
        actions = self.tick(processes=[process(111, created=50)], foreground=None)
        self.assertEqual(actions[0].reason, "daily")
        self.assertEqual(self.used(), 5)

    def test_restart_engine_preserves_live_single_session(self):
        self.tick()
        self.run_seconds(14)
        self.engine = Engine(self.store)
        self.tick()
        self.assertEqual(self.store.session(self.a).seconds, 14)
        self.run_seconds(16)
        self.assertEqual(self.store.session(self.a).seconds, 30)

    def test_disk_reopen_and_reboot_preserves_daily(self):
        self.tick()
        self.run_seconds(10)
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store)
        self.tick(processes=[process(222, created=900)], foreground=222)
        self.assertEqual(self.used(), 10)
        self.assertEqual(self.store.session(self.a).seconds, 0)

    def test_restart_after_daily_exhausted_immediately_blocks(self):
        with self.store.transaction():
            self.store.add_usage(self.a, self.wall.date().isoformat(), 60)
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store)
        actions = self.tick(foreground=None)
        self.assertEqual(actions[0].reason, "daily")

    def test_midnight_splits_usage_and_resets_only_daily(self):
        self.wall = datetime(2026, 10, 8, 23, 59, 59, 500000)
        self.tick(advance=0)
        self.tick()
        self.assertAlmostEqual(self.store.used(self.a, "2026-10-08"), .5)
        self.assertAlmostEqual(self.store.used(self.a, "2026-10-09"), .5)
        self.assertEqual(self.store.session(self.a).seconds, 1)

    def test_midnight_releases_daily_block(self):
        self.wall = datetime(2026, 10, 8, 23, 59, 59)
        with self.store.transaction():
            self.store.add_usage(self.a, "2026-10-08", 60)
        self.assertEqual(self.tick(advance=0)[0].reason, "daily")
        self.tick(processes=[], foreground=None)
        self.assertEqual(self.used(), 0)
        self.assertEqual(self.tick(processes=[process(110)], foreground=110), [])

    def test_sleep_gap_is_not_usage(self):
        self.tick()
        self.tick(advance=3600)
        self.assertEqual(self.used(), 0)
        self.tick()
        self.assertEqual(self.used(), 1)

    def test_clock_jump_not_billed(self):
        self.tick()
        self.wall += timedelta(hours=2)
        self.tick()
        self.assertEqual(self.used(), 0)
        self.wall -= timedelta(hours=3)
        self.tick()
        self.assertEqual(self.used(), 0)

    def test_pause_resume_preserves_usage(self):
        self.tick()
        self.run_seconds(10)
        self.store.enable(self.a, False)
        self.run_seconds(30)
        self.assertEqual(self.used(), 10)
        self.store.enable(self.a, True)
        self.tick()
        self.run_seconds(5)
        self.assertEqual(self.used(), 15)

    def test_pause_disables_exhausted_interception(self):
        with self.store.transaction():
            self.store.add_usage(self.a, self.wall.date().isoformat(), 60)
        self.store.enable(self.a, False)
        self.assertEqual(self.tick(), [])

    def test_delete_disables_interception_keeps_records(self):
        self.tick()
        self.run_seconds(5)
        self.store.delete(self.a)
        self.assertEqual(self.tick(), [])
        record = self.store.records(self.wall.date().isoformat())[0]
        self.assertEqual(record["seconds"], 5)
        self.assertTrue(record["deleted"])

    def test_multiple_apps_have_independent_budgets(self):
        b = self.store.save_rule("音乐", [B], 20, 80)
        procs = [process(), process(200, B)]
        self.tick(processes=procs)
        self.run_seconds(10, processes=procs)
        self.tick(processes=procs, foreground=200)
        self.run_seconds(15, processes=procs, foreground=200)
        self.assertEqual(self.used(), 10)
        self.assertEqual(self.store.used(b, self.wall.date().isoformat()), 15)

    def test_pid_reuse_never_credits_old_interval(self):
        self.tick()
        self.run_seconds(5)
        self.tick(processes=[process(created=20)])
        self.assertEqual(self.used(), 5)
        self.assertEqual(self.store.session(self.a).seconds, 0)

    def test_partial_scan_does_not_erase_single_session(self):
        self.tick()
        self.run_seconds(5)
        self.tick(processes=[], foreground=None, complete=False)
        self.assertEqual(self.store.session(self.a).seconds, 5)
        self.tick()
        self.assertEqual(self.used(), 5)

    def test_limit_change_keeps_counters(self):
        self.tick()
        self.run_seconds(10)
        self.store.save_rule("视频", [A], 5, 60, self.a)
        actions = self.tick()
        self.assertEqual(actions[0].reason, "single")
        self.assertEqual(self.used(), 10)

    def test_fractional_credit_caps_at_limit(self):
        self.store.save_rule("视频", [A], 1, 60, self.a)
        self.tick(advance=0)
        self.tick(advance=.7)
        actions = self.tick(advance=.7)
        self.assertEqual(self.used(), 1)
        self.assertEqual(actions[0].reason, "single")

    def test_no_midnight_service_uptime_required(self):
        self.tick()
        self.run_seconds(5)
        self.engine = Engine(self.store)
        self.wall += timedelta(days=1)
        self.tick()
        self.assertEqual(self.used(), 0)
        self.assertEqual(self.store.used(self.a, "2026-10-08"), 5)

    def test_warnings_deduplicate_across_worker_restart(self):
        self.store.save_rule("视频", [A], 400, 800, self.a)
        self.tick()
        self.run_seconds(100)
        warnings = [e for e in self.store.events_after(0) if e["kind"] == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("5 分钟", warnings[0]["message"])
        self.engine = Engine(self.store)
        self.tick()
        self.run_seconds(240)
        warnings = [e for e in self.store.events_after(0) if e["kind"] == "warning"]
        self.assertEqual(len(warnings), 2)
        self.assertIn("1 分钟", warnings[1]["message"])

    def test_daily_warning_not_repeated_after_app_relaunch(self):
        self.store.save_rule("视频", [A], 1000, 350, self.a)
        self.tick()
        self.run_seconds(50)
        count = self.store.latest_event_id()
        self.tick(processes=[], foreground=None)
        self.tick(processes=[process(110)], foreground=110)
        self.assertEqual(self.store.latest_event_id(), count)

    def test_duplicate_exe_rolls_back_entire_rule_edit(self):
        self.store.save_rule("音乐", [B], 20, 80)
        with self.assertRaises(ValueError):
            self.store.save_rule("错误修改", [B], 1, 1, self.a)
        rule = next(r for r in self.store.rules() if r.id == self.a)
        self.assertEqual(rule.name, "视频")
        self.assertEqual(rule.paths, (A,))

    def test_transaction_rollback_keeps_usage_and_session_atomic(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.add_usage(self.a, "2026-10-08", 10)
                raise RuntimeError("模拟写入中断")
        self.assertEqual(self.store.used(self.a, "2026-10-08"), 0)

    def test_separate_connections_share_persisted_usage(self):
        other = Store(self.path)
        try:
            self.tick()
            self.run_seconds(10)
            self.assertEqual(other.used(self.a, self.wall.date().isoformat()), 10)
            other.enable(self.a, False)
            self.assertEqual(self.tick(), [])
        finally:
            other.close()

    def test_invalid_paths_and_empty_rules_rejected(self):
        for value in ["video.exe", r"C:\apps\video.txt"]:
            with self.assertRaises(ValueError):
                canonical_path(value)
        with self.assertRaises(ValueError):
            self.store.save_rule("", [A], 30, 60)
        with self.assertRaises(ValueError):
            self.store.save_rule("无路径", [], 30, 60)


if __name__ == "__main__":
    unittest.main()
