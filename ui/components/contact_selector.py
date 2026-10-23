import customtkinter as ctk
import threading
import re


class ContactRingtoneDialog(ctk.CTkToplevel):
    def __init__(self, parent, adb_helper, contacts, log_func=None):
        super().__init__(parent)
        self.adb_helper = adb_helper
        self.contacts = contacts
        self.log = log_func

        self.title("联系人铃声试听")
        self.geometry("400x160")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())

        self.after(10, lambda: (self.lift(), self.focus_force()))

        # 提示
        ctk.CTkLabel(self, text="请选择或输入联系人姓名：").pack(pady=(15, 5), padx=15, anchor="w")

        # 联系人选择框
        self.contact_var = ctk.StringVar(value=contacts[0] if contacts else "")
        self.combo = ctk.CTkComboBox(self, values=contacts, variable=self.contact_var, width=360)
        self.combo.pack(pady=5, padx=15, fill="x")

        # 播放按钮
        self.btn_play = ctk.CTkButton(self, text="▶️ 播放该联系人铃声", command=self.on_play,
                                       fg_color="#2d7d46", hover_color="#1e5c32")
        self.btn_play.pack(pady=(10, 15), padx=15, fill="x")

    def on_play(self):
        name = self.contact_var.get().strip()
        if not name:
            if self.log:
                self.log("请选择或输入联系人姓名", "WARNING")
            return

        self.btn_play.configure(state="disabled", text="⏳ 正在播放...")

        def _thread():
            try:
                success, msg = self.adb_helper.play_contact_ringtone(name)
                if self.log:
                    self.log(msg, "SUCCESS" if success else "WARNING")
            except Exception as e:
                if self.log:
                    self.log(f"播放联系人铃声异常: {e}", "ERROR")
            finally:
                self.after(0, lambda: self.btn_play.configure(state="normal", text="▶️ 播放该联系人铃声"))

        self.adb_helper.spawn(_thread)


class IncomingCallDialog(ctk.CTkToplevel):
    """选择通讯录号码或手动输入号码后模拟来电。"""

    def __init__(self, parent, adb_helper, contacts, device_id, log_func=None):
        super().__init__(parent)
        self.adb_helper = adb_helper
        self.contacts = contacts
        self.device_id = device_id
        self.log = log_func

        self.title("设置模拟来电联系人")
        self.geometry("440x245")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.after(10, lambda: (self.lift(), self.focus_force()))

        ctk.CTkLabel(self, text="选择设备通讯录联系人：").pack(pady=(15, 4), padx=15, anchor="w")
        self._display_to_number = {
            f'{item["name"]}  —  {item["number"]}': item["number"]
            for item in contacts
        }
        choices = list(self._display_to_number)
        self.contact_var = ctk.StringVar(value=choices[0] if choices else "未读取到联系人号码")
        self.combo = ctk.CTkComboBox(
            self,
            values=choices or ["未读取到联系人号码"],
            variable=self.contact_var,
            command=self._on_contact_selected,
            state="readonly" if choices else "disabled",
        )
        self.combo.pack(pady=(0, 8), padx=15, fill="x")

        ctk.CTkLabel(self, text="来电号码（可手动修改）：").pack(pady=(0, 4), padx=15, anchor="w")
        self.entry_number = ctk.CTkEntry(self, placeholder_text="例如：13800138000")
        self.entry_number.pack(pady=(0, 8), padx=15, fill="x")
        if choices:
            self.entry_number.insert(0, self._display_to_number[choices[0]])

        is_emulator = device_id.startswith("emulator-")
        hint = (
            "模拟器：将产生系统级来电，联系人姓名由系统通讯录按号码匹配。"
            if is_emulator else
            "实体机：发送带 incoming_number 的测试广播，由被测 App 解析联系人。"
        )
        ctk.CTkLabel(
            self, text=hint, font=ctk.CTkFont(size=11), text_color="gray", wraplength=405,
        ).pack(pady=(0, 8), padx=15, anchor="w")

        self.btn_call = ctk.CTkButton(self, text="模拟来电", command=self.on_call)
        self.btn_call.pack(pady=(0, 15), padx=15, fill="x")

    def _on_contact_selected(self, display):
        number = self._display_to_number.get(display, "")
        self.entry_number.delete(0, "end")
        self.entry_number.insert(0, number)

    def on_call(self):
        number = self.entry_number.get().strip()
        if not number or not re.search(r"\d", number):
            if self.log:
                self.log("请输入有效的来电号码", "WARNING")
            return

        self.btn_call.configure(state="disabled", text="正在模拟来电...")

        def _thread():
            try:
                with self.adb_helper.bind_device(self.device_id):
                    success, msg = self.adb_helper.sim_contact_incoming_call(number)
                if self.log:
                    self.log(msg, "SUCCESS" if success else "ERROR")
                if success:
                    self.after(0, self.destroy)
                else:
                    self.after(0, self._reset_call_button)
            except Exception as exc:
                if self.log:
                    self.log(f"模拟来电异常: {exc}", "ERROR")
                self.after(0, self._reset_call_button)

        self.adb_helper.spawn(_thread)

    def _reset_call_button(self):
        if self.winfo_exists():
            self.btn_call.configure(state="normal", text="模拟来电")
