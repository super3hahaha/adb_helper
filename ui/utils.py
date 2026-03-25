import tkinter.font
import tkinter

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
