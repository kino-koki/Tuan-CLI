# Parity 与差距分析（vs Claude Code）

> 本条目对应 `tuan_cli/parity_claude/`（7 文件/2276 行）、`docs/GAP-ANALYSIS-vs-ClaudeCode.md`。

## 是什么

青小团有一个**显式的 parity 矩阵**，逐项对标 Claude Code：

- `matrix.py`：`matrix.validate()` 返回 []（无未通过项），`matrix.summary()` 输出按状态计数（ahead/aligned/partial/gap/not_applicable）。
- `catalog.py`：能力目录（`M("...")` 条目，含 STATUS_GAP 等状态标记）。
- `evidence.py`：证据核对 `verify_evidence()`。
- `docs/GAP-ANALYSIS-vs-ClaudeCode.md`：差距分析文档。

## 为什么

"对比 Claude Code 是否对得起 0 星"需要**可验证的矩阵**而非主观吹嘘。parity 模块把"对齐/领先/差距"变成数字与断言，测试 `test_matrix_counts_unchanged` 钉死当前状态。

## 关键文件

| 文件 | 职责 |
|---|---|
| `parity_claude/matrix.py` | 矩阵校验 + 汇总 |
| `parity_claude/catalog.py` | 能力目录 |
| `parity_claude/evidence.py` | 证据核对 |
| `docs/GAP-ANALYSIS-vs-ClaudeCode.md` | 差距分析（活文档） |

## 卖点

- 矩阵断言可测试（`matrix.validate() == []`）。
- 领先项（ahead）明确列出（如安全闸门、零依赖实现、58 Provider、10 语言）。
- 差距项（gap）诚实标注，避免自欺。

## 局限

- `docs/GAP-ANALYSIS-vs-ClaudeCode.md` 已同步：slash 88 个、fork/loop/review 已接线、/agents CLI+slash 双入口（2026-11-15 核实）。
- 矩阵 summary 当前 `b_waves_done == ["B1"]`、`superiority_criteria.external_adaptive_red_team is False`（部分领先标准未达标）。
