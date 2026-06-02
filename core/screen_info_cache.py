"""屏幕信息缓存（per-device + per-rotation）。

为什么需要缓存：
- `get_screen_info()` 内部会跑 dumpsys window（输出几十 KB）+ 多次 getprop / settings get / wm 查询，
  每次累计 0.3~0.6s 延迟。截图功能要把可用宽 x 可用高 拼进文件名，每次都查会拖慢截图。
- 同一设备同一方向下，屏幕信息几乎不变。

缓存键设计：device_id + rotation（user_rotation 取值：0=竖屏 1=横屏 2=反向竖屏 3=反向横屏）。
方向变了会自动重新查询并落盘。

存储位置：与 config.json 同目录的 `screen_info_cache.json`。
"""

import json
import os
from core.platform_utils import PlatformUtils

_CACHE_FILE = os.path.join(
    PlatformUtils.get_local_appdata_path("VisualADBManager"),
    "screen_info_cache.json",
)

# 缓存 schema 版本：
# v1 -> 以 user_rotation 作为 key，自动旋转场景下会写入错误方向，弃用
# v2 -> 改用实际 mRotation 作为 key，但 dumpsys 里多个 mRotation 字段，grep -m1 取错的概率高
# v3 -> 横屏时 dp_w/dp_h/px_w/px_h 互换为当前方向值，避免 wm size 返回自然方向导致显示反了
# v4 -> 缓存键改为 Configuration w/h 字符串，但仍用 grep dumpsys，第一个匹配未必是当前全局
# v5 -> key 探针从 grep dumpsys 改为 `am get-config`，更可靠且更快
# v6 -> 修复 Android 12+ statusBars/navigationBars 解析，老缓存里 status_bar/nav_bar="未知" 的脏值需淘汰
# v7 -> 新增 Android 10 三星 ROM 的 BarController.* 兜底解析，淘汰这类机型遗留的 "未知" 脏缓存
# v8 -> 横屏修复：状态栏/导航栏厚度从 b-t 改为 min(w, h)，淘汰横屏下 nav_bar = 整个屏幕高度的脏缓存
# v9 -> 修复退化 frame (w=0 或 h=0) 误判为有效区域，淘汰横屏下 side_gesture = 屏幕高度 的脏缓存
# v10 -> 尊重 InsetsSource 的 visible=true/false，invisible 当 0；淘汰把不可见条带按潜在尺寸报的脏缓存
_SCHEMA_VERSION = 10


def _load():
    if not os.path.exists(_CACHE_FILE):
        return {}
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
    except Exception:
        return {}
    # 版本不匹配 / 无版本号（v1） -> 清空，避免脏数据
    if raw.get("_version") != _SCHEMA_VERSION:
        return {}
    raw.pop("_version", None)
    return raw


def _save(data):
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        payload = {"_version": _SCHEMA_VERSION, **data}
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get(device_id, rotation):
    """命中返回缓存的 info dict，否则返回 None。"""
    if not device_id:
        return None
    data = _load()
    return data.get(device_id, {}).get(str(rotation))


def put(device_id, rotation, info):
    """写入缓存。失败静默，不影响主流程。"""
    if not device_id:
        return
    data = _load()
    if device_id not in data:
        data[device_id] = {}
    data[device_id][str(rotation)] = info
    _save(data)


def clear(device_id=None):
    """清空指定设备或全部缓存。"""
    if device_id is None:
        _save({})
        return
    data = _load()
    if device_id in data:
        del data[device_id]
        _save(data)
