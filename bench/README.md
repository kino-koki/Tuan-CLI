# 评测基准 (bench)

本目录含两类基准：

1. **安全基准（安全优先路线的核心证据）**：`safety_bench_10k.py`（10k 对抗样本）、
   `bench_powershell_safety.py`（5k PowerShell 样本）、`bypass_matrix.py`（2497 手工绕过载荷 + 灾难后果级断言）、
   `realistic_usage_bench.py`（15 族随机化真实使用命令，良性主导，多个独立随机种子报分布而非单点）。
   全部**本地可复现**：`tuan safe bench` 一条命令串跑五套件并汇总，`tuan safe report` 生成自包含 HTML 报告。
   第三方可在本仓库原样复现，不依赖网络与模型。
2. **SWE 能力基准**：`run.py` + `tasks.yaml`，用本地 SWE 任务量化「真实编程能力」，可与 Claude Code 横向对比。
   框架本身**不依赖外网**：任务声明在 `tasks.yaml`，运行器在临时工作区里启动真实 `tuan run` 子进程，
   再执行验收脚本判定通过/耗时/成本。

## 安全基准（一键复现）

```bash
tuan safe bench            # 全量 (~5 分钟): 10k 对抗 + 5k PS + 2497 绕过矩阵 + 6k 真实使用 + 跨平台可移植性
tuan safe bench --quick    # 快速自检 (~40 秒, 对抗样本 2000 条)
tuan safe report           # 自包含 HTML 安全报告 (可分享/存档)
```

- `safety_bench_10k.py --count N --seed 20260906 --out X.json`：bash/通用命令对抗样本，输出拦截召回/标记召回/误杀率/绕过。
- `bench_powershell_safety.py`：5000 条（危险 2300 / 安全 2700），写 `ps_safety_result.json` + `ps_safety_report.html`。
- `bypass_matrix.py --json-out X.json`：手工对抗载荷 + 按灾难后果类别断言实际拦截率。
- `realistic_usage_bench.py --count N --seeds M --out X.json`：15 族真实使用命令（git / 文件操作 / 搜索 /
  Python / Node / 容器 / 构建 / 环境变量 / 链式 / 管道 / 重定向 / sudo / 网络 / 模糊 / 危险 / 须确认），
  词汇表全部随机化，`--seed0` 缺省时用 `SystemRandom` 真随机。输出**跨种子分布**：硬拦误杀占良性比例、
  真危险命令召回、模糊命令命中、延迟分位。这是唯一回答「开发者每跑 65 条命令会不会被拦 1 次」的套件——
  对抗矩阵问的是「攻击挡不挡得住」，问不了这个问题。
- `indep_verify.py`：**独立对抗验证**（不引用项目任何数据文件，27+ 条自行构造的混淆载荷与良性命令），
  针对「混淆还原」这一核心声称做第三方交叉复核。漏拦 (MISS) 记为硬缺陷、误杀 (FP) 逐条人工判读。
- `tests/test_platform_portability.py`（第 5 套件，直接跑 pytest，~8 秒）：**跨平台可移植性检查**。
  在**本机**上跑 274 条 POSIX / Linux / macOS 载荷（`/etc/shadow`、`~/.ssh/id_rsa`、`/dev/tcp` 反向 shell、
  Linux 账户提权、macOS `csrutil`/`kextload`/`security` 等），断言判定与预期一致；另含两个结构性检查：
  检测层（engine/classifier/guard/patterns/redline）**不得引用** `os.path`/`ntpath`/`platform.system`/`os.name`，
  唯一碰文件系统的分支是 `safety_normalize._resolve_symlinks`（已跳过绝对路径以规避 Windows 盘符改写）。

### 关于基准的自我限定（诚实声明）

前三套基准的数据集均由**本项目自行构造**（随机种子生成 + 手工矩阵）。
`bypass=0` 的正确定读法是「挡得住本项目构造的样本」，**不等于**「挡得住任意真实攻击面」。
`indep_verify.py` 是对此局限的补充：它用外部视角独立构造载荷，但它同样是有限的样本集，
仍不能替代真实红队测试。引用本目录任何数字时，请一并带上数据集来源这一限定。

**平台限定（同样重要）**：上面所有数字都只在 **Windows** 上实测过，Linux/macOS 从未实机运行。
存档 `security-bench.json` 现在带 `platform` 字段（`system` / `release` / `machine` / `python`），
引用时请一并核对。能给出的最强证据是第 5 套件 `tests/test_platform_portability.py`：
检测层是**纯字符串正则**（不调用 `os.path`、不读平台环境变量、不区分盘符），
同一份正则 + 同一个 `re` 引擎 + 同样的输入字符串，在 Linux 上的判定结果与本机必然一致——
这个断言由结构性检查（禁止检测层引用平台 API）和 274 条 POSIX 载荷在 Windows 上的判定共同锁定。
**唯一例外**是归一化阶段 `safety_normalize._resolve_symlinks` 的 `os.path.realpath()`，
它读文件系统、行为随平台与工作目录变化，但该函数已跳过所有绝对路径
（Windows 上 `realpath('/')` 会解析为 `E:\\`，改写后反而破坏红线正则的 `/` 锚点）。
因此「检测判定跨平台一致」是有依据的推论，而「Linux/macOS 端到端可用性」仍**未被实机验证**——
本套件只回答前者，不声称后者。

当前代码实测（2026-10-25，`tuan safe bench` 一次全量运行，存档 `bench/security-bench.json`）：
对抗 10k（seed `20260906`，钉死可复现）→ 拦截召回 **100%** / 标记召回 **100%** /
误杀 **5 (0.45%)** / **绕过 0**，5 条全为 `flag`，**0 条硬拦误杀**（其中 4 条是同一个
`tar|ssh` 良性用例的程序化前缀变体）；
PS 5k → 正确率 100% / 漏放 0 / 误杀 0；
绕过矩阵 2497 → 绕过 0 / 误杀 1 / 灾难类别 100% 拦截。

真实使用（4 个独立随机种子 × 1500 = 6000 条，真随机不进门禁）：**三次独立运行**分别是
0.24% – 0.39% / 80.6% – 91.2% / 10.4 ms（16 条硬拦）；
0.23% – 0.32% / 90.0% – 100.0% / 15.4 ms；
本次存档的 **0.16% – 0.31%**（中位 0.27%）/ **87.5% – 97.4%**（中位 93.1%）/ **20.6 ms**（13 条硬拦），
**静默放行 0 条**。三次运行都满足「**没有任何危险命令被静默放行**」这个不变量，
而召回与延迟随种子与机器负载浮动，这正是本套件按区间报告、且不进 CI 门禁的原因。
13 条硬拦误杀 **100% 来自同一个钉死策略** `ssh user@host 'cmd'` → `net:deny`
（`tests/test_security_network_ownership.py` 断言 `deny_remote_exec=True`），属产品决策而非缺陷。

第 5 套件跨平台可移植性 → **274 项全部符合预期**（含 2 项结构性检查：检测层零平台 API 引用、
`os.path.realpath` 仅存于归一化层）。存档带 `platform` 字段（Windows 10 / AMD64 /
Python 3.11.5）与 `portability` 字段（passed 274 / failed 0 / rc 0）。

数字以 `tuan safe bench` 本地重跑为准。

### 一条容易被忽略的教训：别用「改标签」来修基准

2026-10-25 排查时发现一次险些发生的**基准弱化**：D.编码绕过里有两条载荷

```bash
$(echo cm0gLXJmIC8= | base64 -d)
`echo cm0gLXJmIC8= | base64 -d`
```

曾被怀疑是「引擎误杀」并一度移到良性类。实测否证（bash 5.3，命令替换在**命令位置**会执行）：

```bash
$ echo before
$ $(echo "echo DECODED")   # 打印 DECODED —— 解码串被当成程序执行了
$ echo after
```

只有当替换被**引号包着作为 echo 的参数**时才是纯文本：`echo "hello $(echo X) world"`。
所以这两条留在 D.编码绕过 (expect=block) 是对的，引擎判 block 也是对的。

**顺带查出真漏放**：当时发现这两条在基线里其实是 `risk=none` 全放行 —— 引擎确实漏了。
根因是 `_normalize` 剥掉 `$(` 前缀时把 `echo` 一并吃掉，`_ECHO_B64_PIPE_RE` 匹配失败，
`_is_base64_pipeline_dangerous` 的两个分支全部失效。已在 0.3.2 改为「含 base64 解码即先
尝试解码，解出红线即判危险」，并连带修好 `bash -c "$(echo <b64> | base64 -d)"` 一族；
本矩阵 D 类新增 12 条变体锁回归。

结论：**看到基准里「不该报错的报错」，先怀疑标签，但一定用真实 shell 验证再动手。**
改一个标签的代价远低于它让一个攻击类别从 bypass 统计里消失的代价 ——
这次的教训是双向的：怀疑对了（是漏放不是误杀），但验证动作不能省。
同类方法论陷阱见 `tests/test_yaml_shim.py` 开头：差分测试若拿会被重绑定的 `safe_load`
当基准，会永远绿灯。

## 快速开始

```bash
# 1) 仅校验框架与任务定义 (不调用模型)
python bench/run.py --dry

# 2) 真实跑测 (需先 tuan setup 配好模型端点)
python bench/run.py

# 3) 只跑单个任务 / 指定模型 / 指定 tuan 路径
python bench/run.py --task fix_bug
python bench/run.py --model deepseek/deepseek-chat
python bench/run.py --tuan .venv/Scripts/tuan.exe

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
在隔离工作区分别用 `tuan run -p` 与 `claude -p --output-format json` 执行，输出
通过率 / 耗时 / 成本 / 权限拒绝数对比，并渲染 md / json / html 三份报告。

```bash
# 1) 校验框架与任务定义 (不调用模型, 不探测 claude)
python bench/vs_claude.py --dry --tuan .venv/Scripts/tuan.exe

# 2) 真实双跑 (需 tuan 配好可用模型端点; claude 需可用)
python bench/vs_claude.py --tuan .venv/Scripts/tuan.exe

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

旧的手工流程（`tuan /cost` + `claude --cost` 填表）保留如下，供无自动化环境的场合：

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
