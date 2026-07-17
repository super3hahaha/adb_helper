"""纯标准库实现的「限速/延迟/丢包」HTTP 代理，用于精确弱网模拟。

和 tools_tab 里那套「假代理（连不上的地址）」不同，这里起的是一个**真能转发**
的本地代理：设备把 http_proxy 指向本机，所有 HTTP(S) 流量经过这里，我们在字节
转发的过程中人为注入延迟 / 带宽上限 / 丢包，从而得到可配参数的弱网环境。

设计要点（都是应用层近似，不是内核级 tc/netem，见 docs/gotchas.md）：
- 支持 HTTPS：解析 CONNECT 请求，建隧道后双向盲转字节（不解密，无需 CA 证书）。
- 支持明文 HTTP：把发给代理的绝对 URL 请求行改写成相对路径再转发。
- 延迟 delay_ms：每条**新连接**建立后注入一次（模拟高 RTT / 首字节延迟），
  不逐 chunk 累加，避免大流量下延迟雪崩把连接彻底拖死。
- 限速 rate_kbytes：令牌桶思路，按 chunk 大小 sleep 到目标速率（单位 KB/s，1KB=1024B，
  与界面实时速率显示同进制，方便直接对比）。
- 丢包 loss_pct：每条**新连接**掷一次骰子，命中就直接拒绝（模拟该次请求因丢包
  彻底失败）。这是最可控、最好解释的语义 —— 直接对应「请求失败率」，方便测 App
  的重试 / 超时 / 失败兜底逻辑。

事件循环跑在独立后台线程，GUI（tkinter 主线程）通过 start/stop/update 操作它，
参数用一个普通 dict 共享，GIL 保证读写单个键值是安全的。
"""

import asyncio
import random
import socket
import threading


BUFSIZE = 65536


class ThrottleProxy:
    def __init__(self, log=None):
        # log(msg, level) 兼容 tools_tab 的日志签名；没传就静默
        self._log = log or (lambda msg, level="INFO": None)
        # 共享参数，GUI 线程改、事件循环线程读
        self.config = {"delay_ms": 0, "rate_kbytes": 0, "loss_pct": 0}

        self._loop = None            # asyncio 事件循环（后台线程里）
        self._thread = None          # 跑事件循环的线程
        self._server = None          # asyncio.Server
        self._host = None            # 对外可达的本机 IP
        self._port = None            # 实际监听端口

        # 累计吞吐字节数（up=设备->外网，down=外网->设备）。
        # pump 线程 += / GUI 线程读，单个 int 读写靠 GIL 原子，够统计用。
        self._up_bytes = 0
        self._down_bytes = 0
        self._last_up = 0            # sample() 上次快照，用于算增量
        self._last_down = 0

        # 全局令牌桶游标：所有连接共享，实现「整机总带宽」限速而非每条连接各自限。
        # 值为 loop.time() 坐标下「下一次可发送的时刻」，上下行各一个池。
        # 全在单线程事件循环里读改，协程 await 之间原子，无需锁。
        self._tb_next_up = 0.0
        self._tb_next_down = 0.0

    # ---------- 对外接口（GUI 线程调用） ----------

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def sample(self):
        """返回自上次调用以来的字节增量 (up_delta, down_delta)。

        GUI 每隔固定时间调一次，用增量 / 实际间隔即可算出实时速率。
        读快照再更新 last，中间 pump 线程可能又 += 少量，统计场景可忽略。
        """
        up, down = self._up_bytes, self._down_bytes
        d_up = up - self._last_up
        d_down = down - self._last_down
        self._last_up, self._last_down = up, down
        return d_up, d_down

    def update(self, delay_ms=None, rate_kbytes=None, loss_pct=None):
        """实时更新弱网参数。运行中调用立即生效（下一条连接 / 下一个 chunk）。

        rate_kbytes 单位 KB/s（0 表示不限速）。
        """
        if delay_ms is not None:
            self.config["delay_ms"] = max(0, int(delay_ms))
        if rate_kbytes is not None:
            self.config["rate_kbytes"] = max(0, int(rate_kbytes))
        if loss_pct is not None:
            self.config["loss_pct"] = max(0, min(100, float(loss_pct)))

    def start(self, port=0):
        """在后台线程起事件循环 + 代理服务器。

        返回 (host_ip, port)。若已在运行，直接返回当前监听信息（幂等）。
        port=0 表示让系统分配空闲端口。抛异常表示启动失败。
        """
        if self.is_running():
            return self._host, self._port

        ready = threading.Event()
        err_box = {}

        def _run():
            try:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._server = self._loop.run_until_complete(
                    asyncio.start_server(self._handle_client, "0.0.0.0", port)
                )
                self._port = self._server.sockets[0].getsockname()[1]
                self._host = self.local_ip()
            except Exception as e:  # noqa: BLE001 - 把异常带回主线程
                err_box["error"] = e
                ready.set()
                return
            ready.set()
            try:
                self._loop.run_forever()
            finally:
                # run_forever 退出后收尾：关 server、跑完挂起任务、关 loop
                try:
                    self._server.close()
                    self._loop.run_until_complete(self._server.wait_closed())
                except Exception:
                    pass
                try:
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                except Exception:
                    pass
                self._loop.close()

        self._thread = threading.Thread(target=_run, daemon=True, name="ThrottleProxy")
        self._thread.start()
        ready.wait(timeout=5)

        if "error" in err_box:
            self._thread = None
            raise err_box["error"]
        if not self.is_running() or self._port is None:
            self._thread = None
            raise RuntimeError("限速代理启动超时")
        # 重置吞吐计数与令牌桶游标，让本次会话从干净状态开始
        self._up_bytes = self._down_bytes = 0
        self._last_up = self._last_down = 0
        self._tb_next_up = self._tb_next_down = 0.0
        return self._host, self._port

    def stop(self):
        """停止代理服务器并回收后台线程。"""
        if self._loop is not None and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        self._loop = None
        self._server = None
        self._host = None
        self._port = None

    # ---------- 内部：连接处理 ----------

    async def _handle_client(self, reader, writer):
        peer = writer.get_extra_info("peername")
        try:
            # 丢包：每条新连接掷一次骰子，命中即整条请求失败
            loss = self.config["loss_pct"]
            if loss > 0 and random.random() * 100 < loss:
                writer.close()
                return

            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return

            # 请求行形如：CONNECT host:443 HTTP/1.1  或  GET http://host/path HTTP/1.1
            try:
                method, target, version = request_line.decode(
                    "latin-1"
                ).rstrip("\r\n").split(" ", 2)
            except ValueError:
                writer.close()
                return

            # 读完剩余请求头（到空行为止）
            headers = []
            while True:
                line = await reader.readline()
                if not line or line in (b"\r\n", b"\n"):
                    break
                headers.append(line)

            delay_s = self.config["delay_ms"] / 1000.0

            if method.upper() == "CONNECT":
                await self._handle_connect(target, delay_s, reader, writer)
            else:
                await self._handle_plain(method, target, version, headers, delay_s, reader, writer)
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        except Exception as e:  # noqa: BLE001
            self._log(f"限速代理连接异常({peer}): {e}", "WARNING")
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _handle_connect(self, target, delay_s, client_reader, client_writer):
        host, _, port = target.partition(":")
        port = int(port or 443)
        try:
            remote_reader, remote_writer = await asyncio.open_connection(host, port)
        except Exception:
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            return

        # 注入一次连接延迟（模拟高 RTT），再回 200 建立隧道
        if delay_s > 0:
            await asyncio.sleep(delay_s)
        client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_writer.drain()

        await self._pump_bidirectional(client_reader, client_writer, remote_reader, remote_writer)

    async def _handle_plain(self, method, target, version, headers, delay_s, client_reader, client_writer):
        # 从绝对 URL 里拆出 host / port / 相对路径
        if target.startswith("http://"):
            rest = target[len("http://"):]
            hostport, _, path = rest.partition("/")
            path = "/" + path
        else:
            # 非绝对 URL 的代理请求，兜底当作直接转发
            hostport = ""
            path = target
        host, _, port = hostport.partition(":")
        port = int(port or 80)
        if not host:
            # 尝试从 Host 头取
            for h in headers:
                if h.lower().startswith(b"host:"):
                    hv = h.split(b":", 1)[1].strip().decode("latin-1")
                    host, _, p = hv.partition(":")
                    port = int(p or 80)
                    break
        if not host:
            client_writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            return

        try:
            remote_reader, remote_writer = await asyncio.open_connection(host, port)
        except Exception:
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            return

        if delay_s > 0:
            await asyncio.sleep(delay_s)

        # 重建请求行（绝对 URL -> 相对路径），去掉 Proxy-Connection 头后转发
        head = f"{method} {path} {version}\r\n".encode("latin-1")
        for h in headers:
            if h.lower().startswith(b"proxy-connection:"):
                continue
            head += h
        head += b"\r\n"
        remote_writer.write(head)
        await remote_writer.drain()

        await self._pump_bidirectional(client_reader, client_writer, remote_reader, remote_writer)

    async def _pump_bidirectional(self, client_reader, client_writer, remote_reader, remote_writer):
        """双向转发，两个方向各自限速。任一方向结束即收尾。"""
        up = asyncio.ensure_future(self._pump(client_reader, remote_writer, "up"))
        down = asyncio.ensure_future(self._pump(remote_reader, client_writer, "down"))
        try:
            await asyncio.gather(up, down, return_exceptions=True)
        finally:
            for w in (remote_writer, client_writer):
                try:
                    w.close()
                except Exception:
                    pass

    async def _pump(self, reader, writer, direction):
        """单向搬运字节，按 rate_kbytes(KB/s) 限速，并累计吞吐。direction: 'up'/'down'。"""
        try:
            while True:
                chunk = await reader.read(BUFSIZE)
                if not chunk:
                    break
                rate = self.config["rate_kbytes"]
                if rate > 0:
                    # 全局令牌桶：整台设备该方向的总带宽 = rate KB/s，跨所有连接共享。
                    # 把本块要占用的发送时长排到共享游标之后，游标累进 -> 并发连接
                    # 自动被串行化到同一条时间线上，总吞吐不超过设定值。
                    bytes_per_sec = rate * 1024
                    loop = asyncio.get_event_loop()
                    now = loop.time()
                    if direction == "up":
                        start = self._tb_next_up if self._tb_next_up > now else now
                        self._tb_next_up = start + len(chunk) / bytes_per_sec
                    else:
                        start = self._tb_next_down if self._tb_next_down > now else now
                        self._tb_next_down = start + len(chunk) / bytes_per_sec
                    wait = start - now
                    if wait > 0:
                        await asyncio.sleep(wait)
                writer.write(chunk)
                await writer.drain()
                # 统计放在 drain 之后：反映真正搬过去的量（受限速节流后的实际速率）
                if direction == "up":
                    self._up_bytes += len(chunk)
                else:
                    self._down_bytes += len(chunk)
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    # ---------- 工具 ----------

    @staticmethod
    def local_ip():
        """拿本机在默认路由上的局域网 IP（供设备连接用）。不真正发包。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()
