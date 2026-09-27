# qxt 命令精简对照表（2026-09-27）

本次为**保守精简**：只删冗余 / 实验性 / 低价值 / 与核心命令重叠的顶级入口，
**不动底层模块**，不影响微内核插件注册与既有测试。精简前约 48 个顶级子命令，
精简后保留 36 个核心高频命令。

## 一、删除的 12 个顶级命令

| 原命令 | 去向 | 理由 |
|---|---|---|
| `qxt arch` | 删除（文件 `cmd_arch.py` 已删） | 五层架构演示，实验性 / 开发者向，普通用户不用；内核插件 `arch/plugin.py` 仍在 |
| `qxt ext` | 删除（`ext_cli.py` 保留为模块，不再注册 CLI 入口） | 外部引擎调试，开发者向；`qxt --help` 不再出现 |
| `qxt others` | 删除（`cmd_others.py` 已删） | 能力目录，与 `qxt help` 完全冗余 |
| `qxt code-edit` | 删除（`cmd_code_edit.py` 已删） | 代码编辑助手，与 `dev` / `dev codedev` 功能重叠 |
| `qxt impact` | 合并入 `qxt undo --impact` | 操作账本展示；斜杠命令 `/impact` 保留 |
| `qxt mode` | 删除，改用 `qxt config get mode` / `qxt config set mode yolo` | 查看/切换模式，与 config 冗余 |
| `qxt open <file>:<line>` | 删除（IDE 自带定位行） | 低价值 |
| `qxt replay` | 合并入 `qxt session replay` | 回放历史会话 |
| `qxt trajectory` | 合并入 `qxt session trajectory` | 轨迹导出 |
| `qxt compact` | 合并入 `qxt doctor --compact` | 上下文压缩存活自检 |
| `qxt bench` | 删除 CLI 入口（实现函数保留于 `cmd_setup.py` 供测试） | 基准测试，niche / 低频次 |
| `qxt codedev` | 合并入 `qxt dev codedev demo\|doctor\|retrieve\|verify` | 代码开发子系统独立顶级入口 |

## 二、合并后的新入口

| 新用法 | 等价旧用法 | 实现位置 |
|---|---|---|
| `qxt session replay [id] [--json] [--export PATH] [--list]` | `qxt replay ...` | `cmd_session.py`（`session_cmd == "replay"` 分支） |
| `qxt session trajectory show\|export ...` | `qxt trajectory ...` | `cmd_session.py`（`session_cmd == "trajectory"` 分支） |
| `qxt doctor --compact [--workspace DIR]` | `qxt compact --verify` | `cmd_doctor.py`（调用 `runtime.session.compact_survival`） |
| `qxt undo --impact` | `qxt impact` | `cmd_agents.py`（`cmd_undo` 复用 `cmd_impact`） |
| `qxt dev codedev demo\|doctor\|retrieve\|verify` | `qxt codedev ...` | 隐藏解析器 `__dev_codedev`，`main()` 透明改写 argv |

> 说明：`dev` 的 `task` 是自由文本位置参数，无法在其 ArgumentParser 上直接挂
> subparsers（否则任意任务首词会被 argparse 当作未知子命令）。因此 codedev 子命令组
> 由隐藏顶层解析器 `__dev_codedev` 承载，`main()` 入口把 `dev codedev ...` 无感知地
> 改写过去。用户侧仍是 `qxt dev codedev ...`，`qxt --help` 不暴露该隐藏解析器。

## 三、保留的 36 个核心命令

`acp`, `web`, `dev`, `run`, `agent`, `bg`, `setup`, `doctor`, `onboarding`,
`commands`, `models`, `config`, `plugin`, `skill`, `memory`, `cron`, `mcp`, `hooks`,
`undo`, `improve`, `session`, `usercmd`, `agents`, `rewind`, `project`, `chat`,
`worktree`, `safe`, `gh`, `tutorial`, `harden`, `migrate`, `network`（含 `net` 别名）,
`help`, `upgrade`, `permissions`。

## 四、文件改动清单

- 修改：
  - `qingxiaotuan/cli/parser.py`：删 12 个注册块；新增 session replay/trajectory、
    dev codedev（隐藏解析器 + argv 改写）、doctor `--compact`、undo `--impact`。
  - `qingxiaotuan/cli/commands.py`：删 `cmd_mode`/`cmd_others`/`cmd_code_edit`/
    `cmd_impact` 路由；新增 `cmd_codedev` 路由。
  - `qingxiaotuan/cli/cmd_session.py`：迁入 replay / trajectory 分支。
  - `qingxiaotuan/cli/cmd_doctor.py`：迁入 `--compact` 存活自检。
  - `qingxiaotuan/cli/cmd_agents.py`：`cmd_undo` 支持 `--impact`。
  - `qingxiaotuan/cli/cmd_chat.py`：删 `cmd_mode` 函数。
- 删除：`cmd_arch.py`, `cmd_others.py`, `cmd_code_edit.py`, `cmd_replay.py`,
  `cmd_trajectory.py`, `cmd_compact.py`。
- 保留（实现仍在，仅 CLI 入口精简）：`cmd_codedev.py`（dev codedev 实现）、
  `ext_cli.py`（模块保留）、`cmd_setup.py` 中的 `cmd_bench`/`cmd_open`（既有测试直接调用）。

## 五、测试

- 新增 `tests/test_command_consolidation.py`：校验 12 个已删命令解析报错、36 个保留
  命令仍在、新合并入口可解析。
- 调整 `tests/test_parser.py`、`tests/test_compact_survival.py`、`tests/test_cron_cli.py`
  中对已删命令的直接引用。
- 底层能力测试（`test_arch_*.py`、`test_codedev*.py`、`test_replay.py`、
  `test_trajectory.py`、`test_code_edit.py` 等）不受影响，保持可运行。
