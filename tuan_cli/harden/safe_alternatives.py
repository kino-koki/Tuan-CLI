# -*- coding: utf-8 -*-
"""安全替代建议引擎 (Safe Alternatives)。

危险命令被拦截 / 被要求确认时, 不只是说"不行", 而是给出**可执行的安全替代**:
把「拦住你」变成「带你安全地做完」—— 这是安全优先路线最实质的产品能力。

纯函数、无外部依赖、可单测; 规则按 (正则, 类别, 为什么, 替代命令) 组织,
覆盖 EXTREME / CRITICAL / HIGH 主要危险类别 (与 safety_engine 的规则库口径一致)。
"""
from __future__ import annotations

import re
from typing import Any

# (pattern, category, why, replacement)
_RULES: list[tuple[re.Pattern[str], str, str, str]] = [
    # ---- 递归删除 / 不可逆删除 ----
    (re.compile(r"\brm\s+(?:-\S+\s+)*(?:-{1,2}[a-zA-Z]*[rR][a-zA-Z]*[fF]|[fF][rR])\s+(?:/|/~|~|\$HOME|\.\*|\*)"),
     "递归强制删除",
     "rm -rf 不可逆, 误删无法找回; 目标为根/主目录时后果是系统级",
     "先 `ls -la <target>` 确认目标, 或移到回收站: `mv <target> ~/.trash/` (可后悔)"),
    (re.compile(r"\brm\s+-\S*[rR]\S*\s+\S+"),
     "递归删除",
     "递归删除会连带删掉子目录全部内容, 不可逆",
     "先 `ls -R <target>` 预览范围; 需要后悔空间用 `mv <target> ~/.trash/`"),
    (re.compile(r"\brm\b"), "删除操作",
     "rm 删除不可逆, 进入回收站更稳妥",
     "用回收站替代: `mv <target> ~/.trash/` 或 `trash <target>`"),

    # ---- git 强推 / 硬重置 ----
    (re.compile(r"\bgit\s+push\s+(?:--force\b(?!-with-lease)|-[a-zA-Z]*f[a-zA-Z]*\b)"),
     "强制推送",
     "git push --force 会覆盖远端他人提交, 团队协作时可能抹掉同事的工作",
     "改用安全强推: `git push --force-with-lease` (远端未变才推, 不覆盖他人提交)"),
    (re.compile(r"\bgit\s+reset\s+--hard"),
     "硬重置",
     "git reset --hard 丢弃工作区与暂存区全部改动, 不可逆",
     "保留改动: `git reset --soft HEAD~1` (仅撤销提交, 保留工作区); 或 `git revert <sha>` 安全回滚"),

    # ---- 磁盘 / 文件系统 ----
    (re.compile(r"\bdd\s+.*\sof=(?:/dev/(?:sd[a-z]|nvme\S+|vd[a-z]|hd[a-z])\b)"),
     "写入裸设备",
     "dd 直接写磁盘设备不可逆, 一次失误整盘数据全毁",
     "先 `lsblk -f` 确认设备号; 改为写分区挂载点或镜像文件 (of=./backup.img), 并加 `conv=noerror,sync`"),
    (re.compile(r"\bmkfs\.|format\s+[a-zA-Z]:"),
     "格式化文件系统",
     "格式化抹掉设备上全部数据, 不可逆",
     "格式化前完整备份; 确认设备未挂载 (`mount | grep <dev>`); 用 `lsblk -f` 再三核对设备号"),
    (re.compile(r"\bchmod\s+-[Rr]\s+0{2,}\s+"),
     "递归移除权限",
     "chmod -R 000 锁死目录树, 系统/服务立即不可用",
     "改为精确权限: `chmod -R u+rwX,go+rX <dir>` (可读可执行, 不放开写)"),
    (re.compile(r"\bchmod\s+-[Rr]\s+[0-7]{3}\s+"),
     "递归改权限",
     "递归 chmod 777 全开可被任意进程改写, 存在安全隐患",
     "用最小必要权限: `chmod -R u+rwX,go+rX <dir>`, 或只对需要写的目录放开"),
    (re.compile(r"\bchown\s+-[Rr]\s+root\s+/"),
     "递归变更所有权",
     "chown -R root / 改变全盘所有权, 系统不可用",
     "只对目标目录操作: `chown -R <user>:<group> <dir>`"),

    # ---- 系统关机 / 重启 ----
    (re.compile(r"\bshutdown\s+(-[hs]|now|/s)|reboot\b"),
     "关机/重启",
     "立即关机/重启打断所有未保存工作与后台任务",
     "先保存全部工作; 用延迟关机留后悔时间: `shutdown -r +5` (5 分钟后重启) 或 `shutdown -c` 取消"),

    # ---- 远程代码直执行 ----
    (re.compile(r"\bcurl\b.*\|\s*(?:ba)?sh\b|\bwget\b.*\|\s*(?:ba)?sh\b"),
     "管道执行远程代码",
     "curl | sh 等于盲跑外部代码, 未经审查即拥有当前用户全部权限",
     "先下载审查再执行: `curl -fsSL <url> -o /tmp/script.sh && less /tmp/script.sh`"),
    (re.compile(r"base64.*\|\s*(?:ba)?sh|(?:ba)?sh\s*<\(.*base64"),
     "Base64 编码管道到 shell",
     "Base64 编码内容无法静态验证, 常被用于隐藏恶意命令",
     "先解码审查: `echo <b64> | base64 -d` 查看明文再决定"),

    # ---- eval / 命令替换 ----
    (re.compile(r"\beval\b"),
     "eval 执行",
     "eval 内容无法静态验证, 变量/命令替换可能展开出危险命令",
     "先打印展开结果: `printf '%s' <expr>` 确认内容再执行"),

    # ---- Windows 递归强删 ----
    (re.compile(r"remove-item\s+.*-recurse.*-force|rd\s+/s\s+/q"),
     "Windows 递归强删",
     "Remove-Item -Recurse -Force / rd /s /q 不可逆",
     "先预览: `Remove-Item -Recurse -Force <path> -WhatIf` 或 `rd /s <path>` 不带 /q 逐个确认"),

    # ---- 数据库 ----
    (re.compile(r"\bDROP\s+TABLE\b"),
     "删除数据表",
     "DROP TABLE 永久删除整张表及其数据, 不可恢复",
     "先备份: `mysqldump db table > table.sql`; 或改为 TRUNCATE/逻辑删除, 并确认库名无误"),
    (re.compile(r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)"),
     "全表删除",
     "DELETE FROM 不带 WHERE 会清空整表数据",
     "先 `SELECT COUNT(*) FROM <table>` 确认影响行数; DELETE 必须带 WHERE 条件, 或先备份"),

    # ---- 危险下载执行 ----
    (re.compile(r"\bsudo\s+(?:rm|dd|mkfs|chmod)"),
     "sudo 危险操作",
     "sudo 提升权限后执行破坏性命令, 影响面放大到系统级",
     "先确认目标绝对路径与设备号; 避免对 / 和裸设备操作; 用普通权限能完成就别用 sudo"),
]

_FALLBACK = [
    "先 `--dry-run` 或预览模式确认操作范围再执行",
    "对不可逆操作先备份: 复制/导出到安全位置",
]


def suggest_safe_alternatives(command: str, reasons: list[str] | None = None) -> list[dict[str, str]]:
    """按命令形态给出安全替代建议。

    Args:
        command: 原始命令文本。
        reasons: 引擎命中的风险理由 (可选, 当前主要用于口径说明)。

    Returns:
        [{category, why, replacement}] 按类别去重; 无命中时返回空列表。
    """
    lower = command.lower()
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    for pattern, cat, why, repl in _RULES:
        if cat in seen:
            continue
        if pattern.search(command) or pattern.search(lower):
            hits.append({"category": cat, "why": why, "replacement": repl})
            seen.add(cat)
    return hits


def format_suggestions(command: str, reasons: list[str] | None = None) -> list[str]:
    """把建议格式化为展示用字符串列表 (供 Verdict / CLI 直接渲染)。"""
    items = suggest_safe_alternatives(command, reasons)
    out = []
    for it in items:
        out.append(f"[{it['category']}] {it['replacement']} —— {it['why']}")
    if not out:
        out = list(_FALLBACK)
    return out


def suggest_for_decision(command: str, risk: str) -> list[str]:
    """SafetyEngine.score 集成入口: 按风险级别返回建议字符串。

    良性命令不打扰; 危险命令优先给命令感知的替代, 未命中才回退通用建议。
    """
    if risk in ("none",):
        return []
    items = suggest_safe_alternatives(command)
    if items:
        return [f"[{it['category']}] {it['replacement']}" for it in items]
    if risk == "critical":
        return [
            "[通用] 使用更精确的路径, 避免一次性覆盖大范围",
            "[通用] 先备份再执行破坏性操作: cp -r / 导出数据",
            "[通用] 不可逆操作先 dry-run 预览",
        ]
    if risk == "high":
        return [
            "[通用] 确认操作范围后再执行",
            "[通用] 建议添加 --dry-run 先预览",
        ]
    return []
