# B3 XVI 备份分支重放评估（待决策 · 未实施）

> 状态：**评估报告，等待产品决策**。本文档只做分析，不改任何代码。
> 对象：`origin/parallel/b3-xvi-backup`（b5083de3，"B3 XVI: close outbound payload + inbound additionalContext side doors"）。
> 基线：合并基 `740f0763`；对照：`main`（60a93859）。

## 总体分类（213 个变更文件）

| 类别 | 数量 | 含义 |
|---|---|---|
| 已整合 | 71 | 备份与 main 的 blob 完全一致，重放无意义 |
| 双方演进 | 128 | 合并时冲突，已按 0.4.4 线裁决；备份侧差异 = 被刻意搁置的增量 |
| **未移植** | **14** | 备份独有 / main 自基线未动 —— 真正的"重放候选" |
| 备份中删除 | 0 | — |

## 14 个未移植文件明细（重放的全部真实增量）

### 生产代码（3 组）

| 文件 | 内容 | 评估 |
|---|---|---|
| `tuan_cli/sandbox/egress_allowlist.py` | B2 收尾：逐命令域名强绑定（strict allowlist）。补齐 `SandboxProfile` 只有 `network: bool`、裁决不带逐命令主机清单的缺口 | 真实安全增强；但合并时 main 刻意保留了 0.4.4 egress 线 —— 重放需与现行 `sandbox/egress*.py` 重新对齐，**不是纯 cherry-pick** |
| `tuan_cli/tools/permission_fusion.py` | 敏感文件纵深防御叠加层：原生 PermissionPolicy 仍是唯一决策源，allow+写类+敏感文件 → 升级 confirm | 设计克制（绝不降级放行），可独立引入；需接 `tools/permissions.py` 装配点 |
| `tuan_cli/ext/patterns_data/`（5 文件） | critical/extreme/high/medium 分级模式数据表 | 纯数据，跟随上述两者或 safety_score 使用 |

### 测试（6 文件，约 137 个用例）

`tests/test_b2_boundaries.py`(31)、`test_b2_egress_strict.py`(26)、
`test_b2s_egress_uniform.py`(25)、`test_b2su_decided_routing.py`(26)、
`test_b2su_write_boundary.py`(29)、`test_multi_path_fusion.py`、
`test_taint_exfil.py`（备份侧增强版；main 现行版自基线未变）。

测试依赖上述生产代码，**不能单独重放**。

## 128 个"双方演进"文件

这些文件在合并时已裁决取 0.4.4 线（含 hooks/triggers/lifecycle、security_*、
superagent、tui、slogans 等）。备份侧差异是**被刻意搁置的 B3 XVI 语义**
（outbound payload 收口、additionalContext 侧门关闭等）。全量重放 = 推翻
合并裁决，会重新引入已治理的静默吞异常与 egress 行为回退，**不建议**。

## 结论与建议

1. **不建议**整分支重放（71 个已整合 + 128 个已裁决，重放净收益为负）。
2. 若要取其精华，建议**按文件择优移植**，优先级：
   ① `permission_fusion.py`（独立、克制、低风险）
   ② `egress_allowlist.py`（需与现行 egress 线对齐后移植）
   ③ 对应测试随后补齐。
3. 移植后必须：护栏测试（235 模块 silent=0）保持绿、
   `test_sandbox*` / `test_safety_*` 全绿、版本号按发布流程递增。

## 备份分支处置

`origin/parallel/b3-xvi-backup` 与本地 `wip/merge-b3-xvi` 建议至少保留到
上述择优移植完成，再行归档/删除。
