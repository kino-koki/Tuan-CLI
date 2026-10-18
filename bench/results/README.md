# bench/results/ —— 安全基准时间序列存档

> 本目录存放 `tuan safe bench --json`（全量模式）每次运行的汇总结果快照，
> 命名 `security-bench-<UTC时间戳>.json`。同一份数据也写入
> `bench/security-bench.json`（最新存档，`--check` 门禁对比对象）。

## 用途

- **趋势可回看**：安全数字的单点快照没有说服力，时间序列才能展示「改进/回归」。
- **CI 消费**：CI 作业跑 `tuan safe bench --json`（退出码即回归门禁），
  把 `bench/results/` 新快照提交回仓库，安全历史自动积累。
- **第三方复跑**：任何人在任意时刻 clone 仓库，都能看到数字的历史演变与
  对应代码状态（配合 git 提交历史）。

## 约定

- 只有**全量模式**（未带 `--quick`）才写存档 —— quick 是本地自检，不进时间序列。
- 快照内容与 `security-bench.json` 结构完全一致（含 `engine`、`generated_at`、
  `seed`、`quick` 字段），可被 `bench/` 下的脚本直接解析。
- 禁止手工编辑/删除历史快照；需要回滚数字口径时另开新版本字段。
