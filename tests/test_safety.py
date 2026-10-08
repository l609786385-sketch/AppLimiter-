"""Mocked Win32 boundary tests; these do NOT certify native Windows APIs."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from applimiter.model import ProcessRef, canonical_path
from applimiter.windows import WindowsAdapter


PATH = canonical_path(r"C:\Apps\video.exe")


class TerminationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.adapter = WindowsAdapter.__new__(WindowsAdapter)
        self.adapter.windows_dir = r"c:\windows"
        self.adapter.protected_exes = {r"c:\applimiter\applimiter.exe"}
        self.adapter.belongs = Mock(return_value=True)
        self.adapter.k = Mock()
        self.adapter.k.OpenProcess.return_value = 987
        self.adapter.k.TerminateProcess.return_value = True
        self.ref = ProcessRef(123, 100.0, PATH)

        def image(_handle, _flags, buffer, _size):
            buffer.value = PATH
            return True

        def times(_handle, created, _exit, _kernel, _user):
            ticks = (11644473600 + self.ref.created) * 10_000_000
            created._obj.dwHighDateTime = int(ticks) >> 32
            created._obj.dwLowDateTime = int(ticks) & 0xffffffff
            return True

        def critical(_handle, result):
            result._obj.value = False
            return True

        self.adapter.k.QueryFullProcessImageNameW.side_effect = image
        self.adapter.k.GetProcessTimes.side_effect = times
        self.adapter.k.IsProcessCritical.side_effect = critical
        self.process_patch = patch("applimiter.windows.psutil.Process")
        self.process_patch.start()

    def tearDown(self):
        self.process_patch.stop()

    def test_verified_image_uses_same_handle_for_termination(self):
        self.assertTrue(self.adapter.terminate(self.ref, {PATH})[0])
        self.adapter.k.TerminateProcess.assert_called_once_with(987, 1)
        self.assertEqual(self.adapter.k.QueryFullProcessImageNameW.call_args.args[0], 987)
        self.assertEqual(self.adapter.k.GetProcessTimes.call_args.args[0], 987)
        self.adapter.k.CloseHandle.assert_called_once_with(987)

    def test_recycled_pid_is_never_terminated(self):
        stale = ProcessRef(123, 50, PATH)
        self.assertFalse(self.adapter.terminate(stale, {PATH})[0])
        self.adapter.k.TerminateProcess.assert_not_called()
        self.adapter.k.CloseHandle.assert_called_once_with(987)

    def test_changed_image_is_never_terminated(self):
        def changed(_handle, _flags, buffer, _size):
            buffer.value = r"C:\Elsewhere\video.exe"
            return True
        self.adapter.k.QueryFullProcessImageNameW.side_effect = changed
        self.assertFalse(self.adapter.terminate(self.ref, {PATH})[0])
        self.adapter.k.TerminateProcess.assert_not_called()

    def test_critical_process_is_never_terminated(self):
        def critical(_handle, result):
            result._obj.value = True
            return True
        self.adapter.k.IsProcessCritical.side_effect = critical
        self.assertFalse(self.adapter.terminate(self.ref, {PATH})[0])
        self.adapter.k.TerminateProcess.assert_not_called()

    def test_other_user_or_session_is_never_opened(self):
        self.adapter.belongs.return_value = False
        self.assertFalse(self.adapter.terminate(self.ref, {PATH})[0])
        self.adapter.k.OpenProcess.assert_not_called()

    def test_removed_path_is_never_opened(self):
        self.assertFalse(self.adapter.terminate(self.ref, set())[0])
        self.adapter.k.OpenProcess.assert_not_called()

    def test_system_directory_and_self_are_rejected(self):
        for path in [r"C:\Windows\System32\anything.exe", r"C:\AppLimiter\AppLimiter.exe"]:
            ref = ProcessRef(123, 100, canonical_path(path))
            self.assertFalse(self.adapter.terminate(ref, {ref.path})[0])
        self.adapter.k.OpenProcess.assert_not_called()
