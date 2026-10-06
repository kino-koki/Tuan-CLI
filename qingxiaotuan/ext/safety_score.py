"""SafetyEngine IPC 引擎门面 (safety_engine 拆分模块)。

对外暴露 score / analyze / handle / run, 供 IPC 引擎进程与包内工具共用。
"""
import json
import re
import sys

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
)


class SafetyEngine:
    """统一 JSONL IPC 协议的 safety 引擎"""

    # 危险模式库 (label 双语: 英文便于测试/日志, 中文便于展示)
    # 与模块级 _CRITICAL_PATTERNS / _HIGH_PATTERNS / _MEDIUM_PATTERNS 保持一致。
    CRITICAL_PATTERNS = _CRITICAL_PATTERNS
    HIGH_PATTERNS = _HIGH_PATTERNS
    MEDIUM_PATTERNS = _MEDIUM_PATTERNS

    def __init__(self):
        self.methods = {
            "score": self.score,
            "analyze": self.analyze,
            "_meta/list": self.list_methods,
        }

    def list_methods(self, params=None):
        return {
            "engine": "safety",
            "version": "1.1.0-python",
            "methods": list(self.methods.keys()),
            "capabilities": ["risk_scoring", "command_analysis", "sql_analysis", "blast_radius"],
        }

    def _match_patterns(self, text: str, patterns):
        """匹配模式 (尊重用户本地黑名单减负: 被抑制的模式 label 跳过)。"""
        matches = []
        for pattern, label in patterns:
            if _label_suppressed(label):
                continue
            if re.search(pattern, text, re.IGNORECASE):
                matches.append(label)
        return matches

    def score(self, params):
        """评分: command/sql/write"""
        text = params.get("command", "") or params.get("sql", "") or params.get("text", "")
        action_type = params.get("type", "shell")

        # 降误杀: 良性开发命令 (文件读写 / git 常规操作 / 包管理 / 测试运行 / lint 等)
        # 一律判定为 none, 避免常见正常命令被安全引擎升级为 high/critical 而遭拦截或反复确认。
        # 注意「硬红线」(is_hard_redline) 在护栏 step1 独立判定, rm -rf /、dd、mkfs、
        # force push 等不可逆操作仍会被拦截; 写系统关键路径 (如 cp x /etc/...) 已被
        # _SYSTEM_PATH_RE 排除出良性集合, 仍按原风险判定。
        if is_benign_dev_command(text):
            return {
                "risk": "none",
                "score": 0,
                "block": False,
                "reasons": [],
                "blast_radius": {"files": [], "services": [], "data": []},
                "suggestions": [],
            }

        critical = self._match_patterns(text, self.CRITICAL_PATTERNS)
        high = self._match_patterns(text, self.HIGH_PATTERNS)
        medium = self._match_patterns(text, self.MEDIUM_PATTERNS)

        # 与 is_redline 口径一致: 编码/间接混淆 (PowerShell -EncodedCommand Base64、
        # ANSI-C 转义、嵌套命令替换、全角/组合 Unicode 等) 只有经过 _normalize 解码后才
        # 浮现真实命令名。若只在原始文本上匹配会漏判 (如 PS EncodedCommand 删除得 none)。
        # 归一化后的明文同样跑一遍模式库 (is_benign_dev_command 已在入口过滤良性命令)。
        norm_text = _normalize(text)
        critical += self._match_patterns(norm_text, self.CRITICAL_PATTERNS)
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
        blast_radius = {"files": [], "services": [], "data": []}
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

    def analyze(self, params):
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

    def handle(self, line):
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

    def run(self):
        sys.stdout.write(json.dumps({"ready": True}) + "\n")
        sys.stdout.flush()
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            sys.stdout.write(self.handle(line) + "\n")
            sys.stdout.flush()


