# B3 XVI 备份分支重放评估（已核实 · 结论：无需移植）

> 状态：**评估完成**。初版曾把 `permission_fusion.py` / `egress_allowlist.py`
> 误判为「未移植候选」—— 分类脚本对 `m == b`（main 自基线未动）与
> `m is None`（文件不存在）未加区分导致误读。本文为逐文件核实后的修正版。
> 对象：`origin/parallel/b3-xvi-backup`（b5083de3）；基线 `740f0763`；对照 `main`。

## 总体分类（213 个 base→backup 变更文件，blob 级核实）

| 类别 | 数量 | 含义 |
|---|---|---|
| 已整合 | 71 | 备份与 main 的 blob 完全一致 |
| 双方演进 | 124 | 合并时冲突，已按 0.4.4 线裁决；main 版本为后续精修 |
| main 未动 | 9 | main 保持基线版本（含 2 个纯路径搬迁的文档） |
| 备份中删除 | 9 | main 保留（如 test_multi_path_fusion、test_taint_exfil），全部在跑且绿 |

## 两个曾疑似「待移植」文件的核实结论

- `tuan_cli/tools/permission_fusion.py`：main 已有且**已接线**
  （`tools/base.py` 经 `build_permission_policy()` 装配，`tools/__init__.py` 导出）。
  备份侧差异仅为删一行类型注解注释与措辞调整 —— 无可移植增量。
- `tuan_cli/sandbox/egress_allowlist.py`：main 版本更优 —— 拒绝理由更明确
  （含「逐命令域名声明」归因），`profile_domains` 同时接受 NetworkClaim 与
  SandboxProfile（备份版只收 NetworkClaim，属收窄）。备份侧差异是简化，不采。

## 其余「main 未动」文件

- `CAPABILITY-MATRIX.md` / `TUI_PARITY.md`（根目录副本）：main 已把内容
  迁至 `docs/parity/`，路径变化而已，非缺口。
- 5 个 B2 测试（test_b2_boundaries / test_b2_egress_strict /
  test_b2s_egress_uniform / test_b2su_decided_routing / test_b2su_write_boundary）：
  main 保留基线版并实测通过；备份侧改动是配合其被否决的 egress 简化，不采。

## 最终验证

- 上述全部测试在 main 实测：**221 passed, 1 skipped**
  （含 B2 五件套、multi_path_fusion、taint_exfil）。
- 治理护栏（silent=0 / SEC fallback=0）、版本/shell/引擎同步门禁全绿。

## 结论

1. **无需任何移植**：B3 XVI 的有效增量已在 main（合并时取新），被搁置部分
   经逐文件比对均为简化/措辞差异，不构成回 port 理由。
2. `origin/parallel/b3-xvi-backup` 与 `wip/merge-b3-xvi` 的历史使命已完成，
   可归档；删除与否由维护者定（删除不影响 main）。
