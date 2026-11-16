"""slash 命令面板域: 输入联动过滤、高亮滚动、参数补全、面板渲染。

本模块由 tui.py 的 QxtTUI 拆分而来, 方法体逐行原样迁移 (无逻辑改动)。
模块级常量/工具/小类集中在 `tuan_cli.tui.common`, 由 `from .common import *`
注入到本模块命名空间, 因此方法体内对模块级名字的引用保持不变。
"""

from __future__ import annotations

from .common import *  # noqa: F401,F403

import logging
log = logging.getLogger(__name__)



class SlashMenuMixin:
    """slash 命令面板域: 输入联动过滤、高亮滚动、参数补全、面板渲染。"""

    # ---- 跨 mixin 共享实例属性/方法 (纯声明, 运行期不赋值) ----
    _app: Any
    _boot_error: Any
    _booting: Any
    _command_meta: Any
    _command_tiers: Any
    _commands: Any
    _confirm_pending: Any
    _input: Any
    _slash_accepting: Any
    _slash_arg_mode: Any
    _slash_arg_prefix: Any
    _slash_history: Any
    _slash_index: Any
    _slash_items: Any
    _slash_metas: List[str]
    _slash_open: Any
    _slash_scroll: Any
    _trust_pending: Any

    def _on_input_changed(self, buffer: Any = None) -> None:
            """输入文本变化 → 命令面板开合/过滤 (Claude Code 同款体验)。

            规则:
            - 输入以 "/" 或 "+/" 开头且尚未输空格 → 展开面板, 按已输入前缀过滤;
              空前缀 ("/") 列出全部命令并高亮第一项;
            - 出现空格 (命令已定, 开始输参数) / 删空 / 非命令输入 → 关闭面板;
            - boot / 信任确认 / 命令确认 / 思考进行中 → 不展开 (输入框是答复通道)。
            """
            if self._slash_accepting:
                return
            try:
                text = self._input.text
            except Exception as exc:  # noqa: BLE001 - 输入框未就绪 (极早期启动)
                log.debug("SlashMenuMixin._on_input_changed(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                return
            if (not self._commands or self._booting or self._boot_error
                    or self._trust_pending or self._confirm_pending):
                self._close_slash_menu()
                return
            # 命令参数补全: /model <partial> 或 /provider <partial> 时列出候选值
            # (复用 "/" 命令面板: ↑↓ 选择, Enter/Tab 确认填入, Esc 关闭)
            am = re.match(r'^([+/]?(?:model|provider|providers?))\s+(\S*)$', text)
            if am:
                self._slash_arg_mode = True
                self._slash_arg_prefix = am.group(1) + " "
                partial = am.group(2).lower()
                cands = self._arg_completions(am.group(1).lstrip("+/").lower(), partial)
                if not cands:
                    self._close_slash_menu()
                    return
                self._slash_items = cands
                self._slash_metas = [self._command_meta.get(c, "") or t("tui.cmd_meta")
                                     for c in cands]
                self._slash_index = 0
                self._slash_scroll = 0
                self._slash_open = True
                return
            # C-3.2 多级补全: 命令已定 (空格后) 且命令在子命令表中 → 展开子命令
            # (如 /safe → bench/allow/report; 已带子命令时再展开 --flag 第三级)。
            # 不在子命令表中的命令输空格仍按既有行为关闭面板。
            sm = re.match(r'^([+/]?[\w-]+)\s+(.*)$', text)
            if sm:
                cmd = "/" + sm.group(1).lstrip("+/").lower()
                subs = _SLASH_SUBCMDS.get(cmd)
                if subs:
                    tokens = sm.group(2).split(" ", 1)
                    # 第三级: 子命令已选、正在输 --flag (如 /safe bench --q)
                    if len(tokens) == 2 and tokens[1].startswith("--"):
                        flags = [(f, h) for f, h in _SLASH_FLAGS.get(f"{cmd} {tokens[0]}", [])
                                 if not tokens[1] or f.startswith(tokens[1].lower())]
                        if flags:
                            self._slash_arg_mode = True
                            # 回填前缀 = "命令 已选子命令 " (接受后拼成 "/safe bench --quick")
                            self._slash_arg_prefix = sm.group(1) + " " + tokens[0] + " "
                            self._slash_items = [f for f, _h in flags]
                            self._slash_metas = [h for _f, h in flags]
                            self._slash_index = 0
                            self._slash_scroll = 0
                            self._slash_open = True
                            return
                    # 第二级: 子命令候选 (模糊过滤, 带帮助预览)
                    partial = tokens[0].lower()
                    sub_cands = [(s, h) for s, h in subs
                                 if not partial or _fuzzy_rank(s.split(" ")[0], partial) >= 0]
                    if sub_cands:
                        self._slash_arg_mode = True
                        self._slash_arg_prefix = sm.group(1) + " "
                        self._slash_items = [s for s, _h in sub_cands]
                        self._slash_metas = [h for _s, h in sub_cands]
                        self._slash_index = 0
                        self._slash_scroll = 0
                        self._slash_open = True
                        return
                self._close_slash_menu()
                return
            self._slash_arg_mode = False
            if text.startswith("/"):
                typed = text[1:]
            elif text.startswith("+/"):
                typed = text[2:]
            else:
                self._close_slash_menu()
                return
            if " " in typed or "\n" in typed:
                self._close_slash_menu()
                return
            low = typed.lower()
            # 有空输入 (仅 "/" 或 "+/") 且配置了层级: 仅展开核心层 (≤ 20 项)
            # 输入具体前缀时保留全量匹配 (专家层命令按首字母可达)。
            # 仅当调用方显式配置了 command_tiers 才分层过滤; 未配置 (测试/旧调用)
            # 时保持旧行为: 显示全部传入 commands。
            has_tiers = bool(self._command_tiers)
            if not low:
                if has_tiers:
                    items = [c for c in self._commands
                             if self._command_tiers.get(c, "hidden") == "core"]
                else:
                    items = list(self._commands)
                # C-3.5 历史优先: 最近用过的命令提到最前 (MRU 去重, 最多 10 条),
                # 其余保持原序; 未使用过时与既有行为完全一致。
                if self._slash_history:
                    seen = set()
                    recent, rest_items = [], []
                    for c in items:
                        if c in self._slash_history and c not in seen:
                            recent.append(c)
                            seen.add(c)
                        else:
                            rest_items.append(c)
                    items = recent + rest_items
            else:
                # C-3.1 模糊匹配: 前缀 > 子串 > 子序列, 同档保持命令表原序。
                # 有前缀命中时只保留前缀命中 (保持既有 "输入首字母精确过滤" 手感,
                # 如 /mo 仍只出 /model /mode); 无前缀命中才退到子串/子序列 (如 /od→/mode)。
                matched = []
                for idx, c in enumerate(self._commands):
                    if has_tiers and self._command_tiers.get(c, "hidden") == "hidden":
                        continue
                    r = _fuzzy_rank(c[1:].lower(), low)
                    if r >= 0:
                        matched.append((r, idx, c))
                if any(r == 0 for r, _i, _c in matched):
                    matched = [m for m in matched if m[0] == 0]
                matched.sort(key=lambda t: (t[0], t[1]))
                items = [c for _r, _i, c in matched]
            if not items:
                self._close_slash_menu()
                return
            self._slash_items = items
            self._slash_metas = [self._command_meta.get(c) or t("tui.cmd_meta")
                                 for c in items]
            self._slash_index = 0
            self._slash_scroll = 0
            self._slash_open = True

    def _close_slash_menu(self) -> None:
            """关闭命令面板 (幂等)。"""
            self._slash_open = False
            self._slash_items = []
            self._slash_metas = []
            self._slash_index = 0
            self._slash_scroll = 0
            self._slash_arg_mode = False
            if self._app and self._app.is_running:
                try:
                    self._app.invalidate()
                except Exception as exc:  # noqa: BLE001
                    log.warning("SlashMenuMixin._close_slash_menu(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass

    def _record_slash_usage(self, text: str) -> None:
            """记录最近使用的 slash 命令 (MRU, C-3.5 历史优先)。

            只记命令名 (首个 token, 含前导 "/"), 去重置顶, 最多保留 10 条;
            下次 "/" 空前缀展开时这些命令排在最前。异常静默, 绝不阻断发送。
            """
            try:
                name = text.strip().split()[0] if text.strip() else ""
                if not name.startswith("/"):
                    return
                if name in self._slash_history:
                    self._slash_history.remove(name)
                self._slash_history.insert(0, name)
                del self._slash_history[10:]
            except Exception as exc:  # noqa: BLE001
                log.warning("SlashMenuMixin._record_slash_usage(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass

    def _arg_completions(self, cmd: str, partial: str) -> List[str]:
            """命令参数补全候选: /model 返回模型 ID 全集, /provider 返回供应商名。

            partial 为空列出全部 (面板可滚动); 否则按前缀过滤。模型 ID 取自各供应商
            MODEL_LISTS (剥 |free/|paid 标注), 并附供应商名便于 "provider/model" 速选。
            """
            try:
                from ..models.provider_catalog import ALL_PROVIDER_NAMES, MODEL_LISTS
            except Exception as exc:
                log.debug("SlashMenuMixin._arg_completions(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                return []
            if cmd in ("provider", "providers"):
                cands = list(ALL_PROVIDER_NAMES)
            else:  # model
                seen: set = set()
                cands = []
                for _p, models in MODEL_LISTS.items():
                    for m in models:
                        mid = m.split("|")[0]
                        if mid not in seen:
                            seen.add(mid)
                            cands.append(mid)
                for p in ALL_PROVIDER_NAMES:
                    if p not in seen:
                        seen.add(p)
                        cands.append(p)
            if partial:
                return [c for c in cands if c.lower().startswith(partial)]
            return cands

    def _slash_move(self, delta: int) -> None:
            """面板内移动高亮 (循环滚动), 并保持滚动窗口可见。"""
            if not self._slash_items:
                return
            n = len(self._slash_items)
            self._slash_index = (self._slash_index + delta) % n
            self._slash_clamp_scroll()

    def _slash_clamp_scroll(self) -> None:
            visible = min(_SLASH_MAX_VISIBLE, len(self._slash_items))
            if self._slash_index < self._slash_scroll:
                self._slash_scroll = self._slash_index
            elif self._slash_index >= self._slash_scroll + visible:
                self._slash_scroll = self._slash_index - visible + 1

    def _accept_slash(self, event: Any = None) -> bool:
            """Enter/Tab 确认: 把高亮命令填入输入框并关闭面板 (不直接执行)。

            与 Claude Code 一致: 选中只是补全, 用户可继续输入参数, 再按回车执行。
            """
            if not (self._slash_open and self._slash_items):
                return False
            idx = max(0, min(self._slash_index, len(self._slash_items) - 1))
            if self._slash_arg_mode:
                cmd = self._slash_arg_prefix + self._slash_items[idx]
                self._slash_arg_mode = False
            else:
                cmd = self._slash_items[idx]
            try:
                from prompt_toolkit.document import Document

                self._slash_accepting = True
                try:
                    self._input.buffer.document = Document(cmd, cursor_position=len(cmd))
                finally:
                    self._slash_accepting = False
            except Exception:  # noqa: BLE001 - 极端环境退回纯文本赋值
                self._slash_accepting = False
                try:
                    self._input.buffer.text = cmd
                except Exception as exc:
                    log.warning("SlashMenuMixin._accept_slash(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass
            self._slash_open = False
            self._slash_items = []
            self._slash_metas = []
            self._slash_index = 0
            self._slash_scroll = 0
            if self._app and self._app.is_running:
                try:
                    self._app.invalidate()
                except Exception as exc:  # noqa: BLE001
                    log.warning("SlashMenuMixin._accept_slash(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass
            return True

    def _slash_menu_rows(self) -> int:
            """面板高度 (布局期 callable 求值): 条目数封顶 _SLASH_MAX_VISIBLE, 至少 1 行。

            C-3.4: 无溢出 (条目 ≤ 上限) 时多留 1 行放底部 "? 帮助" 行;
            溢出时帮助并入滚动提示行, 不加高 (保持既有 9 行封顶契约)。
            """
            n = len(self._slash_items)
            rows = max(1, min(n, _SLASH_MAX_VISIBLE))
            if 0 < n <= _SLASH_MAX_VISIBLE:
                rows += 1
            return rows
