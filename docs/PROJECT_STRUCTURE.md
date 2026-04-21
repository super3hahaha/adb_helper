# 项目结构

```
adb_helper/
├── main.py                  # 程序入口
├── config.json              # 运行时配置文件（自动生成）
├── start.bat                # Windows 快速启动脚本
├── requirements.txt         # Python 依赖清单
├── core/                    # 核心业务逻辑
│   ├── adb_helper.py        # ADB 命令封装与设备管理
│   ├── config_manager.py    # 配置读写与持久化
│   ├── file_helper.py       # 文件与临时目录操作
│   └── platform_utils.py    # 跨平台适配工具
├── ui/                      # 界面层
│   ├── main_window.py       # 主窗口与 Tab 容器
│   ├── utils.py             # UI 工具函数
│   ├── tabs/                # 主界面各 Tab 页
│   │   ├── app_manage_tab.py    # App 操作 Tab
│   │   ├── tools_tab.py         # 实用工具 Tab
│   │   ├── apk_manager_tab.py   # APK 管理 Tab
│   │   └── settings_tab.py      # 设置 Tab
│   ├── components/          # 可复用 UI 组件
│   │   ├── tooltip.py           # 悬浮提示框
│   │   ├── logcat_window.py     # Logcat 实时日志窗口（含自定义过滤词快捷标签）
│   │   ├── file_manager_window.py  # 设备文件管理器
│   │   ├── firebase_window.py   # Firebase 事件监控窗口
│   │   └── contact_selector.py  # 联系人选择对话框
│   └── windows/             # 独立功能窗口
│       └── screenshot_preview.py  # 截图预览与标注
├── resources/               # 内置资源
│   └── ADBKeyboard.apk      # ADB Keyboard 输入法
├── docs/                    # 文档资源
│   └── setup_guide.png      # 初始化配置引导图
└── .github/workflows/       # CI/CD
    └── build.yml            # GitHub Actions 构建配置
```

# 依赖库

| 库 | 类型 | 作用 |
|---|---|---|
| `customtkinter` | 第三方 | 现代化 Tkinter UI 框架，提供主窗口、按钮、输入框、TabView 等组件 |
| `Pillow` | 第三方 | 图像处理库，用于截图预览、标注绘制和图片格式转换 |
| `tkinterdnd2` | 第三方 | 拖拽支持库，实现文件拖拽安装 APK 和拖拽上传文件 |
| `pywin32` | 第三方 (Windows) | Windows 专用，提供剪贴板等系统级功能 |
| `tkinter` | 标准库 | Python 内置 GUI 库，提供 Treeview、Text、messagebox、filedialog 等基础组件 |
| `subprocess` | 标准库 | 执行 ADB 命令与外部进程调用 |
| `threading` | 标准库 | 后台线程，避免 ADB 命令和网络请求阻塞 UI |
| `json` | 标准库 | 配置文件的读写与解析 |
| `re` | 标准库 | 正则表达式，用于解析 ADB 输出和日志过滤 |
| `shutil` | 标准库 | 文件与目录的复制、移动操作 |
| `glob` | 标准库 | 文件路径模式匹配，用于扫描 APK 文件 |
| `os` / `sys` | 标准库 | 系统路径、环境变量与平台判断 |
