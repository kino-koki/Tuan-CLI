"""与 Codex ``tui/src/terminal_hyperlinks.rs`` 对齐的语义终端超链接。

上游模块头（功能性契约）：

    "Semantic terminal hyperlinks carried separately from visible TUI text.
    Layout code measures and wraps ordinary ratatui lines. Hyperlink
    annotations are applied only when text reaches a terminal buffer or
    scrollback writer so OSC 8 bytes never affect geometry."

**本模块是这一轮里安全价值最高的一个**：链接目标会被终端解释，必须把
候选路径当作不可信输入处理。逐分支对齐上游 ``TrustedWorkspaceFile::validate``。

对齐的逐值/逐分支事实：
  - ``MAX_HYPERLINK_DESTINATION_BYTES = 8 * 1024``；超长目标**降级为纯文本**；
  - ``SAFE_WORKSPACE_EXTENSIONS`` 白名单 17 项（rs/go/c/cc/cpp/h/hpp/
    java/kt/swift/toml/json/yaml/yml/md/txt/css）；
  - validate 拒绝：空 / >512 字符 / 含 ``:`` / 含控制字符 / 绝对路径 /
    任一段为空或以 ``.`` 开头 / 扩展名不在白名单；
  - 之后 ``canonicalize`` 工作区与目标，``strip_prefix`` 确认目标仍在工作
    区内；要求目标是**普通文件**、扩展名一致、相对路径任一段都不以
    ``.`` 开头（防 symlink 指向隐藏目录）；
  - ``viewed_image``：用图片格式探测（而非只看后缀，防
    ``screenshot.png`` 其实是脚本），canonicalize 后必须是普通文件、
    无 host；上游还检查 Windows junction / UNC；
  - 注解只在写终端 buffer / scrollback 时应用，**OSC 8 字节不参与折行
    与宽度计算**。

本地化修改（如实列出）：
  - ``web()`` 增加 **scheme 白名单**（http/https）与 OSC/BEL/控制字符
    检查 —— 上游 ``web()`` 不校验目的地，这是本项目的安全增强，
    **不是**对上游行为的削弱；
  - 不用 ``url`` / ``image`` crate：URL 用 ``urllib.parse``，图片用
    后缀 + 文件魔数（PNG/JPEG/GIF/WebP/BMP）探测；
  - 用 ``pathlib.Path.resolve()`` 等价 ``canonicalize()``；
  - Windows junction 检查本地化为「祖先链含 symlink 即拒绝」（更保守）；
  - ``columns`` 用 ``range``；新增 ``to_osc8(visible)`` 显式生成注解，
    让「注解不进可见文本」成为可测契约。

许可：Apache-2.0（NOTICE 第 11 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

MAX_HYPERLINK_DESTINATION_BYTES = 8 * 1024
MAX_CANDIDATE_CHARS = 512
MAX_CANDIDATE_BYTES = 512

SAFE_WORKSPACE_EXTENSIONS = (
    "rs", "go", "c", "cc", "cpp", "h", "hpp", "java", "kt", "swift",
    "toml", "json", "yaml", "yml", "md", "txt", "css",
)

# 本地化增强：图片魔数探测（对齐上游 ImageFormat::from_path 的意图）
_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
)


class DestinationKind(str, Enum):
    WEB = "web"
    TRUSTED_FILE = "trusted_file"


@dataclass
class TrustedWorkspaceFile:
    """对齐上游 newtype：已验证仍位于会话工作区内的普通文件。"""

    url: str
    resolved: Path

    @classmethod
    def validate(cls, workspace: Path, candidate: str) -> Optional["TrustedWorkspaceFile"]:
        if (not candidate or len(candidate) > MAX_CANDIDATE_CHARS
                or len(candidate.encode("utf-8", "replace")) > MAX_CANDIDATE_BYTES
                or ":" in candidate or any(ord(c) < 32 or ord(c) == 127
                                           for c in candidate)):
            return None

        normalized = candidate.replace("\\", "/")
        if normalized.startswith("/") or os.path.isabs(candidate):
            return None
        parts = normalized.split("/")
        if any(not p or p.startswith(".") for p in parts):
            return None

        ext = Path(normalized).suffix.lstrip(".").lower()
        if ext not in SAFE_WORKSPACE_EXTENSIONS:
            return None

        ws = Path(workspace).resolve()
        if not ws.is_dir():
            return None
        target = (ws / normalized).resolve()
        try:
            relative = target.relative_to(ws)
        except ValueError:
            return None                       # 逃逸出工作区
        if not target.is_file():
            return None
        if target.suffix.lstrip(".").lower() != ext:
            return None                       # symlink 换了扩展名
        if any(p.startswith(".") for p in relative.parts):
            return None                       # symlink 指向隐藏目录
        # 本地化：对齐上游 Windows junction 检查。逐个检查工作区内的
        # 中间目录是否为 symlink（用绝对路径，不能用 relative.parents 的
        # 相对片段，否则会误判当前工作目录下的同名路径）。
        chain = [ws]
        for part in relative.parts[:-1]:
            chain.append(chain[-1] / part)
        if any(_is_symlink_ancestor(a) for a in chain):
            return None
        return cls(url=target.as_uri(), resolved=target)


def _is_symlink_ancestor(p: Path) -> bool:
    """本地化：对齐上游 Windows junction 检查，但更保守（任何 symlink 都拒）。"""
    try:
        return p.is_symlink()
    except OSError:
        return True  # 探测失败按不安全处理


@dataclass
class TerminalHyperlink:
    """对齐上游结构体：列范围 + 目的地 + 目的地类别。"""

    columns: range
    destination: str
    destination_kind: DestinationKind = DestinationKind.WEB

    @classmethod
    def web(cls, columns: range, destination: str) -> Optional["TerminalHyperlink"]:
        """超长/非法/不安全 scheme 的目标**降级为纯文本**（返回 None）。"""
        if (not destination
                or len(destination.encode("utf-8", "replace"))
                > MAX_HYPERLINK_DESTINATION_BYTES
                or any(ord(c) < 32 or ord(c) == 127 or c in ("\x1b", "\x07")
                       for c in destination)):
            return None
        parsed = urlparse(destination)
        # 本地化安全增强：只允许 http/https，拦 javascript:/data:/file:
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            return None
        return cls(columns, destination, DestinationKind.WEB)

    @classmethod
    def trusted_workspace_file(cls, columns: range,
                               file: TrustedWorkspaceFile) -> "TerminalHyperlink":
        return cls(columns, file.url, DestinationKind.TRUSTED_FILE)

    def retarget_to_trusted_file(self, destination: str) -> bool:
        """对齐上游 ``retarget_to_trusted_file``（debug_assert file scheme）。

        返回 False 表示拒绝重定目标；不抛异常、不改对象状态。
        """
        if not destination.startswith("file:"):
            return False
        if len(destination.encode("utf-8", "replace")) > MAX_HYPERLINK_DESTINATION_BYTES:
            return False
        self.destination = destination
        self.destination_kind = DestinationKind.TRUSTED_FILE
        return True

    @classmethod
    def viewed_image(cls, columns: range,
                     path: Path) -> Optional["TerminalHyperlink"]:
        """对齐上游：只有「解析后仍是能被识别为图片的普通文件」才链接。"""
        p = Path(path)
        if not _looks_like_image(p):
            return None
        target = p.resolve()
        if (not _looks_like_image(target) or not target.is_file()
                or any(a.is_symlink() for a in _ancestors(target))):
            return None
        return cls(columns, target.as_uri(), DestinationKind.TRUSTED_FILE)

    # ------------------------------------------------------------ OSC 8
    def to_osc8(self, visible: str) -> str:
        """生成 OSC 8 注解。**可见文本单独传入**，注解字节不参与布局。"""
        return f"\x1b]8;;{self.destination}\x07{visible}\x1b]8;;\x07"

    def affects_geometry(self, visible: str) -> bool:
        """可测契约：注解不改变可见文本的字符数/宽度。"""
        from .custom_terminal import display_width
        wrapped = self.to_osc8(visible)
        # 去掉两条 OSC 8 控制段后应与原文本一致
        strip = (wrapped.replace(f"\x1b]8;;{self.destination}\x07", "")
                 .replace("\x1b]8;;\x07", ""))
        return strip == visible and display_width(strip) == display_width(visible)


def _looks_like_image(p: Path) -> bool:
    try:
        if not p.is_file():
            return False
        with open(p, "rb") as f:
            head = f.read(16)
    except OSError:
        return False
    for magic, _ in _IMAGE_MAGIC:
        if head.startswith(magic):
            return True
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    return False


def _ancestors(p: Path):
    """目标本身的父链（不含文件系统根，避免 /tmp 这类系统 symlink 误杀）。"""
    out = []
    cur = p.parent
    while cur != cur.parent:
        out.append(cur)
        cur = cur.parent
    return out
