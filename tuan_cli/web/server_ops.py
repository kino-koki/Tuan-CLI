"""WebServer 的能力面 mixin: 安全/上下文/MCP/技能/插件/子代理/截图/OCR。"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import json
import logging
import subprocess
import threading

from ._common import (
    _SESSIONS,
    _SESSIONS_LOCK,
)

log = logging.getLogger(__name__)


class ServerOpsMixin:
    # ---- 跨 mixin 共享实例状态 (纯声明; 由 WebServer.__init__ 初始化) ----
    kernel: Any
    workspace: str
    _budget_notified: Dict[str, int]
    _disabled_plugins: set
    _disabled_tools: set
    _settings: Dict[str, Any]

    # ---------------- 安全状态面板 ----------------
    def security_info(self) -> Dict[str, Any]:
        """读取安全基准存档 (bench/security-bench.json), 供前端展示。"""
        bench = Path(self.workspace or ".") / "bench" / "security-bench.json"
        try:
            if not bench.exists():
                return {"available": False}
            data = json.loads(bench.read_text(encoding="utf-8"))
            return {"available": True, "benchmark": data}
        except Exception:  # noqa: BLE001
            return {"available": False}


    # 四道闸门 (与 ToolExecutor._security_gate_check 的实际顺序一致)
    _GATES = (
        {"name": "policy", "label": "策略引擎", "desc": "用户/组织策略 deny 规则"},
        {"name": "redline", "label": "硬红线", "desc": "不可逆破坏 / 编码混淆 / 解释器内联载荷"},
        {"name": "mcp_injection", "label": "MCP 注入扫描", "desc": "外部工具返回内容中的注入指令"},
        {"name": "shell_redline", "label": "Shell 硬红线", "desc": "命令级危险形态"},
        {"name": "write_gate", "label": "文件写闸门", "desc": "写入系统关键路径 / 越界路径"},
    )


    def security_detail(self) -> Dict[str, Any]:
        """安全真实信息 —— 把引擎实际产生的东西呈现出来, 而不只是一张静态卡片。

        内容: 基准数字 + 四道闸门清单 + 近期拦截记录 (从会话历史里提取被拒的工具调用)。
        """
        info = self.security_info()
        recent: List[Dict[str, Any]] = []
        try:
            with _SESSIONS_LOCK:
                for s in _SESSIONS.values():
                    for m in (s.get("messages") or []):
                        for p in (m.get("parts") or []):
                            if p.get("type") != "tool":
                                continue
                            out = str(p.get("out") or "")
                            if ("拦截" in out or "已拒绝" in out or "denied" in out.lower()):
                                recent.append({
                                    "session": s.get("title", ""),
                                    "tool": p.get("name", ""),
                                    "args": str(p.get("args") or "")[:200],
                                    "out": out[:300],
                                })
        except Exception:  # noqa: BLE001
            pass
        return {
            "available": bool(info.get("available")),
            "benchmark": info.get("benchmark"),
            "gates": list(self._GATES),
            "recent": recent[-20:],
        }


    # ---------------- 工作区 / 上下文 / MCP ----------------
    def git_diff(self) -> str:
        """工作区 git diff (只读)。非 git 仓库或 git 缺失时返回说明文本。"""
        try:
            proc = subprocess.run(  # noqa: S603 - 固定参数, 无用户输入拼接
                ["git", "diff", "--no-color", "--stat"], cwd=self.workspace,
                capture_output=True, text=True, timeout=20, errors="replace",
            )
            stat = (proc.stdout or "").strip()
            if not stat and proc.returncode != 0:
                return (proc.stderr or "非 git 仓库").strip()[:2000]
            full = subprocess.run(  # noqa: S603
                ["git", "diff", "--no-color"], cwd=self.workspace,
                capture_output=True, text=True, timeout=30, errors="replace",
            )
            body = (full.stdout or "")[:200000]
            return (stat + "\n\n" + body).strip() if stat else body
        except FileNotFoundError:
            return "未找到 git 可执行文件"
        except subprocess.TimeoutExpired:
            return "git diff 超时"
        except Exception as exc:  # noqa: BLE001
            return f"git diff 失败: {exc}"


    def context_info(self) -> Dict[str, Any]:
        """上下文与 token 用量 (按会话统计字符数并估算 token)。

        估算口径: 混合中英文按 ~3 字符/token (CJK 约 1.5, ASCII 约 4, 折中取 3);
        这是**估算**而非精确分词, 前端会明确标注为 est.
        """
        try:
            window = int(self.kernel.require("config").get("model.context_window", 128000)) \
                if self.kernel is not None else 128000
        except Exception:  # noqa: BLE001
            window = 128000
        sessions: List[Dict[str, Any]] = []
        with _SESSIONS_LOCK:
            for s in _SESSIONS.values():
                chars = 0
                for m in (s.get("messages") or []):
                    chars += len(str(m.get("content") or ""))
                    for p in (m.get("parts") or []):
                        chars += len(str(p.get("text") or "")) + len(str(p.get("out") or ""))
                sessions.append({"id": s["id"], "title": s.get("title", ""),
                                 "messages": len(s.get("messages") or []),
                                 "chars": chars, "est_tokens": chars // 3})
        sessions.sort(key=lambda x: x["est_tokens"], reverse=True)
        return {"window": window, "sessions": sessions[:20],
                "total_est_tokens": sum(s["est_tokens"] for s in sessions)}


    # ---------------- 预算告警 (T-5.2) ----------------
    def check_budget_alert(self, session_id: str) -> None:
        """每轮对话结束后检查上下文用量, 达阈值 (默认 80%) / 用满 (100%) 各告警一次。

        阈值取自 Web UI 设置 budgetAlertPct (/api/settings 任意键), 默认 80。
        按会话档位去重: 80% 与 100% 每档只告警一次; 用量回落到阈值以下后档位复位,
        下次爬升可重新告警。推送复用 core.remote_control.notify (T-5.3, 无配对
        远程设备时仅落日志)。任何异常静默吞掉 —— 告警不能反噬对话主流程。
        """
        try:
            info = self.context_info()
            window = int(info.get("window") or 0)
            used = int(info.get("total_est_tokens") or 0)
            if window <= 0:
                return
            ratio = used / window * 100.0
            try:
                threshold = float(self._settings.get("budgetAlertPct", 80))
            except (TypeError, ValueError):
                threshold = 80.0
            if threshold <= 0:
                return
            prev = self._budget_notified.get(session_id, 0)
            # 用量明显回落 (低于阈值 10 个点) → 复位档位, 允许下轮重新告警
            if ratio < threshold - 10:
                self._budget_notified[session_id] = 0
                prev = 0
            level = 100 if ratio >= 100 else (int(threshold) if ratio >= threshold else 0)
            if level <= prev:
                return
            self._budget_notified[session_id] = level
            pct = f"{ratio:.0f}%"
            if level >= 100:
                title = "预算已用满 100%"
                body = f"上下文已用 {pct} (估算 {used}/{window} tokens), 建议开新会话或压缩历史。"
            else:
                title = f"预算告警 {pct}"
                body = f"上下文已用 {pct} (估算 {used}/{window} tokens), 超过阈值 {threshold:.0f}%。"
            # T-5.3: 复用 remote_control 推送通道 (日志落证 + 远程设备推送)
            from ..core.remote_control import notify as rc_notify
            rc_notify(title, body, kind="budget")
        except Exception:  # noqa: BLE001
            pass


    def mcp_status(self) -> List[Dict[str, Any]]:
        """已接入的 MCP server 状态。"""
        out: List[Dict[str, Any]] = []
        try:
            clients = self.kernel.get("mcp_clients") if self.kernel is not None else None
            if isinstance(clients, dict):
                for name, c in clients.items():
                    tools: List[str] = []
                    try:
                        tl = getattr(c, "tools", None)
                        if isinstance(tl, (list, tuple)):
                            tools = [getattr(t, "name", str(t)) for t in tl][:40]
                    except Exception:  # noqa: BLE001
                        pass
                    out.append({"name": str(name), "connected": True,
                                "tool_count": len(tools), "tools": tools})
            elif clients:
                out.append({"name": "mcp_clients", "connected": True, "tool_count": 0, "tools": []})
        except Exception:  # noqa: BLE001
            pass
        return out


    def mcp_toggle(self, name: str, enabled: bool) -> Dict[str, Any]:
        """热插拔某个 MCP server —— 断开/重连。"""
        try:
            clients = self.kernel.get("mcp_clients") if self.kernel is not None else None
            if clients is None or name not in clients:
                return {"ok": False, "error": f"MCP server not found: {name}"}
            c = clients[name]
            if enabled:
                connect = getattr(c, "connect", None)
                if callable(connect):
                    connect()
            else:
                disconnect = getattr(c, "disconnect", None)
                if callable(disconnect):
                    disconnect()
            return {"ok": True, "name": name, "enabled": enabled}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}


    def mcp_connect(self, name: str) -> Dict[str, Any]:
        return self.mcp_toggle(name, True)


    # ---------------- Skills 管理 ----------------
    def skills_list(self) -> List[Dict[str, Any]]:
        """列出所有已安装技能 (含用户级 + 内置仓库 + 工作区本地)。

        kernel 缺失 → 返回 [] (前端显示"无技能"); 其他异常 → log.error 并返回 [],
        让运维可观测但**不改变 API 返回类型**（前端按 list 处理）。
        """
        try:
            sm = self.kernel.require("skill_manager") if self.kernel is not None else None
            if sm is None:
                return []
            skills = sm.list_all()
            return [
                {
                    "name": s.name,
                    "slug": getattr(s, "slug", s.name.lower().replace(" ", "-")),
                    "description": s.description,
                    "origin": getattr(s, "origin", "user"),
                    "use_count": getattr(s, "use_count", 0),
                    "updated_at": getattr(s, "updated_at", None),
                    "body_preview": (s.body or "")[:300],
                }
                for s in skills
            ]
        except Exception as exc:  # noqa: BLE001
            log.error("skills_list 失败: %s", exc)
            return []


    def skill_save(self, name: str, description: str, body: str) -> Dict[str, Any]:
        if not name or not body:
            return {"ok": False, "error": "name 和 body 必填"}
        try:
            sm = self.kernel.require("skill_manager")
            sk = sm.save(name, description, body)
            return {"ok": True, "name": sk.name, "slug": getattr(sk, "slug", name)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}


    def skill_delete(self, name: str) -> Dict[str, Any]:
        try:
            sm = self.kernel.require("skill_manager")
            slug = sm.slugify(name) if hasattr(sm, "slugify") else name.lower().replace(" ", "-")
            f = Path(sm.dir) / f"{slug}.md" if hasattr(sm, "dir") else None
            if f is None or not f.exists():
                return {"ok": False, "error": f"skill 不存在: {name}"}
            f.unlink()
            return {"ok": True, "name": name}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}


    def skill_search(self, query: str, limit: int) -> List[Dict[str, Any]]:
        try:
            sm = self.kernel.require("skill_manager")
            results = sm.search(query, limit=max(1, min(limit, 20))) if hasattr(sm, "search") else []
            return [{"name": s.name, "description": s.description} for s in results]
        except Exception as exc:  # noqa: BLE001
            log.error("skill_search(%r) 失败: %s", query, exc)
            return []


    def skill_read(self, name: str) -> Dict[str, Any]:
        try:
            sm = self.kernel.require("skill_manager")
            sk = sm.load(name)
            if sk is None:
                return {"ok": False, "error": f"skill 不存在: {name}"}
            return {"ok": True, "name": sk.name, "description": sk.description, "body": sk.body,
                    "use_count": getattr(sk, "use_count", 0), "origin": getattr(sk, "origin", "user")}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}


    # ---------------- Agent Dispatch (Agent of Agents) ----------------
    def dispatch_agent(
        self, instruction: str, agent: str, skills: List[str],
        timeout: int, exclude_tools: List[str],
    ) -> Dict[str, Any]:
        """委派子 Agent 执行任务 (隔离上下文, 不污染主会话)。"""
        if not instruction.strip():
            return {"ok": False, "error": "instruction 必填"}
        timeout = max(10, min(timeout, 600))  # 10s ~ 10min
        try:
            # 与 tools/subagent_tool.py 的同步子代理路径保持同一套契约:
            #   _resolve_subagent_params -> (excluded, system_extra)
            #   create_agent(kernel, workspace, exclude_tools=..., system_extra=...)
            from ..app import create_agent
            from ..tools.subagent_tool import _resolve_subagent_params

            cfg = self.kernel.require("config")
            workspace = self.workspace or "."
            ctx = type("FakeCtx", (), {"kernel": self.kernel, "workspace": workspace})()
            excluded, system_extra = _resolve_subagent_params(
                ctx,
                instruction,
                exclude_tools=",".join(t.strip() for t in (exclude_tools or []) if t and t.strip()),
                name=agent,  # Web 参数 agent -> 子代理参数 name
            )
            if agent and not system_extra:
                return {"ok": False, "error": f"未找到命名 agent: {agent}"}

            # 创建隔离的子代理 (独立上下文, 不污染主会话)
            sub_agent = create_agent(
                self.kernel,
                workspace,
                exclude_tools=tuple(excluded),
                system_extra=system_extra,
            )

            # 预加载技能 (与子代理工具的同步路径一致)
            sm = self.kernel.get("skill_manager")
            for sname in [s.strip() for s in (skills or []) if s.strip()]:
                try:
                    skill = sm.load(sname) if sm is not None else None
                    if skill:
                        content = sm.render_for_prompt([skill], full_body=True)
                        if content:
                            sub_agent.messages.append({
                                "role": "user",
                                "content": f"[已加载技能: {sname}]\n{content}",
                            })
                            sub_agent.messages.append({
                                "role": "assistant",
                                "content": f"已加载技能 {sname}, 继续任务。",
                            })
                except Exception:  # noqa: BLE001
                    pass

            # Agent.run 没有独立 timeout 参数 → 独立线程 + 硬超时
            box: Dict[str, Any] = {}

            def _work() -> None:
                try:
                    box["answer"] = sub_agent.run(
                        instruction,
                        stream=False,
                        max_iterations=cfg.get("agent.subagent_max_iterations", 15),
                    )
                except Exception as exc:  # noqa: BLE001
                    box["error"] = f"{type(exc).__name__}: {exc}"

            th = threading.Thread(target=_work, name="web-dispatch-agent", daemon=True)
            th.start()
            th.join(timeout)
            if th.is_alive():
                return {
                    "ok": False,
                    "error": f"子代理执行超时 ({timeout}s), 请缩小任务范围或调大 timeout",
                }
            if "error" in box:
                return {"ok": False, "error": str(box["error"])}

            answer = str(box.get("answer") or "(子代理未产生输出)")
            if len(answer) > 8000:
                answer = answer[:8000] + f"\n...[摘要截断, 完整输出 {len(answer)} 字符]"
            return {"ok": True, "result": answer}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}


    # ---------------- Model Router 状态 ----------------
    def router_status(self) -> Dict[str, Any]:
        """当前模型路由配置 + 上一次路由决策。"""
        try:
            cfg = self.kernel.require("config")
            router = self.kernel.get("model_router")
            last = getattr(router, "last_route", None) if router else None
            return {
                "enabled": bool(cfg.get("router.enabled", False)),
                "auto_switch": bool(cfg.get("router.auto_switch", True)),
                "last_route": last,
                "available": router is not None,
            }
        except Exception:  # noqa: BLE001
            return {"enabled": False, "auto_switch": True, "available": False}


    # ---------------- Agent Registry ----------------
    def agents_registry_list(self) -> Dict[str, Any]:
        """CLI 外部 Agent 适配器清单 (Agent of Agents 调度目标)。

        注意: ThreadingHTTPServer 的工作线程里 asyncio.get_event_loop() 很可能
        已被主线程关闭或被其他线程占用 → 用 new_event_loop() 创建独立事件循环，
        用完立即 close()，不污染任何全局状态。
        """
        try:
            from ..agents import ADAPTERS
            import asyncio
            items = []
            loop: Optional[asyncio.AbstractEventLoop] = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                for name, adapter in ADAPTERS.items():
                    info = None
                    try:
                        info = loop.run_until_complete(adapter.detect())
                    except Exception:  # noqa: BLE001
                        info = None
                    items.append({
                        "name": name,
                        "description": getattr(adapter, "description", ""),
                        "healthy": getattr(info, "healthy", False) if info else False,
                        "score": getattr(info, "score", 0) if info else 0,
                        "version": getattr(info, "version", "") if info else "",
                    })
            finally:
                if loop is not None:
                    loop.close()
            return {"agents": items}
        except Exception as exc:  # noqa: BLE001
            return {"agents": [], "error": str(exc)}


    # ---------------- Computer Use: 截屏 + OCR ----------------
    def take_screenshot(self) -> Dict[str, Any]:
        """全屏截屏 → PNG → base64。

        可选依赖:
        - Pillow (PIL)：Windows/Linux/Mac 通用
        - mss：更轻量的跨平台截屏库
        两者都没有时返回降级提示，让 Computer Use 走 Rust 端的 shell/browser 工具链。
        """
        try:
            import base64
            png_bytes: Optional[bytes] = None
            via = ""

            # 1. 优先 Pillow.ImageGrab（最成熟，Windows/Mac 原生可用）
            try:
                from PIL import ImageGrab  # noqa: F401
                img = ImageGrab.grab(all_screens=True)
                import io
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                png_bytes = buf.getvalue()
                via = "pillow"
            except Exception:
                png_bytes = None

            # 2. mss 备选（更快，跨平台）
            if png_bytes is None:
                try:
                    import mss
                    import io
                    with mss.mss() as sct:
                        monitor = sct.monitors[0]  # 主屏
                        shot = sct.grab(monitor)
                        from PIL import Image  # noqa: F401
                        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        png_bytes = buf.getvalue()
                        via = "mss+pillow"
                except Exception:
                    png_bytes = None

            # 3. macOS 原生 screencapture 命令（如果 PIL/mss 都没）
            if png_bytes is None:
                import platform
                if platform.system() == "Darwin":
                    import tempfile
                    import subprocess
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    tmp.close()
                    subprocess.run(["screencapture", "-x", tmp.name], capture_output=True, timeout=10)
                    p = Path(tmp.name)
                    if p.exists():
                        png_bytes = p.read_bytes()
                        p.unlink(missing_ok=True)
                        via = "screencapture"

            if png_bytes is None:
                return {
                    "ok": False,
                    "error": "截屏不可用。请 pip install Pillow 或 mss。"
                            "当前可通过 shell 工具执行系统命令做间接 Computer Use。",
                    "dependency_hint": "pip install Pillow  # 跨平台；或 pip install mss pillow  # 更快",
                }

            b64 = base64.b64encode(png_bytes).decode("ascii")
            return {
                "ok": True,
                "base64": b64,
                "mime": "image/png",
                "via": via,
                "bytes": len(png_bytes),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"截屏失败: {exc}"}


    def run_ocr(self, image_b64: str) -> Dict[str, Any]:
        """OCR 文本化：把截屏 base64 转成文本描述。

        可选依赖:
        - pytesseract + Tesseract 可执行文件
        - 如果没装，也返回降级提示（让视觉模型自己看 base64 图）
        """
        try:
            import base64
            import io
            png_bytes = base64.b64decode(image_b64)
            from PIL import Image
            img = Image.open(io.BytesIO(png_bytes))

            try:
                import pytesseract
                text = pytesseract.image_to_string(img, lang="chi_sim+eng")
                return {"ok": True, "text": text.strip(), "via": "pytesseract"}
            except ImportError:
                return {
                    "ok": True,
                    "text": "",
                    "via": "ocr-not-installed",
                    "hint": "pytesseract 未安装。视觉模型可直接看 base64 图；非视觉模型可先装 pip install pytesseract 并安装 Tesseract 可执行文件。",
                }
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"OCR 失败: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"OCR 预处理失败: {exc}"}


    # ---------------- 插件 / 工具 热插拔 ----------------
    def plugins_snapshot(self) -> Dict[str, Any]:
        """可视化插件面板的数据: 工具 (按暴露分层分组) + 内核插件。

        两类都可热插拔 (无需重启、无需输命令):
          - 工具: 开关即从模型可见清单里排除/恢复 (走 Agent 的 exclude_tools);
          - 插件: 开关即调用内核的 activate / deactivate。
        """
        from ..tools.tiers import tier_of

        tools_items: List[Dict[str, Any]] = []
        try:
            reg = self.kernel.get("tool_registry") if self.kernel is not None else None
            if reg is not None:
                for t in sorted(reg.tools, key=lambda x: x.name):
                    if getattr(t, "hidden", False):
                        continue  # 隐藏别名不作为可选项 (它们只是兼容入口)
                    tools_items.append({
                        "name": t.name,
                        "desc": (t.description or "")[:160],
                        "tag": tier_of(t.name),
                        "enabled": t.name not in self._disabled_tools,
                        "locked": False,
                    })
        except Exception:  # noqa: BLE001
            pass

        plugin_items: List[Dict[str, Any]] = []
        try:
            plugins = self.kernel.plugins if self.kernel is not None else {}
            for name, p in sorted(plugins.items()):
                provides = list(getattr(p, "provides", []) or [])
                plugin_items.append({
                    "name": name,
                    "desc": f"v{getattr(p, 'version', '')} · 提供: {', '.join(provides) or '—'}",
                    "tag": f"{len(provides)} svc" if provides else "",
                    "enabled": name not in self._disabled_plugins,
                    "locked": False,
                })
        except Exception:  # noqa: BLE001
            pass

        return {"ok": True, "groups": [
            {"kind": "tool", "title": "工具", "items": tools_items},
            {"kind": "plugin", "title": "内核插件", "items": plugin_items},
        ]}


    def _unprovide_owned(self, owner: str) -> int:
        """摘掉某插件名下仍挂着的服务。

        内核里各插件的 `deactivate` 普遍只做自己的清理, 不会 unprovide 声明过的服务;
        若不兜底, 停用后再启用会直接报 `服务已被提供: xxx (by 自己)` ——
        热插拔就不可逆了。
        """
        svc = getattr(self.kernel, "services", None)
        owners = getattr(svc, "_service_owner", None)
        if not isinstance(owners, dict):
            return 0
        removed = 0
        for sname, own in list(owners.items()):
            # owner 匹配; 或 owner 缺失但服务名与插件同名 (常见约定: 插件提供同名服务)
            if own == owner or (not own and sname == owner):
                try:
                    self.kernel.unprovide(sname)
                    removed += 1
                except Exception:  # noqa: BLE001
                    pass
        return removed


    def toggle_plugin(self, kind: str, name: str, enabled: bool) -> Dict[str, Any]:
        """热插拔开关 (可逆)。返回 {ok, ...}。"""
        if kind == "tool":
            if enabled:
                self._disabled_tools.discard(name)
            else:
                self._disabled_tools.add(name)
            # 已建好的会话 agent 同步生效 (无需重建)
            try:
                with _SESSIONS_LOCK:
                    agents = [s.get("agent") for s in _SESSIONS.values()]
                for a in agents:
                    if a is not None:
                        a.exclude_tools = set(self._disabled_tools)
            except Exception:  # noqa: BLE001
                pass
            return {"ok": True, "kind": kind, "name": name, "enabled": enabled}
        if kind == "plugin":
            if self.kernel is None:
                return {"ok": False, "error": "kernel 不可用"}
            p = self.kernel.plugins.get(name)
            if p is None:
                return {"ok": False, "error": f"插件不存在: {name}"}
            try:
                if enabled:
                    # 先清掉上次停用可能残留的自有服务, 再激活 (保证可逆)
                    self._unprovide_owned(name)
                    p.activate(self.kernel)
                    self._disabled_plugins.discard(name)
                else:
                    p.deactivate(self.kernel)
                    self._unprovide_owned(name)
                    self._disabled_plugins.add(name)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"ok": True, "kind": kind, "name": name, "enabled": enabled}
        return {"ok": False, "error": f"未知类型: {kind}"}


    def git_status(self) -> Dict[str, Any]:
        """工作区 git 状态: 当前分支 + 是否有未提交改动 (供前端展示分支 chip)。

        非 git 仓库 / git 缺失时优雅降级 (branch=None, dirty=False)。
        """
        try:
            br = subprocess.run(  # noqa: S603 - 固定参数
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.workspace,
                capture_output=True, text=True, timeout=10, errors="replace",
            )
            branch: Optional[str] = (br.stdout or "").strip()
            if br.returncode != 0 or not branch:
                branch = None
            st = subprocess.run(  # noqa: S603
                ["git", "status", "--porcelain"], cwd=self.workspace,
                capture_output=True, text=True, timeout=10, errors="replace",
            )
            dirty = bool(st.stdout and st.stdout.strip())
            return {"branch": branch, "dirty": dirty, "repo": branch is not None}
        except FileNotFoundError:
            return {"branch": None, "dirty": False, "repo": False}
        except subprocess.TimeoutExpired:
            return {"branch": None, "dirty": False, "repo": False}
        except Exception:  # noqa: BLE001
            return {"branch": None, "dirty": False, "repo": False}


    def trust_status(self) -> Dict[str, Any]:
        """工作区信任状态 (对标 CLI 的 WorkspaceTrust / TUI prompt_trust)。"""
        try:
            from ..config.loader import home_dir
            from ..core.workspace_trust import WorkspaceTrust
            wt = WorkspaceTrust(home_dir())
            return wt.get_project_info(self.workspace)
        except Exception:  # noqa: BLE001
            return {"path": self.workspace, "trust_level": "unknown",
                    "needs_confirmation": True}


    def set_trust_level(self, level: str) -> Dict[str, Any]:
        """设置工作区信任级别并持久化。level ∈ trusted/limited/untrusted。"""
        level = str(level or "").strip().lower()
        if level not in ("trusted", "limited", "untrusted"):
            return {"ok": False, "error": f"未知信任级别: {level}"}
        try:
            from ..config.loader import home_dir
            from ..core.workspace_trust import WorkspaceTrust
            wt = WorkspaceTrust(home_dir())
            rec = wt.set_trust(
                self.workspace, level,
                project_name=Path(self.workspace).name if self.workspace else "",
            )
            # 同步到已存在的会话 agent ctx (若已构建)
            lvl = "trusted" if level == "trusted" else (
                "untrusted" if level == "untrusted" else "limited")
            with _SESSIONS_LOCK:
                for s in _SESSIONS.values():
                    a = s.get("agent")
                    if a is not None and getattr(a, "ctx", None) is not None:
                        try:
                            setattr(a.ctx, "workspace_trust_level", lvl)
                        except Exception:  # noqa: BLE001
                            pass
            return {"ok": True, "level": level, **self.trust_status()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
