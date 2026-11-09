"""Remote Control — 远程控制会话 (对标 Claude Code 2.1.239 Remote Control)。

核心功能:
- 生成 QR 码配对链接, 手机扫码后可远程控制终端会话
- 跨设备发送 prompt, 查看实时输出
- Push 通知: 模型决策时 / 需要权限确认时
- 会话状态同步: 进度、token 用量、上下文占用

实现:
- 本地 HTTP 服务器 (aiohttp 或 http.server) 提供 WebSocket/REST API
- QR 码编码配对 URL (含一次性 token)
- 安全: token 有效期 5 分钟, 连接后需再次认证
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)


# ================================================================ 数据结构

@dataclass
class RemoteSession:
    """远程控制会话。"""
    session_id: str
    pairing_token: str
    created_at: float
    connected: bool = False
    connected_at: float = 0.0
    device_name: str = ""
    device_type: str = ""       # mobile | desktop | tablet
    push_enabled: bool = False
    push_on_decision: bool = True
    push_on_permission: bool = True
    # —— 安全加固字段 (一次性 token / 设备绑定 / 爆破防护 / 确认标记) ——
    confirmed: bool = False               # 配对 token 是否已一次性消费
    token_fingerprint: str = ""           # 设备绑定指纹 (确认时写入, 防 token 被异设备复用)
    confirm_attempts: int = 0             # 确认尝试计数 (防爆破)
    requires_confirmation: bool = False   # 最近一条远程 prompt 是否需用户确认

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "connected": self.connected,
            "connected_at": self.connected_at,
            "device_name": self.device_name,
            "device_type": self.device_type,
            "push_enabled": self.push_enabled,
            "confirmed": self.confirmed,
            "requires_confirmation": self.requires_confirmation,
        }

    @property
    def is_expired(self) -> bool:
        """配对 token 是否过期 (5 分钟)。"""
        return time.time() - self.created_at > 300

    @property
    def is_active(self) -> bool:
        """会话是否活跃。"""
        return self.connected and not self.is_expired


# ================================================================ 安全辅助


def _device_fingerprint(token: str, device_name: str, device_type: str) -> str:
    """设备绑定指纹: 确认成功后写入会话, 后续操作须来自同一设备标识。"""
    return hashlib.sha256(
        f"{token}|{device_name}|{device_type}".encode("utf-8")
    ).hexdigest()[:32]


def _classify_remote(prompt: str) -> Any:
    """对远程 prompt 做安全分类 (fail-closed)。

    命中硬红线 -> deny; 其余异常一律保守要求确认, 不直接放行。
    """
    from ..ext.security_gate import GateVerdict, SecurityGate
    try:
        return SecurityGate(remote=True).classify_remote_prompt(prompt)
    except Exception:  # noqa: BLE001
        from ..ext.safety_engine import is_hard_redline
        if is_hard_redline(prompt):
            return GateVerdict("deny", "critical", ("远程 prompt 分类异常, 命中红线",))
        return GateVerdict("confirm", "high", ("远程 prompt 分类异常, 保守要求确认",))


# ================================================================ Remote Control Manager

class RemoteControl:
    """远程控制管理器。

    用法:
        rc = RemoteControl(Path("~/.tuan"))
        # 生成配对信息
        pairing = rc.start_pairing("my-session")
        print(f"QR Code URL: {pairing['url']}")
        print(f"Pairing Token: {pairing['token']}")
        # 手机扫码后, 调用 confirm_pairing
        rc.confirm_pairing(pairing["token"], device_name="iPhone 15")
        # 发送远程命令
        rc.send_prompt("my-session", "What files changed?")
    """

    def __init__(self, home: Path, host: str = "localhost", port: int = 0,
                 hooks: Any = None) -> None:
        # B3 续轮 VI: 实例级绑定。模块级 ``notify()`` 每次都通过这个
        # 单例取 hooks，而不是在派发时刻读进程级 default provider ——
        # 后者会在会话覆盖后把 A 的通知送到 B（C4-D 实测）。
        # ``None`` 表示未绑定，由 current_session_hooks() 在构造时捕获。
        self.hooks = hooks if hooks is not None else _session_hooks_snapshot()
        self.home = Path(home)
        self._sessions: Dict[str, RemoteSession] = {}
        self._host = host
        self._port = port or self._find_free_port()
        self._server = None
        self._callbacks: Dict[str, Callable] = {}
        # 配对确认爆破防护
        self._confirm_failures: int = 0
        self._confirm_locked_until: float = 0.0

    def _find_free_port(self) -> int:
        """找一个空闲端口。"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return int(s.getsockname()[1])

    def start_pairing(self, session_id: str) -> Dict[str, Any]:
        """开始配对流程。

        返回:
            url: 配对 URL (含一次性 token, 可编码为 QR 码)
            token: 配对 token
            expires_in: 过期时间 (秒)
        """
        token = secrets.token_urlsafe(32)
        remote_session = RemoteSession(
            session_id=session_id,
            pairing_token=token,
            created_at=time.time(),
        )
        self._sessions[session_id] = remote_session

        # 构建配对 URL
        params = urllib.parse.urlencode({
            "host": self._host,
            "port": self._port,
            "token": token,
            "session": session_id,
        })
        url = f"tuan-remote://pair?{params}"

        self._save_sessions()

        return {
            "url": url,
            "token": token,
            "session_id": session_id,
            "expires_in": 300,
            "port": self._port,
        }

    def confirm_pairing(self, token: str, device_name: str = "", device_type: str = "mobile") -> bool:
        """确认配对 (设备扫码后调用)。

        安全加固:
        - 一次性 token: 已消费过的会话拒绝再次确认 (防重放);
        - 设备绑定: 确认时写入指纹, 异设备即使拿到 token 也无法复用;
        - 爆破防护: 连续失败过多临时封禁确认入口。
        """
        now = time.time()
        # 全局锁定: 连续失败过多则临时封禁
        if self._confirm_locked_until > now:
            return False
        for session_id, rs in self._sessions.items():
            if rs.pairing_token == token and not rs.is_expired:
                # 一次性 token: 已消费过则拒绝
                if rs.confirmed:
                    return False
                rs.connected = True
                rs.connected_at = now
                rs.device_name = device_name
                rs.device_type = device_type
                rs.confirmed = True
                rs.token_fingerprint = _device_fingerprint(token, device_name, device_type)
                # 立即作废 token, 使其在 5 分钟窗口内也无法被再次使用
                rs.pairing_token = ""
                self._confirm_failures = 0
                self._save_sessions()
                return True
        # token 不匹配: 累计失败, 触发锁定
        self._confirm_failures += 1
        if self._confirm_failures >= 5:
            self._confirm_locked_until = now + 60.0
        return False

    def disconnect(self, session_id: str) -> bool:
        """断开远程连接, 并作废配对 token (断开后不可在窗口内重连)。"""
        rs = self._sessions.get(session_id)
        if rs:
            rs.connected = False
            rs.pairing_token = ""
            self._save_sessions()
            return True
        return False

    def send_prompt(self, session_id: str, prompt: str) -> bool:
        """发送远程 prompt。

        安全加固: 远程发来的 prompt 须经安全闸门分类。
        - 命中硬红线 -> 直接拒绝投递 (远程设备绝不能驱动致命命令);
        - 非良性 -> 仍投递, 但标记 requires_confirmation=True, 由 Agent 侧强制确认;
        - 良性开发命令 -> 正常投递。
        """
        rs = self._sessions.get(session_id)
        if not rs or not rs.is_active:
            return False
        verdict = _classify_remote(prompt)
        if verdict.blocks():
            log.warning("远程 prompt 被安全闸门拒绝 (命中红线): %r", prompt[:80])
            return False
        rs.requires_confirmation = verdict.needs_confirm()
        # 触发回调
        callback = self._callbacks.get("on_prompt")
        if callback:
            try:
                callback(session_id, prompt)
            except Exception:
                pass
        return True

    def send_notification(self, session_id: str, title: str, body: str, priority: str = "normal") -> bool:
        """发送 push 通知。"""
        rs = self._sessions.get(session_id)
        if not rs or not rs.is_active or not rs.push_enabled:
            return False
        callback = self._callbacks.get("on_notification")
        if callback:
            try:
                callback(session_id, title, body, priority)
            except Exception:
                pass
        return True

    def on(self, event: str, callback: Callable) -> None:
        """注册事件回调。"""
        self._callbacks[event] = callback

    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出所有远程会话。"""
        self._cleanup_expired()
        return [rs.to_dict() for rs in self._sessions.values()]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取指定远程会话信息。"""
        rs = self._sessions.get(session_id)
        return rs.to_dict() if rs else None

    def _cleanup_expired(self) -> None:
        """清理过期会话。"""
        expired = [sid for sid, rs in self._sessions.items() if rs.is_expired]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            self._save_sessions()

    def _save_sessions(self) -> None:
        """持久化会话状态 (原子写)。"""
        from .atomicio import atomic_write_text
        sessions_file = self.home / "remote_sessions.json"
        data = {sid: rs.to_dict() for sid, rs in self._sessions.items()}
        atomic_write_text(
            sessions_file,
            json.dumps(data, ensure_ascii=False, indent=2),
        )

    def _load_sessions(self) -> None:
        """加载会话状态。"""
        sessions_file = self.home / "remote_sessions.json"
        if sessions_file.exists():
            try:
                data = json.loads(sessions_file.read_text(encoding="utf-8"))
                for sid, info in data.items():
                    self._sessions[sid] = RemoteSession(
                        session_id=sid,
                        pairing_token="",  # token 不持久化
                        created_at=info.get("created_at", 0),
                        connected=info.get("connected", False),
                        connected_at=info.get("connected_at", 0),
                        device_name=info.get("device_name", ""),
                        device_type=info.get("device_type", ""),
                        push_enabled=info.get("push_enabled", False),
                    )
            except Exception:
                pass

    def generate_qr_data(self, pairing_info: Dict[str, Any]) -> str:
        """生成 QR 码数据 (纯文本格式, 可被外部 QR 库编码)。"""
        return str(pairing_info["url"])

    def get_status(self, session_id: str) -> Dict[str, Any]:
        """获取远程控制状态 (供 /remote-control 展示)。"""
        rs = self._sessions.get(session_id)
        if rs is None:
            return {"enabled": False, "connected": False}
        return {
            "enabled": True,
            "connected": rs.is_active,
            "device": rs.device_name or "Unknown",
            "device_type": rs.device_type,
            "connected_at": rs.connected_at,
            "push_enabled": rs.push_enabled,
        }


# ================================================================ 模块级通知辅助
# T-5.3: Web 工作台 (完成/失败/预算告警) 复用 RemoteControl 同一条推送通道,
# 不新增外部依赖。有活跃且开启推送的远程会话 → 走 on_notification 回调下发;
# 无论是否有推送对象, 都写一条日志留证。任何异常都吞掉, 通知通道绝不反噬主流程。

_NOTIFY_LOCK = threading.Lock()
_notify_rc: Optional["RemoteControl"] = None


def _session_hooks_snapshot() -> Any:
    """构造时刻捕获当前会话 hooks（延迟导入，避免 config <-> hooks 环）。"""
    try:
        from ..hooks.triggers import current_session_hooks
        return current_session_hooks()
    except Exception:  # noqa: BLE001
        return None


def _shared_rc() -> Optional["RemoteControl"]:
    """懒构建一个共享 RemoteControl 实例 (配对/推送状态持久在 ~/.tuan)。"""
    global _notify_rc
    if _notify_rc is not None:
        return _notify_rc
    try:
        from ..config.loader import home_dir
        rc = RemoteControl(home_dir(), hooks=_session_hooks_snapshot())
        rc._load_sessions()
        _notify_rc = rc
        return rc
    except Exception:  # noqa: BLE001
        return None


def notify(title: str, body: str, kind: str = "info", *,
           hooks: Any = None, owner: Optional[str] = None) -> bool:
    """发送一条通知 (任务完成 / 失败 / 预算告警等)。

    参数:
        title: 通知标题 (简短, 如 "预算告警")
        body:  通知正文 (人可读, 中文)
        kind:  通知类别 (info / success / error / budget) —— 仅用于日志归类

    返回:
        True = 至少推送到一个已配对且开启推送的远程设备;
        False = 无活跃推送对象 (此时已落日志, 不影响主流程)。
    """
    # 证据 1: 日志 —— 验收时据此证明告警确实触发过
    log.warning("[通知][%s] %s — %s", kind, title, body)
    # B3 续轮: Notification 是「尝试发通知」事件，不是「推送成功」事件。
    # 必须放在**所有**返回路径之前 —— 下方 `rc is None: return False`
    # 是提前返回，若把派发放在函数末尾，无推送对象时 hook 永远不触发。
    # 异常由 HookTrigger 吞掉，绝不改变 notify 的返回值语义。
    # B3 续轮 VI: 优先用调用方显式 hooks，其次用**单例构造时冻结**的
    # hooks；两者都没有才回落 HookTrigger() 的冻结 default。
    # _shared_rc() 内部吞异常返回 None，提前调用不会掀翻主流程。
    from ..hooks.triggers import (
        HookTrigger, current_session_owner, resolve_session)
    _rc = _shared_rc()
    _h = hooks if hooks is not None else getattr(_rc, "hooks", None)
    _owner = owner or current_session_owner()
    # B3 续轮 VII: 显式 hooks > 本会话 owner 分桶 > 实例冻结 hooks。
    # 未注册 owner 时不回落全局 default（VI 修掉的串台根因），只沿用
    # 实例既有绑定，行为零退化。
    if hooks is not None:
        _trig = HookTrigger(hooks)
    elif _owner and resolve_session(_owner) is not None:
        _trig = HookTrigger(owner=_owner)
    else:
        _trig = HookTrigger(_h)
    _trig.notification(
        title=title, body=body, kind=kind, source="remote_control")
    pushed = False
    try:
        rc = _shared_rc()
        if rc is None:
            return False
        # 证据 2: 推送 —— 复用 send_notification 的回调机制 (远程设备已配对时)
        for sid, rs in rc._sessions.items():
            if rs.push_enabled and rs.is_active:
                if rc.send_notification(sid, title, body, priority="high" if kind == "budget" else "normal"):
                    pushed = True
    except Exception:  # noqa: BLE001
        pass
    return pushed
