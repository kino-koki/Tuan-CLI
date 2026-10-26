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
    r"(?:sub[- ]?command\w*|子命令|子指令|サブコマンド|서브커맨드|Unterbefehl\w*|"
    r"pod[- ]?komand\w*|subcomand\w*|sous[- ]?command\w*|под[- ]?команд\w*)",
    re.IGNORECASE,
)

_CLAIMS = (
    ("providers", _PROVIDER_CLAIM),
    ("models", _MODEL_CLAIM),
    ("subcommands", _SUBCOMMAND_CLAIM),
)

# ---- 基准数字断言的正则 (绕过矩阵条数 / 对抗样本误杀率) ----------------------------
# 真值来源: bench/security-bench.json (与 CI 门禁 security-ci.yml 同源的提交存档)。
# 本轮修复前, 10 语种 README 的「绕过矩阵 2,321 / 2,310」与实测 2,497、「误杀率 0.09% (1)」
# 与实测 0.45% (5) 长期不一致, 且旧校验器只管供应商/模型/子命令数, 留有盲区。
# 这里把基准数字也纳入机器可核对范围, 防止再次漂移。
_BYPASS_KW_RE = re.compile(r"bypass|绕过|ペイロード|payload", re.IGNORECASE)
# 千分位可写成逗号 (2,497) 或点 (2.497) 或不写 (2497); 统一去分隔符转 int。
_NUMBER_RE = re.compile(r"\d{1,3}(?:[,\.]\d{3})+|\d{4,}")
# 正确误杀率 (本轮实测): 0.45% (5) / 0,45 % (5)
_FP_CORRECT_RE = re.compile(r"0[.,]45\s*%\s*\(\s*5\s*\)")
# 旧错误误杀率 (漂移值): 0.09% (1) / 0,09 % (1)
_FP_WRONG_RE = re.compile(r"0[.,]09\s*%\s*\(\s*1\s*\)")
# 旧错误绕过矩阵条数 (漂移值)
_OLD_BYPASS_TOTALS = frozenset({2321, 2310})


def bench_truth() -> Dict[str, int]:
    """从提交存档读取基准真值: 绕过矩阵条数 / 对抗误杀数 / 误杀率。"""
    p = REPO_ROOT / "bench" / "security-bench.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    bm = d.get("bypass_matrix") or {}
    adv = d.get("adversarial") or {}
    try:
        return {
            "bypass_total": int(bm.get("total", 0)),
            "adv_false_pos": int(adv.get("false_pos", 0)),
            "adv_false_rate": float(adv.get("false_positive_rate", 0.0)),
        }
    except (TypeError, ValueError):
        return {}


def check_benchmark_consistency(truth: Dict[str, int]) -> List[str]:
    """核对各 README 的基准数字与存档一致。

    规则:
      - 含「绕过矩阵」语境的 README, 必须出现真值条数, 且不得出现旧漂移值 (2321/2310)。
      - 出现「误杀率 0.45% (5)」或旧「0.09% (1)」语境的 README, 必须出现正确值,
        且不得出现旧漂移值。
    无绕过矩阵段落的语种 README (ja/ko/zh-GAT) 不触发, 自然免检。
    """
    problems: List[str] = []
    if not truth:
        return problems
    bt = int(truth["bypass_total"])
    fp = int(truth["adv_false_pos"])
    for path in _readmes():
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        has_bypass_ctx = any(_BYPASS_KW_RE.search(ln) for ln in lines)
        has_fp_ctx = any(_FP_CORRECT_RE.search(ln) or _FP_WRONG_RE.search(ln) for ln in lines)
        seen_bypass_correct = seen_bypass_wrong = False
        seen_fp_correct = seen_fp_wrong = False
        for ln in lines:
            if _BYPASS_KW_RE.search(ln):
                for m in _NUMBER_RE.finditer(ln):
                    num = int(m.group(0).replace(",", "").replace(".", ""))
                    if num == bt:
                        seen_bypass_correct = True
                    if num in _OLD_BYPASS_TOTALS:
                        seen_bypass_wrong = True
            if _FP_CORRECT_RE.search(ln):
                seen_fp_correct = True
            if _FP_WRONG_RE.search(ln):
                seen_fp_wrong = True
        if has_bypass_ctx:
            if not seen_bypass_correct:
                problems.append(
                    f"{path.name}: 绕过矩阵条数未出现真值 {bt} (或仍含旧值)"
                )
            if seen_bypass_wrong:
                problems.append(f"{path.name}: 仍含旧绕过矩阵条数 (2321/2310)")
        if has_fp_ctx:
            if not seen_fp_correct:
                problems.append(
                    f"{path.name}: 对抗误杀率未出现真值 {fp} 条 (0.45%)"
                )
            if seen_fp_wrong:
                problems.append(f"{path.name}: 仍含旧误杀率 0.09% (1)")
    return problems


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
        bench = bench_truth()
    except Exception as exc:  # 环境问题: 无法读取真值
        print(f"[verify_doc_numbers] 无法读取代码真值: {exc}", file=sys.stderr)
        return 2

    problems = check_consistency()
    if bench:
        problems.extend(check_benchmark_consistency(bench))

    if args.json:
        # JSON 面向机器消费, 用 ensure_ascii=True 保证纯 ASCII ——
        # 否则日语片假名/韩语在 GBK(CP936)/CP932 控制台下, 父进程按 locale
        # 解码会直接 UnicodeDecodeError (见 tests/test_doc_numbers.py 的回归)。
        print(json.dumps(
            {
                "truth": truth,
                "bench_truth": bench,
                "claims": claims,
                "problems": problems,
            },
            ensure_ascii=True, indent=2,
        ))
    else:
        print(
            f"真值: 供应商 {truth['providers']} 家, 模型条目 {truth['models']} 条, "
            f"子命令 {truth['subcommands']} 个 (含嵌套共 {truth['subcommands_total']}), "
            f"扫描到 {len(claims)} 条断言"
        )
        if bench:
            print(
                f"基准真值 (bench/security-bench.json): 绕过矩阵 {bench['bypass_total']} 条, "
                f"对抗误杀 {bench['adv_false_pos']} 条 ({bench['adv_false_rate']}%)"
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
