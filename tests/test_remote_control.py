"""远程控制 (core/remote_control.py) 的专项测试。

覆盖:
- RemoteSession 数据类 (to_dict/is_expired/is_active)
- _device_fingerprint / _classify_remote 安全辅助
- RemoteControl: start_pairing / confirm_pairing (一次性 token + 爆破防护 + 设备绑定)
  / disconnect / send_prompt (安全闸门分类) / send_notification / on / list_sessions
  / get_session / get_status / generate_qr_data / 持久化
- 模块级 notify (共享实例, 推送/降级)

远程 prompt 分类用 patch 隔离 SecurityGate, 避免真实安全引擎依赖。
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from tuan_cli.core.remote_control import (
    RemoteControl,
    RemoteSession,
    _device_fingerprint,
    _classify_remote,
)


# ------------------------------------------------------------ RemoteSession

class TestRemoteSession:
    def test_to_dict(self):
        """to_dict 输出关键字段 (不含 token 明文)。"""
        rs = RemoteSession(
            session_id="s1", pairing_token="tok123", created_at=1000.0,
            connected=True, device_name="iPhone", push_enabled=True,
        )
        d = rs.to_dict()
        assert d["session_id"] == "s1"
        assert d["connected"] is True
        assert d["device_name"] == "iPhone"
        assert d["push_enabled"] is True
        assert "pairing_token" not in d  # 不泄露 token

    def test_is_expired_after_5min(self):
        """token 5 分钟后过期。"""
        rs = RemoteSession(session_id="s", pairing_token="t", created_at=time.time())
        assert not rs.is_expired
        old = RemoteSession(session_id="s", pairing_token="t",
                            created_at=time.time() - 301)
        assert old.is_expired

    def test_is_active_requires_connected(self):
        """活跃 = 已连接且未过期。"""
        active = RemoteSession(session_id="s", pairing_token="t",
                               created_at=time.time(), connected=True)
        assert active.is_active
        disconnected = RemoteSession(session_id="s", pairing_token="t",
                                     created_at=time.time(), connected=False)
        assert not disconnected.is_active
        expired = RemoteSession(session_id="s", pairing_token="t",
                                created_at=time.time() - 301, connected=True)
        assert not expired.is_active


# ------------------------------------------------------------ 安全辅助

class TestDeviceFingerprint:
    def test_deterministic(self):
        """同一输入产生同一指纹。"""
        a = _device_fingerprint("tok", "iPhone", "mobile")
        b = _device_fingerprint("tok", "iPhone", "mobile")
        assert a == b
        assert len(a) == 32

    def test_differs_on_device(self):
        """不同设备名/类型产生不同指纹。"""
        a = _device_fingerprint("tok", "iPhone", "mobile")
        b = _device_fingerprint("tok", "iPad", "tablet")
        assert a != b


class TestClassifyRemote:
    def test_deny_on_hard_redline(self):
        """命中硬红线 -> deny (blocks)。"""
        from tuan_cli.ext import security_gate
        # 让 SecurityGate.classify_remote_prompt 抛异常, 走 fallback 硬红线路径
        with patch.object(security_gate.SecurityGate, "classify_remote_prompt",
                          side_effect=RuntimeError("boom")):
            v = _classify_remote("rm -rf /")
            assert v.blocks()

    def test_exception_fallback_confirm(self):
        """分类异常且非红线 -> 保守 confirm。"""
        from tuan_cli.ext.safety_engine import is_hard_redline
        with patch("tuan_cli.ext.safety_engine.is_hard_redline", return_value=False):
            from tuan_cli.ext import security_gate
            with patch.object(security_gate.SecurityGate, "classify_remote_prompt",
                              side_effect=RuntimeError("boom")):
                v = _classify_remote("cat file.txt")
                assert not v.blocks()
                assert v.needs_confirm()


# ------------------------------------------------------------ RemoteControl 实例

@pytest.fixture
def rc(tmp_path):
    """一个隔离的 RemoteControl (临时 home)。"""
    return RemoteControl(tmp_path)


class TestStartPairing:
    def test_returns_url_token_expiry(self, rc):
        """start_pairing 返回 url/token/session/expires_in/port。"""
        info = rc.start_pairing("sess")
        assert info["session_id"] == "sess"
        assert info["token"]
        assert info["expires_in"] == 300
        assert info["url"].startswith("tuan-remote://pair?")
        assert "token=" in info["url"]
        assert "session=sess" in info["url"]

    def test_saves_session(self, rc, tmp_path):
        """start_pairing 持久化会话到 remote_sessions.json。"""
        rc.start_pairing("sess")
        assert (tmp_path / "remote_sessions.json").exists()

    def test_generate_qr_data(self, rc):
        """QR 数据 = 配对 URL。"""
        info = rc.start_pairing("sess")
        assert rc.generate_qr_data(info) == info["url"]


class TestConfirmPairing:
    def test_confirm_success(self, rc):
        """确认成功: 会话连接、token 一次性消费。"""
        info = rc.start_pairing("sess")
        assert rc.confirm_pairing(info["token"], device_name="iPhone",
                                  device_type="mobile")
        rs = rc._sessions["sess"]
        assert rs.connected is True
        assert rs.confirmed is True
        assert rs.device_name == "iPhone"
        assert rs.pairing_token == ""  # 立即作废

    def test_one_time_token_no_replay(self, rc):
        """一次性 token: 已确认的会话拒绝再次确认 (重放攻击防护)。"""
        info = rc.start_pairing("sess")
        rc.confirm_pairing(info["token"], device_name="iPhone")
        # 即使拿到同一个 token 也拒绝 (已被消费)
        assert rc.confirm_pairing(info["token"], device_name="iPhone") is False

    def test_wrong_token_fails(self, rc):
        """错误 token: 确认失败, 会话不连接。"""
        rc.start_pairing("sess")
        assert rc.confirm_pairing("wrong-token") is False
        assert rc._sessions["sess"].connected is False

    def test_expired_token_rejected(self, rc):
        """过期 token 拒绝确认。"""
        info = rc.start_pairing("sess")
        rc._sessions["sess"].created_at = time.time() - 301
        assert rc.confirm_pairing(info["token"]) is False

    def test_bruteforce_lockout(self, rc):
        """连续失败 >=5 次: 确认入口临时封禁 60s。"""
        rc.start_pairing("sess")
        for _ in range(5):
            assert rc.confirm_pairing("bad") is False
        # 第 6 次即使正确 token 也被锁
        info = rc.start_pairing("sess2")
        assert rc.confirm_pairing(info["token"]) is False
        assert rc._confirm_locked_until > time.time()


class TestDisconnect:
    def test_disconnect_voids_token(self, rc):
        """断开: connected=False 且 token 作废。"""
        info = rc.start_pairing("sess")
        rc.confirm_pairing(info["token"])
        assert rc.disconnect("sess") is True
        rs = rc._sessions["sess"]
        assert rs.connected is False
        assert rs.pairing_token == ""

    def test_disconnect_missing_false(self, rc):
        """断开不存在的会话返回 False。"""
        assert rc.disconnect("nope") is False


class TestSendPrompt:
    def test_inactive_session_rejected(self, rc):
        """未激活会话拒绝投递。"""
        rc.start_pairing("sess")  # 未确认
        assert rc.send_prompt("sess", "hello") is False

    def test_hard_redline_denied(self, rc):
        """命中红线的远程 prompt 拒绝投递。"""
        info = rc.start_pairing("sess")
        rc.confirm_pairing(info["token"])
        # patch _classify_remote 返回 deny
        from tuan_cli.ext.security_gate import GateVerdict
        with patch("tuan_cli.core.remote_control._classify_remote",
                   return_value=GateVerdict("deny", "critical", ("红线",))):
            assert rc.send_prompt("sess", "rm -rf /") is False
        assert rc._sessions["sess"].requires_confirmation is False

    def test_confirm_required_flagged(self, rc):
        """非良性 prompt: 投递但标记 requires_confirmation。"""
        info = rc.start_pairing("sess")
        rc.confirm_pairing(info["token"])
        from tuan_cli.ext.security_gate import GateVerdict
        with patch("tuan_cli.core.remote_control._classify_remote",
                   return_value=GateVerdict("confirm", "high", ("需确认",))):
            assert rc.send_prompt("sess", "dangerous cmd") is True
        assert rc._sessions["sess"].requires_confirmation is True

    def test_benign_prompt_ok(self, rc):
        """良性 prompt: 正常投递, 无需确认。"""
        info = rc.start_pairing("sess")
        rc.confirm_pairing(info["token"])
        from tuan_cli.ext.security_gate import GateVerdict
        with patch("tuan_cli.core.remote_control._classify_remote",
                   return_value=GateVerdict("allow", "low", ())):
            assert rc.send_prompt("sess", "ls") is True
        assert rc._sessions["sess"].requires_confirmation is False

    def test_callback_fired(self, rc):
        """on_prompt 回调被触发 (异常吞掉)。"""
        info = rc.start_pairing("sess")
        rc.confirm_pairing(info["token"])
        from tuan_cli.ext.security_gate import GateVerdict
        got = []
        rc.on("on_prompt", lambda sid, p: got.append((sid, p)))
        with patch("tuan_cli.core.remote_control._classify_remote",
                   return_value=GateVerdict("allow", "low", ())):
            assert rc.send_prompt("sess", "ls") is True
        assert got == [("sess", "ls")]
        # 回调抛异常不中断
        rc.on("on_prompt", lambda sid, p: 1 / 0)
        with patch("tuan_cli.core.remote_control._classify_remote",
                   return_value=GateVerdict("allow", "low", ())):
            assert rc.send_prompt("sess", "ls") is True


class TestSendNotification:
    def _active_push(self, rc):
        info = rc.start_pairing("sess")
        rc.confirm_pairing(info["token"])
        rc._sessions["sess"].push_enabled = True

    def test_inactive_fails(self, rc):
        """未激活会话不推送。"""
        assert rc.send_notification("sess", "t", "b") is False

    def test_push_disabled_fails(self, rc):
        """push_enabled=False 不推送。"""
        info = rc.start_pairing("sess")
        rc.confirm_pairing(info["token"])
        assert rc.send_notification("sess", "t", "b") is False

    def test_push_success(self, rc):
        """开启推送且激活: 触发回调。"""
        self._active_push(rc)
        got = []
        rc.on("on_notification", lambda sid, t, b, p: got.append((sid, t, b, p)))
        assert rc.send_notification("sess", "完成", "任务完成", "high") is True
        assert got == [("sess", "完成", "任务完成", "high")]

    def test_callback_error_swallowed(self, rc):
        """回调抛异常仍返回 True。"""
        self._active_push(rc)
        rc.on("on_notification", lambda *a: (_ for _ in ()).throw(RuntimeError()))
        assert rc.send_notification("sess", "t", "b") is True


class TestQuery:
    def test_list_sessions(self, rc):
        """list_sessions 返回会话列表 (含未确认)。"""
        rc.start_pairing("sess")
        sessions = rc.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "sess"
        assert sessions[0]["connected"] is False

    def test_get_session(self, rc):
        """get_session 返回指定会话或 None。"""
        assert rc.get_session("nope") is None
        rc.start_pairing("sess")
        d = rc.get_session("sess")
        assert d["session_id"] == "sess"

    def test_get_status(self, rc):
        """get_status: 未注册返回 disabled; 已确认激活返回状态。"""
        assert rc.get_status("nope") == {"enabled": False, "connected": False}
        info = rc.start_pairing("sess")
        rc.confirm_pairing(info["token"], device_name="iPhone")
        st = rc.get_status("sess")
        assert st["enabled"] is True
        assert st["connected"] is True
        assert st["device"] == "iPhone"

    def test_cleanup_expired(self, rc):
        """过期会话在 list_sessions 时被清理。"""
        rc.start_pairing("sess")
        rc._sessions["sess"].created_at = time.time() - 301
        assert rc.list_sessions() == []


class TestPersistence:
    def test_load_sessions(self, rc, tmp_path):
        """持久化后可加载 (token 不持久化)。"""
        info = rc.start_pairing("sess")
        rc.confirm_pairing(info["token"], device_name="Pixel")
        # 新实例从磁盘加载
        rc2 = RemoteControl(tmp_path)
        rc2._load_sessions()
        assert "sess" in rc2._sessions
        rs = rc2._sessions["sess"]
        assert rs.connected is True
        assert rs.device_name == "Pixel"
        assert rs.pairing_token == ""

    def test_load_corrupt_tolerated(self, rc, tmp_path):
        """损坏的 sessions 文件: 加载不抛, 会话为空。"""
        (tmp_path / "remote_sessions.json").write_text("not json", encoding="utf-8")
        rc._load_sessions()
        assert rc._sessions == {}


# ------------------------------------------------------------ 模块级 notify

class TestNotify:
    def test_no_shared_rc_returns_false(self):
        """无共享实例 (懒构建失败): 返回 False 且不抛。"""
        with patch("tuan_cli.core.remote_control._shared_rc", return_value=None):
            assert _notify_false() is False

    def test_pushes_to_active(self, tmp_path):
        """有活跃+推送会话: notify 推送并返回 True。"""
        rc = RemoteControl(tmp_path)
        info = rc.start_pairing("sess")
        rc.confirm_pairing(info["token"])
        rc._sessions["sess"].push_enabled = True
        got = []
        rc.on("on_notification", lambda *a: got.append(a))
        with patch("tuan_cli.core.remote_control._shared_rc", return_value=rc):
            assert _notify("预算告警", "budget over", "budget") is True
        assert len(got) == 1
        # 预算优先级 high
        assert got[0][3] == "high"

    def test_no_push_target_false(self, tmp_path):
        """无开启推送的会话: 返回 False。"""
        rc = RemoteControl(tmp_path)
        rc.start_pairing("sess")  # 未确认/未推送
        with patch("tuan_cli.core.remote_control._shared_rc", return_value=rc):
            assert _notify("完成", "任务完成", "info") is False


def _notify(title, body, kind):
    """薄封装: 隔离模块级 notify 的日志噪音, 直接透传。"""
    from tuan_cli.core.remote_control import notify
    return notify(title, body, kind)


def _notify_false():
    from tuan_cli.core.remote_control import notify
    return notify("t", "b", "info")
