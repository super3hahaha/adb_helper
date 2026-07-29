import json
import os
from core.platform_utils import PlatformUtils

class ConfigManager:
    DEFAULT_CONFIG = {
        "apk_dir": "",
        "temp_dir_path": "",  # 为空时默认使用项目根目录下的 temp 文件夹
        "pinned_app": None,
        "last_selected_app": None,
        "auto_launch_enabled": False,
        "hide_global_log": False,
        "default_device_pull_path": "/sdcard/temp/",
        "default_device_push_path": "/sdcard/Download/",
        "apps": [],  # 格式: [{"name": "示例App", "pkg": "com.example.app", "keyword": "example"}]
        "hidden_apks": [],  # 隐藏的 APK 相对路径列表
        "filter_words": [],  # Logcat 自定义过滤词（快捷标签），格式: ["com.pkg.a", "Error", ...]
        "device_aliases": {},  # 设备序列号 -> 别名，格式: {"0715f7bd99dd1b3a": "测试机 A"}
        # 曾经无线连接成功过的设备，供"重连已保存设备"一键恢复多台无线设备
        # 格式: [{"addr": "192.168.1.5:5555", "alias": "测试机 A", "last_seen": "2026-07-29 10:30"}]
        "wireless_devices": [],
        "skipped_update_version": ""  # 用户"暂不更新"跳过的版本号，出现更新的版本时会重新提示
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
        return self.data.get("apps", [])

    def get_last_selected_app(self):
        return self.data.get("last_selected_app")

    def set_last_selected_app(self, app_name):
        self.data["last_selected_app"] = app_name
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

    def get_default_device_push_path(self):
        return self.data.get("default_device_push_path", "/sdcard/Download/")

    def set_default_device_push_path(self, path):
        self.data["default_device_push_path"] = path
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

    # ========== 设备别名 ==========
    def get_device_aliases(self):
        """返回 {device_id: alias} 的字典副本。"""
        aliases = self.data.get("device_aliases", {})
        if not isinstance(aliases, dict):
            return {}
        return dict(aliases)

    def get_device_alias(self, device_id):
        """获取单个设备的别名，没有则返回空字符串。"""
        if not device_id:
            return ""
        return self.get_device_aliases().get(device_id, "")

    def set_device_alias(self, device_id, alias):
        """设置/更新设备别名。alias 为空字符串则删除该映射。返回 True 表示有变化。"""
        device_id = (device_id or "").strip()
        alias = (alias or "").strip()
        if not device_id:
            return False
        aliases = self.data.get("device_aliases", {})
        if not isinstance(aliases, dict):
            aliases = {}
        if alias:
            if aliases.get(device_id) == alias:
                return False
            aliases[device_id] = alias
        else:
            if device_id not in aliases:
                return False
            del aliases[device_id]
        self.data["device_aliases"] = aliases
        self.save_config()
        return True

    def delete_device_alias(self, device_id):
        return self.set_device_alias(device_id, "")

    def replace_device_aliases(self, mapping):
        """整体替换别名映射，用于导入。会做基本类型校验。"""
        if not isinstance(mapping, dict):
            return False
        cleaned = {}
        for k, v in mapping.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            k = k.strip()
            v = v.strip()
            if k and v:
                cleaned[k] = v
        self.data["device_aliases"] = cleaned
        self.save_config()
        return True

    def merge_device_aliases(self, mapping):
        """合并别名映射，相同 key 以传入的为准。返回新增/覆盖的条数。"""
        if not isinstance(mapping, dict):
            return 0
        aliases = self.data.get("device_aliases", {})
        if not isinstance(aliases, dict):
            aliases = {}
        changed = 0
        for k, v in mapping.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            k = k.strip()
            v = v.strip()
            if not k or not v:
                continue
            if aliases.get(k) != v:
                aliases[k] = v
                changed += 1
        if changed:
            self.data["device_aliases"] = aliases
            self.save_config()
        return changed

    # ========== 无线设备记录 ==========
    # 无线设备的 device_id 就是 "ip:port"，DHCP 换 IP 后旧记录会失效，
    # 所以这里只当"最近用过的地址"缓存看待，重连失败属正常情况，不清理由用户决定。
    def get_wireless_devices(self):
        """返回 [{"addr","alias","last_seen"}] 列表副本，按 last_seen 倒序（最近用过的在前）。"""
        items = self.data.get("wireless_devices", [])
        if not isinstance(items, list):
            return []
        cleaned = []
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("addr"), str) and it["addr"].strip():
                cleaned.append({
                    "addr": it["addr"].strip(),
                    "alias": (it.get("alias") or "").strip(),
                    "last_seen": (it.get("last_seen") or "").strip(),
                })
        cleaned.sort(key=lambda x: x["last_seen"], reverse=True)
        return cleaned

    def add_wireless_device(self, addr, alias=""):
        """记录/更新一台无线设备。同 addr 视为同一条，只刷新 last_seen 与非空别名。"""
        addr = (addr or "").strip()
        if not addr:
            return False
        import time as _time
        now = _time.strftime("%Y-%m-%d %H:%M")
        existing = self.get_wireless_devices()
        old = next((it for it in existing if it["addr"] == addr), None)
        items = [it for it in existing if it["addr"] != addr]
        items.append({
            "addr": addr,
            "alias": (alias or "").strip() or (old["alias"] if old else ""),
            "last_seen": now,
        })
        self.data["wireless_devices"] = items
        self.save_config()
        return True

    def remove_wireless_device(self, addr):
        """删除一条无线设备记录。返回 True 表示确实删掉了。"""
        addr = (addr or "").strip()
        items = self.get_wireless_devices()
        kept = [it for it in items if it["addr"] != addr]
        if len(kept) == len(items):
            return False
        self.data["wireless_devices"] = kept
        self.save_config()
        return True

    # ========== 自动更新：已跳过的版本 ==========
    def get_skipped_update_version(self):
        """返回用户上次"暂不更新"跳过的版本号（不含 v 前缀），没有则返回空字符串。"""
        return self.data.get("skipped_update_version", "") or ""

    def set_skipped_update_version(self, version):
        """记录用户跳过的版本号；传空字符串表示清除。"""
        self.data["skipped_update_version"] = version or ""
        self.save_config()

    def delete_app(self, name):
        apps = self.data.get("apps", [])
        original_len = len(apps)
        apps = [app for app in apps if app["name"] != name]
        
        if len(apps) == original_len:
            return False  # 未找到
            
        self.data["apps"] = apps
        self.save_config()
        return True
