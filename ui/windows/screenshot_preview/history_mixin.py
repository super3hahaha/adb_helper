"""撤销/重做栈。

本 Mixin 拥有：
    self._undo_stack, self._redo_stack
本 Mixin 读取但不拥有：
    self.shapes  (主窗口持有)
    self.update_image()  (CanvasMixin 提供)

动作格式：{'op': 'add'|'remove', 'shape': dict, 'index': int}
  - 'add'：shape 被插入到 index 位置；撤销=移除
  - 'remove'：shape 从 index 位置被移除；撤销=重新插入
"""


class HistoryMixin:

    def _init_history_state(self):
        self._undo_stack = []
        self._redo_stack = []

    def _push_history(self, action):
        """用户新动作入栈，清空 redo 栈。"""
        self._undo_stack.append(action)
        self._redo_stack.clear()

    def _clear_history(self):
        """切换图片等场景下清空两条栈。"""
        self._undo_stack.clear()
        self._redo_stack.clear()

    def _apply_inverse(self, action):
        """施加 action 的逆操作到 self.shapes。返回逆操作（供推入对面栈）。"""
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

    def undo_last_shape(self, event=None):
        if not self._undo_stack:
            return
        action = self._undo_stack.pop()
        inverse = self._apply_inverse(action)
        self._redo_stack.append(inverse)
        self.update_image()

    def redo_last_shape(self, event=None):
        if not self._redo_stack:
            return
        action = self._redo_stack.pop()
        inverse = self._apply_inverse(action)
        self._undo_stack.append(inverse)
        self.update_image()
