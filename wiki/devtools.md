# 开发者工具

> 本条目对应 `tuan_cli/cli/subcommands/`、`tuan_cli/ext/`、`tuan_cli/kernel_patch/`、`tuan_cli/ports/`。

## 是什么

青小团的工程化工具面：

- **doctor**：环境自检（诊断 Provider、路径、依赖）。
- **bench**：性能基准（bench_report）。
- **integrity**：完整性校验（源码/依赖/测试）。
- **checkpoint**：检查点（会话断点）。
- **evolve**：进化闭环（`tuan evolve run/report`）。
- **safe bench --quick**：安全不降级快速回归。
- **ext/**：外部工具（safety_redline、check_shell_true 等）。
- **kernel_patch/**：内核热补丁。
- **ports/**：可移植性适配。

## 为什么

"世界最强"不仅靠功能，还靠**可运维**：环境诊断、性能基准、完整性校验、安全检查点让项目能持续演进而非烂掉。

## 关键文件

| 文件 | 职责 |
|---|---|
| `cli/subcommands/` | 子命令分组 |
| `ext/safety_redline.py` | 安全红线 |
| `kernel_patch/` | 内核补丁 |
| `ports/` | 可移植性 |
| `scripts/check_shell_true.py` | shell 真伪检查（33/0/0 锚点匹配） |

## 卖点

- doctor/bench/integrity/checkpoint/evolve 全接线。
- `safe bench --quick` 安全不降级回归。
- check_shell_true 根治（锚点匹配，33/0/0）。

## 局限

- 部分工具依赖外部引擎/环境，偶发争用（环境相关）。
