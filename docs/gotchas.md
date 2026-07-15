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

### 部分老 / 定制 ROM 设备的 `screenrecord` 用不了，机制不同但都无法绕过

**实测 OPPO A31 / ColorOS (Android 9, CPH2015EX_11_A.67)**：`adb shell screenrecord ...` 报 `/system/bin/sh: screenrecord: not found`；但 `ls -l /system/bin/screenrecord` 报 `Permission denied`（不是真的没这个文件，是 SELinux 拒绝 `shell` domain 访问/执行该二进制，exec 失败后 sh 呈现成"not found"）；`getenforce` = `Enforcing`；`screencap` 在同一台设备上完全正常，同一份 adb 连别的设备（SDK 36）`screenrecord --help` 也正常——所以这是**这台设备的定制 ROM 策略**，不是分辨率/编码器不兼容，也不是我们代码的问题，更不是 `_log_show_touches_permission_hint` 里提到的"权限监控"开关能解决的（那个只挡 `settings put`，这个是挡二进制执行）。

**实测华为 P9 / EMUI (Android 8.0.0.528, EVA-AL10)**：现象一样（`screenrecord: not found`），但机制不同——`ls -l /system/bin/screenrecord` 直接报 `No such file or directory`，全盘 `find / -iname 'screenrecord*'` 也搜不到，说明这个固件**压根没打包这个二进制**，不是权限/SELinux 问题。`screencap` 同样正常。

两台设备结论一样：**adb 录屏在这类设备上没有已知的绕过方法**（不是权限监控开关、不是 root 就能解决的），截图功能（`screencap`）不受影响。判断逻辑统一按 stderr 里是否含 `screenrecord` + `not found` 识别，不区分具体机制，因为用户侧都是"这台设备用不了 adb 录屏"。

现象链：`start_recording` 里 `screenrecord` 进程刚起来就因 SELinux 拒绝而退出 → `/sdcard/screen_record_tmp.mp4` 从未被创建 → `stop_recording` 里 `adb pull`/`adb shell rm` 都报 `No such file or directory`，表面像是文件没生成，其实是命令根本没跑起来。

`stop_recording`（[adb_helper.py:1364](../core/adb_helper.py:1364)）现在会检测 `recording_process` 是否在用户点停止之前就已经退出（`poll()`），捕获其 stderr，命中 `screenrecord ... not found` 时给出明确的"设备侧限制，非工具问题"提示，并通过 `on_complete(local_path, error_reason)` 把原因带到 UI 的失败弹窗里，不再是干巴巴的"录制失败"。目前没有已知的 adb 侧绕过方法（不是 root 设备的话）。

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

### Qt 预览子进程 stdin/stdout IPC 在 Windows 上不显式设编码会乱码

现象：截图预览窗口第一次截图正常，点击窗口内「➕重新截图」再截一次，日志面板里对应的中文提示（"正在重新截取屏幕..."、"重新截图失败或文件未生成"）变成乱码问号串；同一操作 macOS 上完全正常。

根因：`main.py` 的 `--qt-preview` 分支（[main.py:26](../main.py:26)）在拦截时直接 `sys.exit()` 进入 Qt 子进程，**没有**走到下面第 33 行那段给 `sys.stdout` 显式设 `encoding='utf-8'` 的兜底逻辑。子进程的 `sys.stdout`/`sys.stdin` 因此保持 Python 默认的管道流编码——非控制台管道在 Windows 上默认是系统 ANSI 代码页（简体中文系统是 GBK/cp936），**不是 UTF-8**。而父进程 [launcher.py](../ui/windows/qt_preview/launcher.py:61) 的 `subprocess.Popen(..., encoding="utf-8")` 是显式按 UTF-8 解码子进程的 stdout。子进程用 GBK 编码写中文 JSON 日志，父进程用 UTF-8 解码，两边不一致就乱码。macOS/Linux 非控制台流默认编码本身就是 UTF-8，所以从来没暴露过。

第一次截图的日志之所以正常，是因为那条消息是主窗口自己直接打印的，根本没走这条子进程 IPC 管道；只有经 `preview_app.py` 通过 stdout 回传给主进程的日志（重新截图相关）才会乱码。

解决：`preview_app.py:main()` 入口最开头，对 `sys.stdin`/`sys.stdout`/`sys.stderr` 逐个 `reconfigure(encoding='utf-8', errors='replace')`（Python 3.7+ 支持），必须在任何 IPC 读写之前执行。

排查同类问题的思路：**任何跨进程 stdin/stdout 文本 IPC，只要没有在两端都显式锁定同一编码，就是 Windows 专属地雷**——父进程指定了编码不代表子进程也用同一编码，Windows 的默认行为不是 UTF-8，Mac/Linux 是，所以本地 Mac 测试永远发现不了。

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

### 压缩 .app 必须 `zip -ry`，不加 `-y` 体积翻 4 倍

PyInstaller 打出的 `ADBHelper.app` 内部有 ~123 个符号链接（`Contents/Resources` ↔ `Contents/Frameworks` 互连、Qt framework 内 `Versions/Current` 等），`du -sh` 看只有 103MB。`zip -r` **默认把 symlink 展开成真实拷贝**：zip 39MB → 160MB，用户解压后 437MB（Resources/Frameworks 各一份完整拷贝）。加 `-y`（`--symlinks`）保留链接即可，`unzip` / Finder 归档工具解压都能正常还原。

排查此问题时踩过的弯路（都不是原因，别再走）：
- ❌ 怀疑 PyInstaller 6.21.0 双拷贝行为 → 锁 6.20.0 无效
- ❌ 怀疑 PySide6-Essentials 6.11.1 → 锁 6.10.3 无效
- ✅ 特征识别：解压后 Resources 与 Frameworks 内容成对重复、且本地 `du` 与 CI zip 体积对不上 → 先查 symlink

版本锁（pyinstaller==6.20.0、PySide6-Essentials==6.10.3）保留是为了 CI 与本地一致、避免再次版本漂移误诊，升级前本地打包验证一遍即可。

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

### `push_files` 推文件夹在老设备（Android 8 及更早）上会被 20s 通用超时误杀

现象：给 Android 8.0 设备推文件夹（多个文件）会超时失败，报 `命令执行超时`；推单个文件正常。

根因：`execute_adb_command` 原来统一用 `SHELL_TIMEOUT=20s`（这个值是给 `ls`/`getprop` 这类瞬时 shell 命令设计的），`push_files` 也复用它，文件夹和单文件一视同仁。Android 9 之前的 adb sync 协议没有管线化优化，多文件目录 push 是逐个走 stat+传输，比单文件慢得多；文件数一多（如 23 个 mp3）在老设备/老 USB 栈上很容易超过 20s，而 push 本身其实还在正常进行，只是被我们自己的 subprocess timeout 提前杀掉。

解决：`execute_adb_command(cmd_list, check_dev=True, timeout=None)` 新增可选 `timeout` 参数（不传则回退到 `SHELL_TIMEOUT`）；`push_files` 的 `adb push` 命令和文件夹场景下的媒体扫描 `find -exec` 命令都显式传 `PUSH_TIMEOUT=300`（单文件场景的媒体扫描仍用默认 20s，因为只有一次 broadcast，够用）。`push_files` 已经跑在子线程（`tools_tab.py` 的 `_push_thread`），延长超时不会冻住 UI。

### 华为 P9 (EVA-AL10) 等老 / 定制 ROM 设备，推大文件夹时 USB 连接会中途自己掉线又恢复

现象：修完上面的超时坑后，同一台设备（华为 P9, EMUI, Android 8.0.0.528, EVA-AL10——就是 [gotchas.md `screenrecord`](#screenrecord) 那条里同一台问题机）推 30 个 mp3 的文件夹，推到 80%（24/30 完成）时中止，报 `adb: error: failed to read copy response: EOF`，不是超时（用时仅 7s，远小于 `PUSH_TIMEOUT`）。

排查：设备当时接着电脑，我直接手动跑 `adb devices` 复现——**两次调用之间设备自己从列表消失了，15s 左右后又自动重新出现**。说明这不是超时或代码 bug，是这台设备的 USB/adbd 连接本身在长耗时传输中途会随机掉线又自愈（老 ROM 常见毛病，和 P9 这台机型已知的 `screenrecord` SELinux 限制是同一类"这台设备比较特殊"问题，但机制不同——这次是传输层连接问题，不是 SELinux 拦截）。

验证 `adb push <dir>/. <remote>` 的重试语义时发现一个容易想当然错的点：**它不是增量同步**，不会跳过已存在且内容相同的文件——同一批 30 个 mp3 掉线后已有 25 个到设备，手动重新 push 整个目录，日志显示 `30 files pushed, 0 skipped`，也就是**全部重传了一遍**，不是只补传缺的 5 个。`adb sync` 才有跳过语义，`adb push` 没有。

解决：`push_files`（[core/adb_helper.py:708](../core/adb_helper.py:708)）给 `adb push` 命令加了重试——遇到 `_is_retryable_push_error()` 判定为连接类错误（`failed to read copy response` / `eof` / `device offline` / `device not found` / `no devices` / `protocol fault` / `connection reset`）时，调用 `_wait_for_device_reconnect()` 轮询等设备重新出现在 `adb devices`（最长 `PUSH_RECONNECT_WAIT=20s`），再原样重跑同一条 push 命令，最多重试 `PUSH_RETRIES=2` 次。像"存储空间不足"这类非连接类错误不在重试名单里，会直接判失败，不做无意义等待。重传是整份重来（见上），对小文件夹代价可忽略；大文件夹反复掉线会变慢，但目前没有比"整份重传"更好的手段（`adb push` 没有断点续传）。

### `adb install` 在性能较差的设备上也会被 20s 通用超时误杀

现象：装 apk 时报 `命令超时 (20s)`，但 apk 本身没什么问题，换台好设备装同一个包就正常。

根因：和上面 push 的坑是同一类问题，但触发点不同——`install_apk`（`app_manage_tab.py` 里"安装选中的 APK"走的异步路径，经 `run_adb_async`）、`install_apk_sync`（拖拽安装走的同步路径）以及首次发文本自动装 ADBKeyboard 的那次 `adb install`，原来都没传 `timeout`，一律落到 `SHELL_TIMEOUT=20s`。`adb install` 装完 apk 后设备端还要做 dex/ART 优化编译，存储慢或 CPU 弱的设备这一步可能远超 20s，install 其实还在正常跑，只是被我们自己的 timeout 提前杀掉。

解决：新增 `INSTALL_TIMEOUT=300`；`run_adb_async` 补上 `timeout` 透传参数；上述三处 `adb install` 调用全部显式传 `timeout=self.INSTALL_TIMEOUT`。`install_apk`（异步）和 `install_apk_sync`（拖拽安装的调用方自己开了线程）都不在主线程阻塞，延长超时安全。

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

### 删除设备文件也要通知媒体库（按文件/文件夹分两种取路径方式）

`rm` 删文件后 MediaStore 不会自动更新，相册/音乐 App 里残留点不开的"幽灵条目"（Android 重启/重挂载时才自愈）。对一个**已不存在**的路径发 `MEDIA_SCANNER_SCAN_FILE` 广播，MediaScanner 会发现文件没了并删掉对应行——同一广播既入库又清库。

要广播的路径怎么拿，两种情况**别混淆**：

- **单个文件**：调用方传进来的路径就是它本身，删完直接广播这条，**不需要 find**。
- **文件夹**：MediaStore 一行对应一个**文件**（按各文件全路径 `_data` 记录），广播文件夹路径没用。必须拿到内部每个文件的路径，而 `rm -rf` 之后就枚举不到了——所以**仅文件夹**需要"删除前先 `find '<dir>' -type f` 收集清单"。

`delete_device_file(remote_path, is_dir=...)` 由调用方传入类型（文件管理器 tree 的"类型"列 `值=="文件夹"` 直接知道，无需额外 adb 查询）。实现细节：

- 广播路径转 `/storage/emulated/0/` 形式与 MediaStore `_data` 对齐
- 路径由 Python 逐个单引号化，处理空格/特殊字符
- 按 100 个一批拼接，避免大文件夹单条 shell 命令超 ARG_MAX
- 收集/扫描失败都不影响删除主流程（顶多残留幽灵条目）

### macOS Retina 下 Tkinter Canvas 显示位图必然模糊（Tk 无解，已用 Qt 子进程根治）

Tk Canvas 的 `PhotoImage` 位图在 macOS Retina（2x）下被系统拉伸 → 糊。**矢量绘制（rectangle/line/text）清晰，唯独位图 1x**，是 Tk 固有限制。2026-06/07 三轮隔离实测全部失败，别再试：升 Tk9、换 ctk6 CTkImage、喂 2× 位图（清晰但显示成两倍大，Tk 恒按 1 图像 px = 1 point 栅格化）、ctk `widget_scaling=2.0 + window_scaling=0.5` 对冲（只改控件 geometry，改不了位图栅格化）。注意：**截图文件本身不糊**（adb screencap 是原生分辨率）。

根治（2026-07-09 已实施，见 [handoff_retina_preview_migration.md](handoff_retina_preview_migration.md)）：截图预览标注窗迁移为 **PySide6 独立子进程**（`ui/windows/qt_preview/`），Tk 版保留作 PySide6 缺失时的兜底。相关约束：

- **Tk/Qt 两个 event loop 不能同进程共存**，必须子进程隔离；子进程入口复用 `main.py --qt-preview`（避免 PyInstaller 第二打包目标）
- `main.py` 的 `--qt-preview` 拦截必须在 **stdout 重定向到 crash log 之前**，否则 IPC 通道被劫持
- `screenshot_preview/__init__.py` 必须保持 **PEP 562 惰性导出**：Qt 子进程要 import 包内的 `shared`/`export`（纯 PIL），eager import 会把 ctk/tkinter 拉进 Qt 进程
- 重截不让子进程碰 adb，走 IPC 回主进程调 `adb_helper.take_screenshot`（serial/别名/尺寸后缀天然正确）；`on_complete` 在 adb 工作线程触发，launcher 里只做带锁的 stdin 写，不碰 Tk
- **QGraphicsView 平移受滚动范围钳制**：sceneRect=图像时，图像整幅可见（初始 fit 缩放）滚动范围为 0，✋/空格平移完全拖不动。解法是 `update_scene_margins()` 给场景四周扩一圈视口大小的余量（缩放/视口 resize 时都要更新），恢复 Tk 版自由平移。扩余量后滚动条必须 `ScrollBarAlwaysOn`：按需显示的话，初始 fit 按"无滚动条视口"计算 → 滚动条随后出现挤掉一条边 → 图像底部被遮一截。另：所有按钮/滑块要 `setFocusPolicy(NoFocus)`，否则空格会触发聚焦按钮而不是临时平移
