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
- **Android 10 及更早**：用 `mStableInsets=Insets{left=L, top=T, right=R, bottom=B}` 或 `stableInsets=[L,T][R,B]`，是"insets 厚度"而不是 frame，直接 L/T/R/B 就是各方向占用。

`adb_helper.get_screen_info()` 用同一个正则同时兼容 Android 11/12+ 两种 InsetsSource fmt（接受任意 type 名 + 可选 id 段），落空再退到 Android 10 的 stableInsets 格式。新机型如果再出新 fmt，先 dump 一份原始输出再补正则。

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
