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

### 媒体扫描全版本统一用 `am broadcast`，别用 `content call scan_file`

`push_files` 推完文件后触发媒体扫描，**所有 API 版本都只用** `am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://<path>`。这条 intent 自 Android Q 起官方标记 deprecated，但实测它才是跨版本最可靠的——`content call scan_file` 反而到处坏：

| 方法 | 三星 Note9 / A10 | Pixel 4 / A13 | A7-9 |
|---|---|---|---|
| `content call scan_file` | 静默 no-op（零输出、不入库） | **每次必抛 NPE** `Uri.getPath() on null` | 没实现该 call() 方法 |
| `am broadcast MEDIA_SCANNER_SCAN_FILE` | 正常触发 | 正常，且实测真写进 MediaStore.Audio | 正常 |

- **三星 Note9 / Android 10 (One UI 2)** 实测：导入 20 个 mp3，per-file `content call scan_file` **全程零 stdout**（正常设备每个文件应回 `Result: Bundle[...]`），文件进了设备但音乐 App/媒体库看不到。这就是"导入后没通知媒体库刷新"的根因。
- **Pixel 4 / Android 13** 实测：`content call ... scan_file --arg <path>` 无论路径在 Download 根还是子目录、无论加不加引号，**每次都抛** `java.lang.NullPointerException: ...Uri.getPath() on a null object reference`。同一文件用 broadcast 则正常，`content query --uri content://media/external/audio/media --where "_data='<path>'"` 能查到新插入的行。
- **Android 7-9**：MediaProvider 压根没实现 `scan_file` 这个 call() 方法，命令 exit 0、输出全空，no-op。

为什么 broadcast 的"deprecated + file:// StrictMode 不可靠"担忧不成立：`file://` 的 StrictMode 限制是 `FileUriExposedException`，**只管 app 进程内**通过 Intent 暴露 file URI 的场景；从 adb shell 直接发 broadcast 不经过任何 app 的 VmPolicy，所以 `file://` URI 在 shell 端一直能用。Pixel A13 实测 `Broadcast completed: result=0` 且文件真入库。

排查"推了但文件管理器/媒体库没看到"时，**先看排序方式**：`adb push` 默认保留源文件的 mtime（常是几年前），文件管理器按日期排序时新推的文件会沉底，看着像没生效。`push_files` push 完会先 `touch` 把 mtime 改成设备当前时间再 scan，按日期排序就能看到新文件排在前面。

`scan_file` 只接受**单个文件路径**，传目录是 no-op。推文件夹时用 `find '<dir>' -type f -exec sh -c '...' {} \;` 逐个文件触发。路径要拼进 `file://<path>` URI，跨 toybox/busybox 的 substring 替换不一定稳，统一用 `sh -c '... "$0"' {}` 把路径以 `$0` 传给 inner shell，引号控制权交回 shell 自己。实测 Android 11/13/16 toybox 的 `find -exec` + `\;` 转义都正常。

其他替代方案为什么不用：
- `cmd media scan <path>`：Android 16 上 `cmd: Can't find service: media`，没这个服务。
- 按媒体后缀（jpg/mp4/...）过滤再扫：没必要。能否入库由系统侧 MediaScanner 按文件内容判断，对非媒体（如 .txt）调扫描也是 no-op、无副作用。

**MediaScanner 不认的格式扫了也没用**：`content call scan_file` 返回 `Bundle[...]` 看着成功，但 Android 原生 MediaScanner 只识别一份固定的 MIME 白名单（mp3/aac/m4a/ogg/wav/flac 等），**`.ape` / `.dsf` / `.wv` 等小众无损格式不会入 `MediaStore.Audio`**，音乐 App 看不到。文件本身在设备上、Files app 能看到（进 `MediaStore.Downloads`），但任何按 Audio collection 查询的 App 都查不到。这不是代码 bug，是 Android 系统限制，没法修。Pixel 7 / Android 16 实测：`.ape` 推到 `/sdcard/Download/` 后音乐 App 看不到，同位置 mp3 正常显示。

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

### `adb shell` 的参数会被设备端 sh 重新解析，路径必须自己单引号化

`subprocess.run([adb, "shell", "rm", "-rf", "/sdcard/foo (bar).mp3"])` 看起来是把路径当独立 argv 传，但 adb client 在发送到设备前会把所有 token 用空格拼成一条字符串，再交给设备端 `/system/bin/sh -c` 解析。结果就是 sh 看到的是：

```
rm -rf /sdcard/foo (bar).mp3
```

`( ) 空格 ; & | * ?` 全是 sh 元字符，直接报 `syntax error: unexpected '('`。

**解决**：调用方自己负责单引号化。`core/adb_helper.py` 顶部有 `_device_sh_quote()`，所有把"用户路径"塞给 `adb shell` 的位置都要包一层（`delete_device_file`、`list_device_files` 已修）。注意：

- `adb pull` / `adb push` 走 file-sync 协议，**不**经过设备 sh，原样传路径即可
- 内部硬编码的 `/sdcard/screen.png`、`/sdcard/screen_record_tmp.mp4` 不含特殊字符，可以不引号化（但加上也没坏处）
- 单引号转义就用 POSIX 套路 `'\''`，别用双引号（设备 sh 仍会展开 `$var` 和反引号）

### ADB 同步调用必须加 timeout，且耗时操作不能放主线程

Tkinter 单线程，UI 只能在主线程更新。`subprocess.run(adb ...)` 在设备休眠 / 未授权（等手机弹窗）/ USB 异常 / adb daemon 冷启动时会**长时间甚至无限阻塞**，直接冻住整个窗口——表现为「页面加载偶尔很慢」。

两条防线缺一不可：

1. **加 timeout**：`PlatformUtils.get_subprocess_kwargs(timeout=...)` 支持传秒数；`adb_helper.py` 里 `execute_adb_command` / `get_connected_devices` / `_shell_silent` 已分别用 `SHELL_TIMEOUT=20` / `DEVICES_TIMEOUT=10` 并捕获 `subprocess.TimeoutExpired`。新增同步 adb 调用记得照做，否则会有线程永久挂着。
2. **耗时调用放子线程**：`main_window.refresh_device_list` 已改为「子线程跑 `adb devices` → `self.after(0, self._apply_device_list)` 回主线程更新控件」。子线程里**绝不能碰任何控件**。回调里要 `winfo_exists()` 判窗口是否已关，并用 `_refreshing_devices` 标志防连点并发。

光做 1 不做 2：UI 仍会冻那几秒。光做 2 不做 1：卡死的线程没人回收，越积越多。

### CTkScrollableFrame 的 fit 防抖会导致切换 tab 时首屏宽度"抖一下"

`ui/utils.py` 的 `attach_scrollable` 给 `_fit_frame_dimensions_to_canvas`（把内层 frame 宽度对齐到 canvas）加了 80ms 防抖，目的是解决拖动窗口 resize 时嵌套圆角 frame 重绘卡顿。副作用：tab 第一次显示时，内层 frame 先以"请求宽度"渲染，80ms 后才 snap 到 canvas 真实宽度，肉眼可见地抖一下。

**解决**：给 canvas 额外绑 `<Map>`，在 tab 被 grid 显示的瞬间用 `after_idle` 立即 fit（并取消排队中的防抖）。`<Map>` 只在显示/切换 tab 时触发、拖动 resize 不触发，所以既消掉首屏抖动，又保留 resize 防抖。`<Configure>` 仍走防抖，不要去掉。

注意：`_fit_frame_dimensions_to_canvas(event)` 内部只读 `canvas.winfo_width()`，不使用 event 坐标，所以把 `<Map>` 的 event 传进去没问题。
