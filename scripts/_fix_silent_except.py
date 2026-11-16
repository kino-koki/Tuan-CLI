#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性脚本: except 治理第二轮 —— 治理剩余 51 处 [SEC] 路径静默吞。

对 scripts/except_inventory.txt (silent 明细) 中标记 [SEC] 的每处:
  - ``except Exception:`` 补 ``as exc`` 绑定 (如尚未绑定);
  - 在处理体首行前插入一条日志 (审计证据类 warning, 设计内降级 debug);
  - 模块缺 logger 时自动补 ``import logging`` + ``log = logging.getLogger(__name__)``。

原则: **只加日志, 不改控制流**。日志级别规则:
  处理体是 pass          -> warning (吞掉且无任何替代动作)
  处理体是 continue/return -> debug   (有明确降级动作, 预期内)
  审计证据类文件 (mcp/audit, audit_correlation) 一律 warning。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TUI = ROOT / "tuan_cli"
INVENTORY = Path(__file__).resolve().parent / "except_inventory.txt"

# 每个文件的日志文案 (含 {exc} 占位由 %sexc 填充)
FILE_MSG: dict[str, str] = {
    "tuan_cli/tools/mcp/sandbox.py": "MCP 沙箱操作异常(设计内忽略): %s",
    "tuan_cli/sandbox/backends.py": "沙箱后端探测/执行异常(设计内降级): %s",
    "tuan_cli/sandbox/manager.py": "沙箱管理器操作异常(设计内降级): %s",
    "tuan_cli/sandbox/filters.py": "沙箱过滤器处理异常(设计内降级): %s",
    "tuan_cli/ext/safety_normalize.py": "安全规范化降级: %s",
    "tuan_cli/tools/sandbox.py": "沙箱工具异常(设计内降级): %s",
    "tuan_cli/core/security_classifier.py": "安全分类器降级: %s",
    "tuan_cli/core/sandbox_provider.py": "沙箱 provider 异常(设计内降级): %s",
    "tuan_cli/ext/safety_redline.py": "红线判定降级: %s",
    "tuan_cli/core/security_utils.py": "安全展示原语降级: %s",
    "tuan_cli/core/security_policy.py": "安全策略评估降级: %s",
    "tuan_cli/tui/inputkit/copy_input_guard.py": "剪贴板护栏降级: %s",
    "tuan_cli/tools/mcp/audit.py": "MCP 审计记录失败: %s",
    "tuan_cli/sandbox/isolation.py": "沙箱隔离裁决异常(设计内降级): %s",
    "tuan_cli/harden/crypto_provider.py": "加密 provider 降级: %s",
    "tuan_cli/ext/sandbox.py": "沙箱辅助操作异常(设计内忽略): %s",
    "tuan_cli/core/workspace_trust.py": "工作区信任评估降级: %s",
    "tuan_cli/core/security_plugin.py": "安全插件钩子异常(不影响主流程): %s",
    "tuan_cli/core/audit_correlation.py": "审计关联分析降级: %s",
    "tuan_cli/config/security_schema.py": "安全配置 schema 校验降级: %s",
    "tuan_cli/cli/cmd_trust.py": "trust 命令辅助操作失败(不影响主流程): %s",
}

# 审计证据类文件: 一律 warning
FORCE_WARNING = {"tuan_cli/tools/mcp/audit.py", "tuan_cli/core/audit_correlation.py"}


def parse_inventory() -> dict[str, list[dict]]:
    """从 inventory 的 silent 明细段提取 [SEC] 站点, 按文件分组。"""
    sites: dict[str, list[dict]] = {}
    in_silent = False
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        if line.startswith("== silent"):
            in_silent = True
            continue
        if line.startswith("== fallback"):
            in_silent = False
            continue
        if not in_silent or not line.startswith("[SEC]"):
            continue
        m = re.match(r"\[SEC\] (\S+):(\d+) \((\w+)\)", line)
        assert m, line
        rel, ln, _t = m.group(1), int(m.group(2)), m.group(3)
        body_m = re.search(r"body@(\d+): (.*)$", line)
        sites.setdefault(rel, []).append({
            "lineno": ln,
            "body_lineno": int(body_m.group(1)) if body_m else ln + 1,
            "body_text": body_m.group(2).strip() if body_m else "",
        })
    return sites


def logger_name(src: str) -> str | None:
    """模块内已有的 logging.getLogger 变量名。"""
    for m in re.finditer(r"^(\w+) = logging\.getLogger\(", src, re.M):
        return m.group(1)
    return None


def main() -> None:
    sites = parse_inventory()
    total = sum(len(v) for v in sites.values())
    print(f"待治理 [SEC] silent 站点: {total} 处, 涉及 {len(sites)} 个文件")
    assert total == 51, f"预期 51 处, 实际 {total} —— inventory 与预期不符, 请先重跑 audit_except.py"

    for rel, items in sites.items():
        path = ROOT / rel
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines(keepends=False)

        edits: list[tuple[int, str]] = []      # (insert_at_line_0based, text)
        replaces: list[tuple[int, str, str]] = []  # (line_0based, old, new)

        lname = logger_name(src)
        if lname is None:
            # 找最后一个顶层 import 语句行, 在其后插入 logging 导入与 logger
            tree = ast.parse(src)
            last_import = 0
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    last_import = max(last_import, node.end_lineno)
            assert last_import > 0, rel
            edits.append((last_import, ""))
            edits.append((last_import, "import logging"))
            edits.append((last_import, "log = logging.getLogger(__name__)"))
            lname = "log"
            print(f"  {rel}: 补 logger (插入第 {last_import} 行后)")

        for it in items:
            hidx = it["lineno"] - 1
            bidx = it["body_lineno"] - 1
            hline = lines[hidx]
            assert "except" in hline, (rel, it)
            if it["body_lineno"] == it["lineno"]:
                raise SystemExit(f"{rel}:{it['lineno']}: 单行 except 处理体, 请手工处理: {hline}")
            if " as " not in hline:
                new_h = re.sub(r"except (Exception|BaseException)(\s*):",
                               r"except \1 as exc\2:", hline, count=1)
                assert new_h != hline and ":" in new_h, (rel, hline)
                replaces.append((hidx, hline, new_h))
            body_indent = re.match(r"\s*", lines[bidx]).group(0)  # type: ignore[union-attr]
            level = "warning" if (it["body_text"].startswith("pass")
                                  or rel in FORCE_WARNING) else "debug"
            msg = FILE_MSG[rel]
            edits.append((bidx, f'{body_indent}{lname}.{level}("{msg}", exc)'))

        # 先做行替换 (不位移), 再按行号降序做插入
        for idx, old, new in sorted(replaces, key=lambda x: -x[0]):
            assert lines[idx] == old, (rel, idx, lines[idx], old)
            lines[idx] = new
        for idx, text in sorted(edits, key=lambda x: -x[0]):
            lines.insert(idx, text)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  {rel}: 修复 {len(items)} 处")


if __name__ == "__main__":
    main()
