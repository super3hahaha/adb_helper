import subprocess
import threading
import sys
import re
import time
import os
import queue
import socket
import xml.etree.ElementTree as ET
from core.platform_utils import PlatformUtils

class NoDeviceConnectedError(Exception):
    """当没有设备连接或未选择设备时抛出的异常"""
    pass


def _device_sh_quote(s: str) -> str:
    """把字符串包成可安全交给设备端 sh 的单引号字面量。
    adb shell 会把多个 token 用空格拼成单条命令行交给设备 sh 解析，
    路径里出现 ( ) 空格 ; & | * ? 等字符时必须由调用方自己引号化。"""
    return "'" + s.replace("'", "'\\''") + "'"

class ADBHelper:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.logcat_process = None
        self.recording_process = None
        self.log_queue = None
        self.current_device_id = None # 当前选中的设备序列号
        # 由外部注入：device_id -> 别名 的解析函数（无则回退到序列号）
        self.device_label_resolver = None
        # USB 序列号 -> 该设备的无线地址 "ip:port"。开启无线调试时写入，
        # 用于拔线后把 UI 的选中项跟到同一台设备的无线 entry 上（多设备下
        # 不能简单 fallback 到列表第一台，否则会静默跳到别人的机器上）
        self.wireless_addr_by_serial = {}
        # adb server 是否已确认在运行（见 _ensure_adb_server）
        self._adb_server_ready = False
        self._adb_server_lock = threading.Lock()
        # 设备插拔监听（见 start_device_watch）
        self._watch_thread = None
        self._watch_stop_event = threading.Event()
        self._watch_sock = None
        # ADB 路径适配
        self.adb_cmd = PlatformUtils.get_adb_executable()

    def _device_label_for_filename(self):
        """返回用于文件名的设备标签：有别名优先用别名，否则用序列号。已做合法化处理。"""
        if not self.current_device_id:
            return ""
        alias = ""
        if self.device_label_resolver:
            try:
                alias = (self.device_label_resolver(self.current_device_id) or "").strip()
            except Exception:
                alias = ""
        label = alias if alias else self.current_device_id
        # 替换文件名非法字符和空白
        label = re.sub(r'[\\/:*?"<>|\s]+', '_', label).strip('_')
        return label

    def log(self, message, level="INFO"):
        if self.log_callback:
            self.log_callback(message, level)
        else:
            print(f"[{level}] {message}")

    def run_adb_async(self, cmd_list, on_complete=None, check_dev=True, timeout=None):
        """启动新线程执行 ADB 命令"""
        def _wrapper():
            try:
                success, _ = self.execute_adb_command(cmd_list, check_dev=check_dev, timeout=timeout)
            except NoDeviceConnectedError:
                success = False
                
            if on_complete:
                try:
                    on_complete(success)
                except TypeError:
                    on_complete()
        threading.Thread(target=_wrapper, daemon=True).start()

    # 默认超时（秒）。设备休眠/未授权/USB 异常时，adb 可能永久阻塞，
    # 加超时保证同步调用一定会在有限时间内返回（或报超时）。
    DEVICES_TIMEOUT = 10   # adb devices：含冷启动 daemon 的余量
    SHELL_TIMEOUT = 20     # 普通 shell/命令
    PUSH_TIMEOUT = 300     # adb push：批量/文件夹传输耗时不定，尤其老设备(Android 8 及更早
                           # 缺少 Android 9+ 的 sync 协议管线化优化)，多文件逐个走同步 stat+传输，
                           # 远比单文件慢，20s 通用超时会把仍在正常传输的 push 误杀
    INSTALL_TIMEOUT = 300  # adb install：apk 装到设备后要做 dex/ART 优化编译，
                           # 性能较差/存储较慢的设备上这一步可能远超 20s，同样不能用通用超时

    # 部分老 / 定制 ROM 设备（实测华为 P9 EVA-AL10 / EMUI Android 8.0）USB 连接会在传输中途
    # 短暂掉线又自动恢复（实测 adb devices 15s 内重新出现），推大文件夹时 adb push 会报
    # "failed to read copy response: EOF" 而中止。注意 `adb push <dir>/. <remote>` 不是增量同步，
    # 重试会把整个文件夹全部重传一遍（实测同一批 30 个 mp3 重新 push 是 "30 files pushed, 0 skipped"，
    # 不会跳过已存在的文件）——但重传的代价好过失败，掉线后原样重试同一条命令即可补全。
    PUSH_RETRIES = 2          # 失败后再重试的次数（不含首次尝试）
    PUSH_RECONNECT_WAIT = 20  # 重试前，等待设备重新出现在 `adb devices` 里的最长秒数
    _PUSH_RETRYABLE_PATTERNS = (
        "failed to read copy response",
        "eof",
        "device offline",
        "device not found",
        "no devices",
        "protocol fault",
        "connection reset",
    )

    def _is_retryable_push_error(self, msg):
        low = (msg or "").lower()
        return any(p in low for p in self._PUSH_RETRYABLE_PATTERNS)

    def _wait_for_device_reconnect(self, max_wait=None, poll_interval=2):
        """设备掉线后阻塞等待其重新出现在 `adb devices` 列表，供 push 重试前调用。"""
        device_id = self.current_device_id
        if not device_id:
            return
        max_wait = self.PUSH_RECONNECT_WAIT if max_wait is None else max_wait
        waited = 0
        while waited < max_wait:
            if device_id in self.get_connected_devices():
                return
            time.sleep(poll_interval)
            waited += poll_interval

    def _get_subprocess_kwargs(self, capture_output=True, text=True, timeout=None):
        return PlatformUtils.get_subprocess_kwargs(capture_output, text, timeout)

    def _ensure_adb_server(self, force=False):
        """确保 adb server 已在运行，且是用 DEVNULL 句柄启动的。

        Windows 冷启动死锁（start.bat 后设备列表永远刷不出来的根因）：
        若 server 未运行，任何带 stdout/stderr 管道的 adb 调用（如
        subprocess.run(["adb","devices"], capture_output=True, timeout=10)）会就地
        spawn 出 adb server 守护进程，daemon 继承了管道的写句柄且永不关闭 →
        客户端退出后管道等不到 EOF；到达 timeout 后 subprocess.run 在 Windows
        分支里 kill 掉客户端，随后还会再调一次**不带超时**的 communicate() 收尾，
        这一步永久阻塞——所以连 TimeoutExpired 都抛不出来，调用线程直接卡死。

        解决：抢在所有管道调用之前，用 DEVNULL 显式 start-server，daemon 继承的
        就是无害句柄。server 已在运行时该命令 <100ms 返回，幂等，可放心 force。
        """
        if self._adb_server_ready and not force:
            return
        with self._adb_server_lock:
            if self._adb_server_ready and not force:
                return
            kwargs = self._get_subprocess_kwargs(
                capture_output=False, text=False, timeout=self.DEVICES_TIMEOUT
            )
            kwargs['stdin'] = subprocess.DEVNULL
            kwargs['stdout'] = subprocess.DEVNULL
            kwargs['stderr'] = subprocess.DEVNULL
            try:
                subprocess.run([self.adb_cmd, "start-server"], **kwargs)
                self._adb_server_ready = True
            except subprocess.TimeoutExpired:
                self.log(f"启动 adb server 超时 ({self.DEVICES_TIMEOUT}s)。", "WARNING")
            except FileNotFoundError:
                self.log("错误: 未找到 adb 命令，请检查环境变量。", "ERROR")
            except Exception as e:
                self.log(f"启动 adb server 失败: {e}", "WARNING")

    # ---------------- 设备插拔监听（adb host:track-devices 长连接） ----------------
    #
    # 为什么不定时轮询 adb devices：插拔一天也就几次，轮询要为此全天不停起进程。
    # 为什么不用 `adb track-devices` 子命令：那只是 CLI 层封装，部分 platform-tools
    #   版本里没有；更要紧的是它意味着一个**长驻的、带 stdout 管道的 adb 子进程**，
    #   正好是 _ensure_adb_server 里描述的那个 Windows 管道死锁的形态。
    # 直接连 adb server 的 socket 反而最干净：没有子进程、没有管道，停止时
    #   shutdown 就能立刻打断阻塞的 recv。host:track-devices 是 adb 的远古 host
    #   服务，协议（4 位 hex 长度前缀 + payload）多年没变过。
    #
    # 协议：连上后发 "host:track-devices" → 读 "OKAY" → 之后每次设备状态变化，
    # server 主动推一帧「当前完整设备列表」快照（可能是空帧，表示当前没有设备）。
    WATCH_SOCK_TIMEOUT = 5    # 等待下一帧的 recv 超时，仅用于周期性醒来看停止标志
    WATCH_FRAME_TIMEOUT = 30  # 长度头已读到后，读 payload 的超时（见 _read_track_frame）
    WATCH_RETRY_MAX = 30      # 断线重连退避上限（秒）

    @staticmethod
    def _adb_server_addr():
        """adb server 的监听地址，尊重 adb 自己那两个环境变量。"""
        host = os.environ.get("ANDROID_ADB_SERVER_ADDRESS") or "127.0.0.1"
        try:
            port = int(os.environ.get("ANDROID_ADB_SERVER_PORT") or 5037)
        except ValueError:
            port = 5037
        return host, port

    @staticmethod
    def _recv_exact(sock, n):
        """阻塞读满 n 字节。对端关闭时抛 ConnectionError。"""
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("adb server 关闭了连接")
            buf += chunk
        return buf

    @staticmethod
    def _send_adb_request(sock, service):
        """按 adb 协议发一个 host 服务请求，并校验返回的 OKAY。"""
        payload = service.encode("utf-8")
        sock.sendall(b"%04x" % len(payload) + payload)
        status = ADBHelper._recv_exact(sock, 4)
        if status != b"OKAY":
            reason = ""
            try:  # FAIL 后面还跟一帧「长度 + 原因」
                n = int(ADBHelper._recv_exact(sock, 4), 16)
                reason = ADBHelper._recv_exact(sock, n).decode("utf-8", "replace")
            except Exception:
                pass
            raise ConnectionError(f"adb server 拒绝了 {service}: {status!r} {reason}")

    def _read_track_frame(self, sock):
        """读一帧设备列表文本。返回 None 表示只是 recv 超时（这段时间没有插拔）。"""
        try:
            head = self._recv_exact(sock, 4)
        except socket.timeout:
            return None
        n = int(head, 16)
        if n == 0:
            return ""  # 合法：当前一台设备都没有
        # 长度头已经拿到手，payload 必须完整读完。这里绝不能沿用"超时就继续外层
        # 循环"那套：读一半就跳走会让后续的长度头错位，协议流永久乱掉。宁可判定
        # 连接坏掉走重连（重连会重建干净的流），也不能错位。
        sock.settimeout(self.WATCH_FRAME_TIMEOUT)
        try:
            return self._recv_exact(sock, n).decode("utf-8", "replace")
        finally:
            sock.settimeout(self.WATCH_SOCK_TIMEOUT)

    @staticmethod
    def _parse_track_payload(text):
        """把一帧解析成 {device_id: state}。帧里只有 id 和 state，没有 serialno。"""
        snapshot = {}
        for line in text.splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 2 and parts[0].strip():
                snapshot[parts[0].strip()] = parts[1].strip()
        return snapshot

    def start_device_watch(self, on_change):
        """开始监听设备插拔，列表有变化时在**工作线程**里回调 on_change()。

        on_change 只是「设备列表变了」的通知，不带数据 —— track-devices 的帧里
        只有 id + state，没有 ro.serialno，调用方仍要自己跑一次完整刷新。
        回调在工作线程里执行，里面碰 UI 必须自己 after(0) 切回主线程。

        这是纯增量功能：监听失败、adb server 没起来、连接断开，都只会退化成
        「跟以前一样需要手动点刷新」，绝不影响手动刷新链路（不碰
        _refreshing_devices、不碰按钮状态），不引入新的锁死路径。
        """
        if self._watch_thread and self._watch_thread.is_alive():
            return
        self._watch_stop_event.clear()
        self._watch_thread = threading.Thread(
            target=self._device_watch_loop, args=(on_change,), daemon=True
        )
        self._watch_thread.start()

    def stop_device_watch(self):
        """停止监听。shutdown 让阻塞在 recv 的线程立刻返回，不必等到 socket 超时。"""
        self._watch_stop_event.set()
        sock = self._watch_sock
        self._watch_sock = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass

    def _device_watch_loop(self, on_change):
        delay = 2
        last = None            # 跨连接保留的「最后已知快照」
        got_frame = False      # 是否已经成功收到过任何一帧（决定首帧算基线还是算变化）
        warned = False         # 连接失败只警告一次，避免 adb 缺失时刷屏
        while not self._watch_stop_event.is_set():
            try:
                # 跟所有 adb 调用一样，先确保 server 在（且是用 DEVNULL 句柄起的）。
                # 必须 force：不 force 的话 _adb_server_ready 一旦为 True 就直接返回，
                # server 真的挂掉后我们只会对着 refused 的端口无限重连，永远没人把它
                # 拉起来。server 已在运行时 start-server <100ms 且幂等，退避下最快也
                # 才 2s 一次，开销可忽略。
                self._ensure_adb_server(force=True)
                if self._watch_stop_event.is_set():
                    return
                with socket.create_connection(
                    self._adb_server_addr(), timeout=self.WATCH_SOCK_TIMEOUT
                ) as sock:
                    sock.settimeout(self.WATCH_SOCK_TIMEOUT)
                    self._watch_sock = sock
                    self._send_adb_request(sock, "host:track-devices")
                    delay = 2       # 连上了，重置退避
                    warned = False  # 也重置告警：下次断线值得再报一次
                    first_frame = True
                    while not self._watch_stop_event.is_set():
                        frame = self._read_track_frame(sock)
                        if frame is None:
                            continue  # 只是超时醒来看一眼停止标志
                        snapshot = self._parse_track_payload(frame)
                        if first_frame:
                            # 连上时 server 会立即推一帧当前状态。整个生命周期的
                            # 第一帧跟启动时的初始刷新重复，只用来建基线；重连后的
                            # 首帧则要比对，因为断线期间可能真的插拔过。
                            notify = got_frame and snapshot != last
                            first_frame = False
                            got_frame = True
                        else:
                            notify = snapshot != last
                        last = snapshot
                        if notify:
                            try:
                                on_change()
                            except Exception:
                                pass  # 回调自己的问题不能连累监听线程
            except Exception as e:
                if self._watch_stop_event.is_set():
                    return
                # 每轮连接周期只报一次（warned 在连上后重置），否则 adb 缺失/长期
                # 连不上时会把日志刷爆
                if not warned:
                    if got_frame:
                        # 曾经工作过 → 这是断线（kill-server、休眠唤醒等），会自愈
                        self.log(f"设备插拔监听连接中断，正在自动重连: {e}", "INFO")
                    else:
                        self.log(f"设备插拔监听未能启动，将退化为手动刷新: {e}", "WARNING")
                    warned = True
            finally:
                self._watch_sock = None
            # 退避重连。用 Event.wait 而非 sleep，stop 时能立刻打断
            if self._watch_stop_event.wait(timeout=delay):
                return
            delay = min(delay * 2, self.WATCH_RETRY_MAX)

    def execute_adb_command(self, cmd_list, check_dev=True, timeout=None):
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

        effective_timeout = timeout if timeout is not None else self.SHELL_TIMEOUT

        # 防止本次带管道的调用去冷启动 adb server（Windows 上会死锁，见 _ensure_adb_server）
        self._ensure_adb_server()

        try:
            # 执行命令
            result = subprocess.run(
                cmd_list,
                **self._get_subprocess_kwargs(timeout=effective_timeout)
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

        except subprocess.TimeoutExpired:
            self.log(f"命令超时 ({effective_timeout}s)，设备可能休眠/未授权或 USB 异常。", "ERROR")
            # 超时可能是 server 挂了，下次调用前重新确认 server 状态
            self._adb_server_ready = False
            return False, "命令执行超时"
        except FileNotFoundError:
            self.log("错误: 未找到 adb 命令，请检查环境变量。", "ERROR")
            return False, "未找到 adb 命令"
        except Exception as e:
            self.log(f"发生异常: {str(e)}", "ERROR")
            return False, str(e)

    # --- Specific ADB Actions ---

    def get_connected_devices(self):
        """获取所有已连接的设备列表"""
        # force=True：刷新是用户的"救急"入口，即使 server 中途被杀也要先拉起来，
        # 否则下面带管道的 adb devices 会在 Windows 上冷启动 server 并永久卡死线程
        self._ensure_adb_server(force=True)
        try:
            result = subprocess.run(
                [self.adb_cmd, "devices"],
                **self._get_subprocess_kwargs(timeout=self.DEVICES_TIMEOUT)
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
        except subprocess.TimeoutExpired:
            self.log(f"获取设备列表超时 ({self.DEVICES_TIMEOUT}s)，请检查 adb / USB 连接。", "ERROR")
            return []
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

    def get_device_info(self):
        """查询设备型号、系统版本和 API 级别"""
        self.check_device()

        props = {
            "model": "ro.product.model",
            "release": "ro.build.version.release",
            "sdk": "ro.build.version.sdk",
        }
        results = {}
        for key, prop in props.items():
            success, output = self.execute_adb_command(["adb", "shell", "getprop", prop])
            results[key] = output.strip() if success and output else "未知"

        return f"设备型号: {results['model']}, 系统版本: Android {results['release']} (API {results['sdk']})"

    def _get_orientation_key(self):
        """获取一个稳定反映"当前 Configuration"的字符串，用作 screen_info 缓存键。

        踩坑历史（按时间）：
        1. `settings get user_rotation` —— 只反映用户偏好，auto-rotate 物理转屏不变
        2. `dumpsys window | grep -m1 mRotation` —— dumpsys 里 mRotation 多份，grep -m1 容易拿错
        3. `dumpsys window | grep -m1 sw...dp w...dp h...dp` —— 第一个 Configuration 不一定是
           当前全局的（可能是某个 task/window 的快照），切回竖屏还命中横屏数据

        现在用 `am get-config` —— Android 标准命令，输出当前 Configuration 串，
        转屏后立即更新，输出 < 200 字节、~50ms。串里 "w###dp-h###dp" 直接拿来作 key。
        """
        out = self._shell_silent(["shell", "am", "get-config"])
        if out:
            # 形如 "config: zh-rCN-ldltr-sw533dp-w889dp-h533dp-...-land-..."
            m = re.search(r"w(\d+)dp-h(\d+)dp", out)
            if m:
                return f"w{m.group(1)}h{m.group(2)}"
        return None

    def _shell_silent(self, args):
        """直接执行 adb -s <id> <args>，不打印结果到 log。
        专用于 dumpsys 这类大输出查询，避免污染全局日志面板。
        """
        if not self.current_device_id:
            return ""
        cmd = [self.adb_cmd, "-s", self.current_device_id] + list(args)
        self._ensure_adb_server()
        try:
            result = subprocess.run(cmd, **self._get_subprocess_kwargs(timeout=self.SHELL_TIMEOUT))
            return (result.stdout or "").strip()
        except subprocess.TimeoutExpired:
            self.log(f"静默 ADB 查询超时 ({self.SHELL_TIMEOUT}s)。", "ERROR")
            return ""
        except Exception as e:
            self.log(f"静默 ADB 查询失败: {e}", "ERROR")
            return ""

    def get_screen_info(self, force_refresh=False):
        """查询设备屏幕信息（型号/分辨率/密度/状态栏/导航栏/刘海/Configuration 等），返回 dict。

        说明：
        - wm size / wm density 取真实分辨率与 DPI；存在 Override 时优先取 Override。
        - dumpsys window 解析 stable insets（顶部=状态栏，底部=导航/手势条，左右=侧边手势区）。
        - DisplayCutout 解析刘海/挖孔的 safeInsets，全 0 视为无。
        - sw###dp w###dp h###dp 解析当前 Configuration 的逻辑宽高。
        - dp = px * 160 / density（四舍五入）。

        缓存：按 (device_id, Configuration_w_h) 双键缓存到 appdata 下的 screen_info_cache.json。
        Configuration 串转屏会立即更新，所以横竖屏切换会自动命中不同缓存槽，不会回放陈旧数据。
        force_refresh=True 强制旁路缓存。
        """
        self.check_device()

        from core import screen_info_cache

        # 拿一个反映"当前方向+分辨率+密度"的稳定字符串作缓存键，转屏后会立即变化
        cache_key = self._get_orientation_key()

        if not force_refresh and cache_key is not None:
            cached = screen_info_cache.get(self.current_device_id, cache_key)
            if cached:
                return cached

        info = {
            "model": "未知",
            "android": "?",
            "api": "?",
            "px_w": 0,
            "px_h": 0,
            "dp_w": 0,
            "dp_h": 0,
            "density": 160,
            "orientation": "未知",
            "status_bar": "未知",
            "cutout": "无",
            "nav_bar": "未知",
            "side_gesture": "无",
            "avail_w": "未知",
            "avail_h": "未知",
            "config_w": "未知",
            "config_h": "未知",
        }

        # ===== 设备信息 =====
        manuf = self._shell_silent(["shell", "getprop", "ro.product.manufacturer"]).strip()
        model = self._shell_silent(["shell", "getprop", "ro.product.model"]).strip()
        if manuf and model:
            # 避免重复，比如 model 已经带 "samsung"
            if manuf.lower() in model.lower():
                info["model"] = model
            else:
                info["model"] = f"{manuf} {model}"
        else:
            info["model"] = model or manuf or "未知"

        info["android"] = self._shell_silent(["shell", "getprop", "ro.build.version.release"]).strip() or "?"
        info["api"] = self._shell_silent(["shell", "getprop", "ro.build.version.sdk"]).strip() or "?"

        # ===== 屏幕尺寸 =====
        size_out = self._shell_silent(["shell", "wm", "size"])
        m_over = re.search(r"Override size:\s*(\d+)x(\d+)", size_out)
        m_phys = re.search(r"Physical size:\s*(\d+)x(\d+)", size_out)
        if m_over:
            info["px_w"], info["px_h"] = int(m_over.group(1)), int(m_over.group(2))
        elif m_phys:
            info["px_w"], info["px_h"] = int(m_phys.group(1)), int(m_phys.group(2))

        dens_out = self._shell_silent(["shell", "wm", "density"])
        m_od = re.search(r"Override density:\s*(\d+)", dens_out)
        m_pd = re.search(r"Physical density:\s*(\d+)", dens_out)
        if m_od:
            info["density"] = int(m_od.group(1))
        elif m_pd:
            info["density"] = int(m_pd.group(1))

        scale = 160.0 / info["density"] if info["density"] else 1.0
        if info["px_w"]:
            info["dp_w"] = round(info["px_w"] * scale)
        if info["px_h"]:
            info["dp_h"] = round(info["px_h"] * scale)

        # 方向先按 wm size 的宽高比兜底；下面 Configuration w/h 解析后会覆盖为权威值
        if info["px_w"] and info["px_h"]:
            info["orientation"] = "竖屏" if info["px_h"] >= info["px_w"] else "横屏"

        # ===== dumpsys window 解析 insets / cutout / configuration =====
        dw = self._shell_silent(["shell", "dumpsys", "window"])

        # --- 系统占用：先尝试 Android 11+ 的 InsetsSource 格式 ---
        # Android 11:   InsetsSource type=ITYPE_STATUS_BAR frame=[0,0][1200,54]
        # Android 12+:  InsetsSource id=acc40000 type=statusBars frame=[0,0][1080,136] visible=false ...
        # 两个 fmt 差异：type= 从 ITYPE_XXX 常量改 camelCase；中间多 id=<hex>；后面多 visible=...
        # frame=[L,T][R,B] 即该 inset 条带在屏幕上的矩形位置：
        #   状态栏（顶部条）高度 = B - T
        #   导航栏（底部条）高度 = B - T
        #   左/右手势区（侧边条）宽度 = R - L
        # 注意 Android 12+ 不再单独输出 ITYPE_LEFT/RIGHT_GESTURES，统一进 systemGestures，
        # 而且左右手势区域改用 boundingRects 描述。这里左右手势检测仅保留旧格式兼容。
        def _frame_of(*type_names):
            alt = "|".join(re.escape(n) for n in type_names)
            # 同时抓 frame 和后面跟着的 visible=true/false。visible 段不强制存在，
            # Android 11 的早期 InsetsSource 没这个字段，匹配不到时默认按 visible 处理。
            m = re.search(
                rf"InsetsSource(?:\s+id=\S+)?\s+type=(?:{alt})\s+frame=\[(\d+),(\d+)\]\[(\d+),(\d+)\]"
                rf"(?:\s+visible=(true|false))?",
                dw,
            )
            if not m:
                return None
            fl, ft, fr, fb = map(int, m.groups()[:4])
            vis = m.group(5)
            visible = (vis != "false")  # None 或 "true" 都按可见处理（旧 fmt 没这字段）
            w, h = fr - fl, fb - ft
            # thickness = 较短边。状态栏永远是细横条 (w >> h)，导航栏在竖屏是横条
            # (w >> h)、横屏旋转到屏幕侧边变成细竖条 (h >> w)，侧边手势始终是细竖条
            # (h >> w)。取较短边天然处理这两种情况。
            # 但 InsetsSource 也会用"退化 frame"（w=0 或 h=0 的"线"）表示该条带不存在，
            # 例: TYPE_LEFT_GESTURES frame=[0,0][0,2220] 表示"无左手势区"。
            # 任一维 = 0 视为不存在，thickness=0。
            # 此外 visible=false 表示该条带当前没占屏（如小米手势导航无指示条），
            # 直接当 0；想看"潜在尺寸"再说，目前只反映"当前实际占用"。
            if not visible or w <= 0 or h <= 0:
                thickness = 0
            else:
                thickness = min(w, h)
            return {"l": fl, "t": ft, "r": fr, "b": fb,
                    "w": w, "h": h, "visible": visible, "thickness": thickness}

        sb = _frame_of("ITYPE_STATUS_BAR", "statusBars")
        nb = _frame_of("ITYPE_NAVIGATION_BAR", "navigationBars")
        lg = _frame_of("ITYPE_LEFT_GESTURES")
        rg = _frame_of("ITYPE_RIGHT_GESTURES")

        if sb is not None:
            th = round(sb['thickness'] * scale)
            info["status_bar"] = f"{th} dp" if th > 0 else "无"
        if nb is not None:
            th = round(nb['thickness'] * scale)
            info["nav_bar"] = f"{th} dp" if th > 0 else "无"
        if lg is not None or rg is not None:
            lw = lg["thickness"] if lg else 0
            rw = rg["thickness"] if rg else 0
            if lw > 0 or rw > 0:
                info["side_gesture"] = f"L {round(lw*scale)} dp / R {round(rw*scale)} dp"
            else:
                info["side_gesture"] = "无"

        # --- 回退 1：Android 10 三星等 ROM，InsetsSource 用 TYPE_TOP_BAR / TYPE_SIDE_BAR_1
        # 这种厂商私有常量名，硬列别名穷不完。直接从 BarController 段读 mContentFrame，
        # 这俩字段在 Android 7-10 跨厂商都比较稳定。
        # 例:
        #   BarController.StatusBar
        #       mContentFrame=Rect(0, 0 - 1080, 63)        ← (L, T - R, B) 注意 ' - ' 分隔
        #   BarController.NavigationBar
        #       mContentFrame=Rect(0, 2094 - 1080, 2220)
        def _bar_thickness(section_name):
            """从 BarController.<section> 的 mContentFrame 提取较短边作为厚度（dp）。"""
            m = re.search(
                rf"BarController\.{section_name}.*?mContentFrame=Rect\((\d+),\s*(\d+)\s*-\s*(\d+),\s*(\d+)\)",
                dw, re.DOTALL,
            )
            if not m:
                return None
            l, t, r, b = map(int, m.groups())
            w, h = r - l, b - t
            # 任一维 = 0 视为不存在（同 _frame_of 注释）
            return min(w, h) if w > 0 and h > 0 else 0

        if info["status_bar"] == "未知":
            th = _bar_thickness("StatusBar")
            if th is not None:
                info["status_bar"] = f"{round(th * scale)} dp"
        if info["nav_bar"] == "未知":
            th = _bar_thickness("NavigationBar")
            if th is not None:
                info["nav_bar"] = f"{round(th * scale)} dp"

        # --- 回退 2：更老的版本，从 stableInsets 整段拿 ---
        if info["status_bar"] == "未知" and info["nav_bar"] == "未知":
            l = t = r = b = None
            m_in1 = re.search(
                r"mStableInsets=Insets\{left=(\d+),\s*top=(\d+),\s*right=(\d+),\s*bottom=(\d+)\}",
                dw,
            )
            m_in2 = re.search(r"stableInsets=\[(\d+),(\d+)\]\[(\d+),(\d+)\]", dw)
            if m_in1:
                l, t, r, b = map(int, m_in1.groups())
            elif m_in2:
                l, t, r, b = map(int, m_in2.groups())

            if l is not None:
                info["status_bar"] = f"{round(t * scale)} dp"
                info["nav_bar"] = f"{round(b * scale)} dp"
                if l > 0 or r > 0:
                    info["side_gesture"] = f"L {round(l*scale)} dp / R {round(r*scale)} dp"
                else:
                    info["side_gesture"] = "无"

        # --- 回退 3：Android 7-9 三星等 ROM，BarController 只有 mState 没 mContentFrame，
        # 也没有 mStableInsets 字段；但 PhoneWindowManager dump 一直输出 mUnrestrictedScreen
        # 和 mStable，两者差值就是各方向 inset：
        #   状态栏 px = mStable.top  - mUnrestrictedScreen.top
        #   导航栏 px = mUnrestrictedScreen.bottom - mStable.bottom
        #   左侧 px = mStable.left - mUnrestrictedScreen.left
        #   右侧 px = mUnrestrictedScreen.right - mStable.right
        # 例(Note5/Android 7)：mUnrestrictedScreen=(0,0) 1440x2560 + mStable=(0,84)-(1440,2560)
        #   → 状态栏 84px ≈ 24 dp@560dpi，底部 0（物理 Home 键），左右 0。
        # 注意：用 \b 防止匹配到 Samsung 私有的 OriginalmUnrestrictedScreen / mOriginalStable。
        if info["status_bar"] == "未知" or info["nav_bar"] == "未知":
            m_un = re.search(r"\bmUnrestrictedScreen=\((\d+),(\d+)\)\s+(\d+)x(\d+)", dw)
            m_st = re.search(r"\bmStable=\((\d+),(\d+)\)-\((\d+),(\d+)\)", dw)
            if m_un and m_st:
                ul, ut, uw, uh = map(int, m_un.groups())
                ur_, ub_ = ul + uw, ut + uh
                sl, st_, sr_, sb_ = map(int, m_st.groups())
                top_px = max(0, st_ - ut)
                bot_px = max(0, ub_ - sb_)
                left_px = max(0, sl - ul)
                right_px = max(0, ur_ - sr_)
                if info["status_bar"] == "未知":
                    info["status_bar"] = f"{round(top_px * scale)} dp" if top_px > 0 else "无"
                if info["nav_bar"] == "未知":
                    info["nav_bar"] = f"{round(bot_px * scale)} dp" if bot_px > 0 else "无"
                if left_px > 0 or right_px > 0:
                    info["side_gesture"] = f"L {round(left_px*scale)} dp / R {round(right_px*scale)} dp"

        # --- Cutout：DisplayCutout{... insets=Rect(L, T - R, B) ... 或 safeInsets=...} ---
        m_cut = re.search(r"DisplayCutout\{([^}]*)\}", dw)
        if m_cut:
            body = m_cut.group(1)
            m_safe = re.search(
                r"(?:safeInsets|insets)=Rect\((\d+),\s*(\d+)\s*-\s*(\d+),\s*(\d+)\)",
                body,
            )
            if m_safe:
                cl, ct, cr, cb = map(int, m_safe.groups())
                if cl == 0 and ct == 0 and cr == 0 and cb == 0:
                    info["cutout"] = "无"
                else:
                    parts = []
                    if ct > 0:
                        parts.append(f"上 {round(ct*scale)} dp")
                    if cb > 0:
                        parts.append(f"下 {round(cb*scale)} dp")
                    if cl > 0:
                        parts.append(f"左 {round(cl*scale)} dp")
                    if cr > 0:
                        parts.append(f"右 {round(cr*scale)} dp")
                    info["cutout"] = " / ".join(parts) if parts else "无"

        # Configuration 宽高（取 dp）
        m_conf = re.search(r"sw\d+dp\s+w(\d+)dp\s+h(\d+)dp", dw)
        if m_conf:
            cw_dp = int(m_conf.group(1))
            ch_dp = int(m_conf.group(2))
            info["config_w"] = f"{cw_dp} dp"
            info["config_h"] = f"{ch_dp} dp"
            # Configuration w/h 是 Android 报给 App 的当前方向尺寸（横屏 w>h），
            # 比 _get_actual_rotation 更权威，作为方向判定的最终兜底
            info["orientation"] = "横屏" if cw_dp > ch_dp else "竖屏"

        # wm size 返回的是自然方向 px，横屏时需要把宽高互换成当前方向显示。
        # 判定依据：方向已是"横屏"但 dp_h > dp_w（说明 wm size 还是竖屏数）。
        # 插值 insets 已经是当前方向的，无需调整。
        if (info["orientation"] == "横屏"
                and info["dp_w"] and info["dp_h"]
                and info["dp_h"] > info["dp_w"]):
            info["dp_w"], info["dp_h"] = info["dp_h"], info["dp_w"]
            info["px_w"], info["px_h"] = info["px_h"], info["px_w"]

        # 可用区域 = 当前方向 dp - 状态栏 - 导航栏（侧边手势区是虚拟检测区，不占可视宽度）
        try:
            sb_dp = int(info["status_bar"].split()[0]) if info["status_bar"].endswith("dp") else 0
            nb_dp = int(info["nav_bar"].split()[0]) if info["nav_bar"].endswith("dp") else 0
            if info["dp_w"]:
                info["avail_w"] = f"{info['dp_w']} dp"
            if info["dp_h"]:
                info["avail_h"] = f"{info['dp_h'] - sb_dp - nb_dp} dp"
        except (ValueError, AttributeError):
            pass

        # 写入缓存（按设备 + Configuration 串）。key 取不到时不写，避免污染
        if cache_key is not None:
            screen_info_cache.put(self.current_device_id, cache_key, info)

        return info

    def force_stop_app(self, package_name):
        """强制停止应用"""
        self.check_device()
        return self.execute_adb_command(["adb", "shell", "am", "force-stop", package_name])

    def kill_process(self, package_name):
        """杀死应用进程"""
        self.check_device()
        return self.execute_adb_command(["adb", "shell", "am", "kill", package_name])

    def open_date_settings(self):
        """唤起系统时间与日期设置"""
        self.check_device()
        return self.execute_adb_command(["adb", "shell", "am", "start", "-a", "android.settings.DATE_SETTINGS"])

    def open_language_settings(self):
        """唤起系统语言设置"""
        self.check_device()
        return self.execute_adb_command(["adb", "shell", "am", "start", "-a", "android.settings.LOCALE_SETTINGS"])

    ADB_KB_PKG = "com.android.adbkeyboard"
    ADB_KB_IME = f"{ADB_KB_PKG}/.AdbIME"

    def _install_adb_keyboard(self):
        """确保 ADB Keyboard 已安装，返回是否安装成功"""
        _, output = self.execute_adb_command(["adb", "shell", "pm", "list", "packages", self.ADB_KB_PKG])
        if self.ADB_KB_PKG in (output or ""):
            return True

        apk_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "ADBKeyboard.apk")
        if not os.path.exists(apk_path):
            self.log("ADB Keyboard APK 文件不存在，无法自动安装", "ERROR")
            return False
        self.log("首次发送文本，正在自动安装 ADB Keyboard...", "INFO")
        success, msg = self.execute_adb_command(["adb", "install", apk_path], timeout=self.INSTALL_TIMEOUT)
        if not success:
            self.log(f"ADB Keyboard 安装失败: {msg}", "ERROR")
            return False
        self.log("ADB Keyboard 安装成功", "SUCCESS")
        return True

    def _is_adb_keyboard_active(self):
        """检查当前输入法是否为 ADB Keyboard"""
        _, current_ime = self.execute_adb_command(["adb", "shell", "settings", "get", "secure", "default_input_method"])
        return self.ADB_KB_IME in (current_ime or "").strip()

    def _try_switch_to_adb_keyboard(self):
        """尝试自动切换到 ADB Keyboard，返回是否成功"""
        success, _ = self.execute_adb_command(["adb", "shell", "ime", "set", self.ADB_KB_IME])
        if success:
            return True
        success, _ = self.execute_adb_command(["adb", "shell", "settings", "put", "secure", "default_input_method", self.ADB_KB_IME])
        return success

    def send_text(self, text):
        """通过 ADB Keyboard 广播发送文本，支持所有语言"""
        if not text:
            return False, "Empty text"

        # 1. 确保已安装
        if not self._install_adb_keyboard():
            text_escaped = text.replace(" ", "%s")
            return self.execute_adb_command(["adb", "shell", "input", "text", text_escaped])

        # 2. 如果不是当前输入法，尝试自动切换（只试一次，不阻塞）
        if not self._is_adb_keyboard_active():
            if not self._try_switch_to_adb_keyboard():
                # 自动切换失败，引导用户手动操作
                self.log(
                    "当前设备权限受限，无法自动切换输入法。\n"
                    "请在设备上手动操作：启用 ADB Keyboard，然后在 设置 - 其他设置 - 键盘与输入法 - 默认输入法 中切换为 ADB Keyboard",
                    "WARNING"
                )
                self.execute_adb_command(["adb", "shell", "am", "start", "-a", "android.settings.INPUT_METHOD_SETTINGS"])
                return False, "需要手动切换到 ADB Keyboard"

        # 3. 通过广播发送文本
        safe_text = text.replace("'", "'\\''")
        return self.execute_adb_command([
            "adb", "shell",
            f"am broadcast -a ADB_INPUT_TEXT --es msg '{safe_text}'"
        ])

    def send_raw_text(self, text):
        """通过 adb shell input text 模拟按键输入（仅支持 ASCII）"""
        if not text:
            return False, "Empty text"
        safe_text = text.replace("'", "'\\''")
        return self.execute_adb_command(["adb", "shell", "input", "text", f"'{safe_text}'"])

    def get_focused_input_text(self):
        """通过 uiautomator dump 读取当前界面输入框(EditText)的文本内容。

        优先取 focused=true 的 EditText；没有聚焦项时取第一个有文本内容的 EditText。
        用 _shell_silent 而非 execute_adb_command，避免几十 KB 的界面 XML 刷屏日志面板。
        """
        self.check_device()
        remote_path = "/data/local/tmp/adb_tool_uidump.xml"
        output = self._shell_silent([
            "shell",
            f"uiautomator dump {remote_path} >/dev/null 2>&1 && cat {remote_path}"
        ])
        if not output or "<?xml" not in output:
            return False, "获取界面信息失败，请确认设备屏幕已点亮并停留在可操作界面"

        try:
            root = ET.fromstring(output)
        except ET.ParseError:
            return False, "解析界面信息失败"

        edit_nodes = [n for n in root.iter("node") if "EditText" in n.get("class", "")]
        if not edit_nodes:
            return False, "当前界面未找到输入框"

        focused = next((n for n in edit_nodes if n.get("focused") == "true"), None)
        target = focused or next((n for n in edit_nodes if n.get("text")), edit_nodes[0])
        return True, target.get("text", "")

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

    def sim_incoming_call(self):
        self.execute_adb_command([
            "adb", "shell",
            "am", "broadcast",
            "-a", "android.intent.action.TEST",
            "--es", "state", "RINGING",
        ])

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
        self.run_adb_async(["adb", "install", "-r", apk_path], on_complete, timeout=self.INSTALL_TIMEOUT)

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

            # 推送前打一条 "开始推送" 日志，让用户在 adb push 沉默期间知道任务在跑
            display_name = os.path.basename(os.path.normpath(local_path)) or local_path
            if os.path.isdir(local_path):
                try:
                    file_count = sum(len(files) for _, _, files in os.walk(local_path))
                except OSError:
                    file_count = 0
                self.log(f"开始推送 {display_name} ({file_count} 个文件)...", "INFO")
            else:
                self.log(f"开始推送 {display_name}...", "INFO")

            # 兼容路径带空格的情况，虽然 execute_adb_command 内部用列表传参通常不需要加引号
            # 但为防万一，确保传入的是纯净路径
            cmd = ["adb", "push", push_local_path, push_remote_path]
            attempt = 0
            while True:
                success, msg = self.execute_adb_command(cmd, timeout=self.PUSH_TIMEOUT)
                if success or attempt >= self.PUSH_RETRIES or not self._is_retryable_push_error(msg):
                    break
                attempt += 1
                self.log(f"推送 {display_name} 时连接中断，等待设备恢复后重试 ({attempt}/{self.PUSH_RETRIES})...", "WARNING")
                self._wait_for_device_reconnect()
            if success:
                self.log(f"推送完成: {display_name}", "SUCCESS")
                success_count += 1
                # push 成功后:
                # 1) touch 把 mtime 改为设备当前时间——adb push 默认保留源文件 mtime,
                #    源文件常是几年前的，文件管理器按日期排序时新推的文件会沉底，看着像"没传上"
                # 2) 触发媒体扫描，让文件立即在相册/媒体库中可见
                #
                # 扫描统一用 am broadcast MEDIA_SCANNER_SCAN_FILE，全 API 版本一条路。
                # 这条 intent 自 Android Q 起官方标记 deprecated，但实测它才是跨版本最可靠的：
                # - 三星 Android 10 (One UI 2)：content call scan_file 被 MediaProvider 当
                #   no-op 静默吞掉（Note9 实测：20 文件全程零 stdout、文件在设备上但不入 MediaStore），
                #   broadcast 才真正触发扫描。
                # - Pixel / Android 13：content call scan_file 必抛 NPE
                #   (Uri.getPath() on null)，broadcast 正常且实测能把文件真正写进 MediaStore.Audio。
                # - Android 7-9：MediaProvider 压根没实现 scan_file 这个 call() 方法，只能 broadcast。
                # 从 shell 发 broadcast 不受 app 内 file:// StrictMode 限制（那是
                # FileUriExposedException，只管进程内），所以 file:// URI 在 shell 端始终可用。
                #
                # scan_file 仅对单个文件生效；推送文件夹时用 find -exec 逐个文件触发。
                # find -exec 用 sh -c 包一层，把路径以 $0 传给 inner shell——直接 substring
                # 替换 file://<path> 在不同 toybox/busybox 的 find 实现上不稳，交回 shell 引号最保险。
                scan_path = push_remote_path.replace("/sdcard/", "/storage/emulated/0/", 1)
                safe_path = scan_path.replace("'", "'\\''")
                if os.path.isdir(local_path):
                    per_file = "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d \"file://$0\""
                    shell_cmd = (
                        f"find '{safe_path}' -exec touch {{}} \\; ; "
                        f"find '{safe_path}' -type f -exec sh -c '{per_file}' {{}} \\;"
                    )
                else:
                    scan_one = f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d 'file://{safe_path}'"
                    shell_cmd = f"touch '{safe_path}' ; {scan_one}"
                self.log(f"通知媒体库扫描: {display_name}...", "INFO")
                scan_timeout = self.PUSH_TIMEOUT if os.path.isdir(local_path) else None
                scan_ok, _ = self.execute_adb_command(["adb", "shell", shell_cmd], timeout=scan_timeout)
                if scan_ok:
                    self.log(f"媒体库通知完成: {display_name}", "SUCCESS")
                else:
                    self.log(f"媒体库通知失败: {display_name}（文件已推送，仅扫描未成功）", "ERROR")
            else:
                errors.append(f"Push failed for {os.path.basename(local_path)}: {msg}")

        if success_count == total_count:
            return True, f"Successfully pushed {success_count} items."
        else:
            return False, f"Pushed {success_count}/{total_count} items. Errors: {'; '.join(errors)}"

    def launch_app(self, package_name):
        """通过 monkey 命令启动 App (不需要知道 Activity)

        部分 app（如带 WRITE_SETTINGS 权限的铃声/视频类）会在启动时偷改
        系统的 ACCELEROMETER_ROTATION 开关。这里在启动前快照、启动后 2s
        异步还原，避免污染设备状态。

        刚装完 APK 立即启动时，PackageManager 的 LAUNCHER intent 索引
        可能还没建好，monkey 会以 Code 252 abort。这里失败时短暂等待
        后重试一次，覆盖安装→自动启动的竞态。
        """
        if not package_name:
            return False, "Package name is empty"

        device_id = self.current_device_id
        rotation_before = self._read_accelerometer_rotation(device_id) if device_id else None

        cmd = ["adb", "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"]
        result = self.execute_adb_command(cmd)
        if not result[0]:
            time.sleep(0.8)
            self.log(f"启动失败，重试中: {package_name}", "INFO")
            result = self.execute_adb_command(cmd)

        if rotation_before is not None:
            threading.Thread(
                target=self._restore_accelerometer_rotation,
                args=(device_id, rotation_before, package_name),
                daemon=True,
            ).start()

        return result

    def _read_accelerometer_rotation(self, device_id):
        """读取指定设备的系统自动旋转开关，失败返回 None。绕过 execute_adb_command 以避免日志噪音和设备切换副作用。"""
        try:
            result = subprocess.run(
                [self.adb_cmd, "-s", device_id, "shell", "settings", "get", "system", "accelerometer_rotation"],
                **self._get_subprocess_kwargs()
            )
            if result.returncode != 0:
                return None
            val = (result.stdout or "").strip()
            return val if val in ("0", "1") else None
        except Exception:
            return None

    def _restore_accelerometer_rotation(self, device_id, expected, package_name):
        """启动 2s 后检查并还原 accelerometer_rotation。设备已切换则跳过。"""
        time.sleep(2)
        if self.current_device_id != device_id:
            return
        current = self._read_accelerometer_rotation(device_id)
        if current is None or current == expected:
            return
        try:
            subprocess.run(
                [self.adb_cmd, "-s", device_id, "shell", "settings", "put", "system", "accelerometer_rotation", expected],
                **self._get_subprocess_kwargs()
            )
            self.log(f"已还原系统自动旋转开关 {current} → {expected}（被 {package_name} 启动时修改）", "INFO")
        except Exception as e:
            self.log(f"还原自动旋转开关失败: {e}", "ERROR")

    def stop_app(self, package_name):
        """强制停止 App"""
        if not package_name:
            return False, "Package name is empty"
        return self.execute_adb_command(["adb", "shell", "am", "force-stop", package_name])

    def install_apk_sync(self, apk_path):
        """同步安装 APK 并返回结果，供拖拽安装使用"""
        return self.execute_adb_command(["adb", "install", "-r", apk_path], timeout=self.INSTALL_TIMEOUT)

    def clear_google_play_data(self):
        """清除 Google Play 商店数据"""
        return self.execute_adb_command(["adb", "shell", "pm", "clear", "com.android.vending"])

    def enable_gesture_nav(self):
        """切换为全面屏手势导航"""
        return self.execute_adb_command(["adb", "shell", "cmd", "overlay", "enable", "com.android.internal.systemui.navbar.gestural"])

    def enable_threebutton_nav(self):
        """切换为三键导航"""
        return self.execute_adb_command(["adb", "shell", "cmd", "overlay", "enable", "com.android.internal.systemui.navbar.threebutton"])

    # --- File Manager Logic ---

    def list_device_files(self, remote_path: str):
        """获取设备文件列表"""
        self.check_device()
        cmd = ["adb", "shell", "ls", "-lA", _device_sh_quote(remote_path)]
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

    def delete_device_file(self, remote_path: str, is_dir: bool = False):
        """删除设备文件或文件夹，并通知媒体库清除残留记录。

        why：`rm` 删文件后 MediaStore 仍残留指向已删文件的行，相册/音乐 App 里
        会出现点不开的"幽灵条目"。对一个**已不存在**的路径发
        MEDIA_SCANNER_SCAN_FILE 广播，MediaScanner 会发现文件没了并删掉对应行——
        同一个广播既能入库（push）也能清库（delete）。

        要扫描的路径怎么来：
        - 单个文件：调用方传进来的 remote_path 就是它本身，直接用，无需多查。
        - 文件夹：MediaStore 一行对应一个**文件**（按各文件全路径 _data 记录），
          广播文件夹路径没用。必须拿到内部每个文件的路径，而 rm 之后就枚举不到了，
          所以仅文件夹场景需要"删除前先 find 收集清单"。
        """
        self.check_device()
        quoted = _device_sh_quote(remote_path)

        # 1. 收集要通知媒体库的文件路径（删除前，因为文件夹删后无法枚举内部文件）。
        files_to_scan = []
        if is_dir:
            try:
                ok, out = self.execute_adb_command(["adb", "shell", "find", quoted, "-type", "f"])
                if ok and out:
                    files_to_scan = [ln.strip() for ln in out.splitlines() if ln.strip()]
            except Exception:
                pass  # 收集失败不影响删除主流程（顶多残留幽灵条目）
        else:
            files_to_scan = [remote_path]

        # 2. 删除
        success, msg = self.execute_adb_command(["adb", "shell", "rm", "-rf", quoted])
        if not success:
            return success, msg

        # 3. 通知媒体库清理已删文件的残留行。
        #    - 转成 /storage/emulated/0/ 形式与 MediaStore 的 _data 列对齐（与 push 一致）。
        #    - 路径由 Python 逐个单引号化，天然处理空格/特殊字符。
        #    - 分批拼接，避免文件夹文件过多时单条 shell 命令超出 ARG_MAX。
        if files_to_scan:
            self.log(f"通知媒体库清理已删除文件（{len(files_to_scan)} 个）...", "INFO")
            scan_all_ok = True
            BATCH = 100
            for i in range(0, len(files_to_scan), BATCH):
                cmds = []
                for p in files_to_scan[i:i + BATCH]:
                    sp = p.replace("/sdcard/", "/storage/emulated/0/", 1)
                    safe = sp.replace("'", "'\\''")
                    cmds.append(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d 'file://{safe}'")
                batch_ok, _ = self.execute_adb_command(["adb", "shell", " ; ".join(cmds)])
                scan_all_ok = scan_all_ok and batch_ok
            if scan_all_ok:
                self.log("媒体库清理通知完成", "SUCCESS")
            else:
                self.log("媒体库清理通知部分失败（文件已删除，仅扫描未完全成功）", "ERROR")

        return success, msg

    # --- Wireless Debugging Logic ---

    WIRELESS_DEFAULT_PORT = 5555

    @staticmethod
    def is_wireless_device_id(device_id):
        """device_id 是否是无线连接（adb 的无线设备 id 就是 "ip:port"）。"""
        return bool(re.fullmatch(r'\d+\.\d+\.\d+\.\d+:\d+', (device_id or "").strip()))

    @classmethod
    def normalize_wireless_addr(cls, addr):
        """把用户输入的 "ip" 或 "ip:port" 规整成 "ip:port"，非法则返回 None。"""
        addr = (addr or "").strip()
        m = re.fullmatch(r'(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?', addr)
        if not m:
            return None
        ip, port = m.group(1), m.group(2)
        if any(int(seg) > 255 for seg in ip.split(".")):
            return None
        port = int(port) if port else cls.WIRELESS_DEFAULT_PORT
        if not (1 <= port <= 65535):
            return None
        return f"{ip}:{port}"

    # 取 ro.serialno 只是为了把无线条目认回 USB 序列号（别名/去重），
    # 拿不到就退化成显示 ip:port，不值得为它卡住整个设备列表刷新
    SERIALNO_TIMEOUT = 5

    def get_devices_detailed(self, with_serialno=False):
        """返回 [{"id","transport","state","serialno"}]。

        transport 为 "wifi" / "usb"。with_serialno=True 时给每条 entry 补上
        ro.serialno —— 同一台机器 USB 与 WiFi 两条 entry 的 serialno 相同，
        用来把"这台无线设备就是那台 USB 设备"认出来（别名共享、去重都靠它）。
        只有无线条目需要实际执行 getprop（USB 条目的 device_id 本身就是序列号），
        所以额外的 adb 调用数 = 无线设备台数，不是总设备数。
        """
        self._ensure_adb_server(force=True)
        result = []
        try:
            proc = subprocess.run(
                [self.adb_cmd, "devices"],
                **self._get_subprocess_kwargs(timeout=self.DEVICES_TIMEOUT)
            )
            if proc.returncode != 0:
                return []
            for line in proc.stdout.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) < 2:
                    continue
                dev_id, state = parts[0], parts[1]
                result.append({
                    "id": dev_id,
                    "state": state,
                    "transport": "wifi" if self.is_wireless_device_id(dev_id) else "usb",
                    "serialno": "",
                })
        except subprocess.TimeoutExpired:
            self.log(f"获取设备列表超时 ({self.DEVICES_TIMEOUT}s)，请检查 adb / USB 连接。", "ERROR")
            return []
        except Exception as e:
            self.log(f"获取设备列表失败: {e}", "ERROR")
            return []

        if with_serialno:
            pending = []
            for item in result:
                if item["transport"] == "usb":
                    # USB 的 device_id 本身就是序列号，不用问设备
                    item["serialno"] = item["id"]
                elif item["state"] == "device":
                    pending.append(item)

            def _fetch(target):
                try:
                    proc = subprocess.run(
                        [self.adb_cmd, "-s", target["id"], "shell", "getprop", "ro.serialno"],
                        **self._get_subprocess_kwargs(timeout=self.SERIALNO_TIMEOUT)
                    )
                    target["serialno"] = proc.stdout.strip()
                except Exception:
                    pass

            # 并发取：无线设备的 getprop 每台约 0.3s（网络往返），实测 4 台串行
            # 1.26s vs 并发 0.25s（中位数，5 次），设备越多差距越大。
            # 各线程只写自己那个 dict 的一个键，无竞争。
            # join 给足超时兜底，单台设备卡住不拖垮整次刷新（subprocess 自身也有 timeout）。
            if pending:
                threads = [threading.Thread(target=_fetch, args=(it,), daemon=True)
                           for it in pending]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=self.SERIALNO_TIMEOUT + 2)
        return result

    def get_wireless_devices(self):
        """同步返回当前处于 device 状态的无线设备地址列表 ["ip:port", ...]。"""
        return [d["id"] for d in self.get_devices_detailed()
                if d["transport"] == "wifi" and d["state"] == "device"]

    def start_wireless_debug_flow(self, on_ip_found, on_failure, device_id=None,
                                  port=WIRELESS_DEFAULT_PORT):
        """对指定设备开启无线调试端口并取回它的 IP。

        1. 取该设备的 wlan0 IP
        2. adb -s <device_id> tcpip <port>
        3. 回调 on_ip_found(addr, device_id)，addr 形如 "ip:port"
        4. (UI 随后调 connect_wireless)

        device_id 为 None 时用当前选中设备。多设备场景下必须显式定向 ——
        整个流程横跨数秒，期间用户可能切换下拉框，靠 current_device_id
        隐式注入会把端口开到错误的设备上。
        """
        device_id = device_id or self.current_device_id

        def _thread():
            self.log(f"正在为设备 {device_id} 启动无线调试流程...", "INFO")
            try:
                # 1. Open Port
                # Some devices disconnect when running `adb tcpip 5555` while already connected via tcpip,
                # or the USB connection might temporarily drop and reconnect.
                # To avoid breaking the command pipeline that fetches the IP, we get the IP first.
                
                # 2. Get IP first
                self.log("正在尝试获取设备 IP...", "INFO")
                device_ip = None
                
                # 只存 shell 侧参数，执行时再前置 [adb, -s, device_id]：
                # 原来是就地 insert 把 -s 塞进策略表，既污染列表又只能打到 current_device_id
                ip_strategies = [
                    (["shell", "ip", "route"], [
                        r'dev\s+wlan0\s+.*src\s+(\d+\.\d+\.\d+\.\d+)',
                        r'src\s+(\d+\.\d+\.\d+\.\d+).*dev\s+wlan0',
                        r'src\s+(\d+\.\d+\.\d+\.\d+)'
                    ]),
                    (["shell", "ip", "addr", "show", "wlan0"], [r'inet\s+(\d+\.\d+\.\d+\.\d+)']),
                    (["shell", "ifconfig", "wlan0"], [r'inet\s+(?:addr:)?(\d+\.\d+\.\d+\.\d+)']),
                    (["shell", "ip", "-4", "addr"], [
                        r'wlan0.*?inet\s+(\d+\.\d+\.\d+\.\d+)',
                        r'global\s+wlan0\s+.*?inet\s+(\d+\.\d+\.\d+\.\d+)'
                    ]),
                    (["shell", "netcfg"], [r'wlan0\s+UP\s+(\d+\.\d+\.\d+\.\d+)'])
                ]

                if not device_id:
                    self.log("操作中止: 当前未选择任何设备", "ERROR")
                    if on_failure:
                        on_failure("EXCEPTION: 当前未选择任何设备")
                    return

                for args, patterns in ip_strategies:
                    if device_ip: break
                    try:
                        cmd = [self.adb_cmd, "-s", device_id] + args
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

                        if not device_ip and "ip" in args and "addr" in args:
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
                self.log(f"正在开启设备 {device_id} 的 TCP/IP 端口 {port}...", "INFO")
                ok, msg = self.execute_adb_command(
                    [self.adb_cmd, "-s", device_id, "tcpip", str(port)], check_dev=False
                )
                if not ok:
                    if on_failure:
                        on_failure(f"EXCEPTION: 开启 tcpip {port} 失败: {msg}")
                    return
                time.sleep(2)

                addr = f"{device_ip}:{port}"
                # 记下 USB 序列号 -> 无线地址，拔线后 UI 能把选中项跟到同一台设备上
                if not self.is_wireless_device_id(device_id):
                    self.wireless_addr_by_serial[device_id] = addr

                if on_ip_found:
                    on_ip_found(addr, device_id)

            except Exception as e:
                self.log(f"无线调试流程异常: {str(e)}", "ERROR")
                if on_failure:
                    on_failure(f"EXCEPTION: {str(e)}")

        threading.Thread(target=_thread, daemon=True).start()

    def connect_wireless(self, addr, on_result, async_run=True):
        """连接一台无线设备。addr 接受 "ip" 或 "ip:port"（缺省端口 5555）。

        回调 on_result(success, addr, message)。多台设备可以各自 IP 共用 5555，
        彼此不冲突，所以这里不做"是否已有其它无线设备"的检查，也不要求先拔 USB
        —— adb 允许同一台机器 USB 与 WiFi 两条 entry 并存。
        """
        norm = self.normalize_wireless_addr(addr)

        def _work():
            if not norm:
                self.log(f"无线地址格式非法: {addr}", "ERROR")
                if on_result:
                    on_result(False, addr, "地址格式非法，应形如 192.168.1.5 或 192.168.1.5:5555")
                return

            self.log(f"正在尝试无线连接 {norm} ...", "INFO")
            ok, out = self.execute_adb_command(
                [self.adb_cmd, "connect", norm], check_dev=False
            )
            time.sleep(2)

            # 验证：adb connect 即使失败也常返回 0，必须回查 devices 里该地址是否 device 状态
            connected = norm in self.get_wireless_devices()
            if connected:
                self.log(f"无线调试连接成功: {norm}", "SUCCESS")
                if on_result:
                    on_result(True, norm, out or "")
            else:
                msg = out or "未知错误"
                self.log(f"无线调试连接失败: {norm} ({msg})", "ERROR")
                if on_result:
                    on_result(False, norm, msg)

        if async_run:
            threading.Thread(target=_work, daemon=True).start()
        else:
            _work()

    def connect_wireless_devices(self, addrs, on_complete=None):
        """批量连接多台无线设备（串行执行，避免 adb server 并发 connect 抢锁）。

        回调 on_complete(results)，results 为 [(addr, success, message), ...]。
        """
        def _thread():
            results = []

            def _collect(success, addr, message):
                results.append((addr, success, message))

            for a in addrs:
                self.connect_wireless(a, _collect, async_run=False)
            ok_count = sum(1 for r in results if r[1])
            self.log(f"批量无线连接完成: 成功 {ok_count}/{len(addrs)}", "SUCCESS" if ok_count else "WARNING")
            if on_complete:
                on_complete(results)

        threading.Thread(target=_thread, daemon=True).start()

    def disconnect_wireless(self, targets=None, on_complete=None):
        """断开无线设备。

        targets 为 None 时断开当前所有无线设备（"全部断开"）；
        传 ["ip:port", ...] 则只断开指定的那几台，其它无线设备保持连接。
        回调 on_complete(count, error=None)，count 为实际断开的台数，-1 表示异常。
        """
        def _thread():
            try:
                if targets is None:
                    self.log("正在检查已连接的无线设备...", "INFO")
                    wireless_devices = self.get_wireless_devices()
                else:
                    wireless_devices = [a for a in (self.normalize_wireless_addr(t) for t in targets) if a]

                if not wireless_devices:
                    self.log("未发现要断开的无线调试设备", "WARNING")
                    if on_complete: on_complete(0)
                    return

                count = 0
                for device in wireless_devices:
                    ok, _ = self.execute_adb_command(
                        [self.adb_cmd, "disconnect", device], check_dev=False
                    )
                    if ok:
                        count += 1
                    # 断开后清掉 serial -> addr 映射，避免刷新时把选中项跟到已断开的地址
                    for serial, mapped in list(self.wireless_addr_by_serial.items()):
                        if mapped == device:
                            del self.wireless_addr_by_serial[serial]
                    # 当前操作设备正是被断开的这台，清空选中，避免后续命令打到死地址
                    if self.current_device_id == device:
                        self.current_device_id = None

                self.log(f"已断开 {count} 台无线设备", "SUCCESS")
                if on_complete: on_complete(count)

            except Exception as e:
                self.log(f"断开无线设备异常: {str(e)}", "ERROR")
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

        # 每次启动都重建队列，避免上一次窗口残留的未消费日志被当作"新日志"读出
        self.firebase_log_queue = queue.Queue()

        # -T 1：只回看最后 1 行再继续实时流式输出，不依赖设备/主机时钟（两者可能不同步），
        # 避免用时间戳做 -T 时因设备时钟滞后于主机而把刚产生的新日志也一并过滤掉
        cmd_logcat = [self.adb_cmd, "-s", self.current_device_id, "logcat", "-v", "time", "-T", "1", "-s", "FA", "FA-SVC"]
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

    # --- Contacts ---

    def get_all_contacts(self):
        """获取设备通讯录中所有联系人姓名"""
        self.check_device()
        success, output = self.execute_adb_command([
            "adb", "shell", "content", "query",
            "--uri", "content://com.android.contacts/contacts",
            "--projection", "display_name"
        ])
        if not success or not output:
            return []

        names = []
        for line in output.split('\n'):
            # 格式: Row: 0 display_name=张三
            match = re.search(r'display_name=(.+)', line)
            if match:
                name = match.group(1).strip()
                if name and name not in names:
                    names.append(name)
        names.sort(key=lambda n: n.lower())
        return names

    def play_contact_ringtone(self, contact_name):
        """播放指定联系人的自定义铃声"""
        self.check_device()
        # 查询所有联系人的 display_name 和 custom_ringtone（避免 --where 空格问题）
        success, output = self.execute_adb_command([
            "adb", "shell", "content", "query",
            "--uri", "content://com.android.contacts/contacts",
            "--projection", "display_name:custom_ringtone"
        ])
        if not success or not output:
            return False, "查询联系人铃声失败"

        # 在 Python 端匹配目标联系人
        uri = None
        for line in output.split('\n'):
            if f"display_name={contact_name}" in line:
                match = re.search(r'custom_ringtone=(.+)', line)
                if match:
                    uri = match.group(1).strip()
                break

        if not uri or uri == "NULL":
            return False, f"联系人 {contact_name} 未设置自定义铃声（使用默认铃声）"

        # 清理 URI
        if "0@" in uri:
            uri = uri.replace("0@", "")

        # 播放
        self.execute_adb_command([
            "adb", "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", uri, "-t", "audio/*"
        ])
        return True, f"正在播放 {contact_name} 的铃声"

    # --- Screen Record ---

    def enable_show_touches(self):
        try:
            put_success, _ = self.execute_adb_command(["adb", "shell", "settings", "put", "system", "show_touches", "1"])
            get_success, output = self.execute_adb_command(["adb", "shell", "settings", "get", "system", "show_touches"])
            already_on = get_success and output.strip() == "1"
            if put_success and already_on:
                self.log("已开启「显示点按操作反馈」", "SUCCESS")
                return True
            elif not put_success and already_on:
                self.log("「显示点按操作反馈」已处于开启状态（无需ADB设置）", "INFO")
                return True
            else:
                self.log("开启「显示点按操作反馈」失败", "WARNING")
                self._log_show_touches_permission_hint()
                return False
        except Exception as e:
            self.log(f"开启「显示点按操作反馈」失败: {e}", "WARNING")
            self._log_show_touches_permission_hint()
            return False


    def _log_show_touches_permission_hint(self):
        self.log(
            "你的手机系统可能额外限制了 ADB 修改系统设置的权限，仅开启「USB 调试」是不够的。\n"
            "  解决方法：\n"
            "  1. 小米/HyperOS/MIUI：开发者选项 → 开启「USB 调试（安全设置）」（需登录小米账号，确认3次警告）\n"
            "  2. OPPO/vivo/Realme：开发者选项 → 开启「禁止权限监控」或关闭「权限监控」",
            "WARNING"
        )

    def start_recording(self, bit_rate=4_000_000):
        try:
            self.check_device()
        except NoDeviceConnectedError as e:
            self.log(f"操作中止: {e}", "ERROR")
            raise e

        if self.recording_process:
            return False

        self.enable_show_touches()

        cmd = [self.adb_cmd, "-s", self.current_device_id, "shell",
               "screenrecord", "--bit-rate", str(int(bit_rate)),
               "/sdcard/screen_record_tmp.mp4"]

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
            error_reason = None
            try:
                proc_output = ""
                if self.recording_process:
                    proc = self.recording_process
                    died_early = proc.poll() is not None
                    proc.terminate()
                    self.recording_process = None
                    try:
                        out, err = proc.communicate(timeout=5)
                        proc_output = (err or b"").decode("utf-8", errors="ignore").strip()
                        if not proc_output:
                            proc_output = (out or b"").decode("utf-8", errors="ignore").strip()
                    except Exception:
                        pass
                    if died_early:
                        if "screenrecord" in proc_output and "not found" in proc_output:
                            error_reason = (
                                "此设备无法执行 screenrecord（可能是系统未打包该工具，也可能被定制 ROM 的安全策略拦截），"
                                "无法用 adb 方式录屏，这是设备侧限制，与本工具无关"
                            )
                        else:
                            error_reason = f"screenrecord 进程在录制过程中已提前退出{': ' + proc_output if proc_output else ''}"
                        self.log(error_reason, "WARNING")

                time.sleep(2)

                remote_path = "/sdcard/screen_record_tmp.mp4"
                label = self._device_label_for_filename()
                device_suffix = f"_{label}" if label else ""
                local_filename = f"screenrecord_{int(time.time())}{device_suffix}.mp4"
                local_path = os.path.join(temp_dir, local_filename)

                pull_ok, _ = self.execute_adb_command(["adb", "pull", remote_path, local_path])
                self.execute_adb_command(["adb", "shell", "rm", remote_path])

                if not pull_ok and proc_output and not error_reason:
                    self.log(f"screenrecord 输出: {proc_output}", "WARNING")

                if on_complete:
                    on_complete(local_path, error_reason)

            except Exception as e:
                self.log(f"停止录制失败: {e}", "ERROR")
                if on_complete: on_complete(None, str(e))

        threading.Thread(target=_thread, daemon=True).start()

    # --- Screenshot ---
    
    def take_screenshot(self, temp_dir, on_complete):
        def _thread():
            try:
                remote_path = "/sdcard/screen.png"
                label = self._device_label_for_filename()
                device_suffix = f"_{label}" if label else ""

                # 文件名追加 "_可用宽dp x 可用高dp"，便于按屏幕尺寸归档。
                # 查询走 _shell_silent，不污染日志；失败时退化为无后缀。
                size_suffix = ""
                try:
                    info = self.get_screen_info()
                    aw = re.match(r"(\d+)", str(info.get("avail_w", "")))
                    ah = re.match(r"(\d+)", str(info.get("avail_h", "")))
                    if aw and ah:
                        size_suffix = f"_{aw.group(1)}x{ah.group(1)}"
                except Exception:
                    pass

                local_filename = f"screenshot_{int(time.time())}{device_suffix}{size_suffix}.png"
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

