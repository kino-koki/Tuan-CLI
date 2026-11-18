"""WebServer 的配置 mixin: 模式/推理强度/模型/密钥/设置元数据。"""

from typing import Any, Callable, Dict, List, Optional
import os
import re

from ._common import (
    _SESSIONS,
    _SESSIONS_LOCK,
    _provider_model_ids,
)

import logging
log = logging.getLogger(__name__)


class ServerConfigMixin:
    # ---- 跨 mixin 共享实例状态 (纯声明; 由 WebServer.__init__ 初始化) ----
    kernel: Any
    workspace: str
    engine_label: str
    _mode: Optional[str]
    _effort: Optional[str]

    # ---------------- 模式 / 推理投入 / 工作区信任 / git / 斜杠命令 ----------------
    def _cfg(self) -> Any:
        """取配置对象; 无 kernel 时返回 None (调用方自降级)。"""
        try:
            return self.kernel.require("config") if self.kernel is not None else None
        except Exception as exc:  # noqa: BLE001
            log.debug("ServerConfigMixin._cfg(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            return None


    def mode_effort(self) -> Dict[str, Any]:
        """当前生效模式 (standard/yolo/plan) 与推理投入 (low/medium/high)。

        优先级: Web 工作台里的手动覆盖 (self._mode) > 配置默认值。
        这是 /api/info 的 mode/effort 字段来源 —— 此前这两个字段从不下发,
        导致前端 t-mode / t-effort 两个 chip 永远是空的 (死 UI)。
        """
        cfg = self._cfg()
        if self._mode:
            mode = self._mode
        elif cfg is not None:
            try:
                mode = str(cfg.get("mode.default", "standard") or "standard")
            except Exception:  # noqa: BLE001
                mode = "standard"
        else:
            mode = "standard"
        if self._effort:
            effort = self._effort
        elif cfg is not None:
            try:
                effort = str(cfg.get("agent.effort", "high") or "high")
            except Exception:  # noqa: BLE001
                effort = "high"
        else:
            effort = "high"
        return {"mode": mode, "effort": effort}


    def apply_mode(self, mode: str) -> Dict[str, Any]:
        """设置运行模式并实时作用于当前所有会话 agent (以及后续新建的)。

        五模式体系 (感通/灵码/闲聊/无界/协同)，旧三档 standard/yolo/plan 作为别名保留。
        使用 switch_mode 执行 R1–R7 切换规则校验，同时把覆盖写回配置。
        """
        mode = str(mode or "").strip().lower()
        # 五模式 ID + 旧三档别名
        VALID_MODES = {"gantong", "lingma", "chat", "boundless", "collaboration",
                        "standard", "yolo", "plan"}
        if mode not in VALID_MODES:
            return {"ok": False, "error": f"未知模式: {mode}"}
        # 使用 switch_mode 执行 R1-R7 校验 (force=True 表示 Web 端用户显式切换)
        from ..modes.switcher import switch_mode, current_mode
        ok, reason = switch_mode(mode, force=True)
        if not ok:
            return {"ok": False, "error": reason}
        resolved = current_mode()
        self._mode = resolved
        cfg = self._cfg()
        warnings: list = []
        if cfg is not None:
            try:
                cfg.data.setdefault("mode", {})["current"] = resolved
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"持久化模式失败: {exc}")
        # 向后兼容: boundless → yolo=True, chat → plan_mode=True
        pm = resolved == "chat"
        yl = resolved == "boundless"
        with _SESSIONS_LOCK:
            for s in _SESSIONS.values():
                a = s.get("agent")
                if a is None:
                    continue
                try:
                    a.plan_mode = pm
                    a.yolo = yl
                    if getattr(a, "ctx", None) is not None:
                        a.ctx.plan_mode = pm
                        a.ctx.yolo = yl
                    if hasattr(a, "effective_tool_set"):
                        a.effective_tool_set()
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"会话 agent 模式翻转失败: {exc}")
        out = {"ok": True, "mode": resolved, "name": resolved, "reason": reason,
               **self.mode_effort()}
        if warnings:
            out["warnings"] = warnings
        return out


    def apply_effort(self, effort: str) -> Dict[str, Any]:
        """设置推理投入档位 (low/medium/high), 实时作用于配置 (agent 运行期读取)。"""
        effort = str(effort or "").strip().lower()
        if effort not in ("low", "medium", "high"):
            return {"ok": False, "error": f"未知档位: {effort}"}
        self._effort = effort
        cfg = self._cfg()
        warnings: list = []
        if cfg is not None:
            try:
                cfg.data.setdefault("agent", {})["effort"] = effort
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"持久化 effort 失败: {exc}")
        out = {"ok": True, "effort": effort, **self.mode_effort()}
        if warnings:
            out["warnings"] = warnings
        return out


    # ---------------- 设置 (对标 TUI 的 /config /model /permissions) ----------------
    # 通用标量设置: 前端据此渲染表单, 写回走 /api/config/set。
    # 字段类型: enum(下拉) / int(数字) / float(小数) / bool(开关) / list(逗号分隔文本) / string(文本)
    # min/max 与 config/validate.py 的 _RULES 同口径 —— Web 端写入前就拦住越界值,
    # 而不是等 `tuan config validate` 才报错。
    # sec 即前端左侧导航分组, 需与 frontend.py 的 SET_CATS 保持一致。
    _SETTINGS_META: List[Dict[str, Any]] = [
        # ---- 运行 ----
        {"sec": "运行", "key": "mode.default", "label": "运行模式", "type": "enum",
         "enum": ["standard", "plan", "yolo"], "hint": "plan=只读规划 / yolo=放权 / standard=默认"},
        {"sec": "运行", "key": "agent.effort", "label": "推理投入", "type": "enum",
         "enum": ["low", "medium", "high", "xhigh", "max"], "hint": "low 快省 / max 最深究"},
        {"sec": "运行", "key": "tools.exposure", "label": "工具暴露档位", "type": "enum",
         "enum": ["minimal", "standard", "full"], "hint": "传给模型的工具清单大小"},
        {"sec": "运行", "key": "agent.max_iterations", "label": "最大迭代轮数", "type": "int",
         "min": 1, "max": 200},
        {"sec": "运行", "key": "agent.max_retries", "label": "失败重试次数", "type": "int",
         "min": 0, "max": 10},
        {"sec": "运行", "key": "agent.auto_memory", "label": "自动记忆", "type": "bool"},
        {"sec": "运行", "key": "agent.show_reasoning", "label": "显示思考过程", "type": "bool"},
        {"sec": "运行", "key": "agent.personality", "label": "人设", "type": "string",
         "hint": "留空=默认; 对应 /personality set"},
        {"sec": "运行", "key": "agent.subagent_isolation", "label": "子代理隔离方式", "type": "enum",
         "enum": ["process", "thread"], "hint": "process=进程级沙箱 (推荐) / thread=线程软隔离"},
        {"sec": "运行", "key": "agent.subagent_max_workers", "label": "子代理并发上限", "type": "int",
         "min": 1, "max": 16},
        {"sec": "运行", "key": "agent.subagent_timeout", "label": "子代理超时 (秒)", "type": "int",
         "min": 5, "max": 3600},
        # ---- 模型参数 (供应商/模型本身在「模型与供应商」页签) ----
        {"sec": "模型参数", "key": "model.temperature", "label": "温度 temperature", "type": "float",
         "min": 0.0, "max": 2.0, "hint": "0=确定性 / 2=最发散"},
        {"sec": "模型参数", "key": "model.max_tokens", "label": "最大输出 tokens", "type": "int",
         "min": 1, "max": 1000000},
        {"sec": "模型参数", "key": "model.context_window", "label": "上下文窗口", "type": "int",
         "min": 0, "max": 10000000, "hint": "0=按模型名自动推断"},
        {"sec": "模型参数", "key": "model.stream", "label": "流式输出", "type": "bool"},
        {"sec": "模型参数", "key": "model.prompt_cache", "label": "提示词缓存", "type": "bool"},
        {"sec": "模型参数", "key": "model.timeout", "label": "请求超时 (秒)", "type": "int",
         "min": 1, "max": 600},
        {"sec": "模型参数", "key": "model.max_retries", "label": "API 重试次数", "type": "int",
         "min": 0, "max": 10},
        # ---- 上下文 ----
        {"sec": "上下文", "key": "context.keep_recent", "label": "保留最近消息数", "type": "int",
         "min": 1, "max": 100},
        {"sec": "上下文", "key": "context.budget_tokens", "label": "上下文预算 (tokens)", "type": "int",
         "min": 1000, "max": 2000000},
        {"sec": "上下文", "key": "context.compact_trigger", "label": "触发压缩的用量", "type": "int",
         "min": 1000, "max": 2000000},
        {"sec": "上下文", "key": "context.compact_strategy", "label": "压缩策略", "type": "enum",
         "enum": ["smart", "none"]},
        {"sec": "上下文", "key": "context.pin_codebase", "label": "固定代码库地图", "type": "bool"},
        {"sec": "上下文", "key": "context.auto_index", "label": "自动索引工作区", "type": "bool"},
        {"sec": "上下文", "key": "context.index_max_files", "label": "索引文件数上限", "type": "int",
         "min": 1, "max": 20000},
        # ---- 权限 ----
        {"sec": "权限", "key": "permissions.network.allow_domains", "label": "网络域名白名单",
         "type": "list", "hint": "逗号分隔; 空=不限制"},
        {"sec": "权限", "key": "permissions.shell.deny_patterns", "label": "Shell 拒绝模式",
         "type": "list", "hint": "逗号分隔的正则"},
        {"sec": "权限", "key": "security.network.blocked_domains", "label": "网络黑名单域名",
         "type": "list", "hint": "逗号分隔"},
        {"sec": "权限", "key": "security.network.deny_remote_exec", "label": "禁止远程执行", "type": "bool"},
        {"sec": "权限", "key": "security.network.deny_data_exfil", "label": "禁止数据外泄", "type": "bool"},
        {"sec": "权限", "key": "mode.yolo_require_confirm", "label": "yolo 仍需确认的操作",
         "type": "list", "hint": "逗号分隔的工具名; 对应 /permissions"},
        # ---- 沙箱 ----
        {"sec": "沙箱", "key": "sandbox.enabled", "label": "启用沙箱", "type": "bool"},
        {"sec": "沙箱", "key": "sandbox.backend", "label": "沙箱后端", "type": "enum",
         "enum": ["auto", "local", "docker", "landlock", "seatbelt", "jobobject"],
         "hint": "auto=按平台自动选择; local=不隔离"},
        {"sec": "沙箱", "key": "sandbox.deny_unknown_shell", "label": "拒绝未知 shell", "type": "bool"},
        {"sec": "沙箱", "key": "sandbox.enforce_required", "label": "强制必需沙箱", "type": "bool"},
        # ---- 验证与自治 ----
        {"sec": "验证与自治", "key": "verify.enabled", "label": "启用编码验证闭环", "type": "bool",
         "hint": "对应 /verify"},
        {"sec": "验证与自治", "key": "verify.auto", "label": "自动验证", "type": "bool"},
        {"sec": "验证与自治", "key": "verify.max_heal_rounds", "label": "最大自修复轮数", "type": "int",
         "min": 0, "max": 20},
        {"sec": "验证与自治", "key": "reflector.enabled", "label": "启用反思器", "type": "bool"},
        {"sec": "验证与自治", "key": "reflector.max_auto_fix", "label": "反思自动修复上限", "type": "int",
         "min": 0, "max": 20},
        {"sec": "验证与自治", "key": "loop.enabled", "label": "启用 devloop", "type": "bool"},
        {"sec": "验证与自治", "key": "loop.auto_test", "label": "devloop 自动测试", "type": "bool"},
        {"sec": "验证与自治", "key": "loop.max_iterations", "label": "devloop 最大轮数", "type": "int",
         "min": 1, "max": 200},
        {"sec": "验证与自治", "key": "goal.enabled", "label": "启用目标分解", "type": "bool",
         "hint": "对应 /goal"},
        {"sec": "验证与自治", "key": "goal.max_auto_iterations", "label": "目标自动迭代上限", "type": "int",
         "min": 1, "max": 200},
        # ---- 记忆 ----
        {"sec": "记忆", "key": "memory.fts_enabled", "label": "全文检索", "type": "bool"},
        {"sec": "记忆", "key": "memory.auto_extract", "label": "自动提取记忆", "type": "bool"},
        {"sec": "记忆", "key": "memory.recall_limit", "label": "召回条数", "type": "int",
         "min": 1, "max": 50},
        {"sec": "记忆", "key": "memory.notes_enabled", "label": "启用笔记", "type": "bool"},
        # ---- 技能与提示 ----
        {"sec": "技能与提示", "key": "skills.enabled", "label": "启用技能", "type": "bool"},
        {"sec": "技能与提示", "key": "skills.auto_inject", "label": "自动注入技能", "type": "bool"},
        {"sec": "技能与提示", "key": "skills.inject_limit", "label": "注入技能数上限", "type": "int",
         "min": 1, "max": 20},
        {"sec": "技能与提示", "key": "prompt.tier", "label": "提示词档位", "type": "enum",
         "enum": ["auto", "compact", "full"]},
        {"sec": "技能与提示", "key": "prompt.cache_stable_prefix", "label": "缓存稳定前缀", "type": "bool"},
        {"sec": "技能与提示", "key": "prompt.project_doc_max_bytes", "label": "项目文档上限 (字节)",
         "type": "int", "min": 1024, "max": 1048576},
        # ---- 网络 ----
        {"sec": "网络", "key": "network.search_engines", "label": "搜索引擎", "type": "list",
         "hint": "逗号分隔, 如 duckduckgo, bing"},
        {"sec": "网络", "key": "network.search_max_results", "label": "搜索结果上限", "type": "int",
         "min": 1, "max": 1000},
        {"sec": "网络", "key": "network.fetch_max_chars", "label": "抓取字符上限", "type": "int",
         "min": 1000, "max": 500000},
        {"sec": "网络", "key": "network.fetch_timeout", "label": "抓取超时 (秒)", "type": "int",
         "min": 1, "max": 300},
        # ---- MCP ----
        {"sec": "MCP", "key": "mcp.enabled", "label": "启用 MCP", "type": "bool",
         "hint": "服务器清单见 ~/.tuan/config.yaml 的 mcp.servers"},
        {"sec": "MCP", "key": "mcp.timeout", "label": "MCP 超时 (秒)", "type": "float",
         "min": 1.0, "max": 600.0},
        # ---- 路由 ----
        {"sec": "智能路由", "key": "router.enabled", "label": "启用智能路由", "type": "bool",
         "hint": "对应 /route"},
        {"sec": "智能路由", "key": "router.auto_switch", "label": "自动切换模型", "type": "bool"},
        {"sec": "智能路由", "key": "router.plan_execute", "label": "规划/执行分离", "type": "bool"},
        {"sec": "智能路由", "key": "router.budget_limit", "label": "预算上限 (0=不限)", "type": "float",
         "min": 0.0, "max": 100000.0},
        {"sec": "智能路由", "key": "router.escalate_on_stuck", "label": "卡住时升级模型", "type": "bool"},
        {"sec": "智能路由", "key": "router.stuck_threshold", "label": "卡住判定轮数", "type": "int",
         "min": 1, "max": 50},
        # ---- 后台 ----
        {"sec": "后台任务", "key": "background.enabled", "label": "启用后台任务", "type": "bool"},
        {"sec": "后台任务", "key": "background.max_turns", "label": "后台最大轮数", "type": "int",
         "min": 1, "max": 1000},
        {"sec": "后台任务", "key": "cron.enabled", "label": "启用定时任务", "type": "bool"},
        {"sec": "后台任务", "key": "cron.check_interval", "label": "定时检查间隔 (秒)", "type": "int",
         "min": 5, "max": 86400},
        # ---- 外观 ----
        {"sec": "外观", "key": "ui.show_token_usage", "label": "显示 token 用量", "type": "bool"},
        {"sec": "外观", "key": "ui.show_cost_report", "label": "显示花费报告", "type": "bool"},
        {"sec": "外观", "key": "ui.show_reflect_summary", "label": "显示反思摘要", "type": "bool"},
        {"sec": "外观", "key": "ui.output_style", "label": "输出风格", "type": "enum",
         "enum": ["default", "compact", "verbose"], "hint": "TUI 的输出密度"},
    ]


    @staticmethod
    def _coerce_setting(stype: str, value: Any, options: Any = None) -> Any:
        if stype == "int":
            return int(value)
        if stype == "float":
            return float(value)
        if stype == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if stype == "list":
            if isinstance(value, list):
                return [str(x).strip() for x in value if str(x).strip()]
            return [x.strip() for x in re.split(r"[,\n]", str(value)) if x.strip()]
        if stype == "enum":
            allowed = [str(o) for o in (options or [])]
            v = str(value)
            if allowed and v not in allowed:
                raise ValueError(f"可选值: {' / '.join(allowed)}")
            return v
        return value


    def config_snapshot(self) -> Dict[str, Any]:
        """当前设置快照 (值 + 元数据 + 供应商/模型清单 + 已配置的密钥情况)。"""
        cfg = self._cfg()
        values: Dict[str, Any] = {}
        for s in self._SETTINGS_META:
            values[s["key"]] = cfg.get(s["key"]) if cfg is not None else None
        providers: List[Dict[str, Any]] = []
        try:
            from ..config.loader import read_api_key
            from ..models.provider_catalog import ALL_PROVIDERS
            home = None
            try:
                from ..config.loader import home_dir
                home = home_dir()
            except Exception:  # noqa: BLE001
                home = None
            for p in ALL_PROVIDERS:
                ids = _provider_model_ids(p)
                if not ids:
                    try:
                        from ..models.provider_catalog import get_provider_models
                        ids = list(get_provider_models(p.name))
                    except Exception:  # noqa: BLE001
                        ids = []
                # 免费/付费标注 (仅用于前端在模型名旁打标签)
                tags: Dict[str, str] = {}
                for raw in list(p.recommended_models or []):
                    mid, sep, tag = str(raw).partition("|")
                    if sep and tag.strip():
                        tags[mid.strip()] = tag.strip()
                env = p.api_key_env
                key_set = bool(env and (os.environ.get(env) or read_api_key(env, home)))
                providers.append({
                    "name": p.name, "desc": p.desc, "tier": p.tier, "region": p.region,
                    "free_tier": p.free_tier, "category": p.category, "docs_url": p.docs_url,
                    "key_hint": p.key_hint, "api_key_env": env, "key_set": key_set,
                    "base_url": p.base_url, "models": ids[:80], "tags": tags,
                })
        except Exception as exc:  # noqa: BLE001
            log.warning("ServerConfigMixin.config_snapshot(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        model = {}
        if cfg is not None:
            model = {"provider": cfg.get("model.provider"), "model": cfg.get("model.model"),
                     "base_url": cfg.get("model.base_url"), "api_key_env": cfg.get("model.api_key_env")}
        return {"ok": True, "values": values, "meta": list(self._SETTINGS_META),
                "providers": providers, "model": model,
                "workspace": self.workspace, "engine": self.engine_label}


    def apply_setting(self, key: str, value: Any) -> Dict[str, Any]:
        """写入单个设置 (持久化到用户层 config.yaml, 并作用于当前会话)。"""
        meta = next((s for s in self._SETTINGS_META if s["key"] == key), None)
        if meta is None:
            return {"ok": False, "error": f"该设置项不允许在 Web 端修改: {key}"}
        cfg = self._cfg()
        if cfg is None:
            return {"ok": False, "error": "配置不可用"}
        try:
            coerced = self._coerce_setting(meta["type"], value, meta.get("enum"))
        except (ValueError, TypeError) as exc:
            return {"ok": False, "error": f"值类型错误: {exc}"}
        # 范围校验 (与 config/validate.py 同口径): 越界值直接拒, 不落盘
        lo, hi = meta.get("min"), meta.get("max")
        if isinstance(coerced, (int, float)) and not isinstance(coerced, bool):
            if lo is not None and coerced < lo:
                return {"ok": False, "error": f"取值过小: 最小 {lo}"}
            if hi is not None and coerced > hi:
                return {"ok": False, "error": f"取值过大: 最大 {hi}"}
        try:
            cfg.set_user(key, coerced)
        except Exception as exc:  # noqa: BLE001
            log.debug("ServerConfigMixin.apply_setting(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        # 副作用: 模式/推理投入需实时翻转到会话 agent
        if key == "mode.default":
            self.apply_mode(str(coerced))
        elif key == "agent.effort":
            self.apply_effort(str(coerced))
        return {"ok": True, "key": key, "value": coerced}


    def apply_model(self, provider: str, model: str, api_key: str = "",
                    base_url: str = "", api_key_env: str = "") -> Dict[str, Any]:
        """切换供应商/模型 (对标 CLI cmd_model), 可选同时写入 API Key。

        目录内供应商: 端点与密钥环境变量取预设; 目录外供应商 (自定义 OpenAI
        兼容端点, 如桌面 APP 手动录入的网关): 必须显式传 base_url, 可带
        api_key_env —— 与 cli/cmd_model.py 的自定义端点分支同一口径。
        """
        cfg = self._cfg()
        if cfg is None:
            return {"ok": False, "error": "配置不可用"}
        provider = str(provider or "").strip()
        model = str(model or "").strip()
        base_url = str(base_url or "").strip()
        api_key_env = str(api_key_env or "").strip()
        if not provider or not model:
            return {"ok": False, "error": "供应商与模型不能为空"}
        try:
            from ..models.provider_catalog import get_provider as _get_provider
            preset = _get_provider(provider)
        except Exception:  # noqa: BLE001
            preset = None
        if preset is None and not base_url:
            return {"ok": False, "error": f"未知供应商: {provider} (自定义端点需提供 base_url)"}
        # 模型名校验仅对目录内供应商生效 (剥掉 |free/|paid 标注后比对),
        # 防止把拼错的模型名写进配置, 却要到运行期发请求时才报错。
        if preset is not None:
            known = _provider_model_ids(preset)
            if known and model not in known:
                return {"ok": False, "error": f"{provider} 没有模型 {model}"}
        try:
            cfg.set_user("model.provider", provider)
            cfg.set_user("model.model", model)
            if preset is not None:
                if preset.base_url:
                    cfg.set_user("model.base_url", preset.base_url)
                if preset.api_key_env:
                    cfg.set_user("model.api_key_env", preset.api_key_env)
            else:
                cfg.set_user("model.base_url", base_url)
                cfg.set_user("model.api_key_env", api_key_env or "CUSTOM_API_KEY")
        except Exception as exc:  # noqa: BLE001
            log.debug("ServerConfigMixin.apply_model(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        env = (preset.api_key_env if preset else api_key_env) or cfg.get("model.api_key_env")
        key_note = ""
        if api_key and env:
            os.environ[env] = api_key
            try:
                from ..config.loader import persist_api_key
                persist_api_key(env, api_key)
                key_note = f"已保存密钥 {env} (本次会话 + 重启均生效)"
            except Exception as exc:  # noqa: BLE001
                key_note = f"密钥仅本次会话生效 ({exc})"
        # 关键: Agent 的 model_adapter 是内核启动时按当时 config 缓存的
        # (core/agent.py: self.model = kernel.require("model_adapter"))。只改配置
        # 不重建适配器, 密钥/端点仍是旧快照 —— 与 CLI 热切换同一模式: unprovide+provide。
        try:
            from ..models import create_adapter as _create_adapter
            kernel = getattr(self, "kernel", None)
            if kernel is not None:
                kernel.unprovide("model_adapter")
                kernel.provide("model_adapter", _create_adapter(cfg), owner="web")
                # 中途换供应商/模型: 已缓存会话的 agent 也热刷新, 立即生效
                with _SESSIONS_LOCK:
                    for s in _SESSIONS.values():
                        a = s.get("agent")
                        if a is not None and hasattr(a, "model"):
                            a.model = kernel.require("model_adapter")
        except Exception as exc:  # noqa: BLE001
            log.debug("ServerConfigMixin.apply_model(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            return {"ok": False, "error": f"适配器重建失败: {exc}"}
        # 模型是运行期按 config 解析的, 无需重建会话; 这里只把新端点回显给前端
        return {"ok": True, "model": {"provider": provider, "model": model,
                "base_url": cfg.get("model.base_url"), "api_key_env": env}, "note": key_note}


    def apply_apikey(self, env: str, key: str) -> Dict[str, Any]:
        """设置 (key 非空) 或清除 (key 空) 某个供应商的 API Key。

        审计 P1-14: env 名必须匹配 ``*_API_KEY`` 白名单形态。此前任意环境变量名
        都可写入 (实测 BASH_ENV / LD_PRELOAD / NODE_OPTIONS / PYTHONSTARTUP 全部
        ok=True), 结合 Web 面等于持久化环境变量注入 —— 影响后续所有子进程。
        """
        env = (env or "").strip()
        if not env or "=" in env or not re.fullmatch(r"[A-Z][A-Z0-9_]*_API_KEY", env):
            return {"ok": False, "error": f"非法的环境变量名 (仅允许 *_API_KEY): {env!r}"}
        try:
            from ..config.loader import persist_api_key, remove_api_key
            if key:
                os.environ[env] = key
                persist_api_key(env, key)
                return {"ok": True, "env": env, "set": True}
            os.environ.pop(env, None)
            remove_api_key(env)
            return {"ok": True, "env": env, "set": False}
        except Exception as exc:  # noqa: BLE001
            log.debug("ServerConfigMixin.apply_apikey(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
