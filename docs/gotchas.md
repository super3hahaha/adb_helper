# Gotchas

冷启动接手项目时容易踩的坑，按需补充。

## ADB

### `dumpsys window` insets 格式有多套

不同 Android 版本输出完全不同：

- **Android 11+（Samsung One UI 等）**：用 `InsetsSource type=ITYPE_XXX frame=[L,T][R,B]`，每个系统条带单独一行。`frame` 是该条带在屏幕上的矩形位置，所以：
  - 状态栏高度 = `frame.bottom - frame.top`
  - 导航栏高度 = `frame.bottom - frame.top`
  - 左/右手势区宽度 = `frame.right - frame.left`
- **Android 10 及更早**：用 `mStableInsets=Insets{left=L, top=T, right=R, bottom=B}` 或 `stableInsets=[L,T][R,B]`，是"insets 厚度"而不是 frame，直接 L/T/R/B 就是各方向占用。

`adb_helper.get_screen_info()` 已同时兼容两种，先试 Android 11+ 格式，落空再用旧格式。如果出现新机型解析失败，先 dump 一份原始输出再补正则。

### `dumpsys` 输出几十 KB，别走 `execute_adb_command`

`execute_adb_command` 默认会把 stdout 整段写进全局日志面板，dumpsys 一跑就把日志洗掉。屏幕信息查询用的是 `_shell_silent()`，绕过日志，专门给大输出场景用。

### `wm size` / `wm density` 有 Override 优先 Override

用户在「设置 → 显示 → 屏幕分辨率」改过分辨率，或开过显示模式调试时，会多出一行 `Override size: AxB`。这才是当前生效的值，原始 `Physical size` 是出厂值。Density 同理。

### `get_screen_info()` 有磁盘缓存，缓存键 = device_id + Configuration 串

落盘路径：`%LOCALAPPDATA%\VisualADBManager\screen_info_cache.json`（mac/linux 对应 appdata 目录）。

踩过的坑（按时间顺序）：
1. **`settings get system user_rotation`** 只反映用户设置；auto-rotate 开 + 物理转屏 → setting 不变 → 拿来当缓存键就会出现"明明横屏却显示竖屏"。
2. 改用 **`dumpsys window | grep -m1 mRotation`** 还不行：dumpsys 里 mRotation 字段有多个（每个 window/task 各一份），`-m1` 命中的常是某个滞后的 window 状态，从横屏切回竖屏经常拿到陈旧值。
3. 改用 **`grep -m1 'sw[0-9]+dp w[0-9]+dp h[0-9]+dp'`** 还是会错：第一个 Configuration 不一定是当前全局的，可能是某个 task/window 的快照。表现一样 —— 切回竖屏命中横屏缓存。
4. 现在用 **`am get-config`** 作探针：
   - Android 标准命令，输出当前 Configuration 串（含 `w###dp-h###dp-port|land` 等），< 200 字节
   - 转屏后立即更新，**单一权威源**，没有"多个候选 grep 选错"的可能
   - 从串里抓 `w(\d+)dp-h(\d+)dp` 作缓存键（如 `"w889h533"`）

最终展示的 "屏幕方向" 字段也以 Configuration w/h 比较为准（横屏 w>h），最权威。

- 命中缓存延迟从 ~500ms 降到 ~50ms。
- 方向变了自动重查并落盘。
- 想强制刷新：`get_screen_info(force_refresh=True)`，或直接删 json 文件。
- 如果用户在系统设置里改了分辨率/密度，缓存不会自动失效（rotation 没变）。这种是低频场景，目前不处理。
- Cache schema 版本号在 `screen_info_cache.py:_SCHEMA_VERSION`，改完字段记得 bump，老数据会被自动当作脏数据丢掉。

调用方（截图文件名拼"可用宽x可用高"那段）走默认缓存路径，加速截图。

### Cutout 字段名也不统一

`DisplayCutout{...}` 里早期是 `safeInsets=Rect(L, T - R, B)`，新版本是 `insets=Rect(...)`。两个都要兼容，全 0 视为「无」。
