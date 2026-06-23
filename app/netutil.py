from __future__ import annotations

import os
import socket


def lan_ip() -> str:
    """本机在局域网中的出口 IP(离线时回退 127.0.0.1)。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))   # UDP connect 不真正发包,仅确定出口网卡
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def access_url() -> str:
    """手机可访问的实时地址。"""
    return f"http://{lan_ip()}:{os.environ.get('PORT', '8000')}"
