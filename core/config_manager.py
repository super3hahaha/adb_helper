import json
import os
from core.platform_utils import PlatformUtils

class ConfigManager:
    DEFAULT_CONFIG = {
        "apk_dir": "",
        "temp_dir_path": "",  # 为空时默认使用项目根目录下的 temp 文件夹
        "pinned_app": None,
        "auto_launch_enabled": False,
        "hide_global_log": False,
        "default_device_pull_path": "/sdcard/temp/",
        "apps": [],  # 格式: [{"name": "示例App", "pkg": "com.example.app", "keyword": "example"}]
        "hidden_apks": [],  # 隐藏的 APK 相对路径列表
        "filter_words": []  # Logcat 自定义过滤词（快捷标签），格式: ["com.pkg.a", "Error", ...]
    }

    def __init__(self):
        # 配置文件存放在系统应用数据目录下
        app_data_dir = PlatformUtils.get_local_appdata_path("VisualADBManager")
        self.CONFIG_FILE = os.path.join(app_data_dir, "config.json")
        
        # 兼容旧版本：如果根目录下有旧的 config.json，且新目录没有，则移动过去
        old_config = "config.json"
        if os.path.exists(old_config) and not os.path.exists(self.CONFIG_FILE):
            try:
                import shutil
                shutil.copy(old_config, self.CONFIG_FILE)
            except Exception as e:
                print(f"Failed to migrate old config: {e}")

        self.data = self.load_config()

    def load_config(self):
        if not os.path.exists(self.CONFIG_FILE):
            self.save_config(self.DEFAULT_CONFIG)
            return self.DEFAULT_CONFIG
        try:
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return self.DEFAULT_CONFIG

    def save_config(self, data=None):
        if data is None:
            data = self.data
        try:
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get_temp_dir(self):
        path = self.data.get("temp_dir_path", "")
        if not path:
            return os.path.join(os.getcwd(), "temp")
        return path

    def set_temp_dir(self, path):
        self.data["temp_dir_path"] = path
        self.save_config()

    def get_apk_dir(self):
        return self.data.get("apk_dir", "")

    def set_apk_dir(self, path):
        self.data["apk_dir"] = path
        self.save_config()

    def get_apps(self):
        apps = self.data.get("apps", [])
        pinned = self.data.get("pinned_app")
        
        if not pinned:
            return apps
            
        # 简单排序：置顶 App 排在第一位
        sorted_apps = []
        others = []
        for app in apps:
            if app["name"] == pinned:
                sorted_apps.append(app)
            else:
                others.append(app)
        
        return sorted_apps + others

    def get_pinned_app(self):
        return self.data.get("pinned_app")

    def set_pinned_app(self, app_name):
        self.data["pinned_app"] = app_name
        self.save_config()

    def get_auto_launch_enabled(self):
        return self.data.get("auto_launch_enabled", False)

    def set_auto_launch_enabled(self, state):
        self.data["auto_launch_enabled"] = state
        self.save_config()

    def get_hide_global_log(self):
        return self.data.get("hide_global_log", False)

    def set_hide_global_log(self, state):
        self.data["hide_global_log"] = state
        self.save_config()

    def get_default_device_pull_path(self):
        return self.data.get("default_device_pull_path", "/sdcard/temp/")

    def set_default_device_pull_path(self, path):
        self.data["default_device_pull_path"] = path
        self.save_config()

    def get_hidden_apks(self):
        return self.data.get("hidden_apks", [])

    def set_hidden_apks(self, hidden_list):
        self.data["hidden_apks"] = hidden_list
        self.save_config()

    def add_app(self, name, pkg, keyword):
        # 简单去重逻辑：如果名字相同则更新
        apps = self.data.get("apps", [])
        for app in apps:
            if app["name"] == name:
                app["pkg"] = pkg
                app["keyword"] = keyword
                self.save_config()
                return
        
        apps.append({"name": name, "pkg": pkg, "keyword": keyword})
        self.data["apps"] = apps
        self.save_config()

    # ========== Logcat 自定义过滤词 ==========
    def get_filter_words(self):
        return self.data.get("filter_words", [])

    def add_filter_word(self, word):
        """添加过滤词。重名视为失败（返回 False）。"""
        word = (word or "").strip()
        if not word:
            return False
        words = self.data.get("filter_words", [])
        if word in words:
            return False
        words.append(word)
        self.data["filter_words"] = words
        self.save_config()
        return True

    def update_filter_word(self, old, new):
        """原位更新过滤词，保持顺序。"""
        old = (old or "").strip()
        new = (new or "").strip()
        if not old or not new or old == new:
            return False
        words = self.data.get("filter_words", [])
        if old not in words or new in words:
            return False
        idx = words.index(old)
        words[idx] = new
        self.data["filter_words"] = words
        self.save_config()
        return True

    def delete_filter_word(self, word):
        words = self.data.get("filter_words", [])
        if word not in words:
            return False
        words.remove(word)
        self.data["filter_words"] = words
        self.save_config()
        return True

    def delete_app(self, name):
        apps = self.data.get("apps", [])
        original_len = len(apps)
        apps = [app for app in apps if app["name"] != name]
        
        if len(apps) == original_len:
            return False  # 未找到
            
        self.data["apps"] = apps
        
        # 安全校验：如果删除的是全局置顶 App，则重置为第一个或 None
        if self.data.get("pinned_app") == name:
            if len(apps) > 0:
                self.data["pinned_app"] = apps[0]["name"]
            else:
                self.data["pinned_app"] = None
                
        self.save_config()
        return True
