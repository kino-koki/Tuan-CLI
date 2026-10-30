"""SafetyEngine IPC 引擎门面 (safety_engine 拆分模块)。

对外暴露 score / analyze / handle / run, 供 IPC 引擎进程与包内工具共用。
"""
import json
import re
import sys
from typing import Any

from .safety_normalize import (
    _eval_is_unverifiable,
    _normalize,
)
from .safety_redline import (
    _CRITICAL_PATTERNS,
    _HIGH_PATTERNS,
    _MEDIUM_PATTERNS,
    _is_base64_pipeline_dangerous,
    _label_suppressed,
    has_dangerous_recursive_rm,
    has_force_push,
    has_recursive_rm,
    has_win_recursive_delete,
    is_benign_dev_command,
    is_hard_redline,
)


class SafetyEngine:
    """统一 JSONL IPC 协议的 safety 引擎"""

    # 危险模式库 (label 双语: 英文便于测试/日志, 中文便于展示)
    # 与模块级 _CRITICAL_PATTERNS / _HIGH_PATTERNS / _MEDIUM_PATTERNS 保持一致。
    CRITICAL_PATTERNS = _CRITICAL_PATTERNS
    HIGH_PATTERNS = _HIGH_PATTERNS
    MEDIUM_PATTERNS = _MEDIUM_PATTERNS

    # ---- V-12 跨阶段迭代预算哨兵 ----
    # _expand_var_defs 累计替换超限时返回此哨兵: 必然命中硬红线 (递归删除),
    # 让上层 fail-closed 保守拦截, 而非放行一个未能完全归一化的输入。
    _EXPANSION_SENTINEL = "rm -rf / __tuan_expansion_budget_exceeded__"

    # ---- V-10 降噪 (独立评测 2026-10) ----
    # ssh 远程执行只读命令 -> 不打扰 (危险载荷仍由 critical 规则独立命中)
    _SSH_READONLY_RE = re.compile(
        r"^\s*ssh\b(?:\s+-[A-Za-z0-9]+(?:\s+\S+)?)*\s+[A-Za-z0-9_.@:-]+\s+['\"]?\s*"
        r"(?:ls|ll|cat|echo|pwd|whoami|df|du|ps|top|uptime|uname|hostname|id|date|env|"
        r"tail|head|wc|grep|find|which|systemctl\s+status|docker\s+(?:ps|logs|images)|"
        r"git\s+(?:status|log|diff|branch|show|remote\s+-v))\b",
        re.IGNORECASE,
    )
    # 清理依赖/缓存目录属于常规运维, rm 递归强删已按目标危险度分档
    # (灾难级 -> critical, 相对路径 -> high 需确认), 无需额外降噪规则。

    # ---- V-01 副作用的必要补偿: 「提及 vs 执行」 (独立评测 2026-10) ----
    # V-01 让 critical 不再被良性白名单短路, 修好了 `pip --index-url` 类绕过,
    # 但副作用是只读查看命令里**提到**危险字样也会被硬拦:
    #   grep -rn 'DROP TABLE' docs/      -> 只是搜索文档
    #   cat notes.txt | grep -i 'drop table'
    #   grep -rn 'rm -rf /' README.md
    # 这类命令不执行任何 SQL/shell, 硬拦即为误杀。故: 只读查看类命令命中
    # SQL 族/危险命令族模式时降级 —— 前提是命令里没有真正的数据库客户端。
    _READONLY_VIEW_RE = re.compile(
        r"^\s*(?:sudo\s+)?(?:grep|egrep|fgrep|rg|ag|ack|cat|bat|head|tail|less|more|"
        r"wc|nl|sed\s+-n|awk|cut|sort|uniq|strings|file)\b",
        re.IGNORECASE,
    )
    _DB_CLIENT_RE = re.compile(
        r"\b(?:mysql|psql|sqlite3|mariadb|mongosh?|redis-cli|clickhouse-client|"
        r"sqlcmd|isql|duckdb|psql64)\b", re.IGNORECASE,
    )
    # 这些 label 属于「语句级危险」, 只读查看命令里出现即视为提及而非执行
    _MENTION_ONLY_LABELS = (
        "drop object", "delete rows", "truncate", "alter table",
        "flush database", "mongo drop database", "bulk update",
        "drop database", "drop table",
    )

    def __init__(self) -> None:
        self.methods = {
            "score": self.score,
            "analyze": self.analyze,
            "_meta/list": self.list_methods,
        }

    def list_methods(self, params: Any = None) -> Any:
        return {
            "engine": "safety",
            "version": "1.1.0-python",
            "methods": list(self.methods.keys()),
            "capabilities": ["risk_scoring", "command_analysis", "sql_analysis", "blast_radius"],
        }

    # ---- V-07 变量定义展开 (独立评测 2026-10) ----
    # 实测漏判 `X=$'rm\x20-rf'; $X /`: 变量值用 ANSI-C 引号构造完整命令行,
    # 归一化层未把 $'...' 解码后再做变量替换, 真实命令名始终不浮现。
    _ANSI_C_UNESC = re.compile(
        r"\\(?:x([0-9a-fA-F]{1,2})|u([0-9a-fA-F]{4})|([0-7]{1,3})|(.))", re.S)
    _VAR_DEF = re.compile(
        r"(?:^|[;|\s])([A-Za-z_]\w*)=(\$'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|"
        r"'[^']*'|[^\s;|&]+)")

    @classmethod
    def _decode_ansi_c(cls, s: str) -> str:
        def rep(m):
            if m.group(1):
                return chr(int(m.group(1), 16))
            if m.group(2):
                return chr(int(m.group(2), 16))
            if m.group(3):
                return chr(int(m.group(3), 8))
            c = m.group(4)
            return {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b",
                    "f": "\f", "v": "\v", "e": "\x1b", "0": "\0"}.get(c, c)
        return cls._ANSI_C_UNESC.sub(rep, s)

    @classmethod
    def _expand_var_defs(cls, text: str, max_rounds: int = 8) -> str:
        """把 `VAR=$'...'` / `VAR="..."` 定义内联展开, 让真实命令名浮现。有界迭代防爆炸。

        跨阶段迭代预算: 变量展开与 brace 展开/命令替换可能互相交织 (如
        `X={rm,-rf,/}; eval $X`), 单独限制每步的 max_rounds 无法约束「展开→再归一化→
        再展开」的多轮往返总代价。这里按**累计替换次数**设总预算, 超限即返回一个
        必然命中红线的哨兵, 让上层 fail-closed (保守拦截), 避免病态输入拖垮判定。
        """
        out = text
        total_substitutions = 0
        for _ in range(max_rounds):
            defs = {}
            for m in cls._VAR_DEF.finditer(out):
                name, val = m.group(1), m.group(2)
                if val.startswith("$'"):
                    val = cls._decode_ansi_c(val[2:-1])
                elif val[:1] in ('"', "'"):
                    val = val[1:-1]
                defs.setdefault(name, val)
            if not defs:
                break
            new = out
            for n, v in defs.items():
                new, count = re.subn(r"\$\{?" + re.escape(n) + r"(?:\}|(?![A-Za-z0-9_]))", v, new)
                total_substitutions += count
                # 累计替换总预算: 防止变量间相互引用 (A=$B, B=$A) 或指数级膨胀
                # 在 max_rounds 内反复替换导致 O(2^n) 级文本增长。
                if total_substitutions > 64:
                    return cls._EXPANSION_SENTINEL
            if new == out:
                break
            out = new
        # $IFS 无分隔拼接 (echo$IFS'rm'): IFS 默认空白, 展开为空格使命令名成词
        out = re.sub(r"\$IFS(?![A-Za-z0-9_])", " ", out)
        out = re.sub(r"\$\{IFS\}", " ", out)
        return out

    def _match_patterns(self, text: str, patterns: Any) -> Any:
        """匹配模式 (尊重用户本地黑名单减负: 被抑制的模式 label 跳过)。"""
        matches = []
        for pattern, label in patterns:
            if _label_suppressed(label):
                continue
            if re.search(pattern, text, re.IGNORECASE):
                matches.append(label)
        return matches

    def score(self, params: Any) -> Any:
        """评分: command/sql/write"""
        text = params.get("command", "") or params.get("sql", "") or params.get("text", "")
        action_type = params.get("type", "shell")

        # ---- V-01 架构级修复: 危险判定先行, 良性降级最后 ----
        # 旧实现把 is_benign_dev_command() 放在 score() 开头短路返回 none, 使白名单
        # 命令的参数级危险载荷 (pip --index-url 指向恶意镜像 / npm --registry 劫持 /
        # cp 覆盖 /usr/local/bin/sudo / git remote set-url 改推送目标) 全部跳过危险判定。
        # 现改为「先跑全部危险判定 (模式库 + token 化 + 硬红线), 仅在未命中 critical 时
        # 才允许良性降级」—— 白名单不再优先于危险判定 (安全围堵方案 V-01)。
        # 良性降级只用于消除 high/medium 的误打扰, **永不削弱 critical 与硬红线**。
        benign = is_benign_dev_command(text)

        critical = self._match_patterns(text, self.CRITICAL_PATTERNS)
        high = [] if benign else self._match_patterns(text, self.HIGH_PATTERNS)
        medium = [] if benign else self._match_patterns(text, self.MEDIUM_PATTERNS)

        # 与 is_redline 口径一致: 编码/间接混淆 (PowerShell -EncodedCommand Base64、
        # ANSI-C 转义、嵌套命令替换、全角/组合 Unicode 等) 只有经过 _normalize 解码后才
        # 浮现真实命令名。若只在原始文本上匹配会漏判 (如 PS EncodedCommand 删除得 none)。
        # 归一化后的明文同样跑一遍模式库。
        norm_text = _normalize(text)
        critical += self._match_patterns(norm_text, self.CRITICAL_PATTERNS)
        # V-07: 变量定义展开后再扫一遍 (覆盖 `X=$'rm\x20-rf'; $X /` 形态)
        expanded = self._expand_var_defs(text)
        if expanded != text:
            exp_norm = _normalize(expanded)
            critical += self._match_patterns(expanded, self.CRITICAL_PATTERNS)
            critical += self._match_patterns(exp_norm, self.CRITICAL_PATTERNS)
            # 展开后同样跑 token 化与硬红线判定 (rm -rf / 由 has_recursive_rm/is_hard_redline
            # 而非纯正则判定, 只跑模式库会漏)
            if has_dangerous_recursive_rm(expanded):
                critical.append("recursive force delete (递归强制删除危险目标, 变量展开后)")
            if is_hard_redline(expanded):
                critical.append("hard redline (硬红线, 变量展开后)")
            if not benign:
                high += self._match_patterns(expanded, self.HIGH_PATTERNS)
        if not benign:
            high += self._match_patterns(norm_text, self.HIGH_PATTERNS)
            medium += self._match_patterns(norm_text, self.MEDIUM_PATTERNS)

        # token 化补充检测: 覆盖正则易绕过的变体 (rm -r -f / git push -f / del /s 等)
        # rm 递归强删按**目标危险度**分档: 灾难级目标 (/, ~, /etc, *) -> critical;
        # 相对路径 (./build, node_modules, dist) -> high (需确认, 不拦截)。
        # 避免 `rm -rf ./dist` 这类清构建产物的常规操作被误判为 critical 硬拦。
        if has_dangerous_recursive_rm(text):
            critical.append("recursive force delete (递归强制删除危险目标)")
        elif has_recursive_rm(text):
            high.append("recursive force delete (递归强制删除, 相对路径目标)")
        if has_force_push(text):
            critical.append("force push (强制推送)")
        if has_win_recursive_delete(text):
            critical.append("windows recursive delete (Windows 递归删除)")
        if _eval_is_unverifiable(text):
            critical.append("eval + 命令替换 (内容无法静态验证, 保守拒绝)")
        # GuardFall D类绕过: Base64 编码管道到 shell
        if _is_base64_pipeline_dangerous(text):
            critical.append("base64 pipeline to shell (Base64编码管道到shell解释器, GuardFall D类绕过)")

        # 口径统一 (P0): score() 此前只做「正则模式库 + 少量 token 判定」, 未复用
        # is_hard_redline() 的其余判定 (编码字面量 / 解释器内联载荷 / 系统关机 /
        # 认证文件覆盖 / 归一化后红线), 导致同一命令 is_redline=True 而 score()=none
        # —— IPC 引擎入口 (score/analyze) 因此比 shell 护栏弱, 形成真实缺口
        # (如 `python -c "os.system('rm -rf /')"` / `ln -sf /dev/null /etc/passwd`)。
        #
        # V-10 重要: **不**直接调 is_hard_redline(text), 因为后者现在包含凭证外泄
        # (cat ~/.ssh/id_rsa → 硬红线), 但 SafetyEngine.score() 应把这类命令判为
        # high (而非 critical), 否则 RiskVector engine_floor=10 会拉 composite 超过 8.0
        # 破坏 test_risk_sandbox 预期。凭证外泄硬拒改由 IntentFilter 独立检测。
        # 这里只调 is_hard_redline 的**毁灭操作子集** —— 其余 token 化检测已在上方覆盖。
        from .safety_redline import (
            _has_unresolved_dangerous_substitution,
            _is_encoded_literal_dangerous,
            _interpreter_payload_dangerous,
            _mask_mentioned_literals,
            has_unconditional_force_push, has_system_shutdown, has_auth_overwrite,
            _match_any, _REDLINE_PATTERNS,
        )
        _hard_sub = (
            _eval_is_unverifiable(text)  # 顶部已从 safety_normalize import
            or _has_unresolved_dangerous_substitution(text)
            or _is_base64_pipeline_dangerous(text)  # 顶部已从 safety_redline import
            or _is_encoded_literal_dangerous(text)
            or _interpreter_payload_dangerous(text)
        )
        if _hard_sub:
            critical.append("hard redline core (编码混淆/解释器载荷/不可验证eval)")
        else:
            _pt = _mask_mentioned_literals(text)
            if (has_dangerous_recursive_rm(_pt)  # 顶部已 import
                    or has_unconditional_force_push(_pt)
                    or has_win_recursive_delete(_pt)  # 顶部已 import
                    or has_system_shutdown(_pt)
                    or has_auth_overwrite(_pt)
                    or _match_any(_pt, _REDLINE_PATTERNS)
                    or _match_any(_mask_mentioned_literals(_normalize(_pt)), _REDLINE_PATTERNS)):  # _normalize 顶部已 import
                critical.append("hard redline core (文件系统/OS级毁灭操作)")

        # ---- V-01 补偿: 只读查看命令里「提及」危险语句, 不算执行 ----
        # grep -rn 'DROP TABLE' docs/ / grep -rn 'rm -rf /' README.md 这类命令只是
        # 搜索文档, 不执行任何 SQL/shell。命中只读查看命令且无数据库客户端时,
        # 把「语句级危险」label 从 critical/high 中剔除 (保留真正执行的危险)。
        if (self._READONLY_VIEW_RE.search(text)
                and not self._DB_CLIENT_RE.search(text)):
            critical = [c for c in critical if not any(k in c.lower() for k in self._MENTION_ONLY_LABELS)]
            high = [h for h in high if not any(k in h.lower() for k in self._MENTION_ONLY_LABELS)]
        # ---- V-10 降噪: ssh 远程只读命令不打扰 ----
        if high and self._SSH_READONLY_RE.search(text):
            high = [h for h in high if "ssh remote exec" not in h]

        # ---- V-01 修复: 良性降级仅在「无 critical / 无硬红线」时生效 ----
        # 白名单命令若命中上方任一 critical 判定 (含新增的 V-02~V-09 规则), 一律不再降级,
        # 消除「良性白名单短路优先于危险判定」的架构缺口。此处 is_benign_dev_command()
        # 仍保留其内部的 fail-closed 检查 (命中 critical/high/medium 模式即返回 False),
        # 双重保障: 即使未来新增规则未在此入口同步, 降级也不会吞掉危险判定。
        if not critical and is_benign_dev_command(text):
            return {
                "risk": "none",
                "score": 0,
                "block": False,
                "reasons": [],
                "blast_radius": {"files": [], "services": [], "data": []},
                "suggestions": [],
            }

        # 确定风险级别
        if critical:
            risk = "critical"
            score_val = 100
        elif high:
            risk = "high"
            score_val = 70
        elif medium:
            risk = "medium"
            score_val = 40
        else:
            risk = "none"
            score_val = 0

        # 计算 blast radius
        blast_radius: dict[str, list[str]] = {"files": [], "services": [], "data": []}
        if "rm" in text:
            files = re.findall(r"rm\s+(?:-{1,2}[\w-]+\s+)+(.+)", text)
            blast_radius["files"].extend(f.split()[0] for f in files if f.strip())
        if "git" in text and "push" in text:
            blast_radius["services"].append("git-remote")
        if "DROP" in text.upper() or "DELETE" in text.upper():
            blast_radius["data"].append("database")

        # 替代建议 (命令感知安全替代引擎: 按具体命令形态给出可执行的安全替代)
        from ..harden.safe_alternatives import suggest_for_decision

        suggestions = suggest_for_decision(text, risk)

        return {
            "risk": risk,
            "score": score_val,
            "block": risk == "critical",
            "reasons": critical + high + medium,
            "blast_radius": blast_radius,
            "suggestions": suggestions,
        }

    def analyze(self, params: Any) -> Any:
        """批量分析一组计划中的操作 (dry-run), 返回整体风险与逐条理由。"""
        ops = params.get("ops", [])
        if not isinstance(ops, list):
            ops = [ops]
        items = []
        for op in ops:
            kind = op.get("kind", "command")
            text = op.get("text", "")
            target = op.get("target", "")
            scored = self.score({"command": text, "type": "shell"})
            items.append({
                "kind": kind,
                "target": target,
                "text": text,
                "risk": scored["risk"],
                "score": scored["score"],
                "reasons": scored["reasons"],
            })
        overall = "critical" if any(it["risk"] == "critical" for it in items) else (
            "high" if any(it["risk"] == "high" for it in items) else (
            "medium" if any(it["risk"] == "medium" for it in items) else "none"))
        advice = {
            "critical": "BLOCK: 存在致命风险操作, 必须人工确认后执行",
            "high": "CONFIRM: 存在高风险操作, 建议逐条确认",
            "medium": "REVIEW: 存在中风险操作, 建议复核",
            "none": "ok: 未发现明显风险",
        }[overall]
        return {"overall": overall, "advice": advice, "items": items}

    def handle(self, line: Any) -> Any:
        req_id = None
        try:
            req = json.loads(line)
            method = req.get("method", "")
            params = req.get("params", {})
            req_id = req.get("id", None)
            if method in self.methods:
                result = self.methods[method](params)
                resp = {"id": req_id, "ok": True, "result": result}
            else:
                resp = {"id": req_id, "ok": False, "error": f"Unknown method: {method}"}
            return json.dumps(resp, ensure_ascii=False)
        except Exception as e:
            resp = {"id": req_id, "ok": False, "error": str(e)}
            return json.dumps(resp, ensure_ascii=False)

    def run(self) -> None:
        sys.stdout.write(json.dumps({"ready": True}) + "\n")
        sys.stdout.flush()
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            sys.stdout.write(self.handle(line) + "\n")
            sys.stdout.flush()


