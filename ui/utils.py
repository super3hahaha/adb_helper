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

    def _apply_scrollbar_visibility():
        try:
            bbox = canvas.bbox("all")
            if bbox is None:
                return
            content_h = bbox[3] - bbox[1]
            if content_h <= canvas.winfo_height() + 1:
                scrollbar.grid_remove()
            else:
                scrollbar.grid()
        except Exception:
            pass

    def _do_update_region():
        pending["region"] = None
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
            _apply_scrollbar_visibility()
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
            # canvas 尺寸变了(典型场景:窗口高度被拖小)也要重新判断滚动条
            _apply_scrollbar_visibility()
        except Exception:
            pass

    def _on_canvas_configure(event):
        if pending["fit"] is not None:
            try: sf.after_cancel(pending["fit"])
            except Exception: pass
        pending["fit"] = sf.after(delay_ms, lambda e=event: _do_fit(e))

    sf.bind("<Configure>", _on_inner_configure)
    canvas.bind("<Configure>", _on_canvas_configure)


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
