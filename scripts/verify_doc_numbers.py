#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对外文档数字核对器 (把"宣称"与"代码真值"对齐的可执行化)。

背景: 独立评估发现对外文档存在不可核实的数量断言风险。本脚本把
"文档里的数字"与"代码里的真值"做机器可核对的比较, 让夸大无处藏身。

真值来源:
  - 供应商数: tuan_cli.models.provider_catalog.ALL_PROVIDERS
  - 模型条目: tuan_cli.models.provider_catalog.MODEL_LISTS 合计
  - 子命令数: tuan_cli.cli.parser.build_parser() 解析器实时统计

检查对象: 仓库根目录 README*.md 中的供应商/模型/子命令数量断言。

用法:
    python scripts/verify_doc_numbers.py            # 检查并打印报告
    python scripts/verify_doc_numbers.py --json     # 机器可读输出

退出码: 0 = 一致; 1 = 发现不一致; 2 = 环境问题(无法读取真值)。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---- 数量断言的正则 ------------------------------------------------------------------
# 量词: 中文/日文/韩文里数字与名词之间常夹一个量词, 如「57 家供应商」「5 個模型」。
_MEASURE = r"(?:(?:家|個|个|社|개|곳|つ|件)\s*)?"
# 连接词: 日文「55 社**の**プロバイダ」/ 中文「57 家**的**供应商」/ 韩文「N **의** …」。
# 早期版本漏了这层, 导致 ja.md 的「55 社**の**プロバイダ」根本没被校验到 (盲区),
# 十份 README 里长期停在旧数字而校验器仍报"全部一致"。
_CONNECTOR = r"(?:(?:の|的|의)\s*)?"
# 修饰词: 英语「core subcommands」/ 法语「sous-commandes principales」/ 德语「Kern」等。
_QUALIFIER = (
    r"(?:(?:core|main|mains?|principaux|principais|principales|principali|"
    r"osnovnykh|osnovnih|основных|основної|Kern\w*|主要(?:な|の)?|핵심|하위)\s*)?"
)

# 注意: 名词表必须整体包进 (?:...), 否则顶层 | 会把前面的数字断掉 ——
# 那样正则会在没有数字的地方匹配到裸名词, group(1) 恒为 None。
_PROVIDER_CLAIM = re.compile(
    r"(\d+)\s*" + _MEASURE + _CONNECTOR +
    r"(?:providers?|供应商|供应商|供應[商]?|プロバイダ|プロバイザー|プロバイダー|"
    r"Anbieter\w*|proveedor\w*|fournisseur\w*|provedor\w*|"
    r"провайдер\w*|프로바이더)",
    re.IGNORECASE,
)

_MODEL_CLAIM = re.compile(
    r"(\d+)\s*\+?\s*" + _MEASURE + _CONNECTOR +
    r"(?:models?|模型|모델|モデル|Modelle\w*|Model\w*|modèles?|modelos?|"
    r"модел\w*)",
    re.IGNORECASE,
)

_SUBCOMMAND_CLAIM = re.compile(
    r"(\d+)\s*" + _MEASURE + _CONNECTOR + _QUALIFIER + r"[-]?\s*"
    r"(?:sub[- ]?command\w*|子命令|子指令|サブコマンド|Unterbefehl\w*|"
    r"pod[- ]?komand\w*|subcomand\w*|sous[- ]?command\w*|под[- ]?команд\w*)",
    re.IGNORECASE,
)

_CLAIMS = (
    ("providers", _PROVIDER_CLAIM),
    ("models", _MODEL_CLAIM),
    ("subcommands", _SUBCOMMAND_CLAIM),
)


def ground_truth() -> Dict[str, int]:
    """从代码读取真值: 供应商数 / 模型条目数 / 核心子命令数 / 含嵌套总数。"""
    from tuan_cli.models import provider_catalog as pc

    providers = len(pc.ALL_PROVIDERS)
    models = sum(len(v) for v in pc.MODEL_LISTS.values())
    core, total = _subcommand_truth()
    return {
        "providers": providers,
        "models": models,
        "subcommands": core,
        "subcommands_total": total,
    }


def _subcommand_truth() -> Tuple[int, int]:
    """实时统计 (核心子命令数, 含嵌套总数)。

    排除 argparse 自动加的 ``help``, 以及 ``__`` 前缀的内部开发命令
    (后者在文档里以 ``tuan dev codedev`` 出现, 属内部实现细节)。
    统计口径与 ``tuan --help`` 展示的命令面一致。
    """
    from tuan_cli.cli import parser as cli_parser

    top = cli_parser.build_parser()
    sp = next(
        a for a in top._actions if hasattr(a, "_name_parser_map") and a._name_parser_map
    )
    core = [
        n for n in sp._name_parser_map
        if not n.startswith("__") and n != "help"
    ]
    nested = 0
    for name in core:
        for action in sp._name_parser_map[name]._actions:
            if hasattr(action, "_name_parser_map") and action._name_parser_map:
                nested += len(action._name_parser_map)
    return len(core), len(core) + nested


def collect_numbers() -> Dict[str, int]:
    """对外暴露的真值字典 (供测试断言)。"""
    return ground_truth()


def _readmes() -> List[Path]:
    return sorted(REPO_ROOT.glob("README*.md"))


def scan_claims() -> List[Dict[str, object]]:
    """扫描所有 README 的数量断言, 返回结构化记录。"""
    out: List[Dict[str, object]] = []
    for path in _readmes():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in _CLAIMS:
                for m in pattern.finditer(line):
                    out.append(
                        {
                            "file": path.name,
                            "line": lineno,
                            "kind": kind,
                            "value": int(m.group(1)),
                            "match": m.group(0),
                        }
                    )
    return out


def check_consistency() -> List[str]:
    """返回不一致描述列表; 空列表表示全部一致。

    规则:
      - providers / subcommands: 断言值必须 == 真值。
      - models: 断言形如 "1100+" 表示下界, 真值必须 >= 该下界。
    """
    truth = collect_numbers()
    problems: List[str] = []
    for c in scan_claims():
        kind = str(c["kind"])
        value = int(c["value"])
        if kind == "providers" and value != truth["providers"]:
            problems.append(
                f"{c['file']}:{c['line']} 供应商断言 {value} != 真值 {truth['providers']}"
            )
        if kind == "models" and truth["models"] < value:
            problems.append(
                f"{c['file']}:{c['line']} 模型断言 {value}+ > 真值 {truth['models']}"
            )
        if kind == "subcommands" and value != truth["subcommands"]:
            problems.append(
                f"{c['file']}:{c['line']} 子命令断言 {value} != 真值 {truth['subcommands']}"
                f" (含嵌套共 {truth['subcommands_total']})"
            )
    return problems


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核对对外文档中的数量断言")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    # 报告里含中日韩文; 强制 UTF-8 输出, 避免 GBK/CP932 控制台抛 UnicodeEncodeError。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 非标准流 (如已重定向为 bytes) 时忽略
        pass

    try:
        truth = collect_numbers()
        claims = scan_claims()
    except Exception as exc:  # 环境问题: 无法读取真值
        print(f"[verify_doc_numbers] 无法读取代码真值: {exc}", file=sys.stderr)
        return 2

    problems = check_consistency()

    if args.json:
        # JSON 面向机器消费, 用 ensure_ascii=True 保证纯 ASCII ——
        # 否则日语片假名/韩语在 GBK(CP936)/CP932 控制台下, 父进程按 locale
        # 解码会直接 UnicodeDecodeError (见 tests/test_doc_numbers.py 的回归)。
        print(json.dumps(
            {"truth": truth, "claims": claims, "problems": problems},
            ensure_ascii=True, indent=2,
        ))
    else:
        print(
            f"真值: 供应商 {truth['providers']} 家, 模型条目 {truth['models']} 条, "
            f"子命令 {truth['subcommands']} 个 (含嵌套共 {truth['subcommands_total']}), "
            f"扫描到 {len(claims)} 条断言"
        )
        if problems:
            print(f"发现 {len(problems)} 处不一致:")
            for p in problems:
                print(f"  - {p}")
        else:
            print("全部一致。")

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
