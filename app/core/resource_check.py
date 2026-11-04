"""资源目标校验与网址规范化：纯函数，不碰数据库、不碰界面。

check_resource 返回 None 表示有效；返回字符串表示具体原因（直接展示给用户）。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse, urlunparse

from app.core.models import Resource, ResourceKind

# 「程序」类型只接受真正的可执行文件；.bat/.cmd/.lnk 等请用「文件」类型
APP_SUFFIXES = {".exe", ".com"}


def check_resource(resource: Resource) -> str | None:
    target = resource.target.strip()
    if not target:
        return "目标为空"

    if resource.kind is ResourceKind.URL:
        parsed = urlparse(target)
        if parsed.scheme not in ("http", "https"):
            return "URL 必须以 http:// 或 https:// 开头"
        if not parsed.netloc:
            return "URL 缺少域名"
        try:
            parsed.port
        except ValueError:
            return "URL 端口无效"
        return None

    path = Path(target)
    if not path.is_absolute():
        return "请使用绝对路径"

    if resource.kind is ResourceKind.FILE:
        if not path.exists():
            return "文件不存在"
        if not path.is_file():
            return "这不是文件"
    elif resource.kind is ResourceKind.FOLDER:
        if not path.exists():
            return "文件夹不存在"
        if not path.is_dir():
            return "这不是文件夹"
    elif resource.kind is ResourceKind.APP:
        if path.suffix.lower() not in APP_SUFFIXES:
            return "程序类型只接受 .exe / .com 文件（其他请用「文件」类型）"
        if not path.exists():
            return "程序不存在"
        if not path.is_file():
            return "这不是文件"

    return None


def normalize_url(url: str) -> str:
    """把网址规范化后再比较，用于识别「看起来相同」的重复项。

    规则：协议和域名转小写、去掉默认端口、空路径补 `/`、忽略 #fragment。
    路径和查询参数保持原样（/a 和 /a/ 视为不同页面）。
    """
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()

    try:
        port = parsed.port
    except ValueError:
        port = None
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    netloc = host if port is None else f"{host}:{port}"
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))
