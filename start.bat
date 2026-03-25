@echo off
cd /d "%~dp0"

:: 激活虚拟环境（假设你的虚拟环境文件夹叫 venv）
call venv\Scripts\activate

:: 运行程序（想隐藏黑框就把 python 改成 start pythonw）
start pythonw main.py
