# Gotchas

冷启动接手项目时容易踩的坑，按需补充。

## ADB

### `dumpsys window` insets 格式有多套

不同 Android 版本输出完全不同：

- **Android 12+ / Pixel-AOSP / Android 16**：
  `InsetsSource id=<hex> type=statusBars frame=[L,T][R,B] visible=false ...`
  - `type=` 从 ITYPE 常量名改成 camelCase：`statusBars` / `navigationBars` / `displayCutout` / `systemGestures` / `mandatorySystemGestures` / `tappableElement` / `ime`
  - InsetsSource 和 type= 之间多一段 `id=<hex>`
  - 多了 `visible=true|false` —— 这是当前可见状态，**但 frame 本身仍是显示时的尺寸**，所以即便 visible=false 也要照样解析
  - **左/右手势区不再单独输出**为 `LEFT_GESTURES` / `RIGHT_GESTURES`，统一进 `systemGestures`，左右边由 `boundingRects=...` 描述（不在 frame 里）
- **Android 11**（早期 InsetsSource）：`InsetsSource type=ITYPE_XXX frame=[L,T][R,B]`。`frame` 是条带在屏幕上的矩形位置：
  - 状态栏高度 = `frame.bottom - frame.top`
  - 导航栏高度 = `frame.bottom - frame.top`
  - 左/右手势区宽度 = `frame.right - frame.left`
- **Android 10 三星 / 部分厂商 ROM**：InsetsSource 名字又换了一套，不是 `ITYPE_*`，是 `TYPE_TOP_BAR` / `TYPE_SIDE_BAR_1` / `TYPE_TOP_TAPPABLE_ELEMENT` / `TYPE_BOTTOM_TAPPABLE_ELEMENT` / `TYPE_TOP_GESTURES` 等。**这类厂商私有常量名穷举不完**，不要试图列别名。
- **Android 10 及更早**：用 `mStableInsets=Insets{left=L, top=T, right=R, bottom=B}` 或 `stableInsets=[L,T][R,B]`，是"insets 厚度"而不是 frame，直接 L/T/R/B 就是各方向占用。
- **Android 7-9 三星等 ROM**：`BarController.StatusBar` 只有 `mState=...`，**没有 `mContentFrame=`** 字段；也没有 `mStableInsets`。但 `WINDOW MANAGER POLICY STATE` 段始终输出 AOSP 标准的 `mUnrestrictedScreen=(L,T) WxH` 和 `mStable=(L,T)-(R,B)`，两者差值就是各方向 inset 像素。例（Note5/Android 7）：`mUnrestrictedScreen=(0,0) 1440x2560` + `mStable=(0,84)-(1440,2560)` → 状态栏 84 px ≈ 24 dp@560dpi，导航栏 0（物理 Home 键）。**注意要用 `\bmUnrestrictedScreen=` 锚定**，否则会误匹配 Samsung 私有字段 `OriginalmUnrestrictedScreen=(0,0) 0x0`（这会把厚度算成 0）。

**`adb_helper.get_screen_info()` 的解析顺序**：

1. 先按 `InsetsSource(?:\s+id=<hex>)?\s+type=(?:ITYPE_STATUS_BAR|statusBars)\s+frame=...` 同时匹配 Android 11/12+ 标准 fmt
2. 落空 → 退到 `BarController.StatusBar` / `BarController.NavigationBar` 的 `mContentFrame=Rect(L, T - R, B)`。这俩字段从 Android 7 一直存在到 10，跨厂商**比 InsetsSource type 名字稳得多**，三星魔改 Android 10 也照样有
3. 再落空 → 退到极旧的 `mStableInsets=Insets{...}` 或 `stableInsets=[...]`
4. 还落空 → 退到 `mUnrestrictedScreen` 与 `mStable` 的差值（Android 7-9 三星 ROM 兜底）

新机型再出新 fmt，先 dump 一份原始输出再补正则；**别在 step 1 里硬列三星 / 小米 / 华为各自的 TYPE_* 别名，那条路无止境**。

### 横屏时导航栏 frame 翻 90°，必须用 `min(w, h)` 拿厚度

竖屏：导航栏 frame `[0,2094][1080,2220]` → 宽 1080、高 126，水平条带
横屏：导航栏 frame `[2214,0][2340,1080]` → 宽 126、高 1080，**竖向条带**（被旋转到屏幕右侧）

直接拿 `frame.b - frame.t`（"高度"）当导航栏厚度，竖屏没问题，横屏会拿到整个屏幕高度 1080 px。后果：弹窗显示"导航栏 393 dp"，且可用高度 = dp_h − 状态栏 − 导航栏 = 负数。

正解：**取 `min(frame_w, frame_h)` 作为厚度**，无论横竖屏都正确。状态栏、导航栏、侧边手势都适用。Cutout 的 safeInsets 用法不同（按方向分四边），不受这个影响。

### 退化 frame (w=0 或 h=0) 表示"该区域不存在"，不是"零厚度细线"

dumpsys 里有些 InsetsSource 会给出退化的 frame（其中一维 = 0），表示该系统区域**不存在**而不是"零厚度"：

```
InsetsSource type=TYPE_LEFT_GESTURES  frame=[0,0][0,2220]    ← 宽 0，高 = 屏幕高
InsetsSource type=TYPE_RIGHT_GESTURES frame=[1080,0][1080,2220]  ← 宽 0，高 = 屏幕高
```

这表示"无左/右手势区"。但如果 thickness 计算时遇到 w=0 直接取 max(w,h)，就会把"屏幕高度"误当成厚度，弹窗会显示"侧边手势区 L 393 dp / R 393 dp"。

正解：**任一维 = 0 就视为该区域不存在，thickness = 0**。`thickness = min(w, h) if w > 0 and h > 0 else 0`。

### InsetsSource 的 `visible=true/false` 必须读

```
InsetsSource id=c85b0001 type=navigationBars frame=[0,2274][1080,2400] visible=false
```

`visible=false` 表示该条带**当前没有实际占据屏幕**——例：小米/MIUI 手势导航无指示条，nav bar 的 frame 仍报 47 dp 但 `visible=false`，App 内容能延伸到屏幕底部，用户视觉上不存在导航栏。

如果不看 visible 直接按 frame 报，弹窗会显示"导航栏 47 dp"，但截图/视觉上是 0 占用。

正解：**`visible=false` 直接 thickness=0**。Android 11 早期 fmt 没有这个字段，匹配不到时按可见处理（向前兼容）。

如果以后想区分"潜在保留尺寸"和"当前实际占用"，可以两个值都返回；目前只反映"当前实际占用"，这对截图、UI 测量等下游用途更直接。

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

### `screenrecord` 默认 20 Mbps，必须显式降码率

不传 `--bit-rate` 时 Android 用 20 Mbps，1 分钟 ≈ 150 MB。UI 录屏内容（纯色/文字）压缩效率极高，4 Mbps 肉眼无差、2 Mbps 仍清晰。`start_recording(bit_rate=...)` 默认 4 Mbps，约 30 MB/分钟。参数单位是 bps，传 `int`。

### `content call ... scan_file` 不递归，传文件夹用 `find -exec`

`content call --uri content://media --method scan_file --arg <path>` 只接受**单个文件路径**，传目录是 no-op，里面的文件不会进媒体库。`push_files` 推完一个文件夹后用 `adb shell find '<dir>' -type f -exec content call ... --arg {} \;`，一条命令把所有文件扫掉。实测 Android 11 / Android 16 toybox 的 `find -exec` + `\;` 转义都工作正常，每个文件都会单独触发 `content call` 并返回 `Result: Bundle[...]`，MediaStore 入库可用 `content query --uri content://media/external/audio/media --where "_data='<path>'"` 验证。

排查"推了但文件管理器/媒体库没看到"时，**先看排序方式**：`adb push` 默认保留源文件的 mtime（源文件常常是几年前的），文件管理器按日期排序时新推的文件会沉底，看着像没生效。`push_files` 里 push 完会先 `touch` 把 mtime 改成设备当前时间再 scan，这样按日期排序的文件管理器/媒体库就能看到新文件排在前面。

替代方案为什么都不用:
- `am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://...`：实测 Android 16 仍然能触发扫描，但 Android 7+ 对 `file://` URI 有限制、文档上不推荐，且和 `content call` 是单文件粒度同样的工作量。`content call` 既然在 11/16 都 work，没必要换。
- `cmd media scan <path>`：Android 16 上 `cmd: Can't find service: media`，没这个服务。
- 按媒体后缀（jpg/mp4/...）过滤：没必要。能否入库由系统侧 MediaScanner 根据文件内容判断，对非媒体（如 .txt）调 `scan_file` 也是 no-op、无副作用。

### `launch_app` 启动后会异步还原系统自动旋转开关

部分 app（铃声/视频/直播类常见）申请了 `WRITE_SETTINGS`，启动时会偷偷把 `Settings.System.ACCELEROMETER_ROTATION` 改成 1，每次 monkey 启动都会污染设备状态。

`adb_helper.launch_app()` 的处理：启动前快照 → 启动后异步等 2s → 变了就 put 回原值。绕过 `execute_adb_command`，用裸 `subprocess.run`，避免读 setting 的 `0`/`1` 输出把日志面板刷满。

锁定快照时的 `device_id`，restore 前比对 `current_device_id`，防止延迟期间用户切设备误伤别的机器。如果以后发现 2s 不够（某些 app 启动慢、改 setting 时机晚），可以改成轮询窗口（如 5s 内每 0.5s 检查一次）。

验证某个 app 是不是这种行为：
```
adb shell settings put system accelerometer_rotation 0
adb shell monkey -p <pkg> -c android.intent.category.LAUNCHER 1
adb shell settings get system accelerometer_rotation   # 变 1 就是
```

### Cutout 字段名也不统一

`DisplayCutout{...}` 里早期是 `safeInsets=Rect(L, T - R, B)`，新版本是 `insets=Rect(...)`。两个都要兼容，全 0 视为「无」。

## CI / 发版

### `actions/checkout@v4` 会把 annotated tag 退化成 lightweight

tag-push 触发的 workflow，checkout 内部其实做了两次 fetch：

```
1) fetch +refs/tags/*:refs/tags/*           ← tag object 和 annotation 完整拉下
2) fetch --no-tags +<commit-sha>:refs/tags/<name>  ← 强制让 ref 指向 commit sha
```

第二步把 `refs/tags/vX.Y.Z` 重写成指向 commit 而不是 tag object（tag object 还在 `.git/objects` 里没删，只是 ref 不指了）。后果：`git tag -l --format='%(contents)' vX.Y.Z` 退化为返回 commit message（git 对 lightweight tag 的回退行为），加 `fetch-tags: true` / `fetch-depth: 0` 都没用，因为第二步会再次覆盖。

解决：在 step 内手动恢复 ref：

```yaml
- name: Get tag annotation
  shell: bash
  run: |
    git fetch --tags --force origin   # 把 ref 还原回指向 tag object
    MSG=$(git tag -l --format='%(contents)' "${{ github.ref_name }}")
    ...
```

排查思路：如果发现 GitHub Release 的 body 跟 tag 注释对不上、变成了某个 commit 的 message，多半就是这个坑。验证手段是看 checkout step 日志里有没有 `t [tag update]` 字样。

### Workflow step 跑 Bash 脚本必须显式 `shell: bash`

windows-latest runner 的默认 shell 是 **PowerShell 7**（`pwsh`），写 `MSG=$(...)` 这类 Bash 赋值语法会直接报 `The term '...' is not recognized as a name of a cmdlet`。macOS / Ubuntu 默认就是 bash 所以察觉不到。

解决：跨平台 step 内涉及 Bash 语法时显式声明：

```yaml
- name: Get tag annotation
  shell: bash
  run: |
    MSG=$(...)
```

Windows runner 自带 Git Bash，`shell: bash` 会走它，不需要额外装。
