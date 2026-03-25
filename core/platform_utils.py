import os
import sys
import subprocess
import shutil

class PlatformUtils:
    @staticmethod
    def get_os_type():
        """返回当前操作系统类型: 'win', 'mac', 或 'linux'"""
        if sys.platform == "win32":
            return "win"
        elif sys.platform == "darwin":
            return "mac"
        else:
            return "linux"

    @staticmethod
    def get_adb_executable():
        """
        返回当前系统正确的 adb 可执行文件名。
        在 macOS 尤其是双击 .app 运行时，系统 PATH 可能不包含 /usr/local/bin 等路径，
        所以我们需要尝试找到 adb 的绝对路径。
        """
        if PlatformUtils.get_os_type() == "win":
            return "adb.exe"
            
        # Mac/Linux 寻找 adb 绝对路径
        # 常见安装路径：Homebrew (Intel/ARM), Android SDK 等
        common_paths = [
            "/opt/homebrew/bin/adb",      # Apple Silicon Homebrew
            "/usr/local/bin/adb",         # Intel Homebrew
            os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"), # Android Studio
        ]
        
        # 1. 尝试使用 shutil.which 从当前 PATH 查找
        adb_path = shutil.which("adb")
        if adb_path:
            return adb_path
            
        # 2. 从常见路径回退查找
        for path in common_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
                
        # 如果还是找不到，返回 'adb' 听天由命
        return "adb"

    @staticmethod
    def get_local_appdata_path(app_name="VisualADBManager"):
        """获取当前系统的软件缓存/配置目录"""
        os_type = PlatformUtils.get_os_type()
        if os_type == "win":
            base_path = os.getenv('APPDATA') or os.path.expanduser('~\\AppData\\Roaming')
            path = os.path.join(base_path, app_name)
        elif os_type == "mac":
            path = os.path.expanduser(f"~/Library/Application Support/{app_name}")
        else:
            path = os.path.expanduser(f"~/.config/{app_name}")
            
        # 确保目录存在
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            
        return path

    @staticmethod
    def get_subprocess_kwargs(capture_output=True, text=True):
        """获取跨平台的 subprocess 参数，处理编码和无窗口执行"""
        kwargs = {}
        if capture_output:
            kwargs['capture_output'] = True
        if text:
            kwargs['text'] = True
            # Subprocess 兼容: Mac 默认 UTF-8, Win 可能是 GBK
            kwargs['encoding'] = 'gbk' if PlatformUtils.get_os_type() == "win" else 'utf-8'
            kwargs['errors'] = 'replace'
            
        if PlatformUtils.get_os_type() == "win":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs['startupinfo'] = startupinfo
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            
        return kwargs

    @staticmethod
    def setup_dpi_awareness():
        """跨平台 DPI 适配，防止高分屏下字体发虚"""
        os_type = PlatformUtils.get_os_type()
        if os_type == "win":
            try:
                import ctypes
                # 告诉 Windows 当前应用是 DPI 感知的
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass
        elif os_type == "mac":
            # Mac 下通常由系统的 Info.plist 控制高分屏 (NSHighResolutionCapable)，
            # 但在纯 Python 环境运行中，如果遇到发虚，可通过环境变量提示 Tkinter
            # CustomTkinter 默认会自动处理缩放，这里显式配置确保不双重缩放
            pass
