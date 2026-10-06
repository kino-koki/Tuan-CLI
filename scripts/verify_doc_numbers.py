#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对外文档数字核对器 (把"宣称"与"代码真值"对齐的可执行化)。

背景: 独立评估发现对外文档存在不可核实的数量断言风险。本脚本把
"文档里的数字"与"代码里的真值"做机器可核对的比较, 让夸大无处藏身。

真值来源:
  - 供应商数: qingxiaotuan.models.provider_catalog.ALL_PROVIDERS
  - 模型条目: qingxiaotuan.models.provider_catalog.MODEL_LISTS 合计

检查对象: 仓库根目录 README*.md 中的供应商/模型数量断言。

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

# 各语言中"供应商"的写法 (README 十语言覆盖)
_PROVIDER_WORDS = (
    "providers?|供应商|供應商|プロバイダ|Anbieter|proveedores|fournisseurs|provedores|провайдер\\w*|프로바이더"
)
# 各语言中"模型"的写法
_MODEL_WORDS = (
    "models?|模型|モデル|Modelle|modelos|modèles|модел\\w*|모델"
)

_PROVIDER_CLAIM = re.compile(rf"(\d+)\s*(?:{_PROVIDER_WORDS})", re.IGNORECASE)
_MODEL_CLAIM = re.compile(rf"(\d+)\s*\+?\s*(?:{_MODEL_WORDS})", re.IGNORECASE)


def ground_truth() -> Tuple[int, int]:
    """从代码读取真值: (供应商数, 模型条目数)。"""
    from qingxiaotuan.models import provider_catalog as pc

    providers = len(pc.ALL_PROVIDERS)
    models = sum(len(v) for v in pc.MODEL_LISTS.values())
    return providers, models


def collect_numbers() -> Dict[str, int]:
    """对外暴露的真值字典 (供测试断言)。"""
    providers, models = ground_truth()
    return {"providers": providers, "models": models}


def _readmes() -> List[Path]:
    return sorted(REPO_ROOT.glob("README*.md"))


def scan_claims() -> List[Dict[str, object]]:
    """扫描所有 README 的数量断言, 返回结构化记录。"""
    out: List[Dict[str, object]] = []
    for path in _readmes():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in _PROVIDER_CLAIM.finditer(line):
                out.append(
                    {"file": path.name, "line": lineno, "kind": "providers", "value": int(m.group(1))}
                )
            for m in _MODEL_CLAIM.finditer(line):
                out.append(
                    {"file": path.name, "line": lineno, "kind": "models", "value": int(m.group(1))}
                )
    return out


def check_consistency() -> List[str]:
    """返回不一致描述列表; 空列表表示全部一致。

    规则:
      - providers: 断言值必须 == 真值 (51)。
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
    return problems


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核对对外文档中的数量断言")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    try:
        truth = collect_numbers()
    except Exception as exc:  # 环境问题: 无法读取真值
        print(f"[verify_doc_numbers] 无法读取代码真值: {exc}", file=sys.stderr)
        return 2

    problems = check_consistency()

    if args.json:
        print(json.dumps({"truth": truth, "problems": problems}, ensure_ascii=False, indent=2))
    else:
        print(f"真值: 供应商 {truth['providers']} 家, 模型条目 {truth['models']} 条")
        if problems:
            print(f"发现 {len(problems)} 处不一致:")
            for p in problems:
                print(f"  - {p}")
        else:
            print("全部一致。")

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
