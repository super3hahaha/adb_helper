import subprocess
import threading
import sys
import re
import time
import os
import queue
from core.platform_utils import PlatformUtils

class NoDeviceConnectedError(Exception):
    """当没有设备连接或未选择设备时抛出的异常"""
    pass

class ADBHelper:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.logcat_process = None
        self.recording_process = None
        self.log_queue = None
        self.current_device_id = None # 当前选中的设备序列号
        # ADB 路径适配
        self.adb_cmd = PlatformUtils.get_adb_executable()

    def log(self, message, level="INFO"):
        if self.log_callback:
            self.log_callback(message, level)
        else:
            print(f"[{level}] {message}")

    def run_adb_async(self, cmd_list, on_complete=None, check_dev=True):
        """启动新线程执行 ADB 命令"""
        def _wrapper():
            try:
                success, _ = self.execute_adb_command(cmd_list, check_dev=check_dev)
            except NoDeviceConnectedError:
                success = False
                
            if on_complete:
                try:
                    on_complete(success)
                except TypeError:
                    on_complete()
        threading.Thread(target=_wrapper, daemon=True).start()

    def _get_subprocess_kwargs(self, capture_output=True, text=True):
        return PlatformUtils.get_subprocess_kwargs(capture_output, text)

    def execute_adb_command(self, cmd_list, check_dev=True):
        """执行 ADB 命令并处理输出 (核心函数)"""
        
        # ADB 路径适配
        if cmd_list and cmd_list[0] == "adb":
            cmd_list[0] = self.adb_cmd

        # 自动注入设备 ID (除了 adb devices 这种命令)
        if check_dev:
            # 排除全局命令
            is_global_cmd = (len(cmd_list) >= 2 and cmd_list[0] == self.adb_cmd and cmd_list[1] in ("devices", "connect", "disconnect", "start-server", "kill-server", "version"))
            if not is_global_cmd:
                try:
                    self.check_device()
                    # 假设 cmd_list 是 ["adb", "shell", "ls"]
                    # 注入后变为 ["adb", "-s", "device_id", "shell", "ls"]
                    if cmd_list[0] == self.adb_cmd and "-s" not in cmd_list:
                        cmd_list.insert(1, "-s")
                        cmd_list.insert(2, self.current_device_id)
                except NoDeviceConnectedError as e:
                    self.log(f"操作中止: {e}", "ERROR")
                    raise e # 向上抛出以便 UI 层拦截

        cmd_str = " ".join(cmd_list)
        self.log(f"执行命令: {cmd_str}", "CMD")

        try:
            # 执行命令
            result = subprocess.run(
                cmd_list,
                **self._get_subprocess_kwargs()
            )

            # 处理输出
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode == 0:
                if stdout:
                    self.log(f"结果:\n{stdout}", "SUCCESS")
                else:
                    self.log("结果: 执行成功 (无返回内容)", "SUCCESS")
                return True, stdout
            else:
                error_msg = stderr if stderr else stdout  # 有些 adb 错误可能在 stdout
                self.log(f"执行失败 (Code {result.returncode}):\n{error_msg}", "ERROR")
                
                if "device not found" in error_msg or "no devices" in error_msg:
                    self.log("提示: 请检查 USB 连接及调试模式。", "ERROR")
                return False, error_msg

        except FileNotFoundError:
            self.log("错误: 未找到 adb 命令，请检查环境变量。", "ERROR")
            return False, "未找到 adb 命令"
        except Exception as e:
            self.log(f"发生异常: {str(e)}", "ERROR")
            return False, str(e)

    # --- Specific ADB Actions ---

    def get_connected_devices(self):
        """获取所有已连接的设备列表"""
        try:
            result = subprocess.run(
                [self.adb_cmd, "devices"],
                **self._get_subprocess_kwargs()
            )
            
            devices = []
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]: # 跳过第一行 "List of devices attached"
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == "device":
                            devices.append(parts[0])
            return devices
        except Exception as e:
            self.log(f"获取设备列表失败: {e}", "ERROR")
            return []

    def check_device(self):
        """检查是否有选中的设备，且该设备在线"""
        if not self.current_device_id:
            raise NoDeviceConnectedError("当前未选择任何设备")
            
        # 可选：每次执行前检查设备是否还在连着，但这会增加每次命令的耗时
        # 为了性能，这里可以只做简单的非空判断，或者依赖 adb -s 的自带报错
        # 为了严谨，如果需要可以取消下面注释：
        # current_devices = self.get_connected_devices()
        # if self.current_device_id not in current_devices:
        #     self.current_device_id = None
        #     raise NoDeviceConnectedError(f"设备 {self.current_device_id} 已断开连接")
        return True

    def send_text(self, text):
        if text:
            text_escaped = text.replace(" ", "%s") 
            return self.execute_adb_command(["adb", "shell", "input", "text", text_escaped])
        return False, "Empty text"

    def sim_low_battery(self):
        def _seq():
            self.execute_adb_command(["adb", "shell", "dumpsys", "battery", "unplug"])
            self.execute_adb_command(["adb", "shell", "dumpsys", "battery", "set", "level", "10"])
        threading.Thread(target=_seq, daemon=True).start()

    def sim_full_battery(self):
        def _seq():
            self.execute_adb_command(["adb", "shell", "dumpsys", "battery", "set", "ac", "1"])
            self.execute_adb_command(["adb", "shell", "dumpsys", "battery", "set", "status", "5"])
            self.execute_adb_command(["adb", "shell", "dumpsys", "battery", "set", "level", "100"])
        threading.Thread(target=_seq, daemon=True).start()

    def reset_battery(self):
        self.execute_adb_command(["adb", "shell", "dumpsys", "battery", "reset"])

    # --- Logcat ---
    def start_logcat(self, log_level="E"):
        try:
            self.check_device()
        except NoDeviceConnectedError as e:
            self.log(f"操作中止: {e}", "ERROR")
            raise e

        self.stop_logcat()  # Ensure previous session is stopped
        
        self.log_queue = queue.Queue()
        cmd = [self.adb_cmd, "-s", self.current_device_id, "logcat", "-v", "time", f"*:{log_level}"]
        
        try:
            kwargs = self._get_subprocess_kwargs(capture_output=False)
            kwargs['stdout'] = subprocess.PIPE
            kwargs['stderr'] = subprocess.PIPE
            kwargs['bufsize'] = 1
            
            self.logcat_process = subprocess.Popen(
                cmd,
                **kwargs
            )
            
            def _read_log_thread():
                while self.logcat_process and self.logcat_process.poll() is None:
                    try:
                        line = self.logcat_process.stdout.readline()
                        if not line:
                            break
                        self.log_queue.put(line)
                    except Exception:
                        break
            
            threading.Thread(target=_read_log_thread, daemon=True).start()
            return self.log_queue
            
        except Exception as e:
            self.log(f"Failed to start logcat: {e}", "ERROR")
            return None

    def stop_logcat(self):
        if self.logcat_process:
            try:
                self.logcat_process.terminate()
                self.logcat_process.wait(timeout=1)
            except Exception:
                pass
            self.logcat_process = None
        self.log_queue = None

    # --- APK Installation ---

    def wifi_disable(self):
        self.run_adb_async(["adb", "shell", "svc", "wifi", "disable"])

    def wifi_enable(self):
        self.run_adb_async(["adb", "shell", "svc", "wifi", "enable"])

    def uninstall_app(self, pkg):
        self.run_adb_async(["adb", "uninstall", pkg])

    def clear_data(self, pkg, on_complete=None):
        self.run_adb_async(["adb", "shell", "pm", "clear", pkg], on_complete)

    def install_apk(self, apk_path, on_complete=None):
        self.run_adb_async(["adb", "install", "-r", apk_path], on_complete)

    def push_files(self, local_paths: list, remote_path: str):
        """推送多个文件或文件夹到设备"""
        self.check_device()  # 全局拦截校验，如果无设备会抛出 NoDeviceConnectedError
        
        success_count = 0
        total_count = len(local_paths)
        errors = []

        for local_path in local_paths:
            # 解决 adb 在 Windows 下处理带中文路径时，自动提取文件名可能导致截断的 Bug
            # 如果远端路径明确是目录（以 / 结尾），我们手动补全远端文件或文件夹名
            push_remote_path = remote_path
            push_local_path = local_path

            if push_remote_path.endswith("/"):
                basename = os.path.basename(os.path.normpath(local_path))
                if basename:
                    push_remote_path = push_remote_path + basename

                # 如果是文件夹，为了防止远端目录已存在时 adb 会把文件夹嵌套进去 (变成 /sdcard/xxx/dir/dir)
                # 我们将推送的内容指定为 local_path/. ，代表推送文件夹下的所有内容到我们明确指定的 push_remote_path 目录内
                if os.path.isdir(local_path):
                    push_local_path = os.path.join(local_path, ".")

            # 兼容路径带空格的情况，虽然 execute_adb_command 内部用列表传参通常不需要加引号
            # 但为防万一，确保传入的是纯净路径
            cmd = ["adb", "push", push_local_path, push_remote_path]
            success, msg = self.execute_adb_command(cmd)
            if success:
                success_count += 1
            else:
                errors.append(f"Push failed for {os.path.basename(local_path)}: {msg}")

        if success_count == total_count:
            return True, f"Successfully pushed {success_count} items."
        else:
            return False, f"Pushed {success_count}/{total_count} items. Errors: {'; '.join(errors)}"

    def launch_app(self, package_name):
        """通过 monkey 命令启动 App (不需要知道 Activity)"""
        if not package_name:
            return False, "Package name is empty"
        return self.execute_adb_command(["adb", "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"])

    def stop_app(self, package_name):
        """强制停止 App"""
        if not package_name:
            return False, "Package name is empty"
        return self.execute_adb_command(["adb", "shell", "am", "force-stop", package_name])

    def install_apk_sync(self, apk_path):
        """同步安装 APK 并返回结果，供拖拽安装使用"""
        return self.execute_adb_command(["adb", "install", "-r", apk_path])

    def clear_google_play_data(self):
        """清除 Google Play 商店数据"""
        return self.execute_adb_command(["adb", "shell", "pm", "clear", "com.android.vending"])

    # --- File Manager Logic ---

    def list_device_files(self, remote_path: str):
        """获取设备文件列表"""
        self.check_device()
        cmd = ["adb", "shell", "ls", "-lA", remote_path]
        success, output = self.execute_adb_command(cmd)
        if not success:
            return False, output
            
        files = []
        lines = output.split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('total '):
                continue
            
            parts = line.split(maxsplit=7)
            if len(parts) >= 8:
                permissions = parts[0]
                is_dir = permissions.startswith('d')
                size = parts[4] if not is_dir else "-"
                date = parts[5]
                time_str = parts[6]
                name = parts[7]
                
                # Handle symlinks: name -> target
                if ' -> ' in name:
                    name = name.split(' -> ')[0]
                    
                # Skip . and ..
                if name in ('.', '..'):
                    continue

                files.append({
                    "name": name,
                    "is_dir": is_dir,
                    "size": size,
                    "date": f"{date} {time_str}",
                    "permissions": permissions
                })
                
        return True, files

    def pull_files(self, remote_paths: list, local_dir: str):
        """从设备拉取文件"""
        self.check_device()
        success_count = 0
        total_count = len(remote_paths)
        errors = []

        for remote_path in remote_paths:
            cmd = ["adb", "pull", remote_path, local_dir]
            success, msg = self.execute_adb_command(cmd)
            if success:
                success_count += 1
            else:
                errors.append(f"Pull failed for {os.path.basename(remote_path)}: {msg}")

        if success_count == total_count:
            return True, f"Successfully pulled {success_count} items."
        else:
            return False, f"Pulled {success_count}/{total_count} items. Errors: {'; '.join(errors)}"

    def delete_device_file(self, remote_path: str):
        """删除设备文件或文件夹"""
        self.check_device()
        cmd = ["adb", "shell", "rm", "-rf", remote_path]
        return self.execute_adb_command(cmd)

    # --- Wireless Debugging Logic ---
    
    def start_wireless_debug_flow(self, on_ip_found, on_failure, on_success):
        """
        Starts the wireless debugging flow.
        1. Enables TCPIP
        2. Gets IP
        3. Calls on_ip_found(ip) -> UI should prompt user to unplug
        4. (UI calls connect_wireless_after_confirm)
        """
        def _thread():
            self.log("正在启动无线调试流程...", "INFO")
            try:
                # 1. Open Port
                # Some devices disconnect when running `adb tcpip 5555` while already connected via tcpip,
                # or the USB connection might temporarily drop and reconnect.
                # To avoid breaking the command pipeline that fetches the IP, we get the IP first.
                
                # 2. Get IP first
                self.log("正在尝试获取设备 IP...", "INFO")
                device_ip = None
                
                ip_strategies = [
                    (["adb", "shell", "ip", "route"], [
                        r'dev\s+wlan0\s+.*src\s+(\d+\.\d+\.\d+\.\d+)',
                        r'src\s+(\d+\.\d+\.\d+\.\d+).*dev\s+wlan0',
                        r'src\s+(\d+\.\d+\.\d+\.\d+)'
                    ]),
                    (["adb", "shell", "ip", "addr", "show", "wlan0"], [r'inet\s+(\d+\.\d+\.\d+\.\d+)']),
                    (["adb", "shell", "ifconfig", "wlan0"], [r'inet\s+(?:addr:)?(\d+\.\d+\.\d+\.\d+)']),
                    (["adb", "shell", "ip", "-4", "addr"], [
                        r'wlan0.*?inet\s+(\d+\.\d+\.\d+\.\d+)',
                        r'global\s+wlan0\s+.*?inet\s+(\d+\.\d+\.\d+\.\d+)'
                    ]),
                    (["adb", "shell", "netcfg"], [r'wlan0\s+UP\s+(\d+\.\d+\.\d+\.\d+)'])
                ]

                try:
                    self.check_device()
                except NoDeviceConnectedError as e:
                    self.log(f"操作中止: {e}", "ERROR")
                    if on_failure:
                        on_failure(f"EXCEPTION: {str(e)}")
                    return

                for cmd, patterns in ip_strategies:
                    if device_ip: break
                    try:
                        if cmd[0] == "adb" and "-s" not in cmd:
                            cmd.insert(1, "-s")
                            cmd.insert(2, self.current_device_id)
                            
                        # ADB 路径适配
                        if cmd[0] == "adb":
                            cmd[0] = self.adb_cmd
                            
                        self.log(f"尝试获取IP指令: {' '.join(cmd)}", "INFO")
                        result = subprocess.run(
                            cmd,
                            **self._get_subprocess_kwargs()
                        )
                        output = result.stdout.strip()
                        
                        for pattern in patterns:
                            match = re.search(pattern, output, re.IGNORECASE | re.DOTALL)
                            if match:
                                ip_candidate = match.group(1)
                                if not ip_candidate.startswith("127."):
                                    device_ip = ip_candidate
                                    self.log(f"通过策略成功获取 IP: {device_ip}", "SUCCESS")
                                    break
                        
                        if not device_ip and "ip" in cmd and "addr" in cmd:
                             all_ips = re.findall(r'inet\s+(\d+\.\d+\.\d+\.\d+)', output)
                             for ip in all_ips:
                                 if not ip.startswith("127."):
                                     device_ip = ip
                                     self.log(f"通过通用扫描获取 IP: {device_ip}", "SUCCESS")
                                     break
                    except Exception as e:
                        self.log(f"指令执行异常: {e}", "ERROR")

                if not device_ip:
                    # Notify UI to ask for manual IP
                    self.log("自动获取 IP 失败，请求手动输入...", "WARNING")
                    if on_failure:
                        on_failure("IP_NOT_FOUND")
                    return

                self.log(f"获取到设备 IP: {device_ip}", "INFO")
                
                # 3. Open Port (after getting IP to avoid disconnection issues during IP retrieval)
                self.log("正在开启设备 TCP/IP 端口 5555...", "INFO")
                self.execute_adb_command(["adb", "tcpip", "5555"])
                time.sleep(2)

                if on_ip_found:
                    on_ip_found(device_ip)

            except Exception as e:
                self.log(f"无线调试流程异常: {str(e)}", "ERROR")
                if on_failure:
                    on_failure(f"EXCEPTION: {str(e)}")

        threading.Thread(target=_thread, daemon=True).start()

    def connect_wireless_after_confirm(self, device_ip, on_result):
        """
        Continues the wireless debugging flow after user confirmation.
        """
        def _thread():
            self.log("正在尝试无线连接...", "INFO")
            
            # Check USB
            try:
                check_res = subprocess.run(
                    [self.adb_cmd, "devices"],
                    **self._get_subprocess_kwargs()
                )
                usb_devices = [line for line in check_res.stdout.splitlines() if "\tdevice" in line and not re.search(r'\d+\.\d+\.\d+\.\d+:\d+', line)]
                # Warning logic should be handled by UI if needed, or we just proceed
            except: pass
            
            # Connect
            self.execute_adb_command(["adb", "connect", f"{device_ip}:5555"], check_dev=False)
            time.sleep(2)
            
            # Verify
            final_res = subprocess.run(
                [self.adb_cmd, "devices"],
                **self._get_subprocess_kwargs()
            )
            
            success = f"{device_ip}:5555" in final_res.stdout
            if success:
                self.log(f"无线调试连接成功: {device_ip}", "SUCCESS")
            else:
                self.log("无线调试连接失败", "ERROR")
            
            if on_result:
                on_result(success, device_ip)

        threading.Thread(target=_thread, daemon=True).start()

    def stop_wireless_debug(self, on_complete=None):
        def _thread():
            self.log("正在检查已连接的无线设备...", "INFO")
            try:
                result = subprocess.run(
                    [self.adb_cmd, "devices"],
                    **self._get_subprocess_kwargs()
                )
                output = result.stdout
                wireless_devices = re.findall(r'(\d+\.\d+\.\d+\.\d+:\d+)\s+device', output)
                
                if not wireless_devices:
                    self.log("未发现已连接的无线调试设备", "WARNING")
                    if on_complete: on_complete(0)
                    return

                count = 0
                for device in wireless_devices:
                    self.execute_adb_command(["adb", "disconnect", device], check_dev=False)
                    count += 1
                
                if on_complete: on_complete(count)
                
            except Exception as e:
                self.log(f"关闭无线调试异常: {str(e)}", "ERROR")
                if on_complete: on_complete(-1, str(e)) # -1 indicates error

        threading.Thread(target=_thread, daemon=True).start()

    # --- Firebase & Logcat ---

    def enable_firebase_debug(self, pkg):
        """开启 Firebase 本地调试模式属性 (前置命令)"""
        self.log(f"正在开启 {pkg} 的 Firebase 调试模式...", "INFO")
        self.execute_adb_command(["adb", "shell", "setprop", "log.tag.FA", "VERBOSE"])
        self.execute_adb_command(["adb", "shell", "setprop", "log.tag.FA-SVC", "VERBOSE"])
        self.execute_adb_command(["adb", "shell", "setprop", "debug.firebase.analytics.app", pkg])
        self.log("Firebase 调试属性设置完成", "SUCCESS")

    def start_firebase_logcat(self):
        """以非阻塞流模式执行 Firebase 专属 logcat 命令"""
        try:
            self.check_device()
        except NoDeviceConnectedError as e:
            self.log(f"操作中止: {e}", "ERROR")
            raise e

        self.stop_firebase_logcat()
        
        if not hasattr(self, 'firebase_log_queue') or self.firebase_log_queue is None:
            self.firebase_log_queue = queue.Queue()
            
        cmd_logcat = [self.adb_cmd, "-s", self.current_device_id, "logcat", "-v", "time", "-s", "FA", "FA-SVC"]
        self.log(f"执行专属 Firebase Logcat 命令: {' '.join(cmd_logcat)}", "CMD")
        
        try:
            kwargs = self._get_subprocess_kwargs(capture_output=False)
            kwargs['stdout'] = subprocess.PIPE
            kwargs['stderr'] = subprocess.PIPE
            kwargs['bufsize'] = 1
            
            self.firebase_logcat_process = subprocess.Popen(
                cmd_logcat,
                **kwargs
            )
            
            def _read_thread():
                while hasattr(self, 'firebase_logcat_process') and self.firebase_logcat_process and self.firebase_logcat_process.poll() is None:
                    try:
                        line = self.firebase_logcat_process.stdout.readline()
                        if not line:
                            break
                        self.firebase_log_queue.put(line)
                    except Exception:
                        break
                        
            threading.Thread(target=_read_thread, daemon=True).start()
            return self.firebase_log_queue
            
        except Exception as e:
            self.log(f"Firebase Logcat 启动失败: {e}", "ERROR")
            return None

    def stop_firebase_logcat(self):
        """终止 Firebase 的 Popen 进程"""
        if hasattr(self, 'firebase_logcat_process') and self.firebase_logcat_process:
            try:
                self.firebase_logcat_process.terminate()
                self.firebase_logcat_process.wait(timeout=1)
            except Exception:
                pass
            self.firebase_logcat_process = None
            self.log("已停止 Firebase 专属日志抓取", "INFO")

    # --- Screen Record ---

    def start_recording(self):
        try:
            self.check_device()
        except NoDeviceConnectedError as e:
            self.log(f"操作中止: {e}", "ERROR")
            raise e

        if self.recording_process:
            return False
            
        cmd = [self.adb_cmd, "-s", self.current_device_id, "shell", "screenrecord", "/sdcard/screen_record_tmp.mp4"]
        
        try:
            kwargs = self._get_subprocess_kwargs(capture_output=False, text=False)
            kwargs['stdout'] = subprocess.PIPE
            kwargs['stderr'] = subprocess.PIPE

            self.recording_process = subprocess.Popen(
                cmd,
                **kwargs
            )
            return True
        except Exception as e:
            self.log(f"启动录制失败: {e}", "ERROR")
            return False

    def stop_recording(self, temp_dir, on_complete):
        """
        Stops recording, pulls file, deletes remote file.
        Calls on_complete(local_path) when done.
        """
        def _thread():
            try:
                if self.recording_process:
                    self.recording_process.terminate()
                    self.recording_process = None
                
                time.sleep(2)
                
                remote_path = "/sdcard/screen_record_tmp.mp4"
                local_filename = f"screenrecord_{int(time.time())}.mp4"
                local_path = os.path.join(temp_dir, local_filename)
                
                self.execute_adb_command(["adb", "pull", remote_path, local_path])
                self.execute_adb_command(["adb", "shell", "rm", remote_path])
                
                if on_complete:
                    on_complete(local_path)
                    
            except Exception as e:
                self.log(f"停止录制失败: {e}", "ERROR")
                if on_complete: on_complete(None)

        threading.Thread(target=_thread, daemon=True).start()

    # --- Screenshot ---
    
    def take_screenshot(self, temp_dir, on_complete):
        def _thread():
            try:
                remote_path = "/sdcard/screen.png"
                local_filename = f"screenshot_{int(time.time())}.png"
                local_path = os.path.join(temp_dir, local_filename)
                
                self.execute_adb_command(["adb", "shell", "screencap", "-p", remote_path])
                self.execute_adb_command(["adb", "pull", remote_path, local_path])
                self.execute_adb_command(["adb", "shell", "rm", remote_path])
                
                if on_complete:
                    on_complete(local_path)
            except Exception as e:
                self.log(f"截图失败: {e}", "ERROR")
                if on_complete: on_complete(None)
        
        threading.Thread(target=_thread, daemon=True).start()

