import tkinter.font
import tkinter
import customtkinter as ctk


def attach_scrollable(parent, **kwargs):
    """创建带防抖与自动隐藏滚动条的 CTkScrollableFrame。

    Why: customtkinter 的 ScrollableFrame 默认每个 <Configure> 事件都会重算
         scrollregion 并且永远显示滚动条;窗口里嵌套大量带圆角的 CTkFrame 时,
         resize 会非常卡。此函数对两个内部 Configure 处理器加 80ms 防抖,
         同时按内容是否超出可视区自动 grid/grid_remove 滚动条。
    """
    sf = ctk.CTkScrollableFrame(parent, fg_color="transparent", corner_radius=0, **kwargs)
    _install_scrollable_optimizations(sf)
    return sf


def _install_scrollable_optimizations(sf, delay_ms=80):
    canvas = sf._parent_canvas
    scrollbar = sf._scrollbar
    pending = {"region": None, "fit": None}

    # 永久隐藏滚动条,避免内容是否溢出导致 canvas 宽度变化带来的微小布局抖动。
    # 鼠标滚轮仍可滚动:CTkScrollableFrame 在 __init__ 里通过 bind_all("<MouseWheel>")
    # 监听滚轮事件,与滚动条是否可见无关。
    scrollbar.grid_remove()

    def _do_update_region():
        pending["region"] = None
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

    def _on_inner_configure(_event):
        if pending["region"] is not None:
            try: sf.after_cancel(pending["region"])
            except Exception: pass
        pending["region"] = sf.after(delay_ms, _do_update_region)

    original_fit = sf._fit_frame_dimensions_to_canvas

    def _do_fit(event):
        pending["fit"] = None
        try:
            original_fit(event)
        except Exception:
            pass

    def _on_canvas_configure(event):
        if pending["fit"] is not None:
            try: sf.after_cancel(pending["fit"])
            except Exception: pass
        pending["fit"] = sf.after(delay_ms, lambda e=event: _do_fit(e))

    def _on_canvas_map(event):
        # tab 被显示（grid 进来）的瞬间立即把内层 frame 宽度 snap 到 canvas，
        # 否则它会先以"请求宽度"出现、80ms 防抖后才对齐，肉眼可见地"抖一下"。
        # <Map> 只在显示/切换 tab 时触发，拖动窗口 resize 不触发，
        # 所以不会把 resize 的防卡顿效果破坏掉。
        if pending["fit"] is not None:
            try: sf.after_cancel(pending["fit"])
            except Exception: pass
            pending["fit"] = None
        # after_idle 确保在本轮几何计算完成后再 fit，此时 canvas 宽度已是最终值
        sf.after_idle(lambda: _do_fit(event))

    sf.bind("<Configure>", _on_inner_configure)
    canvas.bind("<Configure>", _on_canvas_configure)
    canvas.bind("<Map>", _on_canvas_map)


def optimize_combobox_width(combo, offset=120):
    """优化下拉框宽度，使其下拉列表与控件宽度一致"""
    def on_configure(event):
        # 获取 Combobox 实际宽度
        width = combo.winfo_width()
        if width < 20: return
        
        # 使用字体测量来精确计算需要的字符数，不再使用估算值
        if hasattr(combo, "_dropdown_menu"):
            try:
                # 获取下拉菜单使用的字体 (经过缩放的)
                # CustomTkinter 内部方法 _apply_font_scaling 返回 (family, size, style)
                font_tuple = combo._dropdown_menu._apply_font_scaling(combo._dropdown_menu._font)
                
                # 创建临时字体对象用于测量
                temp_font = tkinter.font.Font(font=font_tuple)
                
                # 测量空格的宽度 (因为 ljust 使用空格填充)
                space_width = temp_font.measure(" ")
                if space_width < 1: space_width = 1
                
                # 计算需要的字符数
                # 减去一个固定值 (约 offset px) 以补偿：
                # 1. 实际字符比空格宽造成的长度溢出
                # 2. 菜单自身的边框和内边距
                adjusted_width = max(0, width - offset)
                new_min_char = int(adjusted_width / space_width)
                
                current_min = combo._dropdown_menu._min_character_width
                # 只有变化较大时才更新，避免频繁刷新
                if abs(current_min - new_min_char) > 2:
                    combo._dropdown_menu._min_character_width = new_min_char
                    combo._dropdown_menu._add_menu_commands()
            except Exception:
                pass
    
    combo.bind("<Configure>", on_configure)
