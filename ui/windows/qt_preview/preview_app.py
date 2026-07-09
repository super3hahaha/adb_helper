# -*- coding: utf-8 -*-
"""PySide6 截图预览标注窗（独立子进程入口）。

由主进程以 `<program> --qt-preview <image_path> <temp_dir> [--theme dark|light]`
拉起（见 main.py 顶部拦截）。Qt 原生 HiDPI，Retina 下位图清晰。

与 Tk 版（ui/windows/screenshot_preview/preview_window.py）功能一比一对应：
    矩形/箭头/文字标注、8 控制点文字编辑器、Undo/Redo、缩放平移、
    保存/另存为/复制剪贴板、➕重新截图、未保存关闭时删除 temp 原图。
导出合成与 Tk 版共用 export.render_annotated_image（纯 PIL），产物一致。

跨进程 IPC（每行一条 JSON）：
    子 → 父 (stdout): {"type":"log","level":...,"msg":...} / {"type":"rescreenshot"}
    父 → 子 (stdin):  {"type":"new_image","path":...} / {"type":"rescreenshot_failed"}
线程模型：stdin 读取线程只发 Qt Signal（自动跨线程排队到主线程）；
stdout 写入带锁；所有 UI 操作都在 Qt 主线程。
"""
import io
import json
import math
import os
import sys
import threading

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QKeySequence, QPainter, QPen, QPixmap,
    QPolygonF, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGraphicsPixmapItem, QGraphicsScene,
    QGraphicsTextItem, QGraphicsView, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from PIL import Image

from ui.windows.screenshot_preview.export import render_annotated_image
from ui.windows.screenshot_preview.shared import (
    BORDER_HIT_PAD, DEFAULT_LINE_WIDTH, HANDLE_HIT_PAD, HANDLE_SIZE,
    MIN_HEIGHT_IMG, MIN_WIDTH_IMG, font_size_from_width, preferred_tk_font,
)

IS_MAC = sys.platform == "darwin"

# 与 ctk 版一致的按钮配色
BTN_DEFAULT = "#3B8ED0"
BTN_DEFAULT_HOVER = "#36719F"
BTN_ACTIVE = "#1F6AA5"
BTN_ACTIVE_HOVER = "#144870"
BTN_GREEN = "#2d7d46"
BTN_GREEN_HOVER = "#1e5c32"
BTN_RED = "#c42b1c"
BTN_RED_HOVER = "#8a1f15"
BTN_GRAY = "#6b6b6b"
BTN_GRAY_HOVER = "#4a4a4a"

# handle_idx (0 TL,1 T,2 TR,3 R,4 BR,5 B,6 BL,7 L) -> drag_kind（与 Tk 版一致）
_HANDLE_DRAG_KIND = {
    0: 'resize_tl', 1: 'resize_t', 2: 'resize_tr',
    3: 'resize_r',
    4: 'resize_br', 5: 'resize_b', 6: 'resize_bl',
    7: 'resize_l',
}

_HANDLE_CURSOR = {
    0: Qt.SizeFDiagCursor, 1: Qt.SizeVerCursor, 2: Qt.SizeBDiagCursor,
    3: Qt.SizeHorCursor,
    4: Qt.SizeFDiagCursor, 5: Qt.SizeVerCursor, 6: Qt.SizeBDiagCursor,
    7: Qt.SizeHorCursor,
}


def _btn_style(bg, hover, text_color="white"):
    return (
        f"QPushButton {{ background-color: {bg}; color: {text_color}; border: none;"
        f" border-radius: 5px; padding: 4px 8px; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
        f"QPushButton:disabled {{ background-color: #555555; color: #999999; }}"
    )


def _annotation_font(pixel_size):
    font = QFont(preferred_tk_font())
    font.setPixelSize(max(1, int(pixel_size)))
    return font


# ----------------------------------------------------------------------
# IPC
# ----------------------------------------------------------------------

class IpcBridge(QObject):
    """stdin 读取线程 → Qt Signal（跨线程自动排队到主线程）。"""

    new_image = Signal(str)
    rescreenshot_failed = Signal()
    parent_closed = Signal()

    def __init__(self):
        super().__init__()
        self._write_lock = threading.Lock()

    def start_reader(self):
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self):
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                mtype = msg.get("type")
                if mtype == "new_image":
                    self.new_image.emit(msg.get("path") or "")
                elif mtype == "rescreenshot_failed":
                    self.rescreenshot_failed.emit()
        except Exception:
            pass
        # stdin EOF：主进程已退出/关闭管道，预览窗跟随关闭
        self.parent_closed.emit()

    def send(self, obj):
        try:
            data = json.dumps(obj, ensure_ascii=False)
            with self._write_lock:
                sys.stdout.write(data + "\n")
                sys.stdout.flush()
        except Exception:
            pass  # 父进程已退出时忽略

    def log(self, msg, level="INFO"):
        self.send({"type": "log", "level": level, "msg": msg})


# ----------------------------------------------------------------------
# 画布视图
# ----------------------------------------------------------------------

class AnnotationView(QGraphicsView):
    """场景坐标 = 图像像素坐标；缩放/平移/绘制/文字编辑器交互都在这里分发。"""

    def __init__(self, scene, window):
        super().__init__(scene)
        self.win = window
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setDragMode(QGraphicsView.NoDrag)
        # 滚动条常驻（场景恒大于视口，本来就总会出现）：若按需显示，
        # 初始 fit 会按"无滚动条的视口"计算，滚动条随后出现挤掉一条边，
        # 导致图像底部被遮住一截
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ---- 缩放：Cmd/Ctrl + 滚轮，普通滚轮走默认滚动（与 Tk 版一致） ----

    def wheelEvent(self, event):
        # mac 上 Qt 把 Command 映射为 ControlModifier，故两平台统一判断
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y() or event.angleDelta().x()
            factor = 1.1 if delta > 0 else 0.9
            new_scale = self.win.current_scale * factor
            new_scale = max(0.1, min(new_scale, 5.0))
            factor = new_scale / self.win.current_scale
            if abs(factor - 1.0) > 1e-6:
                self.win._auto_fit = False
                self.scale(factor, factor)
                self.win.current_scale = new_scale
                self.win.update_scene_margins()
            event.accept()
            return
        super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 初始 fit 不能依赖 singleShot 的时机（macOS 上窗口映射后还可能有布局
        # 调整）：只要用户还没手动操作过画布，每次视口变化都重新 fit，
        # 最后一次布局 resize 必然得到正确的适配比例
        if self.win._auto_fit:
            self.win.reset_view()
        else:
            self.win.update_scene_margins()

    # ---- 空格临时平移（与 Tk 版一致：文字编辑中空格由文本项自行消费） ----

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.win.text_editor is not None:
            self.win.cancel_text_entry()
            event.accept()
            return
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            if self.win.text_editor is None and self.win.drawing_mode is not None \
                    and self.win._mode_before_space is None:
                self.win._mode_before_space = self.win.drawing_mode
                self.win.set_mode(None)
                event.accept()
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            if self.win._mode_before_space is not None:
                prev = self.win._mode_before_space
                self.win._mode_before_space = None
                self.win.set_mode(prev)
                event.accept()
                return
        super().keyReleaseEvent(event)

    # ---- 鼠标分发（优先级与 Tk on_drag_start 一致） ----

    def mousePressEvent(self, event):
        # 用户开始手动操作画布后，窗口 resize 不再自动重新 fit（与 Tk 版一致）
        self.win._auto_fit = False
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        win = self.win
        vp = event.position().toPoint()

        # 1) 活跃文字编辑器的控制点 / 内部
        if win.text_editor is not None:
            hit = win.hit_test_editor(vp)
            if hit == 'inside':
                win.start_drag_editor('move', vp)
                event.accept()
                return
            if hit.startswith('handle_'):
                win.start_drag_editor('resize', vp, handle_idx=int(hit.split('_')[1]))
                event.accept()
                return
            # 2) 点击空白：固化当前编辑
            win.commit_text_entry()
            if win.drawing_mode == "text":
                win.create_text_editor(self.mapToScene(vp))
                event.accept()
                return

        # 3) 文字模式：新建编辑器
        if win.drawing_mode == "text":
            win.create_text_editor(self.mapToScene(vp))
            event.accept()
            return
        # 4) 矩形/箭头：开始绘制
        if win.drawing_mode in ("rect", "arrow"):
            win.start_shape_drag(self.mapToScene(vp))
            event.accept()
            return
        # 5) 平移模式：交给 ScrollHandDrag
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        win = self.win
        vp = event.position().toPoint()
        if win.text_editor is not None and win.text_editor.get('drag_kind'):
            win.update_drag_editor(vp)
            event.accept()
            return
        if win.shape_drag_start is not None:
            win.update_shape_drag(self.mapToScene(vp))
            event.accept()
            return
        # 悬停光标反馈（与 Tk _on_canvas_motion 一致）
        if win.text_editor is not None and not event.buttons():
            hit = win.hit_test_editor(vp)
            cursor = win.editor_cursor_for_hit(hit)
            if cursor is not None:
                self.viewport().setCursor(cursor)
            else:
                win.apply_mode_cursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        win = self.win
        if event.button() == Qt.LeftButton:
            if win.text_editor is not None and win.text_editor.get('drag_kind'):
                win.end_drag_editor(event.position().toPoint())
                event.accept()
                return
            if win.shape_drag_start is not None:
                win.end_shape_drag(self.mapToScene(event.position().toPoint()))
                event.accept()
                return
        super().mouseReleaseEvent(event)

    # ---- 文字编辑器覆盖层：虚线边框 + 8 控制点（设备像素坐标绘制，恒锐利恒等大） ----

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        win = self.win
        if win.text_editor is None:
            return
        bbox = win.editor_bbox_viewport()
        if bbox is None:
            return
        x1, y1, x2, y2 = bbox
        painter.save()
        painter.resetTransform()
        pen = QPen(QColor("#6c9ef8"))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(x1, y1, x2 - x1, y2 - y1))

        pen.setStyle(Qt.SolidLine)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor("#ffffff")))
        hs = HANDLE_SIZE / 2
        for hx, hy in win.editor_handle_centers_viewport((x1, y1, x2, y2)):
            painter.drawRect(QRectF(hx - hs, hy - hs, HANDLE_SIZE, HANDLE_SIZE))
        painter.restore()


# ----------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------

class PreviewWindow(QWidget):

    def __init__(self, ipc, image_path, temp_dir, theme="light"):
        super().__init__()
        self.ipc = ipc
        self.image_path = image_path
        self.temp_dir = temp_dir
        self.theme = theme

        self.setWindowTitle("截图预览 (Preview) - 标注模式")
        self.resize(900, 700)

        # 窗口级状态（与 Tk 版同名同语义）
        self.drawing_mode = "rect"
        self.current_color = "red"
        self.line_width = DEFAULT_LINE_WIDTH
        self.shapes = []
        self.is_saved_to_temp = False
        self.current_scale = 1.0
        self._mode_before_space = None
        self._auto_fit = True  # 用户手动操作画布前，视口 resize 自动重新 fit

        # 绘制/编辑器状态
        self.shape_drag_start = None      # 图像坐标 (x, y)
        self.temp_shape_items = []        # 拖拽中的临时预览 items
        self.text_editor = None           # dict，None 表示无活跃编辑器
        self._committing_text = False

        # 撤销/重做栈（语义与 HistoryMixin 一致）
        self._undo_stack = []
        self._redo_stack = []

        # 加载图片
        try:
            self.original_image = Image.open(image_path)
            self.pixmap = QPixmap(image_path)
            if self.pixmap.isNull():
                raise ValueError("无法解码图片")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法加载图片: {e}")
            raise SystemExit(1)

        # 场景：坐标系 = 图像像素
        self.scene = QGraphicsScene(self)
        self.pixmap_item = QGraphicsPixmapItem(self.pixmap)
        self.pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self.scene.addItem(self.pixmap_item)
        self.scene.setSceneRect(0, 0, self.pixmap.width(), self.pixmap.height())
        self.shape_items = []

        self.view = AnnotationView(self.scene, self)
        bg = "#2b2b2b" if theme == "dark" else "#ffffff"
        self.view.setBackgroundBrush(QColor(bg))

        self._build_ui()
        self._bind_shortcuts()

        # IPC 信号（Signal 跨线程自动排队到主线程）
        self.ipc.new_image.connect(self._load_new_image)
        self.ipc.rescreenshot_failed.connect(self._on_rescreenshot_failed)
        self.ipc.parent_closed.connect(self.close)

        self.set_mode("rect")
        QTimer.singleShot(0, self.reset_view)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        if self.theme == "dark":
            self.setStyleSheet("QWidget { background-color: #242424; color: #dce4ee; }")

        # ---- 工具栏 ----
        toolbar = QFrame(self)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(5, 5, 5, 5)
        tb.setSpacing(5)

        self.btn_new_screenshot = QPushButton("➕")
        self.btn_new_screenshot.setFixedSize(34, 28)
        self.btn_new_screenshot.setStyleSheet(_btn_style(BTN_GREEN, BTN_GREEN_HOVER))
        self.btn_new_screenshot.clicked.connect(self.take_new_screenshot)
        tb.addWidget(self.btn_new_screenshot)

        self.mode_buttons = {}
        for key, label in ((None, "✋"), ("rect", "⬜"), ("arrow", "↗"), ("text", "T")):
            btn = QPushButton(label)
            btn.setFixedSize(44, 28)
            btn.clicked.connect(lambda checked=False, m=key: self.set_mode(m))
            tb.addWidget(btn)
            self.mode_buttons[key] = btn

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #888888;")
        tb.addWidget(sep)

        tb.addWidget(QLabel("颜色:"))
        for color in ("red", "blue", "green", "yellow"):
            btn = QPushButton("")
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color}; border: none; border-radius: 5px; }}"
            )
            btn.clicked.connect(lambda checked=False, c=color: self.set_color(c))
            tb.addWidget(btn)

        tb.addSpacing(10)
        tb.addWidget(QLabel("粗细:"))
        self.width_slider = QSlider(Qt.Horizontal)
        self.width_slider.setRange(1, 24)
        self.width_slider.setValue(DEFAULT_LINE_WIDTH)
        self.width_slider.setFixedWidth(150)
        self.width_slider.valueChanged.connect(self.update_width_label)
        tb.addWidget(self.width_slider)
        self.width_label = QLabel(str(DEFAULT_LINE_WIDTH))
        self.width_label.setFixedWidth(30)
        tb.addWidget(self.width_label)

        tb.addStretch(1)
        self.btn_undo = QPushButton("↩ 撤销")
        self.btn_undo.setFixedHeight(28)
        self.btn_undo.setStyleSheet(_btn_style(BTN_RED, BTN_RED_HOVER))
        self.btn_undo.clicked.connect(self.undo_last_shape)
        tb.addWidget(self.btn_undo)

        root.addWidget(toolbar)
        root.addWidget(self.view, stretch=1)

        # ---- 控制栏 ----
        control = QFrame(self)
        cb = QHBoxLayout(control)
        cb.setContentsMargins(10, 5, 10, 5)
        cb.setSpacing(10)

        btn_shortcuts = QPushButton("⌨ 快捷键")
        btn_shortcuts.setFixedHeight(28)
        btn_shortcuts.setStyleSheet(_btn_style(BTN_GRAY, BTN_GRAY_HOVER))
        btn_shortcuts.setToolTip(self._shortcut_tooltip_html())
        cb.addWidget(btn_shortcuts)

        cb.addStretch(1)

        btn_reset = QPushButton("位置复原")
        btn_reset.setStyleSheet(_btn_style(BTN_GRAY, BTN_GRAY_HOVER))
        btn_reset.clicked.connect(self.reset_view)
        cb.addWidget(btn_reset)

        btn_copy = QPushButton("复制")
        btn_copy.setStyleSheet(_btn_style(BTN_GREEN, BTN_GREEN_HOVER))
        btn_copy.clicked.connect(self.copy_to_clipboard)
        cb.addWidget(btn_copy)

        btn_save_as = QPushButton("另存为...")
        btn_save_as.setStyleSheet(_btn_style(BTN_GREEN, BTN_GREEN_HOVER))
        btn_save_as.clicked.connect(self.save_as)
        cb.addWidget(btn_save_as)

        btn_save = QPushButton("保存")
        btn_save.setStyleSheet(_btn_style(BTN_DEFAULT, BTN_DEFAULT_HOVER))
        btn_save.clicked.connect(self.save_to_temp)
        cb.addWidget(btn_save)

        for b in (btn_reset, btn_copy, btn_save_as, btn_save):
            b.setFixedHeight(28)

        root.addWidget(control)

        # 所有控件不参与键盘焦点：焦点始终留在画布上，
        # 空格临时平移才能随时生效（否则空格会触发聚焦的按钮）
        for w in self.findChildren(QPushButton) + [self.width_slider]:
            w.setFocusPolicy(Qt.NoFocus)

    def _shortcut_tooltip_html(self):
        mod = "⌘" if IS_MAC else "Ctrl"
        sections = [
            ("视图操作",
             f"空格 + 鼠标拖动 — 临时切换为平移模式（松开空格恢复原模式）<br>"
             f"{mod} + 滚轮 — 以鼠标位置为中心缩放画布<br>"
             f"滚轮 — 垂直滚动画布"),
            ("文字输入（编辑文字时）",
             "Esc — 取消当前文字输入（不保存）"),
            ("编辑 / 历史",
             f"{mod} + Z — 撤销<br>{mod} + Y — 重做"),
            ("文件操作",
             f"{mod} + S — 保存到临时文件夹<br>"
             f"{mod} + C — 复制带标注的图片到剪贴板"),
        ]
        html = ""
        for title, body in sections:
            html += f"<b>{title}</b><br>{body}<br><br>"
        return html.rstrip("<br>")

    def _bind_shortcuts(self):
        for seq, slot in (
            (QKeySequence.Copy, self.copy_to_clipboard),
            (QKeySequence.Undo, self.undo_last_shape),
            (QKeySequence("Ctrl+Y"), self.redo_last_shape),
            (QKeySequence.Redo, self.redo_last_shape),
            (QKeySequence.Save, self.save_to_temp),
        ):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(slot)

    # ------------------------------------------------------------------
    # 模式/颜色/线宽
    # ------------------------------------------------------------------

    def set_mode(self, mode):
        if mode != "text" and self.text_editor is not None:
            self.commit_text_entry()

        self.drawing_mode = mode
        for key, btn in self.mode_buttons.items():
            active = (key == mode)
            btn.setStyleSheet(_btn_style(
                BTN_ACTIVE if active else BTN_DEFAULT,
                BTN_ACTIVE_HOVER if active else BTN_DEFAULT_HOVER,
            ))

        if mode is None:
            self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        else:
            self.view.setDragMode(QGraphicsView.NoDrag)
        self.apply_mode_cursor()

    def apply_mode_cursor(self):
        if self.drawing_mode == "text":
            self.view.viewport().setCursor(Qt.IBeamCursor)
        elif self.drawing_mode:
            self.view.viewport().setCursor(Qt.CrossCursor)
        else:
            self.view.viewport().setCursor(Qt.OpenHandCursor)

    def set_color(self, color):
        self.current_color = color
        if self.text_editor is not None:
            self.text_editor['color'] = color
            self.text_editor['item'].setDefaultTextColor(QColor(color))
            self.view.viewport().update()

    def update_width_label(self, value):
        self.line_width = int(value)
        self.width_label.setText(str(self.line_width))
        if self.text_editor is not None:
            self.text_editor['font_size'] = font_size_from_width(self.line_width)
            self.text_editor['item'].setFont(_annotation_font(self.text_editor['font_size']))
            self.view.viewport().update()

    # ------------------------------------------------------------------
    # 视图
    # ------------------------------------------------------------------

    def update_scene_margins(self):
        """场景四周留一圈视口大小的余量。

        QGraphicsView 的平移受滚动范围钳制：场景=图像时，图像整幅可见就没有
        滚动范围，✋/空格平移完全拖不动。扩出余量后恢复 Tk 版的自由平移手感。
        """
        scale = self.current_scale or 1.0
        mw = self.view.viewport().width() / scale
        mh = self.view.viewport().height() / scale
        self.scene.setSceneRect(
            -mw, -mh,
            self.pixmap.width() + 2 * mw, self.pixmap.height() + 2 * mh,
        )

    def reset_view(self):
        vw = max(1, self.view.viewport().width())
        vh = max(1, self.view.viewport().height())
        img_w = max(1, self.pixmap.width())
        img_h = max(1, self.pixmap.height())
        scale = min(vw / img_w, vh / img_h, 1.0)
        self.view.resetTransform()
        self.view.scale(scale, scale)
        self.current_scale = scale
        self.update_scene_margins()
        self.view.centerOn(self.pixmap_item)

    # ------------------------------------------------------------------
    # 形状绘制（矩形/箭头）
    # ------------------------------------------------------------------

    def _make_pen(self, color, width):
        pen = QPen(QColor(color))
        pen.setWidthF(max(1.0, float(width)))
        pen.setJoinStyle(Qt.MiterJoin)
        return pen

    def _add_shape_items(self, shape, temp=False):
        """把一个 shape 画进场景，返回 items 列表。"""
        x1, y1, x2, y2 = shape['coords']
        color = shape['color']
        width = shape['width']
        items = []
        if shape['type'] == 'rect':
            rect = QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized()
            items.append(self.scene.addRect(rect, self._make_pen(color, width)))
        elif shape['type'] == 'arrow':
            # 箭头形状与 Tk arrowshape=(4w, 5w, 2w) 一致：
            # 颈点在距终点 4w 处，尾角在距终点 5w、侧偏 2w 处，填充多边形
            d1, d2, d3 = width * 4, width * 5, width * 2
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-6:
                ux, uy = 1.0, 0.0
            else:
                ux, uy = dx / length, dy / length
            nx, ny = -uy, ux
            neck = QPointF(x2 - ux * d1, y2 - uy * d1)
            barb1 = QPointF(x2 - ux * d2 + nx * d3, y2 - uy * d2 + ny * d3)
            barb2 = QPointF(x2 - ux * d2 - nx * d3, y2 - uy * d2 - ny * d3)
            items.append(self.scene.addLine(x1, y1, neck.x(), neck.y(),
                                            self._make_pen(color, width)))
            poly = QPolygonF([QPointF(x2, y2), barb1, neck, barb2])
            items.append(self.scene.addPolygon(
                poly, QPen(QColor(color), 0), QBrush(QColor(color))))
        elif shape['type'] == 'text':
            item = QGraphicsTextItem(shape.get('text', ''))
            item.setFont(_annotation_font(shape.get('font_size', 24)))
            item.setDefaultTextColor(QColor(color))
            item.document().setDocumentMargin(0)
            width_img = shape.get('width_img')
            if width_img:
                item.setTextWidth(float(width_img))
            item.setPos(x1, y1)
            self.scene.addItem(item)
            items.append(item)
        for it in items:
            it.setZValue(10 if not temp else 20)
        return items

    def rebuild_shapes(self):
        for it in self.shape_items:
            self.scene.removeItem(it)
        self.shape_items = []
        for shape in self.shapes:
            self.shape_items.extend(self._add_shape_items(shape))

    def start_shape_drag(self, scene_pos):
        self.shape_drag_start = (scene_pos.x(), scene_pos.y())

    def update_shape_drag(self, scene_pos):
        for it in self.temp_shape_items:
            self.scene.removeItem(it)
        self.temp_shape_items = []
        if self.shape_drag_start is None:
            return
        shape = {
            'type': self.drawing_mode,
            'coords': (self.shape_drag_start[0], self.shape_drag_start[1],
                       scene_pos.x(), scene_pos.y()),
            'color': self.current_color,
            'width': self.line_width,
        }
        self.temp_shape_items = self._add_shape_items(shape, temp=True)

    def end_shape_drag(self, scene_pos):
        for it in self.temp_shape_items:
            self.scene.removeItem(it)
        self.temp_shape_items = []
        if self.shape_drag_start is None:
            return
        shape = {
            'type': self.drawing_mode,
            'coords': (self.shape_drag_start[0], self.shape_drag_start[1],
                       scene_pos.x(), scene_pos.y()),
            'color': self.current_color,
            'width': self.line_width,
        }
        self.shape_drag_start = None
        self.shapes.append(shape)
        self._push_history({'op': 'add', 'shape': shape, 'index': len(self.shapes) - 1})
        self.rebuild_shapes()

    # ------------------------------------------------------------------
    # 撤销/重做（语义与 HistoryMixin 一致）
    # ------------------------------------------------------------------

    def _push_history(self, action):
        self._undo_stack.append(action)
        self._redo_stack.clear()

    def _clear_history(self):
        self._undo_stack.clear()
        self._redo_stack.clear()

    def _apply_inverse(self, action):
        op = action['op']
        shape = action['shape']
        index = action['index']
        if op == 'add':
            if 0 <= index < len(self.shapes):
                self.shapes.pop(index)
            elif self.shapes and self.shapes[-1] is shape:
                self.shapes.pop()
            return {'op': 'remove', 'shape': shape, 'index': index}
        if op == 'remove':
            index = max(0, min(index, len(self.shapes)))
            self.shapes.insert(index, shape)
            return {'op': 'add', 'shape': shape, 'index': index}
        return action

    def undo_last_shape(self):
        if not self._undo_stack:
            return
        action = self._undo_stack.pop()
        self._redo_stack.append(self._apply_inverse(action))
        self.rebuild_shapes()

    def redo_last_shape(self):
        if not self._redo_stack:
            return
        action = self._redo_stack.pop()
        self._undo_stack.append(self._apply_inverse(action))
        self.rebuild_shapes()

    # ------------------------------------------------------------------
    # 文字编辑器（8 控制点；文本编辑/IME 由 QGraphicsTextItem 原生承担）
    # ------------------------------------------------------------------

    def create_text_editor(self, scene_pos):
        font_size = font_size_from_width(self.line_width)
        default_width = max(MIN_WIDTH_IMG, font_size * 12)
        default_height = max(MIN_HEIGHT_IMG, int(font_size * 1.4))

        item = QGraphicsTextItem("")
        item.setFont(_annotation_font(font_size))
        item.setDefaultTextColor(QColor(self.current_color))
        item.document().setDocumentMargin(0)
        item.setTextWidth(float(default_width))
        item.setPos(scene_pos.x(), scene_pos.y())
        item.setZValue(30)
        item.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.scene.addItem(item)

        self.text_editor = {
            'item': item,
            'anchor_img': [scene_pos.x(), scene_pos.y()],
            'width_img': float(default_width),
            'height_img': float(default_height),
            'color': self.current_color,
            'font_size': font_size,
            'drag_kind': None,
            'drag_start_viewport': None,
            'drag_start_anchor': None,
            'drag_start_width': None,
            'drag_start_height': None,
        }
        item.document().contentsChanged.connect(self._on_editor_content_changed)
        item.setFocus(Qt.MouseFocusReason)
        self.view.viewport().update()

    def _on_editor_content_changed(self):
        # 内容变化 → 边框高度可能变化，刷新覆盖层
        if self.text_editor is not None:
            self.view.viewport().update()

    def _editor_bbox_scene(self):
        """编辑器 bounding box（场景坐标）。高度取 max(内容实际高度, 用户设定高度)。"""
        ed = self.text_editor
        if ed is None:
            return None
        ax, ay = ed['anchor_img']
        content_h = ed['item'].boundingRect().height()
        h = max(content_h, ed['height_img'])
        return QRectF(ax, ay, ed['width_img'], h)

    def editor_bbox_viewport(self):
        """编辑器 bbox（视口像素坐标，含 2px 外边距，与 Tk 版 pad 一致）。"""
        rect = self._editor_bbox_scene()
        if rect is None:
            return None
        tl = self.view.mapFromScene(rect.topLeft())
        br = self.view.mapFromScene(rect.bottomRight())
        pad = 2
        return (tl.x() - pad, tl.y() - pad, br.x() + pad, br.y() + pad)

    @staticmethod
    def editor_handle_centers_viewport(bbox):
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        return [
            (x1, y1), (cx, y1), (x2, y1),
            (x2, cy),
            (x2, y2), (cx, y2), (x1, y2),
            (x1, cy),
        ]

    def hit_test_editor(self, vp_point):
        """返回 'outside' | 'inside' | 'handle_{i}'（视口像素坐标，判定逻辑与 Tk 版一致）。"""
        bbox = self.editor_bbox_viewport()
        if bbox is None:
            return 'outside'
        cx, cy = vp_point.x(), vp_point.y()
        hs = HANDLE_SIZE / 2 + HANDLE_HIT_PAD
        for i, (hx, hy) in enumerate(self.editor_handle_centers_viewport(bbox)):
            if hx - hs <= cx <= hx + hs and hy - hs <= cy <= hy + hs:
                return f'handle_{i}'
        x1, y1, x2, y2 = bbox
        pad = BORDER_HIT_PAD
        if x1 - pad <= cx <= x2 + pad and y1 - pad <= cy <= y2 + pad:
            return 'inside'
        return 'outside'

    @staticmethod
    def editor_cursor_for_hit(hit):
        if hit == 'inside':
            return Qt.SizeAllCursor
        if hit.startswith('handle_'):
            return _HANDLE_CURSOR.get(int(hit.split('_')[1]), Qt.ArrowCursor)
        return None

    def start_drag_editor(self, kind, vp_point, handle_idx=None):
        ed = self.text_editor
        # 以当前显示 bbox 高度为 resize 基准（与 Tk 版一致）
        rect = self._editor_bbox_scene()
        display_height_img = max(MIN_HEIGHT_IMG, rect.height())
        ed['drag_start_viewport'] = (vp_point.x(), vp_point.y())
        ed['drag_start_anchor'] = list(ed['anchor_img'])
        ed['drag_start_width'] = ed['width_img']
        ed['drag_start_height'] = max(ed['height_img'], display_height_img)
        if kind == 'move':
            ed['drag_kind'] = 'move'
            self.view.viewport().setCursor(Qt.SizeAllCursor)
        else:
            ed['drag_kind'] = _HANDLE_DRAG_KIND.get(handle_idx, 'move')
            cur = self.editor_cursor_for_hit(f'handle_{handle_idx}')
            self.view.viewport().setCursor(cur or Qt.ArrowCursor)
        ed['item'].setFocus(Qt.MouseFocusReason)

    def update_drag_editor(self, vp_point):
        ed = self.text_editor
        if ed is None or not ed.get('drag_kind'):
            return
        start_vx, start_vy = ed['drag_start_viewport']
        # 视口位移 → 图像坐标位移
        scale = self.current_scale or 1.0
        dx_img = (vp_point.x() - start_vx) / scale
        dy_img = (vp_point.y() - start_vy) / scale

        start_ax, start_ay = ed['drag_start_anchor']
        start_w = ed['drag_start_width']
        start_h = ed['drag_start_height']
        kind = ed['drag_kind']

        if kind == 'move':
            ed['anchor_img'][0] = start_ax + dx_img
            ed['anchor_img'][1] = start_ay + dy_img
            self._sync_editor_item()
            return

        axis_map = {
            'resize_l':  ('l', None),
            'resize_r':  ('r', None),
            'resize_t':  (None, 't'),
            'resize_b':  (None, 'b'),
            'resize_tl': ('l', 't'),
            'resize_tr': ('r', 't'),
            'resize_bl': ('l', 'b'),
            'resize_br': ('r', 'b'),
        }
        hx, vy = axis_map.get(kind, (None, None))

        new_w = start_w
        new_ax = start_ax
        if hx == 'r':
            new_w = max(MIN_WIDTH_IMG, start_w + dx_img)
        elif hx == 'l':
            new_w = max(MIN_WIDTH_IMG, start_w - dx_img)
            new_ax = start_ax + (start_w - new_w)

        new_h = start_h
        new_ay = start_ay
        if vy == 'b':
            new_h = max(MIN_HEIGHT_IMG, start_h + dy_img)
        elif vy == 't':
            new_h = max(MIN_HEIGHT_IMG, start_h - dy_img)
            new_ay = start_ay + (start_h - new_h)

        ed['width_img'] = new_w
        ed['height_img'] = new_h
        ed['anchor_img'][0] = new_ax
        ed['anchor_img'][1] = new_ay
        self._sync_editor_item()

    def _sync_editor_item(self):
        ed = self.text_editor
        item = ed['item']
        item.setPos(ed['anchor_img'][0], ed['anchor_img'][1])
        item.setTextWidth(float(ed['width_img']))
        self.view.viewport().update()

    def end_drag_editor(self, vp_point):
        ed = self.text_editor
        if ed is None:
            return
        ed['drag_kind'] = None
        ed['drag_start_viewport'] = None
        hit = self.hit_test_editor(vp_point)
        cursor = self.editor_cursor_for_hit(hit)
        if cursor is not None:
            self.view.viewport().setCursor(cursor)
        else:
            self.apply_mode_cursor()

    def commit_text_entry(self):
        """将当前输入框中的文字固化为标注形状（与 Tk 版语义一致）。"""
        if self._committing_text or self.text_editor is None:
            return
        self._committing_text = True
        try:
            ed = self.text_editor
            item = ed['item']
            text = item.toPlainText()
            anchor = tuple(ed['anchor_img'])
            self.text_editor = None
            self.scene.removeItem(item)

            if text and text.strip():
                shape = {
                    'type': 'text',
                    'coords': (anchor[0], anchor[1], anchor[0], anchor[1]),
                    'color': ed['color'],
                    'width': self.line_width,
                    'text': text,
                    'font_size': ed['font_size'],
                    'width_img': float(ed['width_img']),
                    'height_img': float(ed['height_img']),
                }
                self.shapes.append(shape)
                self._push_history({'op': 'add', 'shape': shape, 'index': len(self.shapes) - 1})
                self.rebuild_shapes()
            self.view.viewport().update()
        finally:
            self._committing_text = False

    def cancel_text_entry(self):
        """取消当前输入（Esc），不保存。"""
        if self._committing_text or self.text_editor is None:
            return
        self._committing_text = True
        try:
            item = self.text_editor['item']
            self.text_editor = None
            self.scene.removeItem(item)
            self.view.viewport().update()
        finally:
            self._committing_text = False

    # ------------------------------------------------------------------
    # 重新截图（IPC 回主进程，见 handoff 7.3）
    # ------------------------------------------------------------------

    def take_new_screenshot(self):
        # 如果当前截图没有保存，先删除它（与 Tk 版一致，temp 文件归子进程管）
        if not self.is_saved_to_temp and self.image_path and os.path.exists(self.image_path):
            try:
                os.remove(self.image_path)
                self.ipc.log(f"截图 {os.path.basename(self.image_path)} 已从temp删除", "INFO")
            except Exception as e:
                print(f"Error deleting unsaved screenshot: {e}", file=sys.stderr)

        self.btn_new_screenshot.setEnabled(False)
        self.btn_new_screenshot.setText("⏳")
        self.ipc.log("正在重新截取屏幕...", "INFO")
        self.ipc.send({"type": "rescreenshot"})

    def _restore_screenshot_button(self):
        self.btn_new_screenshot.setEnabled(True)
        self.btn_new_screenshot.setText("➕")

    def _on_rescreenshot_failed(self):
        self._restore_screenshot_button()
        self.ipc.log("重新截图失败或文件未生成", "ERROR")

    def _load_new_image(self, new_image_path):
        """主进程重截完成，加载新图片并重置状态。"""
        self._restore_screenshot_button()
        if not new_image_path or not os.path.exists(new_image_path):
            self.ipc.log("重新截图失败或文件未生成", "ERROR")
            return
        self.ipc.log(f"新截图已保存至临时目录: {new_image_path}", "SUCCESS")

        if self.text_editor is not None:
            self.cancel_text_entry()
        self.image_path = new_image_path
        self.is_saved_to_temp = False
        self.shapes = []
        self._clear_history()

        try:
            self.original_image = Image.open(new_image_path)
            pixmap = QPixmap(new_image_path)
            if pixmap.isNull():
                raise ValueError("无法解码图片")
            self.pixmap = pixmap
            self.pixmap_item.setPixmap(pixmap)
            self.rebuild_shapes()
            self.reset_view()
            self.set_mode("rect")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法加载新图片: {e}")

    # ------------------------------------------------------------------
    # 保存 / 另存为 / 复制
    # ------------------------------------------------------------------

    def get_annotated_image(self):
        return render_annotated_image(self.original_image, self.shapes)

    def save_to_temp(self):
        try:
            final_image = self.get_annotated_image()
            final_image.save(self.image_path, optimize=True)
            self.is_saved_to_temp = True
            self.ipc.log(f"截图已保存至临时文件夹: {self.image_path}", "SUCCESS")
        except Exception as e:
            self.ipc.log(f"保存截图失败: {e}", "ERROR")
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def copy_to_clipboard(self):
        try:
            final_image = self.get_annotated_image()
            buf = io.BytesIO()
            final_image.convert("RGB").save(buf, "PNG")
            qimage = QImage.fromData(buf.getvalue(), "PNG")
            QApplication.clipboard().setImage(qimage)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"复制失败: {e}")

    def save_as(self):
        try:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "另存为", os.path.basename(self.image_path),
                "PNG 图像 (*.png);;JPEG 图像 (*.jpg);;所有文件 (*.*)",
            )
            if not file_path:
                return
            final_image = self.get_annotated_image()
            if file_path.lower().endswith(('.jpg', '.jpeg')):
                if final_image.mode in ('RGBA', 'P'):
                    final_image = final_image.convert('RGB')
                final_image.save(file_path, quality=85, optimize=True)
            else:
                if not os.path.splitext(file_path)[1]:
                    file_path += ".png"
                final_image.save(file_path, optimize=True)
            self.is_saved_to_temp = True  # 视同已保存，关闭时不删原图
            self.ipc.log(f"截图另存为: {file_path}", "SUCCESS")
            QMessageBox.information(self, "成功", f"截图已保存至:\n{file_path}")
            self.close()
        except Exception as e:
            self.ipc.log(f"另存为失败: {e}", "ERROR")
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    # ------------------------------------------------------------------
    # 关闭：未保存则删除 temp 原图（与 Tk 版 on_close 一致）
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if not self.is_saved_to_temp:
            try:
                if os.path.exists(self.image_path):
                    filename = os.path.basename(self.image_path)
                    os.remove(self.image_path)
                    self.ipc.log(f"截图 {filename} 已从 temp 删除", "INFO")
            except Exception:
                pass
        event.accept()


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------

def main(argv):
    args = [a for a in argv[1:] if a != "--qt-preview"]
    theme = "light"
    if "--theme" in args:
        i = args.index("--theme")
        if i + 1 < len(args):
            theme = args[i + 1]
        del args[i:i + 2]
    if len(args) < 2:
        print("usage: --qt-preview <image_path> <temp_dir> [--theme dark|light]",
              file=sys.stderr)
        return 2

    image_path, temp_dir = args[0], args[1]

    app = QApplication([argv[0]])
    app.setApplicationDisplayName("截图预览")

    ipc = IpcBridge()
    window = PreviewWindow(ipc, image_path, temp_dir, theme=theme)
    ipc.start_reader()

    window.show()
    window.raise_()
    window.activateWindow()
    window.view.setFocus()
    return app.exec()


if __name__ == "__main__":
    # 允许直接调试：python -m ui.windows.qt_preview.preview_app <img> <temp_dir>
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
    sys.exit(main(sys.argv))
