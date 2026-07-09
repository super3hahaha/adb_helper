# -*- coding: utf-8 -*-
"""Qt 截图预览子进程启动器（主进程侧）。

职责（对应 handoff 第 7 节的 4 项跨进程耦合）：
    - log_func：读子进程 stdout 的 {"type":"log"}，转发到主 app 日志面板
    - 重截：读到 {"type":"rescreenshot"} 后调主进程现成的 adb_helper.take_screenshot，
      结果经 stdin 回传 {"type":"new_image"} / {"type":"rescreenshot_failed"}
    - temp 所有权：删除/保存全部由子进程负责，主进程不持有该路径引用
    - transient：独立 OS 窗口，主窗口最小化不跟随（已知的可接受回退）

线程模型：
    - stdout/stderr 各一条守护读线程；log_func(=MainWindow.log_message) 本身
      线程安全（内部 after(0) 调度），可在读线程直接调用
    - adb_helper.take_screenshot 只负责起后台线程，任意线程可调；
      其 on_complete 在 adb 工作线程触发，只做 stdin 写（带锁），不碰 Tk
"""
import importlib.util
import json
import os
import subprocess
import sys
import threading
from collections import deque

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def qt_preview_available():
    """PySide6 是否可用（find_spec 不实际加载 Qt，开销可忽略）。"""
    try:
        return importlib.util.find_spec("PySide6") is not None
    except Exception:
        return False


def launch_qt_preview(image_path, temp_dir, log_func=None, adb_helper=None):
    """拉起 Qt 预览子进程。返回 True=已接管；False=不可用，调用方应回退 Tk 窗口。"""
    if not qt_preview_available():
        return False

    theme = "light"
    try:
        import customtkinter as ctk
        theme = "dark" if ctk.get_appearance_mode() == "Dark" else "light"
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        cmd = [sys.executable, os.path.join(_PROJECT_ROOT, "main.py")]
    cmd += ["--qt-preview", image_path, temp_dir, "--theme", theme]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=_PROJECT_ROOT if not getattr(sys, "frozen", False) else None,
        )
    except Exception as e:
        if log_func:
            log_func(f"启动截图预览窗口失败: {e}", "ERROR")
        return False

    _PreviewSession(proc, temp_dir, log_func, adb_helper).start()
    return True


class _PreviewSession:
    """一个子进程一条会话；多窗口并存时各自独立。"""

    def __init__(self, proc, temp_dir, log_func, adb_helper):
        self.proc = proc
        self.temp_dir = temp_dir
        self.log_func = log_func
        self.adb_helper = adb_helper
        self._stdin_lock = threading.Lock()
        self._stderr_tail = deque(maxlen=20)

    def start(self):
        threading.Thread(target=self._stdout_loop, daemon=True).start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()

    def _log(self, msg, level="INFO"):
        if self.log_func:
            try:
                self.log_func(msg, level)
            except Exception:
                pass  # 主窗口已销毁

    def _send(self, obj):
        try:
            data = json.dumps(obj, ensure_ascii=False)
            with self._stdin_lock:
                self.proc.stdin.write(data + "\n")
                self.proc.stdin.flush()
        except Exception:
            pass  # 子进程已退出

    # ---- 子进程 stdout：JSON 行协议 ----

    def _stdout_loop(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                self._handle_message(msg)
        except Exception:
            pass
        rc = self.proc.wait()
        if rc not in (0, None):
            tail = "\n".join(self._stderr_tail)
            self._log(f"截图预览窗口异常退出 (code={rc}) {tail}".strip(), "ERROR")

    def _handle_message(self, msg):
        mtype = msg.get("type")
        if mtype == "log":
            self._log(msg.get("msg", ""), msg.get("level", "INFO"))
        elif mtype == "rescreenshot":
            self._do_rescreenshot()

    # ---- 重截：调主进程现成的 take_screenshot（serial/别名/尺寸全部天然正确） ----

    def _do_rescreenshot(self):
        if not self.adb_helper:
            self._log("无法重新截图: 未提供 ADB 助手", "ERROR")
            self._send({"type": "rescreenshot_failed"})
            return

        def on_complete(local_path):
            # 运行在 adb 工作线程：只写 stdin（带锁），不碰 Tk
            if local_path and os.path.exists(local_path):
                self._send({"type": "new_image", "path": local_path})
            else:
                self._send({"type": "rescreenshot_failed"})

        try:
            self.adb_helper.take_screenshot(self.temp_dir, on_complete)
        except Exception as e:
            self._log(f"重新截图异常: {e}", "ERROR")
            self._send({"type": "rescreenshot_failed"})

    # ---- 子进程 stderr：只留尾部用于异常退出诊断，不转发常规噪音 ----

    def _stderr_loop(self):
        try:
            for line in self.proc.stderr:
                line = line.rstrip()
                if line:
                    self._stderr_tail.append(line)
        except Exception:
            pass
