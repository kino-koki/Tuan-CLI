# 评测基准 (bench)

本目录含两类基准：

1. **安全基准（安全优先路线的核心证据）**：`safety_bench_10k.py`（10k 对抗样本）、
   `bench_powershell_safety.py`（5k PowerShell 样本）、`bypass_matrix.py`（2310 手工绕过载荷 + 灾难后果级断言）。
   全部**本地可复现**：`qxt safe bench` 一条命令串跑三套件并汇总，`qxt safe report` 生成自包含 HTML 报告。
   第三方可在本仓库原样复现，不依赖网络与模型。
2. **SWE 能力基准**：`run.py` + `tasks.yaml`，用本地 SWE 任务量化「真实编程能力」，可与 Claude Code 横向对比。
   框架本身**不依赖外网**：任务声明在 `tasks.yaml`，运行器在临时工作区里启动真实 `qxt run` 子进程，
   再执行验收脚本判定通过/耗时/成本。

## 安全基准（一键复现）

```bash
qxt safe bench            # 全量 (~3 分钟): 10k 对抗 + 5k PS + 2310 绕过矩阵
qxt safe bench --quick    # 快速自检 (~30 秒, 对抗样本 2000 条)
qxt safe report           # 自包含 HTML 安全报告 (可分享/存档)
```

- `safety_bench_10k.py --count N --seed 20260906 --out X.json`：bash/通用命令对抗样本，输出拦截召回/标记召回/误杀率/绕过。
- `bench_powershell_safety.py`：5000 条（危险 2300 / 安全 2700），写 `ps_safety_result.json` + `ps_safety_report.html`。
- `bypass_matrix.py --json-out X.json`：手工对抗载荷 + 按灾难后果类别断言实际拦截率。

当前代码实测（2026-09-19）：对抗 10k → 拦截召回 100% / 标记召回 100% / 误杀率 1.87% / 绕过 0；
PS 5k → 正确率 100% / 漏放 0 / 误杀 0；绕过矩阵 2310 → 绕过 0 / 误杀 1 / 灾难类别 100% 拦截。
数字以 `qxt safe bench` 本地重跑为准。

## 快速开始

```bash
# 1) 仅校验框架与任务定义 (不调用模型)
python bench/run.py --dry

# 2) 真实跑测 (需先 qxt setup 配好模型端点)
python bench/run.py

# 3) 只跑单个任务 / 指定模型 / 指定 qxt 路径
python bench/run.py --task fix_bug
python bench/run.py --model deepseek/deepseek-chat
python bench/run.py --qxt .venv/Scripts/qxt.exe

# 4) 机器可读输出
python bench/run.py --json
```

## 任务定义 (tasks.yaml)

每个任务字段：

| 字段 | 含义 |
| --- | --- |
| `id` | 任务标识 |
| `instruction` | 给 agent 的自然语言指令 |
| `files` | 工作区初始化文件 (`相对路径: 内容`) |
| `check` | 验收 shell 命令，退出码 0 = 通过 |
| `timeout` | 单任务超时（秒）|

四类覆盖：理解 / 修 bug / 补测试 / 多文件重构。

## 对比 Claude Code（自动双跑）

**`vs_claude.py` 把「同一任务集双跑」自动化**：同一份 `tasks.yaml`、同一组验收脚本，
在隔离工作区分别用 `qxt run -p` 与 `claude -p --output-format json` 执行，输出
通过率 / 耗时 / 成本 / 权限拒绝数对比，并渲染 md / json / html 三份报告。

```bash
# 1) 校验框架与任务定义 (不调用模型, 不探测 claude)
python bench/vs_claude.py --dry --qxt .venv/Scripts/qxt.exe

# 2) 真实双跑 (需 qxt 配好可用模型端点; claude 需可用)
python bench/vs_claude.py --qxt .venv/Scripts/qxt.exe

# 3) 只跑单任务 / 指定模型 / 指定 claude 可执行
python bench/vs_claude.py --task fix_bug --model openrouter/deepseek/deepseek-chat
python bench/vs_claude.py --claude "C:\Users\me\claude.cmd"

# 4) 机器可读 / 跳过 claude 探测
python bench/vs_claude.py --json --no-html
python bench/vs_claude.py --skip-probe          # 不探测 claude, 直接逐任务真跑
```

**诚实性约定（可复验）**：双跑前先探测 claude 是否真能完成一轮调用；探测失败时
Claude 侧如实标注 **N/A** 并写明原因，绝不假装跑过。报告里的数字只有在你本机
跑通两端点后才有意义——这也正是「可复现测量」的一部分。

**Windows 注意**：npm 安装的 claude 是 `.ps1`/`.cmd` shim，脚本会自动解析真实
可执行路径；老版本 claude 不支持 `--no-input`，脚本已统一用 stdin 重定向替代。

旧的手工流程（`qxt /cost` + `claude --cost` 填表）保留如下，供无自动化环境的场合：

| 任务 | (通过/耗时/成本) | Claude Code(通过/耗时/成本) |
| --- | --- | --- |
| understand_api |  |  |
| fix_bug |  |  |
| add_test |  |  |
| refactor_util |  |  |

## 注意

- 真实跑测需要可用的模型端点（OpenAI 兼容 / Anthropic / 本地）。无端点时请用 `--dry` 校验框架。
- 验收脚本越「行为化」（跑 pytest / 断言真实输出）越能反映真实能力；不要只用「文件存在」做验收。
- `check` 在改完代码后的临时工作区执行，与 CI 语义一致。
