# Handoff：截图预览 Retina 模糊 → PySide6 独立进程重写

> 状态：**已实施（2026-07-09），待真机验收**。方案 B′ 按本文落地，实施要点见文末第 11 节。
> 涉及模块：`ui/windows/qt_preview/`（新）、`ui/windows/screenshot_preview/`（保留作兜底）
> 2026-06-30 修订：核对代码后改写第 5、7、9 节 —— 跨进程耦合实为 4 项（log_func/重截/temp/transient），重截方案由「子进程自调 adb」改为「IPC 回主进程」；确认全量迁移 Qt 不划算（UI 层深度耦合 ctk，仅为不糊不值）。
> 2026-07-09 补充：另两个 demo 也实测失败——`retina_tile_demo.py`（喂 2× 位图：清晰但显示成两倍大，Tk 恒按 1 图像 px = 1 point 栅格化）、`retina_preview_demo_trick.py`（ctk widget_scaling 2.0 + window_scaling 0.5 对冲：只影响控件 geometry，改不了位图栅格化）。三个 demo 验证完毕可删。

## 1. 问题

macOS Retina（HiDPI，devicePixelRatio=2）下，app 内的截图预览/标注窗口显示**模糊**。

## 2. 根因（已确认，别再重新推演）

- **截图文件本身不糊**。`core/adb_helper.py:1389 take_screenshot` 走 `adb screencap`，抓的是手机原生分辨率（1080×2400 这类），高清。
- 糊在**显示层**：`canvas_mixin.py:70` 把原图 `resize` 成 Canvas 的**逻辑点尺寸**（macOS 上 `winfo_width()` 返回 points 不是物理像素），Tk 按 1x 把位图画到 Canvas，再由系统把整窗口放大 2x → 位图被拉伸 → 糊。
- **这是 Tk 在 macOS 的固有限制**：Tk Canvas 的矢量绘制（`create_rectangle`/`create_line`/`create_text`，即我们的标注）在新版 Tk 上是清晰的，**唯独 PhotoImage 位图是 1x**，没有干净可靠的绕过办法（`tk scaling`、按 2x 渲染再塞进去等都试无效或副作用）。
- **2026-06-30 隔离环境实测，已排除「升 Tk9 / 换 ctk6」两条路，别再试**：
  - **Tk 9.0.3**（brew `python-tk@3.13` 隔离 venv）：screencapture 量得 PhotoImage 恒为「1 图像像素 = 2 物理像素」（源竖线 4px 周期 → 抓到 8px 周期、黑条 2px，锐利最近邻翻倍）。`create_image` 无任何 scale/dpi item 选项。即 Tk9 仍按逻辑 point 栅格化位图，**不修**。信息论上：app 那条「先把原图缩到逻辑点尺寸再贴」的路任何 Tk 版本都救不了，数据在缩放步已丢。
  - **customtkinter 6.0.0 / `CTkImage`**：底层仍是同一个 `ImageTk.PhotoImage`；ctk 在 **macOS `widget_scaling=1.0`**（不把 Retina 当 2x），故 CTkImage 不生成高分图。用户在真机真截图上肉眼确认 `CTkImage` 与 `tk.Canvas+create_image` **一样糊**，只有「系统预览」清晰。`CTkImage` 还是 CTkLabel 上的静态图控件，无法画标注/缩放平移，**也无法顶替标注画布**。
  - 验证手段留痕：根目录 `retina_preview_demo.py`（点截图→同图三路并排：Canvas / CTkImage / 系统预览）。验证完即可删。
- 现状逃生口：`preview_window.py:345 _open_in_system_preview` —— "在 Preview 中查看"按钮，系统 Preview 原生 Retina，清晰。这是当时撞墙后的临时措施。

## 3. 已敲定的决策

| 决策 | 结论 | 理由 |
|---|---|---|
| 要不要换框架 | **要**（如果在线标注体验是硬需求） | Tk Canvas 位图 Retina 无解；只想"看清楚"则维持 Preview 入口即可，零成本 |
| Qt 选哪个 | **PySide6**，不要 PyQt6 | 都是 Qt6、API 几乎一样、都原生 HiDPI；PyQt6 是 GPL/商业授权会传染，PySide6 是 LGPL，分发闭源 app 不踩雷 |
| 全量迁移还是局部 | **局部** | 整个 app 是 customtkinter，全量换风险高、收益只为"不糊"不划算 |
| 同进程嵌入还是独立进程 | **独立进程** | Tk 的 `mainloop()` 和 Qt 的 `app.exec()` 都要独占主线程，**同进程混用会互相饿死/崩溃**；"定时 pump 另一个 loop"的偏方脆弱，不碰 |

## 4. 推荐方案 B′：独立 PySide6 子进程

预览/标注窗口本质是**纯函数式工具**：输入一张图 → 输出标注后的图。边界天然干净，适合进程隔离。

```
主 app (customtkinter)                        子进程 (PySide6, 独立 app.exec())
  ui/tabs/app_manage_tab.py
    show_screenshot_preview(image_path)
      └─ subprocess.Popen([                    preview_app.py <image_path> <temp_dir> [adb参数]
           sys.executable, "preview_app.py",      ├─ QGraphicsView 显示原图（Qt 全程 HiDPI，清晰）
           image_path, temp_dir, ...])            ├─ 矩形/箭头/文字标注交互
                                                   ├─ 保存 → 写回 image_path / 另存
  主进程不需要返回值：                              └─ 复制剪贴板（自包含）
  子进程写完文件，主进程照原路径读
```

进程隔离 → 两个事件循环互不干扰，根本不存在 loop 冲突。这正是 Snipaste 那类截图标注工具的通用做法。

## 5. 调用方改造点

- `ui/tabs/app_manage_tab.py:327 show_screenshot_preview` —— 当前直接 `ScreenshotPreviewWindow(self.winfo_toplevel(), image_path, log_func=self.log, adb_helper=self.adb_helper, temp_dir=temp_dir)`，改成 `subprocess.Popen([sys.executable, <preview_app入口>, image_path, temp_dir], stdin=PIPE, stdout=PIPE, text=True)`，并起一个后台线程读子进程 stdout（见第 7 节 IPC）。
- `ui/tabs/app_manage_tab.py:13` 的 import 删除或保留（看是否还留 Tk 版本兜底）。
- 入口约定（建议）：`python preview_app.py <image_path> <temp_dir>`。注意：**adb 相关参数不再走命令行**（serial 会变、别名是回调），重截改走 IPC 回主进程，见第 7 节。
- 调用方**不取返回值**（已确认：当前就是 `self.after(0, lambda: show_screenshot_preview(...))`，弹窗即走），所以无需等待子进程退出。

## 6. 代码复用清单

**可 100% 原样搬（纯 PIL/逻辑，与 UI 框架无关）：**
- `preview_window.py:504 get_annotated_image` —— 标注合成回 PIL Image，含越界自动扩画布。**核心资产，直接复用。**
- `shared.py` 全部：`font_size_from_width` / `get_pil_font` / `wrap_text_pil`（`preferred_tk_font` 可弃，Qt 用自己的字体 API）。
- `history_mixin.py`（62 行）—— Undo/Redo 栈是纯数据结构，逻辑可搬，只是触发点接 Qt。
- 剪贴板复制：`preview_window.py:439 copy_to_clipboard` 的 PIL→剪贴板逻辑可参考；Qt 有更简单的 `QClipboard.setImage()`，建议直接用 Qt 原生替换 osascript/win32clipboard 那套。

**需重写成 Qt（显示 + 交互层）：**
- `canvas_mixin.py` 整体 —— Tk Canvas 缩放/平移/重绘 → `QGraphicsView` + `QGraphicsScene`（自带缩放平移、HiDPI 清晰），或 `QLabel` + `QPainter`。坐标变换 `_img_to_canvas`/`_canvas_to_img` 的思路保留，换 Qt API。
- `drawing_tools_mixin.py`（125 行）—— 矩形/箭头鼠标事件 → Qt 的 `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`。
- `text_annotation_mixin.py`（528 行，最重）—— 8 控制点文字编辑器，Tk 手搓的。Qt 下可用 `QGraphicsTextItem` 大幅简化，但交互细节要重做，**这是工作量大头**。
- 工具栏/控制栏（`preview_window.py:133/222`）—— CTk 按钮 → Qt 的 `QToolBar`/`QPushButton`。

`shapes` 数据结构（每项 dict：`type`/`coords`/`color`/`width`，text 额外 `text`/`font_size`/`width_img`/`height_img`）建议**保持不变**，这样 `get_annotated_image` 零改动即可复用。

## 7. 跨进程必须处理的耦合（4 项，2026-06-30 核对代码后修订）

> 原版本只列了「重截依赖 adb」一个耦合，且推荐「子进程自调 adb」。核对代码后发现耦合有 4 项，且重截方案应改为 IPC。下面是修订后的完整清单。
>
> **核心结论：log_func 这条耦合逼我们无论如何都要建一条「父读子 stdout」的通道。一旦这条通道存在，把它做成双向，重截、日志、temp 通知就全搭在同一条通道上解决，子进程不碰 adb。** 这是整个改造的关键简化点。

### 7.1 IPC 通道（地基，先建这个）

`subprocess.Popen(..., stdin=PIPE, stdout=PIPE, text=True)`，父进程起后台线程逐行读子进程 stdout。约定子进程每行输出一条 JSON：

```
子进程 → 父进程（stdout，每行一条）：
  {"type":"log","level":"INFO","msg":"..."}      # 替代原 log_func 回调
  {"type":"rescreenshot"}                          # 请求重截
  {"type":"saved","path":"..."}                    # 通知主进程文件已写回（temp 一致性）
父进程 → 子进程（stdin，每行一条）：
  {"type":"new_image","path":"..."}                # 重截完成，回传新文件路径
```

### 7.2 log_func（原版本完全漏掉）

`preview_window.py` 有 ~13 处 `self.log_func(...)`（保存/删除/另存为/重截失败等），把消息写回主 app 日志面板。跨进程后回调断裂。
→ 子进程把这些调用改成 `print(json.dumps({"type":"log",...}), flush=True)`，父进程读到 `type:log` 转发给 `self.log(...)`。否则主 app 日志面板会静默丢这些用户可见反馈。

### 7.3 重新截图（**改为 IPC 回主进程，不再子进程自调 adb**）

原推荐「子进程自调 adb，照抄三行」**低估了依赖**。实际链路：
`take_new_screenshot`（preview_window.py:369）→ `adb_helper.take_screenshot`（adb_helper.py:1389）→ `execute_adb_command`（adb_helper.py:77，注入 `-s <serial>`、解析 adb 路径、`check_device()`、跨平台 subprocess kwargs）+ `get_screen_info()`（文件名尺寸后缀）+ `device_label_resolver` 回调（别名后缀）。

子进程复刻这一套 = 把 adb_helper 的基础设施抄一份，且主进程改逻辑时会漂移。

**改为：** 子进程点「➕重截」→ 发 `{"type":"rescreenshot"}` → 父进程**直接调现成的** `self.adb_helper.take_screenshot(temp_dir, on_complete)`（serial/别名/尺寸/超时/跨平台全部天然正确，主进程零改动）→ on_complete 拿到新路径后通过 stdin 发 `{"type":"new_image","path":...}` → 子进程走 `_load_new_image(新路径)`。

子进程零 adb 代码，重截行为与现状逐字节一致。**「➕重截」按钮保留（用户明确要求不删）。**

### 7.4 temp 文件所有权（原版本漏掉）

`on_close`（preview_window.py:393）有「未保存(`is_saved_to_temp=False`)就删除 temp 原图」逻辑。该文件是**主进程**截到 temp 的。跨进程后需明确所有权，否则主 app 若仍持有该路径引用（截图列表等）会与子进程的删除动作不一致。
→ 建议：**删除/保留由子进程负责**（它知道用户存没存），删除或保存后通过 `{"type":"saved",...}` 或关闭信号通知主进程刷新自己的引用。落地前确认主 app 侧是否真的还持有该路径。

### 7.5 transient 父子关系会丢（小回退，知会即可）

`preview_window.py:81 self.transient(parent.winfo_toplevel())` 让预览窗跟随主窗、不单独占任务栏。独立进程后是完全独立 OS 窗口：主 app 最小化时它不跟随，可能在 Dock/任务栏单独出现。属可接受的轻微体验回退，无需特殊处理，但要事先知道、别当 bug 查。

## 8. 打包注意（有 PyInstaller，根目录 `ADBHelper.spec`）

- PySide6 进 PyInstaller 会让产物涨 **~40–60MB**（多打一个 Qt 子程序）。
- 子进程入口要单独加进 spec 的打包目标，或作为 `sys.executable` 子命令分发。
- 验证 Qt 插件（`platforms`、`imageformats`）在打包后能被找到（PyInstaller 偶尔漏 Qt plugin，导致打包版起不来）。

## 9. 验收标准

- [ ] macOS Retina 下预览图清晰（与"在 Preview 中查看"等效）。
- [ ] 矩形/箭头/文字标注、Undo/Redo、缩放平移、保存/另存/复制剪贴板全部可用。
- [ ] **「➕重截」按钮保留**，走 IPC 回主进程截图，行为与现状一致。
- [ ] 子进程的日志（保存/删除/另存为/重截等）经 IPC 正常回流到主 app 日志面板，无静默丢失。
- [ ] temp 文件「未保存即删除」逻辑跨进程后正确，主 app 侧无残留路径引用不一致。
- [ ] Windows 下功能不回退（剪贴板、字体）。
- [ ] 打包版（PyInstaller）能正常起子进程。

## 10. 备选（不做 B′ 时）

- **方案 A**：维持现状，仅靠 `_open_in_system_preview` 入口看清晰图，不在 app 内标注。零成本止血。Windows 无对应系统 Preview，需另想（如调用系统图片查看器）。（注：该按钮在实施前已被移除，此条仅存档。）

## 11. 实施记录（2026-07-09）

按方案 B′ 完成，与上文设计的差异/要点：

| 项 | 落地方式 |
|---|---|
| 子进程入口 | **复用 `main.py --qt-preview <img> <temp_dir> [--theme dark\|light]`**，而非独立 preview_app 脚本——打包后 `sys.executable` 自调即可，spec 无需第二打包目标。拦截必须在 main.py 的 stdout 重定向之前（否则劫持 IPC 通道） |
| 新增文件 | `ui/windows/qt_preview/launcher.py`（主进程侧）、`preview_app.py`（子进程侧，~750 行） |
| 导出复用 | `get_annotated_image` 抽成 `screenshot_preview/export.py::render_annotated_image`（纯 PIL），Tk/Qt 共用；已用 git HEAD 旧实现做 6 组 case 逐字节对比，一致 |
| 兜底 | `screenshot_preview` 整包保留；`launch_qt_preview` 返回 False（PySide6 缺失/spawn 失败）时回退 Tk 窗。`screenshot_preview/__init__.py` 改 PEP 562 惰性导出，避免 Qt 子进程连带加载 ctk |
| IPC | 按第 7 节协议实现，另加父→子 `{"type":"rescreenshot_failed"}`（恢复 ➕ 按钮 + 报错）；子进程 stdin EOF = 主进程已退出 → 自动关窗清理 temp |
| 文字编辑器 | Tk 手搓的 IME 中继 Entry/光标闪烁不再需要——`QGraphicsTextItem(TextEditorInteraction)` 原生承担编辑+IME；8 控制点/虚线框在 `drawForeground` 按视口像素绘制（恒等大恒锐利），命中判定/轴分解逻辑照抄 Tk 版 |
| 依赖 | `PySide6-Essentials`（6.10.3，Python 3.9 兼容）；spec 加了未用 Qt 模块的 excludes |
| 已验证 | 导出逐字节一致、IPC 全链路（换图/EOF 清理/退出码）、窗口逻辑（形状/undo/文字编辑器/保存）offscreen 全通过；主进程不加载 PySide6、子进程不加载 tkinter |
| 待真机验收 | 第 9 节清单的视觉/交互项（Retina 清晰度、真机重截、剪贴板到微信/飞书、Windows 回归、PyInstaller 打包版起子进程） |
