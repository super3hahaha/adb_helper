import os
import shutil
import subprocess
from core.platform_utils import PlatformUtils

class FileHelper:
    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        # 确保临时目录存在
        temp_dir = self.get_temp_dir()
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

    def get_temp_dir(self):
        """返回临时目录的绝对路径，如果不存在则创建"""
        if self.config_manager:
            path = self.config_manager.get_temp_dir()
        else:
            path = os.path.join(os.getcwd(), "temp")
        if not os.path.exists(path):
            os.makedirs(path)
        return path

    def open_temp_directory(self):
        """调用系统资源管理器打开 Temp 目录"""
        path = self.get_temp_dir()
        try:
            os_type = PlatformUtils.get_os_type()
            if os_type == "win":
                os.startfile(path)
            elif os_type == "mac":
                subprocess.run(['open', path])
            else:
                subprocess.run(['xdg-open', path])
            return True
        except Exception as e:
            print(f"打开目录失败: {e}")
            return False

    def clear_temp_directory(self):
        """清空 Temp 目录下的所有文件和文件夹，但保留 Temp 目录本身"""
        path = self.get_temp_dir()
        deleted_count = 0
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                    deleted_count += 1
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    deleted_count += 1
            return True, deleted_count
        except Exception as e:
            print(f"清理目录失败: {e}")
            return False, deleted_count
