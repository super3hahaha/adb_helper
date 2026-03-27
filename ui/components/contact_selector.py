import customtkinter as ctk
import threading


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

        threading.Thread(target=_thread, daemon=True).start()
