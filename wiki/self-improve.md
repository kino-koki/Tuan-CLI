# 反思性自我进化闭环

> 本条目对应 `tuan_cli/self_improve/`（11 文件/1601 行）、`tuan_cli/cli/cmd_evolve.py`。

## 是什么

AGENT-EVOLUTION-ROADMAP 阶段 A：**执行 → 自评 → 改进 → 回归验证** 的可循环闭环（Hermes 技能自进化理念的强化版）：

- **Evaluator**（`evaluator.py`）：对一次任务产物做结构化自评（正确性/完整性/性能/风格维度打分），产出 `EvaluationResult`。
- **RegressionGate**（`regression_gate.py`）：改进前后跑同一任务集，对比评分，只接受净改进（fail-safe：回退劣化）。
- **EvolutionLoop**（`evolution_loop.py`）：调度 evaluator → 生成改进候选 → 应用 → 回归验证 → 接受/回滚，记录到 `self_improve/evolution_ledger.jsonl`。
- **CLI**（`cmd_evolve.py`）：`tuan evolve run <task>` / `tuan evolve report`。
- 蒸馏/规则/技能生成（`self_improve/` 其余文件）。

## 为什么

让青小团**从经验中成长**，而非静止的"功能集合"。闭环保证只接受**净改进**（劣化自动回滚），是"世界最强"在自我进化维度的体现。

## 关键文件

| 文件 | 职责 |
|---|---|
| `self_improve/evaluator.py` | 评测器 |
| `self_improve/regression_gate.py` | 回归验证器 |
| `self_improve/evolution_loop.py` | 进化循环驱动 |
| `cli/cmd_evolve.py` | evolve CLI |
| `self_improve/evolution_ledger.jsonl` | 进化账本 |

## 卖点

- 只接受净改进（fail-safe 回滚劣化）。
- 进化账本落盘（jsonl）。
- 15 个进化闭环测试通过（阶段 A 验收）。

## 局限

- 进化候选生成依赖评测器打分，需任务集定义良好才能有意义。
- 无外部自适应红队（superiority_criteria.external_adaptive_red_team is False）。
