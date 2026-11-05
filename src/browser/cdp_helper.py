from __future__ import annotations

import base64
import json
import os
import socket
import struct
import urllib.request
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


def list_cdp_pages(port: int = 9222) -> List[Dict[str, Any]]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as resp:
        items = json.loads(resp.read().decode("utf-8"))
    return [i for i in items if i.get("type") == "page"]


def cdp_evaluate(ws_url: str, expression: str, await_promise: bool = True, timeout: float = 15, max_retries: int = 3) -> Any:
    """Evaluates JavaScript in a Chrome tab over raw WebSocket (zero external dependencies)."""
    last_err = None
    for attempt in range(max_retries):
        parsed = urlparse(ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 9222
        path = parsed.path
        if not path.startswith("/"):
            path = f"/devtools/page/{path}"

        try:
            sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as e:
            last_err = e
            time.sleep(1.2)
            continue

        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            handshake = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            )
            sock.sendall(handshake.encode("ascii"))

            header_buf = b""
            while b"\r\n\r\n" not in header_buf:
                chunk = sock.recv(4096)
                if not chunk:
                    raise RuntimeError("WebSocket handshake closed prematurely")
                header_buf += chunk

            payload = json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "returnByValue": True,
                        "awaitPromise": await_promise,
                        "userGesture": True,
                    },
                }
            ).encode("utf-8")

            # Send masked client frame
            mask_key = os.urandom(4)
            header = bytearray([0x81])
            length = len(payload)
            if length < 126:
                header.append(0x80 | length)
            elif length < 65536:
                header.append(0x80 | 126)
                header.extend(struct.pack("!H", length))
            else:
                header.append(0x80 | 127)
                header.extend(struct.pack("!Q", length))
            header.extend(mask_key)
            masked = bytearray(payload[i] ^ mask_key[i % 4] for i in range(length))
            sock.sendall(header + masked)

            # Read response frames until id == 1
            leftover = header_buf.split(b"\r\n\r\n", 1)[1]

            def recv_exact(n: int) -> bytes:
                nonlocal leftover
                while len(leftover) < n:
                    chunk = sock.recv(65536)
                    if not chunk:
                        raise RuntimeError("EOF reading WebSocket frame")
                    leftover += chunk
                out, leftover = leftover[:n], leftover[n:]
                return out

            while True:
                b1, b2 = recv_exact(2)
                plen = b2 & 0x7F
                if plen == 126:
                    (plen,) = struct.unpack("!H", recv_exact(2))
                elif plen == 127:
                    (plen,) = struct.unpack("!Q", recv_exact(8))
                if b2 & 0x80:
                    mkey = recv_exact(4)
                    raw = bytearray(recv_exact(plen))
                    data = bytes(raw[i] ^ mkey[i % 4] for i in range(plen))
                else:
                    data = recv_exact(plen)

                if (b1 & 0x0F) == 0x1:
                    msg = json.loads(data.decode("utf-8", errors="replace"))
                    if msg.get("id") == 1:
                        return (
                            msg.get("result", {})
                            .get("result", {})
                            .get("value")
                        )
        except (ConnectionResetError, BrokenPipeError, RuntimeError, OSError) as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(1.5)
                continue
            raise e
        finally:
            try:
                sock.close()
            except Exception:
                pass
    if last_err:
        raise last_err


def cdp_command(ws_url: str, method: str, params: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Sends a raw CDP command over WebSocket and returns the result dict."""
    parsed = urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9222
    path = parsed.path
    if not path.startswith("/"):
        path = f"/devtools/page/{path}"

    sock = socket.create_connection((host, port), timeout=15)
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(handshake.encode("ascii"))

        header_buf = b""
        while b"\r\n\r\n" not in header_buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket handshake closed prematurely")
            header_buf += chunk

        cmd_dict = {
            "id": 1,
            "method": method,
            "params": params or {},
        }
        if session_id:
            cmd_dict["sessionId"] = session_id

        payload = json.dumps(cmd_dict).encode("utf-8")

        mask_key = os.urandom(4)
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask_key)
        masked = bytearray(payload[i] ^ mask_key[i % 4] for i in range(length))
        sock.sendall(header + masked)

        leftover = header_buf.split(b"\r\n\r\n", 1)[1]

        def recv_exact(n: int) -> bytes:
            nonlocal leftover
            while len(leftover) < n:
                chunk = sock.recv(65536)
                if not chunk:
                    raise RuntimeError("EOF reading WebSocket frame")
                leftover += chunk
            out, leftover = leftover[:n], leftover[n:]
            return out

        while True:
            b1, b2 = recv_exact(2)
            plen = b2 & 0x7F
            if plen == 126:
                (plen,) = struct.unpack("!H", recv_exact(2))
            elif plen == 127:
                (plen,) = struct.unpack("!Q", recv_exact(8))
            if b2 & 0x80:
                mkey = recv_exact(4)
                raw = bytearray(recv_exact(plen))
                data = bytes(raw[i] ^ mkey[i % 4] for i in range(plen))
            else:
                data = recv_exact(plen)

            if (b1 & 0x0F) == 0x1:
                msg = json.loads(data.decode("utf-8", errors="replace"))
                if msg.get("id") == 1:
                    return msg.get("result", {})
    finally:
        sock.close()


def cdp_real_click(ws_url: str, x: float, y: float) -> None:
    """Dispatches hardware-level mousePressed + mouseReleased events at (x, y)."""
    cdp_command(
        ws_url,
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
    )
    cdp_command(
        ws_url,
        "Input.dispatchMouseEvent",
        {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
    )


def close_cdp_tab(tab_id_or_ws_url: str, port: int = 9222) -> bool:
    """Closes a Chrome tab via CDP HTTP endpoint once an application is completed."""
    raw = (tab_id_or_ws_url or "").strip()
    if not raw:
        return False
    tab_id = raw.rstrip("/").split("/")[-1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{tab_id}", timeout=5) as resp:
            resp.read()
        return True
    except Exception:
        return False


def start_on_demand_chrome_cdp(port: int = 9222) -> bool:
    """
    Launches Chrome on port 9222 on-demand in the background (hidden/minimized, anti-throttled)
    if not already running, waits until CDP is ready, and ensures LinkedIn + Gmail tabs are available.
    """
    import subprocess
    import time

    version_url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(version_url, timeout=2) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass

    from src.config import BROWSER_PROFILE_DIR

    profile_dir = str(BROWSER_PROFILE_DIR)
    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    cmd = [
        chrome_bin,
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "-- start-minimized",
        "https://www.linkedin.com/jobs/",
        "https://mail.google.com/mail/u/0/#inbox",
    ]
    # Remove any accidental space in flag
    cmd = [c.replace("-- start-minimized", "--start-minimized") for c in cmd]

    with open(os.devnull, "wb") as devnull:
        subprocess.Popen(
            cmd,
            stdout=devnull,
            stderr=devnull,
            start_new_session=True,
        )

    ready = False
    for _ in range(25):
        time.sleep(0.6)
        try:
            with urllib.request.urlopen(version_url, timeout=2) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            continue

    # Hide Chrome window in macOS so it runs silently in the background without stealing focus
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to set visible of (every process whose unix id is (do shell script "pgrep -f remote-debugging-port='
                + str(port)
                + ' | head -n 1")) to false',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except Exception:
        pass

    return ready


def stop_on_demand_chrome_cdp(port: int = 9222) -> bool:
    """
    Gracefully closes the on-demand Chrome CDP instance via Browser.close so cookies/sessions
    are cleanly flushed to disk and zero Chrome processes consume battery between 6-hour runs.
    """
    import subprocess
    import time

    version_url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(version_url, timeout=3) as resp:
            info = json.loads(resp.read().decode("utf-8", errors="replace"))
        browser_ws = info.get("webSocketDebuggerUrl")
        if browser_ws:
            try:
                cdp_command(browser_ws, "Browser.close", {})
            except Exception:
                pass
    except Exception:
        pass

    time.sleep(1.5)
    try:
        subprocess.run(
            ["pkill", "-TERM", "-f", f"remote-debugging-port={port}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except Exception:
        pass
    return True


