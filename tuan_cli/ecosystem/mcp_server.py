"""MCP Server —— 把 tuan 的能力以 MCP (Model Context Protocol) 暴露给外部 Agent。

这是「青小团被 Claude Code / Hermes 直接使用」的关键通道:

- Claude Code:  项目 ``.mcp.json`` 声明 ``tuan ecosystem serve`` 后, Claude Code 会话
  里直接多出一组 ``tuan_*`` 工具 (记忆检索/写入、技能清单/读取、Agent 清单、
  生态盘点、headless 任务派发), 且全部走 tuan 自己的安全口径。
- Hermes Agent: ``hermes config set mcp.servers.tuan ...`` 指向同一命令即可。

协议实现 (零依赖, 纯标准库): MCP stdio 传输 = **JSON-RPC 2.0 换行帧**
(每行一个 JSON 对象, ``\\n`` 结尾)。实现 ``initialize`` / ``notifications/initialized`` /
``tools/list`` / ``tools/call`` / ``ping`` —— 与 ``runtime/mcp/client_stdio.py``
(本项目自研 MCP 客户端) 同构, 客户端/服务端共用同一行帧语义。

安全口径 (fail-closed):
- 默认只暴露**只读/受控**工具: 记忆/技能/Agent 清单、生态盘点、tuan_run (headless
  任务, 内部仍走完整四道闸);
- ``run_shell`` 等危险工具**默认不暴露**, 需显式 ``ecosystem.mcp.allow_dangerous_tools=true``;
- 所有工具输出截断到上限, 防止把海量内容灌进外部 Agent 上下文。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import __version__ as _eco_version

import logging
log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "tuan_cli-ecosystem"
MAX_OUTPUT_CHARS = 4000          # 单工具文本输出上限 (防上下文膨胀)
MAX_TOOL_DESC = 800              # 工具描述长度上限 (防提示词注入)
RUN_TIMEOUT = 300                # tuan_run 子进程超时 (秒)


def _tool(name: str, description: str, schema: Dict[str, Any],
          handler: Callable[[Dict[str, Any]], Tuple[str, bool]]) -> Dict[str, Any]:
    """构造 MCP 工具定义 (描述截断, 防注入)。"""
    return {
        "name": name,
        "description": description[:MAX_TOOL_DESC],
        "inputSchema": schema,
        "_handler": handler,
    }


def _ok(text: str) -> Tuple[str, bool]:
    return text[:MAX_OUTPUT_CHARS], False


def _err(text: str) -> Tuple[str, bool]:
    return text[:MAX_OUTPUT_CHARS], True


def _prop(desc: str, ptype: str = "string", default: Any = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"type": ptype, "description": desc}
    if default is not None:
        out["default"] = default
    return out


class McpToolServer:
    """MCP stdio 服务端: 纯逻辑可测, ``handle_line`` 喂一行 JSON-RPC 返回响应行。

    home:      tuan 主目录 (~/.tuan 或 TUAN_HOME) —— 记忆/技能都从这读。
    workspace: 当前项目目录 (context_files / 生态探测用)。
    config:    带 ``get("a.b", default)`` 的配置对象 (缺省按默认值)。
    """

    def __init__(
        self,
        home: Path,
        workspace: Optional[Path] = None,
        config: Any = None,
        *,
        allow_dangerous_tools: Optional[bool] = None,
    ) -> None:
        self.home = Path(home)
        self.workspace = Path(workspace) if workspace else None
        self._config = config
        if allow_dangerous_tools is None:
            allow_dangerous_tools = bool(
                self._cfg("ecosystem.mcp.allow_dangerous_tools", False)
            )
        self.allow_dangerous_tools = allow_dangerous_tools
        self._req_id: Optional[int] = None
        self._session_id = 0
        self._tools = self._build_tools()

    def _cfg(self, key: str, default: Any = None) -> Any:
        if self._config is not None and hasattr(self._config, "get"):
            try:
                return self._config.get(key, default)
            except Exception as exc:  # noqa: BLE001
                log.debug("McpToolServer._cfg(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                return default
        return default

    # ------------------------------------------------------------ 工具清单

    def _build_tools(self) -> List[Dict[str, Any]]:
        tools: List[Dict[str, Any]] = []

        tools.append(_tool(
            "tuan_status",
            "青小团生态桥接状态: 版本、Claude Code/Hermes 探测结果与资产计数 (JSON)",
            {"type": "object", "properties": {}},
            self._h_status,
        ))
        tools.append(_tool(
            "tuan_run",
            "把任务派发给青小团 headless 执行 (tuan run)。任务在 tuan 内走完整四道闸安全引擎, "
            "返回最终答复。适合需要文件读写/记忆/技能/多步推理的重活。",
            {
                "type": "object",
                "properties": {
                    "task": _prop("要执行的任务描述 (自然语言, 尽量具体)"),
                    "timeout": _prop("超时秒数 (默认 300)", "integer", 300),
                },
                "required": ["task"],
            },
            self._h_run,
        ))
        tools.append(_tool(
            "memory_search",
            "检索青小团跨会话记忆 (FTS5 全文, 含 Hermes 导入的记忆)。返回命中条目与来源。",
            {
                "type": "object",
                "properties": {
                    "query": _prop("检索关键词"),
                    "limit": _prop("最多返回条数 (默认 5)", "integer", 5),
                },
                "required": ["query"],
            },
            self._h_memory_search,
        ))
        tools.append(_tool(
            "memory_write",
            "往青小团长期记忆写一条事实 (偏好/约定/结论)。可与 Hermes MEMORY.md 双向同步。",
            {
                "type": "object",
                "properties": {
                    "fact": _prop("要记住的事实, 一句话"),
                    "section": _prop("分类: user/feedback/project/reference, 默认 reference"),
                },
                "required": ["fact"],
            },
            self._h_memory_write,
        ))
        tools.append(_tool(
            "skill_list",
            "列出青小团可用的技能 (原生 + 从 Claude Code/Hermes 导入), 含名称/描述/来源。",
            {"type": "object", "properties": {}},
            self._h_skill_list,
        ))
        tools.append(_tool(
            "skill_read",
            "读取某个技能的完整 SKILL.md 正文 (按 slug 或名称)。",
            {
                "type": "object",
                "properties": {"name": _prop("技能 slug 或名称")},
                "required": ["name"],
            },
            self._h_skill_read,
        ))
        tools.append(_tool(
            "agent_list",
            "列出青小团可用的命名 Agent (含从 .claude/agents 发现的 Claude Code 子代理)。",
            {"type": "object", "properties": {}},
            self._h_agent_list,
        ))
        tools.append(_tool(
            "context_files",
            "读取当前项目上下文文件 (TUAN.md / AGENTS.md / CLAUDE.md) 与 SOUL.md 的存在情况。",
            {"type": "object", "properties": {}},
            self._h_context_files,
        ))
        # ---- 阶段 4: 动画/视频工具 (对齐最新开源卖点: 代码制作动画视频) ----
        tools.append(_tool(
            "codeanim_render",
            "把 code-animation 项目 JSON 渲染为 mp4 视频 (纯 Python Pillow + ffmpeg, 零外部模型)。"
            "project_json 需含 width/height/fps/duration/nodes; 未知节点类型跳过 (fail-closed)。"
            "输出写入 workspace 的 media 目录, 返回文件路径与帧数。",
            {
                "type": "object",
                "properties": {
                    "project_json": _prop("渲染项目对象 (含 width/height/fps/duration/nodes)"),
                    "fps": _prop("帧率 (默认取 project_json.fps, 缺省 30)", "integer"),
                },
                "required": ["project_json"],
            },
            self._h_codeanim_render,
        ))
        tools.append(_tool(
            "codeanim_frame",
            "渲染 code-animation 项目在时间 t 的单帧为 PNG (快速预览, 不出视频)。",
            {
                "type": "object",
                "properties": {
                    "project_json": _prop("渲染项目对象"),
                    "t": _prop("时间点秒 (默认 0)", "number"),
                },
                "required": ["project_json"],
            },
            self._h_codeanim_frame,
        ))
        # ---- 阶段 6: 多模型网关直调 (外部 Agent 直接调 tuan 模型层做自动化视频) ----
        tools.append(_tool(
            "llm_call",
            "通过青小团多模型网关 (ModelGateway) 调用任意已配置 Provider 生成文本。"
            "支持 intent 意图路由 / 指定 provider_id (如 'deepseek:deepseek-chat') / "
            "json_schema 结构化输出 (返回 JSON)。解析失败或 provider 未配置一律 fail-closed 报错。",
            {
                "type": "object",
                "properties": {
                    "prompt": _prop("用户提示 (必填)"),
                    "system_prompt": _prop("系统提示 (可选)"),
                    "intent": _prop("意图路由名 (可选, 如 plan/script/compose; 未注册则拒绝)"),
                    "provider_id": _prop("provider_id (可选, 如 'deepseek:deepseek-chat'; 缺省用激活 provider)"),
                    "json_schema": _prop("期望的结构化输出 JSON Schema (可选, dict)"),
                    "max_tokens": _prop("最大生成 token (可选, 默认 8192)", "integer"),
                    "temperature": _prop("采样温度 (可选, 默认 0.7)", "number"),
                },
                "required": ["prompt"],
            },
            self._h_llm_call,
        ))
        tools.append(_tool(
            "models_list",
            "列出青小团模型目录中已知的 Provider (名称/base_url/档位/免费额度/地区/推荐模型)。"
            "不含密钥, 仅元数据, 供外部 Agent 选型。",
            {"type": "object", "properties": {}},
            self._h_models_list,
        ))
        tools.append(_tool(
            "video_pipeline_run",
            "OpenMontage 式 9 阶段自动化视频流水线: brief→research→script→scene→gate→"
            "narration→music→compose→render。用 ModelGateway 按 intent 串联多模型, "
            "质量闸门 (gate) 未通过或任一段失败一律 fail-closed 报错。"
            "默认走 code_anim_render 出 mp4 (ffmpeg 可用时); 否则 rendered=false+reason。"
            "可注入 stages 子集 (如 ['brief','compose','render'])。",
            {
                "type": "object",
                "properties": {
                    "brief": _prop("创作 brief (必填)"),
                    "out_path": _prop("输出 mp4 路径 (可选, 默认 workspace/media/pipeline_<ts>.mp4)"),
                    "stages": _prop("阶段子集 (可选 list, 默认全 9 阶段)"),
                },
                "required": ["brief"],
            },
            self._h_video_pipeline_run,
        ))
        tools.append(_tool(
            "narration_tts",
            "多语言叙事 TTS: 把旁白文本合成 WAV 音频轨, 供视频流水线混音。"
            "自动探测 edge-tts / pyttsx3, 兜底内置确定性 WAV 合成器 (零外部依赖, 帧稳定)。"
            "输出写入 workspace/media/narration_<ts>.wav; 返回 {path,duration,engine,lang}。"
            "文本为空 → fail-closed 报错。",
            {
                "type": "object",
                "properties": {
                    "text": _prop("旁白文本 (必填)"),
                    "lang": _prop("语言 (可选, 默认 zh; 影响音节切分)"),
                    "voice": _prop("音色 (可选, 仅外部引擎用)"),
                    "engine": _prop("引擎 (可选: auto/synth, 默认 auto)"),
                    "out_path": _prop("输出 wav 路径 (可选, 默认 workspace/media/narration_<ts>.wav)"),
                },
                "required": ["text"],
            },
            self._h_narration_tts,
        ))
        if self.allow_dangerous_tools:
            tools.append(_tool(
                "run_shell",
                "[危险] 在青小团侧执行 shell 命令。仅在 "
                "ecosystem.mcp.allow_dangerous_tools=true 时暴露。经文本红线 + "
                "统一四层滤网裁决, 子进程拿脱敏 env (真实密钥不进入)。"
                "边界: 本通道是同步裸执行, 没有 OS 级隔离 / 逐命令域名强绑定 / "
                "副本确认; 凡裁决要求隔离、需人工确认、DENY 或出网合规拒绝的命令"
                "一律 fail-closed 拒绝。重活请改用 tuan_run。",
                {
                    "type": "object",
                    "properties": {"command": _prop("要执行的 shell 命令")},
                    "required": ["command"],
                },
                self._h_run_shell,
            ))
        return tools

    # ------------------------------------------------------------ 处理器

    def _h_status(self, _: Dict[str, Any]) -> Tuple[str, bool]:
        from .detect import EcosystemProbe

        probe = EcosystemProbe.probe(
            str(self.workspace) if self.workspace else None,
        )
        summary = probe.summarize()
        payload = {
            "server": SERVER_NAME,
            "version": _eco_version,
            "claude_code": {
                "cli": probe.claude_cli or "",
                "assets": summary["claude_code"].to_dict(),
            },
            "hermes": {
                "home": str(probe.hermes_home) if probe.hermes_home else "",
                "assets": summary["hermes"].to_dict(),
            },
        }
        return _ok(json.dumps(payload, ensure_ascii=False))

    def _h_run(self, args: Dict[str, Any]) -> Tuple[str, bool]:
        import subprocess

        task = str(args.get("task", "")).strip()
        if not task:
            return _err("task 不能为空")
        timeout = min(int(args.get("timeout", RUN_TIMEOUT) or RUN_TIMEOUT), 600)
        python = sys.executable
        try:
            proc = subprocess.run(
                [python, "-m", "tuan_cli", "run", "--print", task],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _err(f"tuan run 超时 ({timeout}s)")
        except OSError as exc:
            return _err(f"启动 tuan run 失败: {exc}")
        out = (proc.stdout or "").strip()
        if proc.returncode != 0:
            return _err(f"tuan run 退出码 {proc.returncode}: {out or proc.stderr or ''}")
        return _ok(out or "(无输出)")

    def _h_memory_search(self, args: Dict[str, Any]) -> Tuple[str, bool]:
        from ..memory.store import MemoryStore

        store = MemoryStore(self.home, fts_enabled=True)
        try:
            hits = store.search(str(args.get("query", "")), limit=int(args.get("limit", 5)))
        except Exception as exc:  # noqa: BLE001
            return _err(f"记忆检索失败: {exc}")
        if not hits:
            return _ok("没有找到相关记忆。")
        lines = [f"- [{h.get('kind','?')}] {str(h.get('content',''))[:300]} (来源: {h.get('source','')})"
                 for h in hits]
        return _ok("\n".join(lines))

    def _h_memory_write(self, args: Dict[str, Any]) -> Tuple[str, bool]:
        from ..memory.store import MemoryStore

        fact = str(args.get("fact", "")).strip()
        if not fact:
            return _err("fact 不能为空")
        section = str(args.get("section", "reference") or "reference")
        store = MemoryStore(self.home, fts_enabled=True)
        try:
            line = store.append_memory(fact, section=section)
        except Exception as exc:  # noqa: BLE001
            return _err(f"写入记忆失败: {exc}")
        return _ok(f"已写入: {line}")

    def _h_skill_list(self, _: Dict[str, Any]) -> Tuple[str, bool]:
        from ..skills.manager import SkillManager

        try:
            manager = SkillManager(self.home)
            skills = manager.list_all()
        except Exception as exc:  # noqa: BLE001
            return _err(f"读取技能失败: {exc}")
        if not skills:
            return _ok("(暂无技能)")
        lines = [f"- **{s.name}** ({s.slug}) [{s.origin}] {s.description[:80]}" for s in skills]
        return _ok("\n".join(lines))

    def _h_skill_read(self, args: Dict[str, Any]) -> Tuple[str, bool]:
        from ..skills.manager import SkillManager

        name = str(args.get("name", "")).strip()
        if not name:
            return _err("name 不能为空")
        try:
            manager = SkillManager(self.home)
            skill = manager.load(name)
        except Exception as exc:  # noqa: BLE001
            return _err(f"读取技能失败: {exc}")
        if skill is None:
            return _err(f"未找到技能: {name}")
        head = f"# {skill.name}\n{skill.description}\n"
        return _ok(head + skill.body)

    def _h_agent_list(self, _: Dict[str, Any]) -> Tuple[str, bool]:
        from ..core.agents_registry import discover_agents, format_agent_list

        try:
            agents = discover_agents(
                str(self.workspace) if self.workspace else None,
                str(self.home),
            )
        except Exception as exc:  # noqa: BLE001
            return _err(f"读取 Agent 失败: {exc}")
        return _ok(format_agent_list(agents))

    def _h_context_files(self, _: Dict[str, Any]) -> Tuple[str, bool]:
        parts = []
        for name in ("TUAN.md", "QXT.md", "AGENTS.md", "CLAUDE.md", ".tuan.md"):
            for base in ([self.workspace] if self.workspace else []) + [self.home]:
                if base is None:
                    continue
                f = base / name
                if f.exists():
                    try:
                        text = f.read_text(encoding="utf-8", errors="replace")
                        parts.append(f"== {f} ({len(text)} 字符) ==\n{text[:1500]}")
                    except OSError as exc:
                        parts.append(f"== {f} == 读取失败: {exc}")
                    break
        soul = self.home / "SOUL.md"
        parts.append(f"== SOUL.md == {'存在 (' + str(soul.stat().st_size) + ' 字节)' if soul.exists() else '未配置'}")
        return _ok("\n\n".join(parts) or "(无上下文文件)")

    def _h_codeanim_render(self, args: Dict[str, Any]) -> Tuple[str, bool]:
        """渲染 code-animation 项目 JSON → mp4 (写入 workspace/media)。"""
        import tempfile

        from ..web import code_anim_render as car

        pj = args.get("project_json")
        if not isinstance(pj, dict):
            return _err("project_json 必须是 JSON 对象 (fail-closed)")
        err = car.validate_project(pj)
        if err:
            return _err(f"project_json 非法: {err} (fail-closed)")
        fps = int(args.get("fps") or pj.get("fps") or 30)
        if fps <= 0:
            return _err("fps 必须 > 0")
        # 输出目录: workspace/media (缺省用系统临时目录)
        base = self.workspace if self.workspace else Path(tempfile.gettempdir())
        media = base / "media"
        try:
            media.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _err(f"创建 media 目录失败: {exc}")
        out_path = media / f"codeanim_{int(__import__('time').time() * 1000)}.mp4"
        try:
            result = car.render_video(pj, str(out_path), fps=fps,
                                      workspace=str(self.workspace) if self.workspace else None)
        except RuntimeError as exc:
            return _err(f"渲染失败: {exc}")
        except Exception as exc:  # noqa: BLE001
            return _err(f"渲染异常: {exc}")
        payload = {
            "out_path": str(out_path),
            "frames": result.get("frames", 0),
            "fps": result.get("fps", fps),
            "size_bytes": result.get("size_bytes", 0),
            "elapsed": result.get("elapsed", 0),
        }
        return _ok(json.dumps(payload, ensure_ascii=False))

    def _h_codeanim_frame(self, args: Dict[str, Any]) -> Tuple[str, bool]:
        """渲染 code-animation 项目在时间 t 的单帧为 PNG (快速预览)。"""
        import base64
        import io
        import tempfile

        from ..web import code_anim_render as car

        pj = args.get("project_json")
        if not isinstance(pj, dict):
            return _err("project_json 必须是 JSON 对象 (fail-closed)")
        err = car.validate_project(pj)
        if err:
            return _err(f"project_json 非法: {err} (fail-closed)")
        t = float(args.get("t") or 0.0)
        try:
            img = car.draw_frame(pj, t)
        except Exception as exc:  # noqa: BLE001
            return _err(f"帧渲染异常: {exc}")
        # 编码 PNG, 返回 data URL + 尺寸 (可写文件供外部取用)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        # 同时落盘 (供下载)
        base = self.workspace if self.workspace else Path(tempfile.gettempdir())
        media = base / "media"
        try:
            media.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        out_path = media / f"codeanim_{int(__import__('time').time() * 1000)}.png"
        try:
            img.save(str(out_path), format="PNG")
            saved = str(out_path)
        except OSError:
            saved = ""
        payload = {
            "width": img.width,
            "height": img.height,
            "png_data_url": f"data:image/png;base64,{b64}",
            "saved_path": saved,
        }
        return _ok(json.dumps(payload, ensure_ascii=False))

    def _h_llm_call(self, args: Dict[str, Any]) -> Tuple[str, bool]:
        """阶段 6: 通过 ModelGateway 直调模型 (intent 路由 / provider_id / json_schema)。"""
        from ..runtime.gateway import ModelGateway

        prompt = str(args.get("prompt", "")).strip()
        if not prompt:
            return _err("prompt 不能为空 (fail-closed)")
        system_prompt = args.get("system_prompt")
        if system_prompt is not None:
            system_prompt = str(system_prompt)
        intent = args.get("intent")
        if intent is not None:
            intent = str(intent) or None
        provider_id = args.get("provider_id")
        if provider_id is not None:
            provider_id = str(provider_id) or None
        json_schema = args.get("json_schema")
        if json_schema is not None and not isinstance(json_schema, dict):
            return _err("json_schema 必须是 JSON 对象 (fail-closed)")
        max_tokens = args.get("max_tokens")
        if max_tokens is not None:
            max_tokens = int(max_tokens)
        temperature = args.get("temperature")
        if temperature is not None:
            temperature = float(temperature)

        gw = ModelGateway()
        try:
            result = gw.generate(
                prompt,
                system_prompt=system_prompt,
                intent=intent,
                provider_id=provider_id,
                json_schema=json_schema,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except ValueError as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _err(f"LLM 调用异常: {exc}")
        payload = {
            "provider_id": result.get("provider_id"),
            "model": result.get("model"),
            "text": (result.get("text") or "")[:MAX_OUTPUT_CHARS],
            "json": result.get("json"),
            "tool_calls": result.get("tool_calls") or [],
        }
        return _ok(json.dumps(payload, ensure_ascii=False))

    def _h_models_list(self, _: Dict[str, Any]) -> Tuple[str, bool]:
        """阶段 6: 列出模型目录已知 Provider 元数据 (不含密钥, 紧凑行防超上限截断)。"""
        try:
            from ..models.provider_catalog import ALL_PROVIDERS
        except Exception as exc:  # noqa: BLE001
            return _err(f"读取模型目录失败: {exc}")
        # 先满字段; 若 JSON 超出 MAX_OUTPUT_CHARS 则逐级降字段 (截断会破坏 JSON, 必须避免)。
        full = [
            {
                "name": p.name, "model": p.model, "tier": p.tier,
                "free_tier": bool(p.free_tier), "region": p.region,
                "category": p.category,
                "recommended_models": list(p.recommended_models),
                "docs_url": p.docs_url,
            }
            for p in ALL_PROVIDERS
        ]
        candidates = [
            full,
            [{k: v for k, v in r.items() if k not in ("docs_url", "category")} for r in full],
            [{k: v for k, v in r.items() if k not in ("docs_url", "category", "recommended_models")}
             for r in full],
        ]
        for rows in candidates:
            text = json.dumps({"providers": rows}, ensure_ascii=False)
            if len(text) <= MAX_OUTPUT_CHARS:
                return _ok(text)
        # 兜底: 仅核心字段; 若仍超上限则截断条目数并标记 (保证 JSON 完整合法)。
        minimal = [
            {"name": p.name, "model": p.model, "tier": p.tier,
             "free_tier": bool(p.free_tier), "region": p.region}
            for p in ALL_PROVIDERS
        ]
        rows: List[Dict[str, Any]] = minimal
        text = json.dumps({"providers": rows}, ensure_ascii=False)
        if len(text) > MAX_OUTPUT_CHARS:
            # 逐条剔除尾部直到 JSON 落回上限内
            while rows and len(json.dumps({"providers": rows}, ensure_ascii=False)) > MAX_OUTPUT_CHARS:
                rows = rows[:-1]
            text = json.dumps({"providers": rows, "truncated": True}, ensure_ascii=False)
        return _ok(text)

    def _h_video_pipeline_run(self, args: Dict[str, Any]) -> Tuple[str, bool]:
        """阶段 10: OpenMontage 式 9 阶段视频流水线 (fail-closed)。"""
        from ..web.video_pipeline import VideoPipeline, STAGE_NAMES

        brief = str(args.get("brief", "")).strip()
        if not brief:
            return _err("brief 不能为空 (fail-closed)")
        stages = args.get("stages")
        if stages is not None:
            if not isinstance(stages, list) or not all(isinstance(s, str) for s in stages):
                return _err("stages 必须是字符串数组 (fail-closed)")
            unknown = [s for s in stages if s not in STAGE_NAMES]
            if unknown:
                return _err(f"未知流水线阶段: {unknown} (fail-closed)")
        out_path = args.get("out_path")
        if out_path is None:
            import time as _t
            base = Path(self.workspace or ".") / "media"
            base.mkdir(parents=True, exist_ok=True)
            out_path = str(base / f"pipeline_{int(_t.time() * 1000)}.mp4")
        else:
            out_path = str(out_path)
            # 审计 P1-13: 同 narration_tts —— 输出路径必须落在工作区内。
            try:
                ws_root = Path(self.workspace or ".").resolve()
                resolved = Path(out_path).resolve()
                resolved.relative_to(ws_root)
            except (ValueError, OSError):
                return _err("out_path 越界: 必须位于工作区内 (fail-closed)")
            out_path = str(resolved)
        try:
            pipe = VideoPipeline(stages=list(stages) if stages else None)
            result = pipe.run(brief, out_path=out_path)
        except ValueError as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _err(f"流水线异常: {exc}")
        payload = {
            "brief": result["brief"],
            "rendered": result["rendered"],
            "out_path": result.get("out_path"),
            "frames": result.get("frames"),
            "stages": list(result["stages"].keys()),
        }
        return _ok(json.dumps(payload, ensure_ascii=False))

    def _h_narration_tts(self, args: Dict[str, Any]) -> Tuple[str, bool]:
        """阶段 12: 多语言叙事 TTS (fail-closed)。"""
        from ..web.narration_tts import synthesize_narration

        text = str(args.get("text", "")).strip()
        if not text:
            return _err("text 不能为空 (fail-closed)")
        lang = str(args.get("lang") or "zh")
        voice = str(args.get("voice") or "")
        engine = str(args.get("engine") or "auto")
        out_path = args.get("out_path")
        if out_path is None:
            import time as _t
            base = Path(self.workspace or ".") / "media"
            base.mkdir(parents=True, exist_ok=True)
            out_path = str(base / f"narration_{int(_t.time() * 1000)}.wav")
        else:
            out_path = str(out_path)
            # 审计 P1-12: out_path 必须落在工作区内 (resolve + relative_to),
            # 否则外部 Agent 可把 TTS 输出写到工作区外的任意路径。
            try:
                ws_root = Path(self.workspace or ".").resolve()
                resolved = Path(out_path).resolve()
                resolved.relative_to(ws_root)
            except (ValueError, OSError):
                return _err("out_path 越界: 必须位于工作区内 (fail-closed)")
            out_path = str(resolved)
        try:
            res = synthesize_narration(text, out_path, voice=voice,
                                       lang=lang, engine=engine)
        except ValueError as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _err(f"TTS 异常: {exc}")
        return _ok(json.dumps({
            "path": res["path"],
            "duration": res["duration"],
            "engine": res["engine"],
            "lang": res.get("lang", lang),
        }, ensure_ascii=False))

    def _h_run_shell(self, args: Dict[str, Any]) -> Tuple[str, bool]:
        """[危险] 对外 MCP 通道执行 shell 命令。

        **本轮实测缺口（先复现再修）**：这是全仓唯一一处「外部 Agent 直接
        提供 command、用 ``shell=True`` 执行」的入口，却完全绕过了前十几轮
        建好的整套闸门：

        1. 只做 ``is_hard_redline`` / ``is_redline`` **文本判定**，不经过
           ``SandboxManager.assess_command`` / ``plan_egress`` —— 深度轮
           fuzz 已证明零宽字符 / ANSI-C / 注释换行能绕过文本层；
        2. ``subprocess.run`` **不传 env**，后台子进程继承父进程完整环境，
           实测 ``GITHUB_TOKEN=ghp_REAL_SECRET_VALUE`` 原样进入子进程，
           与 §13/§15 刚落地的「子进程不持密钥」直接矛盾；
        3. 异常分支把 ``str(exc)`` 原样回显给外部 Agent，实测真实密钥串
           与 OSC / RLO 控制字符都会外泄。

        **修复（如实，不夸大）**：把四层滤网裁决 + ``plan_egress`` 的
        脱敏 env 真正接到这个入口；但 MCP 是同步 ``subprocess.run``，
        **做不到** OS 级隔离 / copy-diff-apply 确认 / 回环出网代理，
        所以凡是需要这些能力的命令一律 fail-closed 拒绝，绝不假装已隔离。
        """
        import os
        import subprocess

        from ..core.security_utils import safe_error_text, safe_exception_text
        from ..ext.safety_engine import (
            SafetyEngine,
            is_hard_redline,
            is_redline,
        )
        from ..sandbox.egress_plan import plan_egress
        from ..sandbox.manager import SandboxManager
        from ..sandbox.verdict import Action

        command = str(args.get("command", "")).strip()
        if not command:
            return _err("command 不能为空")
        try:
            hard = is_hard_redline(command)
            risk = is_redline(command)
        except Exception as exc:  # noqa: BLE001
            return _err(f"安全判定失败 (fail-closed): {safe_exception_text(exc)}")
        if hard:
            return _err("硬红线拦截: 该命令在任何模式下都不可自动执行 (fail-closed)。")
        if risk:
            return _err("安全引擎标记高风险, MCP 通道拒绝自动执行; 请改用 tuan_run 走完整确认流程。")

        # 审计 P0-05: 红线判定之外再过一次**不截断**的共享打分库 —— 与 shell 主链路
        # / decide_mcp_tool 三入口口径统一 (同一命令在任何入口结论一致);
        # critical/block 一律拒绝, 不给「前置填充绕过文本红线」留入口差异。
        try:
            shared = SafetyEngine().score({"command": command, "type": "shell"})
        except Exception as exc:  # noqa: BLE001
            return _err(f"安全引擎评分失败 (fail-closed): {safe_exception_text(exc)}")
        if shared.get("block") or shared.get("risk") == "critical":
            return _err("安全引擎判定 critical/block (不截断全文扫描), MCP 通道拒绝执行。")

        # 与 tools/shell.py 主链路共用同一套四层滤网裁决（不再只看文本红线）。
        class _McpKernel:
            """最小 kernel 视图: 只读 config, 供沙箱策略查询使用。"""

            def __init__(self, cfg: Any) -> None:
                self._cfg = cfg

            def get(self, name: str):
                return self._cfg if name == "config" else None

        class _McpCtx:
            # 审计 P2-32: 旧实现 kernel=None, _allowed_domains 抛
            # AttributeError 后被「设计内降级」吞掉 -> egress 策略层对 MCP
            # 通道完全失效。这里提供只读 config 的最小 kernel 视图。
            def __init__(self, ws: Optional[Path], cfg: Any) -> None:
                self.workspace = str(ws) if ws else None
                self.kernel = _McpKernel(cfg)

        try:
            manager = SandboxManager()
            verdict = manager.assess_command(
                command,
                _McpCtx(self.workspace, getattr(self, "_config", None)))
        except Exception as exc:  # noqa: BLE001
            # 裁决器异常一律拒绝，不回落裸跑（同 decided 契约）。
            return _err(f"统一滤网裁决失败 (fail-closed): {safe_exception_text(exc)}")

        if getattr(verdict, "action", None) == Action.DENY:
            return _err("统一滤网裁决拒绝 (DENY): MCP 通道不执行被拒命令。")
        if getattr(verdict, "action", None) == Action.CONFIRM:
            return _err("该命令需要人工确认, 但 MCP 通道没有确认通道: "
                        "fail-closed 拒绝。请改用 tuan_run 走完整确认流程。")
        if getattr(verdict, "isolate", False):
            return _err("该命令被裁决要求系统级强隔离, 但 MCP 通道是同步 "
                        "subprocess.run、套不上隔离后端 / 出网代理 / 副本确认: "
                        "fail-closed 拒绝 (与后台 `! cmd` 同一契约)。")

        # backend 固定 local：MCP 本来就是裸 subprocess，如实申报，
        # 绝不把 verdict.backend 里的强后端名字拿来假装已隔离。
        try:
            plan = plan_egress(verdict, "local", manager.policy, os.environ)
        except Exception as exc:  # noqa: BLE001
            return _err(f"出网/凭据裁决失败 (fail-closed): {safe_exception_text(exc)}")
        if not plan.allowed:
            return _err(f"出网合规拒绝 (未执行): {safe_error_text(plan.reason)}")

        child_env = dict(plan.env)  # 敏感键已是 sentinel，真实值不在此字典里
        if self.workspace:
            # SECRET_HINTS 含 "TUAN_"，按 workspace 参数补回（同 §15 provider）。
            child_env["TUAN_WORKSPACE"] = str(self.workspace)
        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=60,
                cwd=str(self.workspace) if self.workspace else None,
                env=child_env,
            )
        except subprocess.TimeoutExpired:
            return _err("命令超时 (60s)")
        except OSError as exc:
            return _err(f"执行失败: {safe_exception_text(exc)}")
        except Exception as exc:  # noqa: BLE001 - 兜住其它执行异常，不回显原文
            return _err(f"执行失败: {safe_exception_text(exc)}")
        out = (proc.stdout or "") + (("\n[stderr] " + proc.stderr) if proc.stderr else "")
        status = f"[退出码 {proc.returncode}] " if proc.returncode else ""
        return _ok(status + (out[:MAX_OUTPUT_CHARS] or "(无输出)"))

    # ------------------------------------------------------------ 协议层

    def tools(self) -> List[Dict[str, Any]]:
        """返回对外可见的工具定义 (去掉内部 handler)。"""
        return [{k: v for k, v in t.items() if k != "_handler"} for t in self._tools]

    def handle_line(self, line: str) -> Optional[str]:
        """处理一行 JSON-RPC 消息, 返回响应行 (通知无响应返回 None)。"""
        if not line.strip():
            return None
        try:
            msg = json.loads(line)
        except ValueError:
            return self._error_response(None, -32700, "Parse error")
        if not isinstance(msg, dict) or "method" not in msg:
            return self._error_response(msg.get("id"), -32600, "Invalid Request")
        method = msg.get("method")
        req_id = msg.get("id")
        if method == "notifications/initialized" or method == "notifications/cancelled":
            return None
        if method == "ping":
            return self._response(req_id, {})
        if method == "initialize":
            return self._response(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": _eco_version},
            })
        if method == "tools/list":
            return self._response(req_id, {"tools": self.tools()})
        if method == "tools/call":
            return self._handle_tool_call(msg)
        if method == "shutdown":
            return self._response(req_id, {})
        return self._error_response(req_id, -32601, f"Method not found: {method}")

    def _handle_tool_call(self, msg: Dict[str, Any]) -> str:
        req_id = msg.get("id")
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            return self._error_response(req_id, -32602, "Invalid params")
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return self._error_response(req_id, -32602, "arguments must be object")
        tool = next((t for t in self._tools if t["name"] == name), None)
        if tool is None:
            return self._error_response(req_id, -32602, f"Unknown tool: {name}")
        try:
            text, is_error = tool["_handler"](args)
        except Exception as exc:  # noqa: BLE001 - 工具异常必须回包而非崩溃
            return self._response(req_id, {
                "content": [{"type": "text", "text": f"工具执行异常: {exc}"}],
                "isError": True,
            })
        return self._response(req_id, {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        })

    def _response(self, req_id: Any, result: Any) -> str:
        return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result},
                          ensure_ascii=False)

    def _error_response(self, req_id: Any, code: int, message: str) -> str:
        return json.dumps({"jsonrpc": "2.0", "id": req_id,
                           "error": {"code": code, "message": message}},
                          ensure_ascii=False)

    # ------------------------------------------------------------ 主循环

    def serve_stdio(self) -> int:
        """阻塞式 stdio 主循环: 逐行读 stdin, 逐行回 stdout (flush 保证时序)。"""
        import os
        for raw in sys.stdin:
            try:
                resp = self.handle_line(raw)
            except Exception:  # noqa: BLE001 - 单行异常不中断服务
                resp = self._error_response(None, -32603, "Internal error")
            if resp is not None:
                sys.stdout.write(resp + "\n")
                sys.stdout.flush()
            if raw.strip() and "shutdown" in raw:
                break
        return 0


def serve_stdio(home: Path, workspace: Optional[Path] = None, config: Any = None) -> int:
    """CLI 入口: 构建服务端并进入 stdio 主循环。"""
    server = McpToolServer(home, workspace=workspace, config=config)
    return server.serve_stdio()


__all__ = ["McpToolServer", "serve_stdio", "SERVER_NAME", "PROTOCOL_VERSION"]
