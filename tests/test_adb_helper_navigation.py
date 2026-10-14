import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.adb_helper import ADBHelper


class NavigationSettingsTests(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.helper = ADBHelper(lambda message, level: self.logs.append((level, message)))
        self.helper.current_device_id = "serial-1"

    def test_uses_settings_search_when_direct_action_is_missing(self):
        with (
            patch.object(
                self.helper,
                "_shell_silent",
                side_effect=[
                    "No activity found",
                    "com.google.android.settings.intelligence/.modules.search.SearchActivity",
                ],
            ),
            patch.object(
                self.helper,
                "execute_adb_command",
                return_value=(True, "Status: ok"),
            ) as execute,
        ):
            success, message = self.helper.open_navigation_settings()

        self.assertTrue(success)
        self.assertIn("请点击搜索结果", message)
        command = execute.call_args.args[0]
        self.assertIn("android.settings.APP_SEARCH_SETTINGS", command)
        self.assertEqual(command[-3:], ["--es", "query", "'系统导航'"])

    def test_reports_failure_when_no_supported_entry_exists(self):
        with patch.object(
            self.helper,
            "_shell_silent",
            side_effect=["No activity found", "No activity found"],
        ):
            success, message = self.helper.open_navigation_settings()

        self.assertFalse(success)
        self.assertIn("未提供可用", message)

    def test_am_start_stdout_error_is_not_treated_as_success(self):
        failed_start = SimpleNamespace(
            returncode=0,
            stdout=(
                "Starting: Intent { act=missing.action }\n"
                "Error: Activity not started, unable to resolve Intent"
            ),
            stderr="",
        )
        with (
            patch.object(self.helper, "_ensure_adb_server"),
            patch.object(self.helper, "_get_subprocess_kwargs", return_value={}),
            patch("core.adb_helper.subprocess.run", return_value=failed_start),
        ):
            success, message = self.helper.execute_adb_command(
                ["adb", "shell", "am", "start", "-a", "missing.action"],
                check_dev=False,
            )

        self.assertFalse(success)
        self.assertIn("Error: Activity not started", message)


if __name__ == "__main__":
    unittest.main()
