import unittest
from unittest.mock import patch

from core.adb_helper import ADBHelper


class IncomingCallTests(unittest.TestCase):
    def setUp(self):
        self.helper = ADBHelper()

    def test_parse_phone_contacts_keeps_multiple_numbers_and_commas_in_name(self):
        output = "\n".join([
            "Row: 0 display_name=张三, data1=138 0013 8000",
            "Row: 1 display_name=Doe, John, data1=555-0100",
            "Row: 2 display_name=张三, data1=138 0013 8000",
            "Row: 3 display_name=张三, data1=13900139000",
        ])

        self.assertEqual(self.helper._parse_phone_contacts(output), [
            {"name": "Doe, John", "number": "555-0100"},
            {"name": "张三", "number": "138 0013 8000"},
            {"name": "张三", "number": "13900139000"},
        ])

    def test_emulator_uses_gsm_call_and_normalizes_number(self):
        self.helper.current_device_id = "emulator-5554"
        with patch.object(self.helper, "execute_adb_command", return_value=(True, "OK")) as execute:
            success, _ = self.helper.sim_contact_incoming_call("+86 138-0013-8000")

        self.assertTrue(success)
        execute.assert_called_once_with(["adb", "emu", "gsm", "call", "+8613800138000"])

    def test_physical_device_uses_original_broadcast_exactly(self):
        self.helper.current_device_id = "R58M123456A"
        with patch.object(self.helper, "execute_adb_command", return_value=(True, "Broadcast completed")) as execute:
            success, _ = self.helper.sim_incoming_call()

        self.assertTrue(success)
        execute.assert_called_once_with([
            "adb", "shell", "am", "broadcast",
            "-a", "android.intent.action.TEST",
            "--es", "state", "RINGING",
        ])

    def test_physical_contact_call_includes_incoming_number(self):
        self.helper.current_device_id = "R58M123456A"
        with patch.object(self.helper, "execute_adb_command", return_value=(True, "Broadcast completed")) as execute:
            success, _ = self.helper.sim_contact_incoming_call("+86 138-0013-8000")

        self.assertTrue(success)
        execute.assert_called_once_with([
            "adb", "shell", "am", "broadcast",
            "-a", "android.intent.action.TEST",
            "--es", "state", "RINGING",
            "--es", "incoming_number", "+8613800138000",
        ])


if __name__ == "__main__":
    unittest.main()
