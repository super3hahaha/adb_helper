# -*- coding: utf-8 -*-
"""
自动更新模块。

职责划分：
- `parse_version` / `is_newer`：纯函数，做语义化版本号比较。
- `Updater`：封装 GitHub Releases 查询、资源包下载、Windows 下的替换重启。
  所有网络请求都在后台线程跑，通过回调与 UI 交互，本模块不直接触碰 UI。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import requests  # 优先使用 requests，支持 stream 下载
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

from core.config import APP_VERSION, GITHUB_REPO
from core.platform_utils import PlatformUtils


def parse_version(v):
    """把 '1.0.3' / 'v1.0.3' 解析为整型元组；非数字段会被忽略。"""
    v = (v or "").lstrip("vV").strip()
    parts = re.split(r"[.\-+]", v)
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            break
    return tuple(result) if result else (0,)


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


class Updater:
    API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    TIMEOUT = 15
    _USER_AGENT = "adb_helper-updater"

    def __init__(self, current_version=APP_VERSION):
        self.current_version = current_version
        self._cancel = threading.Event()

    # ---------- 版本检查 ----------
    def check_async(self, on_result, on_error):
        """
        on_result(info | None)：None 表示已是最新；info 为新版本字典
        on_error(msg_str)
        """
        threading.Thread(
            target=self._check_thread,
            args=(on_result, on_error),
            daemon=True,
        ).start()

    def _check_thread(self, on_result, on_error):
        try:
            req = Request(
                self.API_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": self._USER_AGENT,
                },
            )
            with urlopen(req, timeout=self.TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            tag = data.get("tag_name", "")
            remote_ver = tag.lstrip("vV").strip()
            if not remote_ver:
                on_error("Release 数据缺少 tag_name")
                return

            if not is_newer(remote_ver, self.current_version):
                on_result(None)
                return

            asset = self._pick_asset(data.get("assets") or [])
            if not asset:
                on_error(
                    f"未在 Release {tag} 中找到适合当前平台"
                    f"（{PlatformUtils.get_os_type()}）的资源包"
                )
                return

            on_result({
                "version": remote_ver,
                "tag": tag,
                "body": data.get("body") or "",
                "asset_name": asset["name"],
                "asset_url": asset["browser_download_url"],
                "asset_size": int(asset.get("size") or 0),
            })
        except HTTPError as e:
            if e.code == 403:
                on_error("GitHub API 速率限制（HTTP 403），请稍后再试。")
            elif e.code == 404:
                on_error("仓库或 Release 不存在（HTTP 404），请检查仓库名。")
            else:
                on_error(f"GitHub API 返回 HTTP {e.code}: {e.reason}")
        except URLError as e:
            on_error(f"网络请求失败: {e.reason}")
        except (TimeoutError, OSError) as e:
            on_error(f"网络超时或连接异常: {e}")
        except Exception as e:
            on_error(f"检查更新时发生未知错误: {e}")

    def _pick_asset(self, assets):
        """
        CI 产物命名约定（见 .github/workflows/build.yml）：
          - Windows: ADBHelper-vX.Y.Z.exe
          - macOS : ADBHelper-macOS-vX.Y.Z.zip
        """
        os_type = PlatformUtils.get_os_type()
        for a in assets:
            name = (a.get("name") or "").lower()
            if os_type == "win" and name.endswith(".exe"):
                return a
            if os_type == "mac" and "macos" in name and name.endswith(".zip"):
                return a
        return None

    # ---------- 下载 ----------
    def download_async(self, asset_url, asset_name, on_progress, on_complete, on_error):
        """
        on_progress(downloaded:int, total:int) total 可能为 0（GitHub redirect 后丢失 header）
        on_complete(save_path:str)
        on_error(msg:str)
        返回 cancel() 函数，调用它可中止下载
        """
        self._cancel.clear()
        threading.Thread(
            target=self._download_thread,
            args=(asset_url, asset_name, on_progress, on_complete, on_error),
            daemon=True,
        ).start()
        return self._cancel.set

    def _download_thread(self, url, asset_name, on_progress, on_complete, on_error):
        save_path = os.path.join(tempfile.gettempdir(), f"adb_helper_update_{asset_name}")
        try:
            if _HAS_REQUESTS:
                self._download_requests(url, save_path, on_progress)
            else:
                self._download_urllib(url, save_path, on_progress)

            if self._cancel.is_set():
                self._safe_remove(save_path)
                on_error("下载已取消")
                return

            on_complete(save_path)
        except Exception as e:
            self._safe_remove(save_path)
            on_error(f"下载失败: {e}")

    def _download_requests(self, url, save_path, on_progress):
        with requests.get(url, stream=True, timeout=self.TIMEOUT, allow_redirects=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if self._cancel.is_set():
                        return
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    on_progress(downloaded, total)

    def _download_urllib(self, url, save_path, on_progress):
        req = Request(url, headers={"User-Agent": self._USER_AGENT})
        with urlopen(req, timeout=self.TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(save_path, "wb") as f:
                while True:
                    if self._cancel.is_set():
                        return
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    on_progress(downloaded, total)

    @staticmethod
    def _safe_remove(path):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    # ---------- 应用更新（Windows） ----------
    def apply_update_windows(self, new_exe_path):
        """
        生成临时 bat：等当前进程退出 → 替换 exe → 启动新版 → 自删除。
        调用方应在此方法返回后立即退出主程序（bat 会轮询等待）。
        仅在打包后（sys.frozen）有效；开发模式会抛异常，由上层转给 UI 提示。
        """
        if not getattr(sys, "frozen", False):
            raise RuntimeError(
                "当前处于开发模式（非打包运行），无法自动替换。\n"
                f"更新包已下载至：{new_exe_path}"
            )

        current_exe = sys.executable
        current_dir = os.path.dirname(current_exe)
        current_exe_name = os.path.basename(current_exe)

        # 资源包名形如 ADBHelper-v1.0.3.exe，剥离前缀后作为目标文件名
        target_name = os.path.basename(new_exe_path)
        if target_name.startswith("adb_helper_update_"):
            target_name = target_name[len("adb_helper_update_"):]
        target_exe = os.path.join(current_dir, target_name)

        bat_path = os.path.join(tempfile.gettempdir(), "adb_helper_update.bat")
        log_path = os.path.join(tempfile.gettempdir(), "adb_helper_update.log")
        # 所有命令都 append 到 log，便于失败后排查
        bat_lines = [
            "@echo off",
            "setlocal",
            f'set "OLD_EXE={current_exe}"',
            f'set "OLD_NAME={current_exe_name}"',
            f'set "NEW_SRC={new_exe_path}"',
            f'set "NEW_DST={target_exe}"',
            f'set "LOG={log_path}"',
            'echo [START] %date% %time% > "%LOG%"',
            'echo Waiting for %OLD_NAME% to exit...',
            'echo Waiting for %OLD_NAME% to exit... >> "%LOG%"',
            ':wait_loop',
            'tasklist /FI "IMAGENAME eq %OLD_NAME%" 2>nul | find /I "%OLD_NAME%" >nul',
            'if not errorlevel 1 (',
            '    ping -n 2 127.0.0.1 >nul',
            '    goto wait_loop',
            ')',
            'echo Replacing executable...',
            'echo Replacing %NEW_SRC% -> %NEW_DST% >> "%LOG%"',
            'move /Y "%NEW_SRC%" "%NEW_DST%" >> "%LOG%" 2>&1',
            'if errorlevel 1 (',
            '    echo [FAIL] move returned errorlevel %errorlevel% >> "%LOG%"',
            '    echo Update failed: cannot move new file. See %LOG%',
            '    ping -n 5 127.0.0.1 >nul',
            '    exit /b 1',
            ')',
            'if /I not "%OLD_EXE%"=="%NEW_DST%" if exist "%OLD_EXE%" del /F /Q "%OLD_EXE%" >> "%LOG%" 2>&1',
            'echo Starting new version...',
            'echo Starting %NEW_DST% >> "%LOG%"',
            'start "" "%NEW_DST%"',
            'echo [DONE] %date% %time% >> "%LOG%"',
            'endlocal',
            '(goto) 2>nul & del /F /Q "%~f0"',
        ]
        with open(bat_path, "w", encoding="ascii", errors="ignore", newline="\r\n") as f:
            f.write("\n".join(bat_lines))

        # CREATE_NEW_CONSOLE 让 bat 拿到一个真正的控制台（会闪一下黑窗）——
        # 旧实现用 DETACHED_PROCESS 导致 tasklist/timeout 无控制台可用而静默失败。
        # CREATE_NEW_PROCESS_GROUP 保证父进程退出不会把 bat 也带走。
        CREATE_NEW_CONSOLE = 0x00000010
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
