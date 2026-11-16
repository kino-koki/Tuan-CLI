"""WebServer 的运行期 mixin: 建 Agent / 取消当前轮 / 斜杠命令清单 / 启动服务。"""

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, cast
import sys
import threading

if TYPE_CHECKING:
    from .server import WebServer

from ._common import (
    _APPROVALS,
    _APPROVALS_LOCK,
    _SESSIONS,
    _SESSIONS_LOCK,
    is_loopback,
    non_loopback_warning,
)

from .handler import (
    _WebHTTPServer,
)

import logging
log = logging.getLogger(__name__)


class ServerRuntimeMixin:
    # ---- 跨 mixin 共享实例状态 (纯声明; 由 WebServer.__init__ 初始化) ----
    kernel: Any
    workspace: str
    host: str
    port: int
    model_label: str
    _cancel: Optional[threading.Event]
    _disabled_tools: set
    _httpd: Optional["_WebHTTPServer"]
    _make_agent_fn: Any
    _save_timer: Optional[threading.Timer]

    # ---- 由兄弟 mixin 提供的方法 ----
    _ask_approval: Callable[..., Any]
    _cfg: Callable[[], Any]
    mode_effort: Callable[[], Dict[str, Any]]
    save_sessions: Callable[[], Any]

    def slash_commands(self) -> List[Dict[str, str]]:
        """斜杠命令清单 (名称 + 描述), 供前端命令面板发现/补全 (与 TUI 共用同一权威清单)。"""
        try:
            from ..cli.cmd_slash import list_slash_commands, slash_command_meta
        except Exception as exc:  # noqa: BLE001
            log.debug("ServerRuntimeMixin.slash_commands(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            return []
        meta = slash_command_meta()
        out = []
        for name in list_slash_commands():
            out.append({"name": name, "desc": meta.get(name, "")})
        return out


    # ---------------- 运行 ----------------
    def make_agent(self) -> Any:
        if self._make_agent_fn is not None:
            return self._make_agent_fn()
        from ..app import create_agent

        # 注入审批回调: 危险工具在 Web 端会弹 allow/ask/deny 弹窗而非静默执行
        # exclude_tools: 面板上被关掉的工具 (热插拔)
        agent = create_agent(self.kernel, self.workspace, confirm=self._ask_approval,
                             exclude_tools=tuple(sorted(self._disabled_tools)))
        # 应用 Web 工作台内的模式/推理投入覆盖 (若有)
        me = self.mode_effort()
        try:
            if me["mode"] == "plan":
                agent.plan_mode = True
                agent.yolo = False
            elif me["mode"] == "yolo":
                agent.plan_mode = False
                agent.yolo = True
            else:
                agent.plan_mode = False
                agent.yolo = False
            if getattr(agent, "ctx", None) is not None:
                agent.ctx.plan_mode = agent.plan_mode
                agent.ctx.yolo = agent.yolo
            if me["effort"] in ("low", "medium", "high"):
                self._cfg().data.setdefault("agent", {})["effort"] = me["effort"]
        except Exception as exc:  # noqa: BLE001
            log.warning("ServerRuntimeMixin.make_agent(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        return agent


    def set_agent_factory(self, fn: Any) -> None:
        """注入 agent 工厂 (测试/外部装配用)。"""
        self._make_agent_fn = fn


    def cancel_current(self) -> None:
        ev = self._cancel
        if ev is not None:
            ev.set()
        # 挂起的审批一律按"拒绝"结算, 否则被取消的回合会一直等审批而挂住
        with _APPROVALS_LOCK:
            for rec in _APPROVALS.values():
                rec["result"] = False
                rec["event"].set()
        try:
            with _SESSIONS_LOCK:
                agents = [s.get("agent") for s in _SESSIONS.values()]
            for a in agents:
                if a is not None and hasattr(a, "cancel"):
                    a.cancel()
        except Exception as exc:  # noqa: BLE001
            log.warning("ServerRuntimeMixin.cancel_current(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass


    def serve_forever(self, banner: Optional[Callable[[str, str, str], None]] = None) -> None:
        # mixin 在运行期由 WebServer 组合, cast 仅补足静态 self 类型。
        self._httpd = _WebHTTPServer((self.host, self.port), cast("WebServer", self))
        self.port = self._httpd.server_address[1]  # 端口 0 → 实际分配
        url = f"http://{self.host}:{self.port}"
        # 非回环绑定: 接口无鉴权, 必须在控制台显著告警 (与 CLI 闸门同逻辑)。
        if not is_loopback(self.host):
            self.insecure_binding = True
            sys.stderr.write(non_loopback_warning(self.host, self.port))
            sys.stderr.flush()
        if banner is not None:
            # 嵌入场景 (TUI /web): 横幅走回调 (如 ui 桥接), 避免 print 打爆全屏界面
            banner(url, self.workspace, self.model_label)
        else:
            print(f"  青小团 Web 工作台已启动: {url}")
            print(f"  工作区: {self.workspace}  ·  模型: {self.model_label}")
            print("  按 Ctrl+C 停止服务")
        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            # 冲刷防抖定时器: 否则最后 1 秒内的消息可能没落盘
            t = self._save_timer
            if t is not None:
                t.cancel()
            self.save_sessions()
            self._httpd.server_close()
