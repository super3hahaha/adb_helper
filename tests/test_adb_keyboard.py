import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.adb_helper import ADBHelper


class AdbKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.helper = ADBHelper()
        self.helper.current_device_id = "serial-1"

    def test_ime_set_stdout_failure_is_not_success(self):
        self.assertFalse(self.helper._ime_command_succeeded(
            True,
            "Unknown input method com.android.adbkeyboard/.AdbIME cannot be selected for user #0",
        ))

    def test_ime_list_summary_flag_does_not_suppress_device_selector(self):
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with (
            patch.object(self.helper, "_ensure_adb_server"),
            patch.object(self.helper, "_get_subprocess_kwargs", return_value={}),
            patch("core.adb_helper.subprocess.run", return_value=completed) as run,
        ):
            self.helper.execute_adb_command(["adb", "shell", "ime", "list", "-s"])

        command = run.call_args.args[0]
        self.assertEqual(
            command[:4],
            [self.helper.adb_cmd, "-s", "serial-1", "shell"],
        )
        self.assertEqual(command[-1], "-s")

    def test_installed_disabled_package_is_reenabled(self):
        with patch.object(
            self.helper,
            "execute_adb_command",
            side_effect=[
                (True, "package:com.android.adbkeyboard versionCode:6"),
                (True, "package:com.android.adbkeyboard"),
                (True, "Package com.android.adbkeyboard new state: enabled"),
                (True, "com.android.adbkeyboard/.AdbIME"),
            ],
        ) as execute:
            self.assertTrue(self.helper._install_adb_keyboard())

        self.assertEqual(
            execute.call_args_list[-2].args[0],
            ["adb", "shell", "pm", "enable", "com.android.adbkeyboard"],
        )

    def test_incompatible_installed_package_is_replaced(self):
        def command_result(command, **_kwargs):
            if command[2:5] == ["pm", "list", "packages"] and "-d" not in command:
                return True, "package:com.android.adbkeyboard versionCode:6"
            if command[2:5] == ["pm", "list", "packages"] and "-d" in command:
                return True, ""
            return True, "Success"

        with patch.object(
            self.helper,
            "execute_adb_command",
            side_effect=command_result,
        ) as execute, patch.object(
            self.helper,
            "_wait_for_adb_keyboard_available",
            side_effect=lambda timeout=5: timeout != 2,
        ):
            self.assertTrue(self.helper._install_adb_keyboard())

        commands = [call.args[0] for call in execute.call_args_list]
        self.assertIn(["adb", "uninstall", "com.android.adbkeyboard"], commands)
        self.assertEqual(commands[-1][1], "install")

    def test_switch_enables_then_selects_and_verifies(self):
        with (
            patch.object(
                self.helper,
                "execute_adb_command",
                side_effect=[
                    (True, "Input method enabled"),
                    (True, "Input method selected"),
                ],
            ) as execute,
            patch.object(self.helper, "_is_adb_keyboard_active", return_value=True),
        ):
            self.assertTrue(self.helper._try_switch_to_adb_keyboard())

        self.assertEqual(execute.call_args_list[0].args[0][2:4], ["ime", "enable"])
        self.assertEqual(execute.call_args_list[1].args[0][2:4], ["ime", "set"])

    def test_send_text_uses_base64_broadcast(self):
        text = "Ahoy!!\n我ら宝鐘海賊団☆"
        with (
            patch.object(self.helper, "_install_adb_keyboard", return_value=True),
            patch.object(self.helper, "_is_adb_keyboard_active", return_value=True),
            patch.object(self.helper, "_wait_for_adb_keyboard_process", return_value=True),
            patch.object(
                self.helper,
                "execute_adb_command",
                return_value=(True, "Broadcast completed: result=-1"),
            ) as execute,
        ):
            success, _ = self.helper.send_text(text)

        self.assertTrue(success)
        command = execute.call_args.args[0]
        self.assertIn("ADB_INPUT_B64_ACK", command)
        self.assertIn("-p", command)
        self.assertEqual(
            command[-1],
            base64.b64encode(text.encode("utf-8")).decode("ascii"),
        )

    def test_ready_device_sends_only_one_broadcast(self):
        self.helper._adb_keyboard_ready_devices.add("serial-1")
        with patch.object(
            self.helper,
            "execute_adb_command",
            return_value=(True, "Broadcast completed: result=-1"),
        ) as execute:
            success, _ = self.helper.send_text("宝鐘マリン")

        self.assertTrue(success)
        execute.assert_called_once()
        self.assertIn("ADB_INPUT_B64_ACK", execute.call_args.args[0])

    def test_send_text_fails_before_broadcast_when_ime_process_is_missing(self):
        with (
            patch.object(
                self.helper,
                "_broadcast_adb_keyboard_text",
                return_value=(False, "no receiver"),
            ),
            patch.object(self.helper, "_install_adb_keyboard", return_value=True),
            patch.object(self.helper, "_is_adb_keyboard_active", return_value=True),
            patch.object(self.helper, "_wait_for_adb_keyboard_process", return_value=False),
            patch.object(self.helper, "_try_switch_to_adb_keyboard", return_value=False),
            patch.object(self.helper, "execute_adb_command") as execute,
        ):
            success, message = self.helper.send_text("hello")

        self.assertFalse(success)
        self.assertIn("可编辑输入框", message)
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
