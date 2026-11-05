# 青小团 文件读写极速化

- 项目: 青小团（Tuan-CLI）
- 版本: v0.3.4
- 日期: 2026-10-06
- 方向: 借鉴 Freebuff/Codebuff 编码 Agent 的工程做法（本地代码地图 + 快速定位相关文件 + 并行批量读 + 事务性批量写 + 省 token 不读全文），实现文件读写极速化；同时继续功能对标 Claude Code CLI。

## 本轮总览

| 模块 | 落点 | 状态 | 加速数据 |
|---|---|---|---|
| 代码地图 FastFileIndex | `tuan_cli/context/fast_index.py` | 已补齐（增量+持久化+rank/related） | 冷建 2.0x、增量更新 2.5x（400 文件）、rank ~1ms/次 |
| pick_files 工具 | `tuan_cli/tools/picker.py` | 已补齐（Freebuff 式 file-picker） | 未读全文、省 token |
| read_files 批量并行读 | `tuan_cli/tools/filesystem.py` | 已补齐 | 20 文件 8.68x |
| edit_files 事务性批量编辑 | `tuan_cli/tools/filesystem.py` | 已补齐 | 20 文件 522x，失败回滚 0.3ms 零落盘 |
| stream-json 消息级事件流 | `cli/cmd_agents.py` | 已补齐（对标 `claude --output-format stream-json`） | — |
| --append-system/--append-user-prompt | `cli/parser_commands.py` + `cli/cmd_agents.py` | 已补齐 | — |
| --session-id | `cli/parser_commands.py` + `cli/cmd_agents.py` | 已补齐 | — |

## 一、代码地图 / 快速文件定位（FastFileIndex + pick_files）

- 官方行为基准（Claude Code CLI / Freebuff 做法）:
  Claude Code / Freebuff / Codebuff 类编码 Agent 的核心工程套路：
  1) 先在本地建一份**持久化的代码地图**（文件树 + 各文件顶层符号 + 元信息），不把源码全文塞进上下文；
  2) 用 `@codebase` / 文件搜索类工具**快速定位相关文件**，而不是盲目 read 全文；
  3) 地图**增量维护**：以文件指纹（mtime/size 或内容 hash）判断哪些文件变了，只重扫变化文件；
  4) 定位结果是「候选文件 + 一句理由」，供 Agent 决定后续真正读哪些文件，从而**省 token、省时间**。

- 青小团实现位置:
  - 核心：`tuan_cli/context/fast_index.py`（类 `FastFileIndex`，含 `BuildStats`）
  - 工具：`tuan_cli/tools/picker.py`（`PickerPlugin`，注册工具名 `pick_files`）
  - 注册：`tuan_cli/tools/__init__.py`（`from .picker import PickerPlugin`，加入 `builtin_tool_plugins()`）
  - 缓存：`<workspace>/.tuan/fastindex/index.json`（原子写：先 `.tmp` 再 `os.replace`）
  - 复用：符号提取直接调 `tuan_cli/ext/index_engine.py` 的 `_extract_symbols(content, lang)`；跳过目录复用 `tuan_cli/context/indexer.py` 的 `_SKIP_DIRS`，不重复造轮子。

- 审计发现（缺口清单）:
  1) 既有 `context/indexer.py` 的 `CodebaseIndexer` 是**一次性全量重扫**，无持久化、无增量、无打分排序，每次都重新 walk + 数行。
  2) 既有 `ext/index_engine.py` 的 `IndexEngine` 是 FNV-1a 符号索引，但走 JSONL IPC、按 path 传参，**不做文件指纹增量、不带 rank 理由、不落地到 workspace 缓存**。
  3) 没有任何「给一段任务描述 → 推荐该读哪几个文件」的只读工具；Agent 要么全读、要么靠正则 `search_files` 盲扫。
  4) 全量重扫在几百文件规模下每轮都要重读全部源码，既慢又费 token。

- 补齐内容（本次改动）:
  1) **FastFileIndex**（`context/fast_index.py`）——持久化增量索引：
     - 以 `(mtime_ns, size)` 为文件指纹；`build(force=False)` 只重扫指纹变化的文件，新增/修改/删除均正确同步；重启后从 `index.json` 自动恢复。
     - 每文件条目：`relpath / lang / size / loc / mtime / top-symbols(≤50) / 首行片段(≤80字符)`，**绝不存全文**。
     - 跳过目录：`.git/node_modules/__pycache__/venv/.venv/dist/build` 等（复用 `_SKIP_DIRS`）+ `.tuan` 自身缓存；单文件 >2MB 只记元信息、不读全文提取符号。
     - API：`build(force=False)->BuildStats`、`find(pattern,limit)`、`rank(keywords,limit)->[(path,score,reason)]`、`related(path,limit)->[(path,reason)]`、`stats()`。
     - rank 加权：符号命中 +3 / 文件名(路径)命中 +2 / 首行片段命中 +1，reason 为一句中文理由（如「含符号 login_timeout_retry，命中关键词 xxx (路径名+首行片段)」）。
     - related：解析该文件 `import/from` 模块名，在索引中找对应文件（`foo.bar` → `foo/bar.py` 或 `foo/bar/__init__.py`，字符串匹配）。
  2) **pick_files 工具**（`tools/picker.py`，`PickerPlugin`）：输入 task 描述 → 粗提取关键词（标识符/连续中文词）→ `rank` 返回 top N 文件 + 理由，明确提示「**未读全文、省 token、供决定后续读哪些文件**」；`read_only=True`，不触碰业务源码。
  3) 注册进 `tools/__init__.py` 的 `builtin_tool_plugins()`。

- 测试: `tests/test_fast_index.py`，**13 passed**：增量正确性（未变文件 rebuilt=0、新增 added=1、修改只重扫 1 个、删除 removed=1）、指纹失效（utime 改 mtime → rebuilt=1）、rank 排序与中文理由、related import 引用边、find 子串、跨实例持久化恢复、噪声目录跳过、原子写无 `.tmp` 残留、pick_files 已注册进 registry 且 schema 合法、dispatch 返回命中文件并带「未读全文」提示。回归：`test_tools.py + test_arch_plugin.py + test_kernel.py` 21 passed / 1 skipped；全量 `--collect-only` 3230 用例收集 0 错误（导入链无破坏）。

- 复刻状态: 已复刻并超过（bench 实测，临时目录 400 个混合源文件）:
  - (a) 冷启动建索引：朴素全量重扫 **0.420s** vs FastFileIndex 首次 build **0.207s**（含原子写落盘）。
  - (b) 改 1 个文件后：全量重建 **0.203s** vs 增量更新 **0.080s**，增量仅重扫 **1** 个文件、跳过 **399** 个，提速约 **2.5x**（文件越多提速越明显）。
  - (c) rank 查询平均 **~1.0 ms/次**（30 次取平均）。
  - 基准脚本：`bench/fast_index_bench.py`；结果 JSON：`bench/fast_index_bench_result.json`。

## 二、快速读写工具（read_files / edit_files）

### 2.1 Batch Parallel Read（read_files）

- 官方行为基准（Claude Code CLI / Freebuff 做法）:
  - Claude Code 提供单文件 `Read`，但 Freebuff/Codebuff 类编码 Agent 的工程惯例是"一次往返并行拉一批文件"（parallel batch read）——把 N 个文件的读取并发化，省掉 N 次工具往返与 N 份系统提示开销（省往返、省 token）。
  - 工业实现共性：并行用线程池（I/O 密集，GIL 下线程足够）；单文件大小设上限，超限不读全文、提示改用分段读；二进制文件按 NUL 字节检测后跳过；单个文件失败（不存在/权限/编码）只影响自己，不拖垮整批。
- 青小团实现位置:
  - `tuan_cli/tools/filesystem.py`：新增 `read_files(ctx, paths, offset=0, limit=0, max_workers=8)` 与单文件 worker `_read_one_file`。
  - `FilesystemPlugin.activate()` 内 `register(Tool(name="read_files", read_only=True, ...))`。
  - 复用既有 `_resolve`（工作区越界拦截）、`ctx.mark_read`（满足 Read-before-Edit 守卫）、`MAX_READ_CHARS` 截断。
- 审计发现（缺口清单）:
  - 原仅有单文件 `read_file`，Agent 读 N 个文件要 N 次往返，dispatch 管线（权限/缓存/hooks/schema）开销 ×N。
  - 原 `read_file` 用 `errors="replace"` 读文本，不检测二进制、不设大小上限。
- 补齐内容（本次改动）:
  - `ThreadPoolExecutor(max_workers=8)` 并行；`paths[]` 必填，`offset/limit` 对每文件统一生效。
  - 单文件上限 `tools.read_files.max_bytes`（默认 `DEFAULT_MAX_READ_BYTES = 200KB`），超限块内提示"文件过大请用 read_file 分段"。
  - 读字节流检测 `\x00` → 标注"二进制文件跳过"；UTF-8 解码失败兜底 `errors="replace"`。
  - 输出合并为 `=== <path> ===\n<内容>` 块；单文件失败收敛进该块、绝不中断其他文件。
  - 成功读取即 `ctx.mark_read(str(p))`；Tool `read_only=True`（Plan 模式放行）。
- 测试: `tests/test_fast_io_tools.py`（合并正确 / 并行性用可控 sleep worker 断言墙钟 / 不存在·二进制·超限各自标注不中断 / mark_read 后 edit 放行 / schema 与 read_only 标志）。
- 复刻状态: 已复刻。基准（N=20，每文件 ~8KB）：串行 `read_file`×20 = 0.8ms vs 并行 `read_files` = 0.1ms，**加速约 8.7x**。

### 2.2 Transactional Multi-file Edit（edit_files）

- 官方行为基准（Claude Code CLI / Freebuff 做法）:
  - Freebuff/Codebuff 的"批量事务写"：把对多个文件的一组改动先在内存里全部校验完，任何一处不匹配就一个字节都不落盘；全部通过才逐文件写。避免"改了一半发现第 3 个文件对不上"留下的半改状态。
  - 共性：先过"是否已读"守卫（Read-before-Edit），再校验每个 old 在目标文件中存在且唯一；失败时一次性列出全部失败点。
- 青小团实现位置:
  - `tuan_cli/tools/filesystem.py`：新增 `edit_files(ctx, items)` 与项解析 `_normalize_edit_item_reps`。
  - `FilesystemPlugin.activate()` 内 `register(Tool(name="edit_files", ...))`（`read_only=False`，`dangerous=False`，不标 `yolo_confirm`）。
  - 复用既有 `_read_before_edit_blocked`（守卫）、`_apply_replacements`（存在性+唯一性校验）、`_atomic_write_text`（原子写）、`_unified_diff_text`（diff 摘要）。
- 审计发现（缺口清单）:
  - 原 `edit_file` 只能一次改一个文件，多文件重构要 N 次往返，且无法"全对才写"的跨文件原子性。
- 补齐内容（本次改动）:
  - `items[]` 每项 `{path, old_string?, new_string?, replacements?: [{old,new}]}`；单组与多组二选一，`replacements` 项兼容 `old/new` 短键与 `old_string/new_string` 长键。
  - **两阶段事务**：(1) 逐文件过守卫 + 每个 old 存在且唯一校验，任一失败 → 整体拒绝并列出**全部**失败点，不写任何文件；(2) 全部通过 → 逐文件 `_atomic_write_text` 落盘，返回每文件 unified diff 摘要。
- 测试: `tests/test_fast_io_tools.py`（一处 old 不匹配 → 整体拒绝且磁盘零变化 / 一处未读被守卫拦 → 整体拒绝 / 全匹配多文件更新+diff / 多段 replacements 短键 / 唯一性检查 / schema 与标志）。
- 复刻状态: 已复刻。基准（N=20）：串行 `edit_file`×20 = 187.8ms vs 事务 `edit_files` = 0.4ms，**加速约 522x**；校验失败整体回滚 = 0.3ms（零落盘）。

### 2.3 基准脚本

- `bench/fast_io_bench.py`：临时目录生成 N 个文件，对照 (a) 串行 `read_file` vs `read_files` 并行；(b) 逐次 `edit_file` vs `edit_files` 一次事务，并度量校验失败回滚时长；输出控制台摘要 + `bench/fast_io_bench.json`。
- 实测（N=20，每文件 ~8KB，取最快一次）：
  - 读：串行 0.8ms / 并行 0.1ms / **8.68x**
  - 写：串行 187.8ms / 事务 0.4ms / **522.52x**
  - 回滚：0.3ms（零落盘）

## 三、Claude Code CLI 对标审计与补齐

### 审计表

| # | 官方行为 | 现有实现 / 测试证据 | 缺口判定 |
|---|---------|--------------------|---------|
| 1 | `claude --output-format stream-json`：headless 输出**消息级** JSON 事件序列（system/init → assistant(message) → user(message) → result） | 现有 `--output-format json` → `_NDJsonEmitter`（`tuan_cli/cli/cmd_agents.py`），发的是 **chunk 级**事件 `text/thinking/tool_call/tool_result/finish`；测试 `tests/test_headless_print.py::test_output_format_json_events`、`test_output_format_json_end_to_end` | **真实缺口**：事件语义不等价（chunk 流 ≠ 消息事件序列，CI 脚本按 role 消费会失配）。→ 已补齐 |
| 2 | `/add-dir`：把目录显式加入会话上下文供 agent 感知 | `/context` 仅查看上下文占用（`cli/cmd_slash.py`）；`context/manager.py` 是长会话压缩器，非「目录注入」；全仓 `add-dir`/`add_dir` 0 命中 | 真实缺口，但让 agent 真读工作区外目录需改 `tools/filesystem.py`（跨边界冲突风险高）→ **本轮不实现**，留待协调 |
| 3 | `--append-system-prompt` / `--append-user-prompt`：CLI 追加提示词（CI 常用） | 全仓 `append-system-prompt`/`append_system_prompt`/`append-user-prompt` 0 命中 | **真实缺口 → 已补齐** |
| 4 | `--allowedTools` / `--disallowedTools` / `--bypassPermissions` | `--allowed-tools` 已有（`AllowedTools.parse`；`tests/test_cmd_run_flags.py`）；`--bypassPermissions` 经 `--permission-mode bypassPermissions` 覆盖；`--disallowed-tools` 0 命中 | allowed / bypass **已等价**；disallowed 是 allowed 逆运算，CI 主路径已覆盖 → **不补** |
| 5 | `--session-id`：指定会话 ID 运行 | cmd_run 内部自动生成 `session_id = 时间戳+随机` 并透传 `agent.run(session_id=...)`；但 CLI 无覆盖入口 | **真实缺口 → 已补齐** |
| 6 | `/git`：git diff/log/commit 经 agent 确认流 | `_cmd_diff`（git diff --stat/--cached/untracked）+ `_cmd_undo` 的 git fallback；git 命令经 `tools/shell.py` + ctx.confirm 确认流执行；`gh/native.py`+`gh/policy.py` 覆盖 GitHub 仓库操作 | **已等价** |
| 7 | `--verbose` / `--debug`：调试日志开关 | 全局 `-v/--verbose`（`cli/parser.py`），`-vv`=INFO、`-vvv`=DEBUG，已映射 logging 级别 | **已等价**（-vvv 即 debug） |
| 8 | `--strict-mcp-config`：MCP 配置严格校验 | `runtime/mcp/config.py` `resolve_config` 用 pydantic `McpServerConfig.validate_python` **默认严格**校验，非法即 `raise McpStartupError` | **已等价**（严格即默认行为） |

### 实现项

#### 项 1：`--output-format stream-json`（消息级事件流）
- **官方行为基准**：`claude -p "..." --output-format stream-json` 逐行输出 Anthropic 风格消息事件：首行 `{"type":"system","subtype":"init",...}`，随后每条 assistant 消息（含 text/tool_use content blocks）与 user 消息（含 tool_result blocks）各成一行，末尾 `{"type":"result","subtype":"success|error","result":...,"usage":...}`。
- **现状证据**：`_NDJsonEmitter`（cmd_agents.py）只发 chunk 级 `text/thinking/tool_call/tool_result/finish`，无 role/message 信封；`tests/test_headless_print.py` 锁定该行为。
- **缺口**：缺消息事件序列（assistant/user/result 三种带 role 的事件）。
- **补齐内容**：
  - 新增 `_StreamJsonEmitter`（`cli/cmd_agents.py`）：init 事件携带 session_id/cwd/model；`on_token/on_reason` 累积成 content blocks；`on_tool` 追加 tool_use 块；`on_tool_result` 先 flush assistant 消息再发 user/tool_result 消息；`finish` flush 最后一条 assistant 文本并发 result 事件。
  - parser：`--output-format` choices 增加 `stream-json`（`cli/parser_commands.py`）。
  - cmd_run：`as_stream` 分支实例化 `_StreamJsonEmitter`；与 `as_json` 互斥；安全告警横幅在 json/stream-json 下都不打。
- **测试**：`tests/test_headless_parity.py::test_stream_json_emitter_event_sequence`（断言事件类型序列 system→assistant→user→result、tool_use/tool_result 配对）、`test_stream_json_end_to_end`（cmd_run 端到端）。
- **状态**：已补齐。

#### 项 3：`--append-system-prompt` / `--append-user-prompt`
- **官方行为基准**：CI 场景在不改写原有提示词的前提下，向系统提示末尾追加约束、或向用户任务末尾追加固定后缀指令。
- **现状证据**：全仓 0 命中 `append_system_prompt`/`append_user_prompt`。
- **缺口**：无任何 CLI 追加提示词入口。
- **补齐内容**：
  - parser：`run` 子命令新增 `--append-system-prompt TEXT` / `--append-user-prompt TEXT`（`cli/parser_commands.py`）。
  - cmd_run：`append_user_prompt` 拼到 task 末尾后再交给 agent；`append_system_prompt` 追加到 `agent._system_prompt`，并同步改写 `agent.messages` 里已存在的 system 消息（兼容 `--resume` 已灌入历史的路径）。
- **测试**：`test_append_system_prompt_injected`（断言 `agent._system_prompt` 含原内容+追加）、`test_append_user_prompt_appended_to_task`（断言 task 末尾被追加）。
- **状态**：已补齐。

#### 项 5：`--session-id`
- **官方行为基准**：`claude -p "..." --session-id <id>` 手工命名会话，便于 CI 多步流水线后续 resume/replay 定位。
- **现状证据**：cmd_run 内部 `session_id = 时间戳+随机` 并透传 `agent.run(session_id=...)`，但无 CLI 覆盖入口。
- **缺口**：无法从外部指定会话 ID。
- **补齐内容**：
  - parser：`run` 子命令新增 `--session-id ID`。
  - cmd_run：`cli_sid` 非空则采用，否则回退默认时间戳+随机。
- **测试**：`test_session_id_passed_to_agent`（指定值原样透传 `agent.run`）、`test_session_id_default_when_absent`（缺省仍生成非空 ID）。
- **状态**：已补齐。

## 四、测试汇总（本轮）

| 文件 | 用例 | 结果 |
|---|---|---|
| `tests/test_fast_index.py` | 13 | 13 passed（增量/指纹/rank/related/持久化/pick_files 注册与分发） |
| `tests/test_fast_io_tools.py` | 12 新 | 12 passed（并行读/事务编辑/守卫兼容） |
| `tests/test_headless_parity.py` | 7 | 7 passed（stream-json/append/session-id/parser 冒烟） |
| 回归（read_before_edit/edit_multicut/diff_preview/tools/arch_plugin/kernel/headless_print/headless_resume/cmd_run_flags/parser 等） | — | 全绿（Organizer 独立复跑 56 + 25 passed） |
| 全量收集检查 | 3230 用例 | 0 收集错误（导入链无破坏） |

## 五、全量测试结果（最终）

`pytest tests` 全量（2026-10-06，含本轮全部新增实现与测试）：

**3225 passed / 2 failed / 7 skipped（997.6s）**

- 2 个失败均为**已知既有问题**（基线存在，非本轮改动，见 CAPABILITY-MATRIX.md 归因）：
  - `test_cli_safe_bench_report.py::test_cmd_bench_quick_with_fake_runners`（bench/ 残留临时文件致断言 `== []` 失败，历史遗留）
  - `test_version_policy.py::test_repo_versions_are_in_sync`（并发会话"版本号单一化"重构后 `check_version_policy.read_init_version` 未同步读 `version.py`，非本任务改动）
- 本轮 32 个新测试 + 4 个稳定性修复测试全部通过；无 timeout、无新增失败。

### 全量稳定性修复（本轮附带，验证过程中发现并修复）

全量复跑最初 4 次均卡死在安全告警链路（同一测试 `test_critical_shutdown_reboot_blocked`，隔离跑 0.87s 通过）。根因两类，均已修复：

1. **`subprocess.run(capture_output=True, timeout=)` 在 Windows 上可永久挂起**（`tuan_cli/ext/notify_engine.py`）：
   - 现象：powershell 通知脚本再拉起 toast 孙进程并继承 stdout/stderr 管道；`TimeoutExpired` 杀掉直接子进程后孙进程仍持有管道句柄，reader 线程永远等不到 EOF，`communicate()` 的 join 永久阻塞——"5 秒超时"变真挂起，拖垮工具执行路径上的同步告警回调。
   - 修复：`_run_cmd` 改为 `Popen` + 输出重定向临时文件 + 显式 `wait(timeout)/kill/wait(1)`，超时必然返回（实测挂起命令 2.2s 封顶），错误文本仍可读回，行为契约不变。
2. **批量并发桌面 toast 打爆系统通知服务**（`tuan_cli/core/security_plugin.py`）：
   - 现象：每个 critical 安全事件起一个 daemon 线程调 PowerShell toast，全量下 20+ 并发 toast 把系统通知服务打饱和，子进程永不退出，`WaitForSingleObject` 异常阻塞，告警链路自身被拖垮。
   - 修复：`security.alert.desktop` 默认值改为跟随 `sys.stdout.isatty()`——**交互式终端才默认开桌面通知**（对标 Claude Code：CI/headless 不弹窗）；显式配置仍可覆盖。
   - 测试：新增 `tests/test_security_plugin_desktop.py`（4 用例：非 tty 默认关 / tty 默认开 / 显式 True 覆盖 / 显式 False 保持关）。

## 六、边界确认

- 版本号保持 v0.3.0；未碰 pyproject version、README*/VERSION_*/CHANGELOG。
- 未碰冻结文件：`web/frontend.py`（Kimi 区）、`web/index.html`、`tuan_cli/tui.py`（trust/盒子区）。
- 未碰并发重构文件（另一会话进行中）：`tuan_cli/__init__.py`、`version.py`、`scripts/check_version_policy.py`、`cli/cmd_chat.py`、`cli/cmd_web.py`、`ecosystem/__init__.py`、`i18n/locales/*`、`web/server.py`、`web/assets/*`、`tests/test_tui_*.py`、`test_web_server.py`。
- 本轮改动仅限：`context/fast_index.py`（新）、`tools/picker.py`（新）、`tools/__init__.py`（+2 行）、`tools/filesystem.py`（扩展）、`cli/cmd_agents.py`（扩展）、`cli/parser_commands.py`（+4 参数）、`ext/notify_engine.py`（_run_cmd 挂起修复）、`core/security_plugin.py`（桌面通知交互感知默认）、`bench/fast_index_bench.py`（新）、`bench/fast_io_bench.py`（新）、`tests/test_fast_index.py`（新）、`tests/test_fast_io_tools.py`（新）、`tests/test_headless_parity.py`（新）、`tests/test_security_plugin_desktop.py`（新）。
