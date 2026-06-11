#!/bin/bash
# 可视化 ADB 管理工具 启动器（双击运行）
cd "$(dirname "$0")" || exit 1

# 让 adb 命令可用（Homebrew / Android SDK 常见路径）
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$HOME/Library/Android/sdk/platform-tools:$PATH"

# 激活虚拟环境
source venv/bin/activate

# 后台启动 GUI 并与终端完全解绑：
# 重定向全部标准流到 /dev/null + nohup + disown，使其脱离控制终端，
# 这样关闭启动窗口不会杀掉 app。
nohup python main.py </dev/null >/dev/null 2>&1 &
disown

# 关掉这个启动窗口。关键：延迟到本脚本 shell 退出之后再关，
# 否则 Terminal 检测到脚本进程仍在跑会弹"是否终止进程"确认框。
# 把关窗任务甩成脱离会话的孤儿进程(nohup+disown+全流重定向)，再立刻 exit。
MYTTY=$(tty)
nohup bash -c "sleep 1; osascript -e 'tell application \"Terminal\" to close (every window whose tty of selected tab is \"$MYTTY\")'" </dev/null >/dev/null 2>&1 &
disown
exit 0
