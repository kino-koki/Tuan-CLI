# 运行时标语（Spinner Verbs）与 TUI 缺陷修复

> 本轮主题来自用户提供的一条 B 站视频标题：**「给 Claude Code 转圈的英文挂上中文后，
> 我发现它在摸鱼」**。视频正文未获取（页面只返回播放器框架），所以本文不转述
> 视频内容；「同款」的依据是可公开查证的 Claude Code spinner verbs 资料与社区
> 中文译名整理，来源列在 §7。

---

## 1. 「同款」到底指什么

Claude Code 在等待模型时，spinner 旁会随机显示一个英文动名词，而不是
`Loading…`：

```
🌑 Marinating…
🌒 Lollygagging…
🌓 Whatchamacalliting…
```

- v2.1.42 内置约 **185 个** spinner verbs，分烹饪、认知、自然、科学、
  舞蹈、荒诞自嘲等语义场；官方文档（code.claude.com / platform.claude.com）
  **不收录**这份词表，它属于 UI 彩蛋。
- `~/.claude/settings.json` 的 `spinnerVerbs: {mode: "replace"|"append",
  verbs: [...]}` 可自定义（v2.1.23+）；`replace` 加 `verbs: [""]` 可只留转圈、
  清空文字。
- 中文社区把整份词表译成中文后，「游手好闲 / 磨洋工 / 溜达 / 撒欢 /
  看报纸中」集体露馅 —— 这就是标题里「摸鱼」的梗。

**关键事实**：这些词**只是 spinner 动画的随机装饰**，不对应任何阶段，
也不代表任何进展。「看起来在忙」和「真的在动」是两件事。

---

## 2. 本项目做了什么，以及刻意做不同的地方

新增 `tuan_cli/tui/runtime_slogans.py`（纯标准库、无新依赖），并接入
`tuan_cli/tui/tui.py` 的顶部 HUD。同款的部分：spinner 旁挂中文标语、
`spinnerVerbs` 配置键名一致、`off/replace/append` 三种模式、10 种界面语言。

**刻意不同、也是本轮最值钱的一点：文案由真实事件驱动，不靠定时器空转。**

| | Claude Code | Tuan-CLI |
|---|---|---|
| 换词触发 | 定时随机 | `submit` / 流式分片 / `begin_tool` 等**真实事件**；同阶段按 `interval_ms` 节流 |
| 阶段含义 | 无 | `booting` / `waiting_model` / `streaming` / `running_tool` / `retrying` |
| 无进展时 | 继续换词，看起来仍在忙 | 超过 `stall_ms` **如实**显示「疑似摸鱼 · 已 N s 没收到模型/工具/流式的任何动静」 |
| 每帧重绘 | 动画继续 | `render()` 是纯读，**不会换词**、不推进序号 |
| 本地化 | 英文单语（用户可自行替换） | 10 语言全覆盖，中文词池保留摸鱼梗 |

幽默归幽默，诚实归诚实：中文词池里照样有「正在腌制入味 / 正在磨洋工 /
正在看报纸中 / 正在那个啥来着」，能复现视频的笑点；但一旦真的没进展，
标语会**自己揭穿自己**，顺便给用户一条「可能卡在网络或死循环」的实用诊断。

---

## 3. 配置

`~/.tuan/settings.json`（键名与上游同款，便于迁移）：

```json
{
  "spinnerVerbs": {
    "mode": "append",
    "verbs": ["正在给团队写周报", "正在假装很忙"],
    "interval_ms": 1800,
    "stall_ms": 15000
  }
}
```

| 字段 | 取值 | 说明 |
|---|---|---|
| `mode` | `default` / `append` / `replace` / `off` | `default` 用内置词库；`off` 只留转圈、清空文字 |
| `verbs` | 字符串数组（≤200 条） | 自定义词；`append` 追加在内置池后，`replace` 完全替换 |
| `interval_ms` | 200–60000，默认 1800 | 同阶段最短换词间隔 |
| `stall_ms` | 1000–600000，默认 15000 | 无真实事件多久后给「疑似摸鱼」诊断 |

`TUAN_HOME` 环境变量可改配置目录。任何非法配置（mode 拼错、verbs 非列表、
数字越界、文件损坏）**都回落到出厂配置并在 `source` 标注 `invalid:*`**，
既不让 TUI 崩，也不静默生效。

---

## 4. 安全：标语是要渲染进终端的文本

`sanitize_verb()` 在写入终端前严格净化，避免自定义词变成转义序列注入口：

- 去掉 **OSC 8 超链接**（`ESC ] 8 ;; … BEL/ST`）、**CSI**（`ESC [ … m/J`）、
  C0 / C1 / DEL 控制字符；
- 非字符串输入、空串一律丢弃；
- 按**显示列宽**截断（CJK 算 2 列，上限 40 列），不是按字符数硬切。

这延续了 `tui/inputkit/terminal_hyperlinks.py` 的教训：上游 `web()` 不校验
OSC 目的地，而终端会解释执行这些序列。标语走的是同一条输出通道，不能例外。

---

## 5. 十语言覆盖

每个语言、每个阶段都有独立词条，**不把英文 fallback 冒充本地化**：

| 语言 | waiting_model 示例 | 无进展诊断示例 |
|---|---|---|
| zh-CN | 正在腌制入味 / 正在磨洋工 / 正在看报纸中 | 疑似摸鱼 · 已 18s 没收到… |
| zh-TW | 正在醃製入味 / 正在摸魚 | 疑似摸魚 · 已 18s… |
| en | Marinating / Lollygagging / Whatchamacalliting | Possibly slacking · no event for 18s |
| ja | 漬け込み中 / サボり中 / 新聞読み中 | サボり疑い · 18 秒間… |
| ko | 재우는 중 / 땡땡이 중 / 신문 보는 중 | 땡땡이 의심 · 18초간… |
| es | Marinando / Holgazaneando | Posible holgazanería · … |
| pt-BR | Marinando / Enrolando | Possível enrolação · … |
| fr | On marine / On tire au flanc | Ça flâne peut-être · … |
| de | Mariniert / Macht blau | Möglicherweise blau · … |
| ru | Маринуется / Бездельничает | Похоже, бездельничает · … |

中文 `waiting_model` 池 16 条，一半正经（琢磨 / 沉吟 / 反刍）、一半摸鱼梗，
其余阶段各 6–8 条；其他语言每阶段 4–9 条。

---

## 6. 顺带修掉的三个真实 TUI 缺陷

这三个都是**实测复现**，不是补文档：

### B1 错误注释 + 有界缓存（**性能数字不适用于远端主线**）
`_display_width` 的文件头旧注释声称 `wcwidth.wcswidth`「内部是 C 实现」——
**不对**。`wcwidth` 0.8.x 的 `wcswidth()` 是纯 Python，对串中每个字符做
`wcwidth()` 表查找 + bisect。本次修正该注释，并加 **有界** LRU（4096 条）
作第二层保险；有界是刻意的，不加 `maxsize` 会让长会话无上限持有历史字符串。

**如实边界（必须读）**：远端主线的 `_line_heights` **已经自带**
`(width, text)` 高度缓存，历史行在流式期间绝大多数不变，每帧只在首次
miss 时调用 `_display_width`。「16.2 ms/帧超预算 → 0.39 ms/帧、命中
13999/14000」这组数字来自**本地分叉副本**（它缺了主线的高度缓存），
**不适用于本次推送的远端主线**，不得当作本提交的性能成果。
本次推送里 B1 的真实内容只有：修正错误注释 + 加有界缓存保险。

### B2 状态口径分裂（最贴合「摸鱼」主题）
`_render_footer` 把 `busy/streaming` 判定放在 `running` 之前，而
`begin_tool()` 同时置 `_busy = True` —— 于是 `_running` 分支成了**死代码**：
明明在跑 `git status`，底栏却显示「思考中」。修为工具名优先，状态与真实活动
一致。

### B3 两套宽度算法
`_disp_width`（`prompt_toolkit.get_cwidth` 逐字）与 `_display_width`
（wcwidth 整串）并存：**视口切片按 A 算法、单行裁剪按 B 算法**，组合字符 /
emoji ZWJ / 控制字符下会算错行高、顶破布局。更糟的是旧 fallback
`return len(text)`，prompt_toolkit 缺失时中文按 1 列算，欢迎盒右边框必然错位。
现在全 TUI 只有一个宽度真值来源。

---

## 7. 合规与来源

- 灵感来自用户提供的 B 站视频标题（BV1F8nB6fEc1）；**视频正文未获取**，
  本文不转述其内容。
- spinner verbs 的事实（约 185 词、`settings.json` 的 `spinnerVerbs` 接口、
  官方文档不收录、`mode: replace/append`、v2.1.23+ 可定制）来自公开资料：
  Coding Cocoon《Every Spinner Verb in Claude Code》、quidproquo 的 185 词
  分类整理、Clauder Navi 的配置说明、阿里云开发者社区与多篇中文整理。
- 中文词池里「腌制入味 / 磨洋工 / 看报纸中 / 那个啥来着 / 光合作用中 / 闲庭信步」
  等**短词条**借鉴自公开社区对这 185 个词的中文译名（如
  `taekchef/claude-code-zh-cn` 的 `verbs/zh-CN.json`）。这些是事实性短 UI 文案，
  不是源码、混淆产物或商标资产；其余词条、阶段划分、10 语言自译、事件驱动
  引擎与 stall 诊断均为本项目独立编写。
- **未复制任何 Claude Code 源码**；Anthropic 不背书、不赞助本项目
  （`NOTICE` 第 15 条）。A 线 Codex TUI 对齐仍按 `NOTICE` 第 9–13 条
  Apache-2.0 / MIT 处理，两条线许可口径互不混用。

---

## 8. 验证

```
tests/test_runtime_slogans.py   57 例全绿（在「远端基线 + 本轮改动」副本实测）
引擎独立验证               19 项全绿（纯 stdlib，不依赖 pytest / 第三方运行时）
```

覆盖：10 语言 × 5 阶段词库完整性、OSC/CSI/C0/C1 净化、配置非法值拒绝、
替换/追加/关闭模式、阶段切换与节流、**render 100 次纯读不转词**、
stall 诊断与本地化、确定性 seed、三个 TUI 缺陷的针对性回归。

### 如实边界

1. `stall` 是**启发式诊断**，不是心跳或超时控制：它只反映「TUI 没收到事件」，
   无法区分模型慢、网络挂、工具卡死，也不触发任何中断或重试。
2. 事件只接了 `submit` / `stream_assistant` / `begin_tool` 三处；若某条执行
   路径完全绕过 TUI 事件回调，仍可能被误判为无进展。
3. `off` 模式只留转圈；`_clip_parts` 仍会对超长诊断文案做单行裁剪。
4. 本轮**没有**新增 CLI 子命令，子命令总数断言不变（51 / 含嵌套 197）。
5. `CLAUDE_PARITY.md` 的 99 模块基线**未改**：spinner verbs 属 UI 文案层，
   作为 B10 `statusline` 的前置实现记录在 §11，不靠新增模块凑领先数。
6. 远端 `_render_header` 是 Codex 风格 `_working_status_line()`（`Working (Ns
   • esc to interrupt)`），不是月亮 spinner；标语挂在其后，`off` 模式只留
   状态行。测试已按主线适配，不沿用本地分叉副本的月亮帧断言。

---

## 9. 推送范围与分叉说明（重要）

本提交基于远端真实 HEAD `8611d5ddf4537275290e16481b26537a7faed380` 逐文件
比对 tree 后**增量提交**：不改写历史、不删除任何远端文件、不 force push。

核查中发现**本地工作副本与远端主线存在实质分叉**：

| 文件 | 远端主线 | 本地副本 |
|---|---|---|
| `tuan_cli/tui/tui.py` | 4694 行 | 2563 行 |
| `tuan_cli/ext/safety_patterns.py` | 1784 行 | 833 行 |
| `tuan_cli/ext/safety_normalize.py` | 928 行 | 635 行 |
| `bench/security-bench.json` | 476 行 | 1844 行 |

直接覆盖会把主线已有的功能回退掉。因此：

- **本提交只含 11 个文件**：3 个新增（`runtime_slogans.py`、
  `test_runtime_slogans.py`、`RUNTIME_SLOGANS.md`）、1 个在**远端基线原文**上
  精确应用 11 处改动的 `tui.py`、7 个在**远端基线原文**上追加的文档。
- 此前若干轮次在本地副本上的改动（B2/B3 边界能力、稳定基线 113 项、
  hooks 扩展等）**没有推送**，另打成离线补丁包，需人工决定是否合并。
- 逐文件差异审查里 21 个「远端独有内容 > 12 行」的文件全部跳过，未覆盖。
- 远端 tree 中仍存在 `PROVENANCE.md` 与
  `GIT_HISTORY_RECONSTRUCTION_AUDIT.md`（早前清理似被 merge 回退）。本轮
  **没有删除任何文件**，是否清理需你确认后再单独提交。


---

## 10. 深度轮：把「疑似摸鱼」做成可信的活性判定

> 本轮按「不再执着于广度而放弃深度」执行：**没有新增模块、没有新增
> CLI 子命令、99 模块基线 / `fully_superior` / 任何对齐指标一律不动**。
> 只把 §2 那条「事件驱动」往下挖。

### 10.1 上版其实还是很浅

上版做了「绑 3 个事件 + 一个固定 15 秒阈值」，看起来诚实，实际有四个洞：

| | 上版 | 本轮 |
|---|---|---|
| 并发 | 5 个可变字段无锁复合读写，GIL 只保证单条赋值原子 | `RLock` 全线性化 + 单调化时钟 + `(seq, verb)` 不变量 |
| 阈值 | 所有阶段一律 15s | 分阶段预算 + `slow_ratio` 三态 |
| 输出 | 一句字符串 | `Liveness` 结构化快照 + 脱敏证据链 + 分类建议 |
| 事件面 | 只接 3 处 | 补 `note_progress` 生命周期事件，`_animate` 明令禁止 |

### 10.2 并发：为什么 GIL 不够

`note_activity` 从 UI 线程（submit）、模型线程（流式）、工具线程
（`begin_tool`）并发进入，`render` 从动画 invalidate 线程进入。
`self._current = self._pick(phase)` 与 `self._seq += 1` 是两条字节码，
中间会切线程 —— 渲染线程可能读到「新 seq + 旧文案」，或间隔判断读到
半更新的 `_last_change_at`。这不是理论风险：8 线程 × 2400 次并发用例
专门用证据里的 `(seq, verb)` 配对来抓撕裂。

另外补了**时钟单调化**：乱序事件 / 时钟回拨会让 `idle_ms` 变负、预算错乱，
现在把 `at` 钳到不早于 `_last_event_at`。

### 10.3 分阶段预算（D2）

| 阶段 | 预算 | 为什么 |
|---|---|---|
| `booting` | 30s | 加载内核本就要时间 |
| `waiting_model` | 45s | 等首个 token 最慢，冷启动/排队都可能 |
| `streaming` | 6s | 分片断了就是异常，6s 足够暴露 |
| `running_tool` | 120s | 编译/测试/拉取本来就跑很久 |
| `retrying` | 20s | 回炉重试的合理等待 |

`healthy → slow → stalled` 三态：`slow` 发生在预算 × `slow_ratio`
（默认 0.5）之后，**仍显示标语、不报摸鱼**，header 只用 textdim 变暗；
只有真超预算才给 warning 诊断。这样「比预期慢」不会被冤枉成「在摸鱼」。

配置优先级：**显式 `stall_ms`（全局覆盖）> `phase_budgets_ms` 逐项 >
分阶段表 > 兜底**。显式写 `stall_ms` 的旧配置继续生效，不被新表悄悄吃掉。
未知阶段键整段拒绝，不静默忽略。

### 10.4 结构化判定与脱敏（D3）

`liveness()` 返回与 `busy` 无关的快照：阶段、静默时长、预算、
`slow_after_ms`、剩余、按阶段区分的 10 语言建议、完整诊断行、
最近 16 条证据。文案只是它的渲染。

**证据脱敏是硬要求**：`detail` 可能是 `begin_tool(name)` 乃至未来的工具
参数（路径、命令、token）。证据只记 `detail_len` 与 `detail_class`
（empty / ascii / cjk / mixed），绝不记原文；时间用 `time.monotonic()`
毫秒，不含墙钟。证据只在进程内存里，不落盘、不上传、不进审计日志。

`SloganView` 保留原 6 个位置字段与语义，新增字段全带默认值 ——
旧调用方零改动。

### 10.5 事件面与「不空转」硬约束（D4）

`note_progress()` 只刷新活性时间戳、**不改阶段、不换词、不推进 seq**，
给 `end_tool` / `end_stream` 用，修掉「工具结束 → 下一事件」间隙的误判。

**绝不从 `_animate` 调用 `note_activity` / `note_progress`**：动画循环每
120ms 跑一次，一旦在那里刷新时间戳，「疑似摸鱼」就永远不报，
整个功能退回它本来要反对的定时空转。有源码级回归（剥离注释后检查
`_animate` 函数体）守住这条线。

### 10.6 顺带修的第三个真缺陷

`load_config` 旧逻辑把「没写 `mode`」一律当 `append`，而 `append`
强制 `verbs` 非空 —— 用户只想收紧 `stall_ms`、或只写
`phase_budgets_ms`，整段配置就被判 `invalid:empty-verbs`，
**静默回落出厂值**：以为收紧了，其实什么都没变。这种「假安全感」
比直接报错更危险。现在：给了 `verbs` 但没写 `mode` 才推断 `append`；
两者都没给就是 `default`（内置词库）。

### 10.7 其他深化

- `reset()` 跨回合**保留**证据链并记一条 `reset` 分隔，使「上一回合
  为什么卡住」可回放；上版把证据一起清了。
- `reload()` 显式热重载：原子切换，非法配置保留旧配置并返回原因，
  词池变化时不沿用旧文案。**刻意不做文件监听/轮询** —— 长驻 TUI 里
  后台轮询会引入 I/O 线程与竞态，收益却只是省一次显式调用。
- `QxtTUI.liveness()` 透传供 doctor/调试；不新增 CLI 子命令。
- header 三态分级：`stalled` → warning，`slow` → textdim，
  `healthy` → primary。文案与裁决都不变。

### 10.8 验证与边界

```
tests/test_runtime_slogans.py   93 例全绿
verify_deep.py                  22 项纯 stdlib 独立验证全绿
                                （含 8 线程 × 2400 次并发不变量）
py_compile                     全部通过
```

- `stall` 仍是启发式可观测提示，**不是安全闸门、心跳或超时控制**，
  不触发中断/重试，不改变任何裁决。
- `slow` 只是视觉降级；证据链只在进程内存；`reload()` 需显式调用。
- 验证副本骨架是本地分叉（离线跑测试用），`tui.py` 与
  `runtime_slogans.py` 用的是**远端主线基线 + 本轮改动**；
  不是真机 TUI 长跑，Windows / 终端能力组合仍未实测。
- 本轮**没有**合并上轮 `local_fork_unmerged/` 里的分叉改动；
  远端 `PROVENANCE.md`、`GIT_HISTORY_RECONSTRUCTION_AUDIT.md` 原样保留。
