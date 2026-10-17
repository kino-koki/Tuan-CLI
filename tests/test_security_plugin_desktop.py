"""SecurityPlugin 桌面通知默认值: 非交互/CI 场景不开桌面通知 (对标 Claude Code)。

背景: 全量测试在 Windows 上偶发死挂 —— 每个 critical 安全事件都会起一个
daemon 线程调 PowerShell toast, 批量并发把系统 toast 服务打饱和后子进程
永不退出, 告警链路自身被拖垮。修复: `security.alert.desktop` 默认值改为
跟随 `sys.stdout.isatty()` (交互式终端才默认开桌面通知); 显式配置仍可覆盖。
"""

import io

from tuan_cli.core.security_plugin import SecurityPlugin


class _FakeConfig:
    """最小 config 假件: 支持 dotted get 与 home。"""

    def __init__(self, home, overrides=None):
        self.home = home
        self._overrides = overrides or {}

    def get(self, key, default=None):
        return self._overrides.get(key, default)


class _FakeKernel:
    """最小内核假件: require/provide/get 直通字典。"""

    def __init__(self, config):
        self._config = config
        self._svc = {}

    def require(self, name):
        if name == "config":
            return self._config
        return self._svc.get(name)

    def provide(self, name, obj, owner=None):
        self._svc[name] = obj

    def get(self, name):
        return self._svc.get(name)


class _Tty:
    def isatty(self):
        return True


def _activate(home, overrides=None):
    kernel = _FakeKernel(_FakeConfig(home, overrides))
    SecurityPlugin().activate(kernel)
    return kernel.get("security_alerter")


def test_desktop_default_off_when_stdout_not_tty(tmp_path, monkeypatch):
    """非交互 (stdout 非 tty, 如 pytest/CI/重定向) → 默认不开桌面通知。"""
    monkeypatch.setattr("sys.stdout", io.StringIO())
    alerter = _activate(tmp_path)
    assert alerter is not None
    assert alerter._enable_desktop is False


def test_desktop_default_on_when_stdout_tty(tmp_path, monkeypatch):
    """交互式终端 → 默认开桌面通知。"""
    monkeypatch.setattr("sys.stdout", _Tty())
    alerter = _activate(tmp_path)
    assert alerter._enable_desktop is True


def test_desktop_explicit_config_overrides_default(tmp_path, monkeypatch):
    """显式配置 security.alert.desktop=True 覆盖非 tty 默认。"""
    monkeypatch.setattr("sys.stdout", io.StringIO())
    alerter = _activate(tmp_path, {"security.alert.desktop": True})
    assert alerter._enable_desktop is True


def test_desktop_explicit_false_keeps_off(tmp_path, monkeypatch):
    """显式配置 False 在 tty 下也保持关闭。"""
    monkeypatch.setattr("sys.stdout", _Tty())
    alerter = _activate(tmp_path, {"security.alert.desktop": False})
    assert alerter._enable_desktop is False
