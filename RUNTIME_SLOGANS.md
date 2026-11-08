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


---

## 11. 深度轮 2：把「净化」也做成可信边界

> 继续「不扩广度、只挖深度」：无新增模块、无新增 CLI 子命令、
> 无对齐指标变化、`fully_superior` 仍 false。

### 11.1 先复现，再修（6 类实测）

| # | 缺陷 | 实测输入 | 旧输出 |
|---|---|---|---|
| 1 | bidi 覆写 / isolate 泄漏 | `正常\u202e话反` | 原样输出 `\u202e`，终端重排方向 |
| 2 | 零宽 / BOM / WJ / 软连字符泄漏 | `摸\u200b鱼` | `摸\u200b鱼` |
| 3 | 非 CSI/OSC 的 ESC 序列 | `\x1b(B正常` | `(B正常`（残留参数） |
| 4 | 组合标记开头（docstring 声称做了） | `\u0301accent` | `\u0301accent` |
| 5 | 按码点截断切断 grapheme | `e\u0301`×60 | 尾部孤立 `\u0301` |
| 6 | 第三套宽度算法 | `👩\u200d💻` | 算 5 列，wcwidth 算 2 列 |

### 11.2 净化层重写

剥序列顺序：**OSC(BEL/ST) → CSI → 通用 ESC → C0/C1**，再按 Unicode
通用类别删 `Cc / Cf / Cs / Co / Cn`（bidi 与全部零宽都在 `Cf`），
拒绝开头连续组合标记，删除**变体选择符**，最后按 grapheme 簇在
**簇边界**上同时满足 40 列 / 48 码点双上限。

**幂等是构造出来的**：`_sanitize_once` 迭代到不动点，最多 3 轮；
不收敛 fail-closed 返回空串。`f(f(x)) == f(x)` 是净化函数最该守的性质，
否则 `load_config` 存词与 `reload` 换词池会在两条路径上得到不同结果。
500 串 fuzz 0 例不幂等。

### 11.3 宽度真值收口（S2）

上一轮 B3 合并了两套算法，`sanitize_verb` 里的 `_char_cols` 是漏网的
第三套。新增纯 stdlib `display_cols()`，并加 **500 串交叉回归**：

```
display_cols(sanitize_verb(x)) == tui._display_width(sanitize_verb(x))
```

实测发现 `VS16` 会让 wcwidth 把 `❤` 从 1 列升到 2 列，而
`east_asian_width` 实现给 1 列 —— 净化层删掉变体选择符后两边完全一致，
500 串 0 不一致。刻意不 import wcwidth、不做运行时注入：引擎要能被
`verify_deep2.py` 这类纯 stdlib 脚本独立验证，也不该为对齐宽度引入
全局可变状态（那会破坏 D1 的并发不变量）。

**代价如实说**：emoji 呈现序列（`❤️`、`👩‍💻`）会被拆成文本样式。
短 UI 文案里选「宽度可预测 + 零不可见字符」优先。

### 11.4 补齐上一轮承诺的短版诊断（S3）

上一轮写了「header 只显示短文案、完整诊断放 `diagnostic`」，但
`render()` 实际把 `_STALL_TEXT` 整串塞进 `text`：中文约 52 列，
比 40 列上限还长，窄终端下关键秒数被 `_clip_parts` 裁没。
**更根本的是内置诊断文案绕过了净化层** —— 净化留了一道侧门。

- 新增 10 语言 `_STALL_SHORT` 与 `SloganView.headline`（默认空串，
  `text` 保持完整诊断，旧调用零改动）。
- 新增 `_fit_headline()`：自定义 verbs 与内置诊断共用同一出口，
  都过净化 + 40 列约束。
- `header` 诊断态不再挂 `Working (Ns • esc)`：那条「还在工作」字样
  正是本诊断要戳破的假象，且约 35 列会挤掉诊断；改为短锚点 +
  `headline`。普通态 Codex 状态行完全不动。40 列窄终端回归验证
  诊断完整可读、plan badge / 长模型名让位。
- 完整信息仍在 `view.diagnostic` 与 `Liveness.diagnostic`（含预算、
  剩余、按阶段分类的可操作建议）。

### 11.5 配置严格化（S4）

1 MiB 读取上限；`_strict_int` / `_strict_ratio` 拒绝 `bool` 冒充
`int`、字符串数字、浮点截断、`NaN`/`Infinity`；`phase_budgets_ms`
的值同样严格。自定义 verbs 与 10 语言内置词库共用同一套净化/列宽
不变量并已自检。

### 11.6 验证与边界

```
tests/test_runtime_slogans.py   139 例全绿
verify_deep2.py                 20 项纯 stdlib 独立验证全绿
其它 TUI 回归                   291 passed / 4 failed（4 个经隔离验证
                                在上一轮 tui.py 上同样存在，属分叉副本
                                与主线代码线错配的既有失败，与本轮无关）
```

- VS16 删除会让 emoji 呈现退化成文本样式（见 §11.3）。
- 不是真机 TUI 长跑；Windows / 终端能力组合未实测。
- `stall` 仍是启发式可观测提示，不是安全闸门/心跳/超时控制。
- 上轮分叉改动仍未合并；远端 `PROVENANCE.md` 等原样保留；
  第三方自适应红队仍未做。


---

## 12. 与 1108 条标语库的对应（「每个标语都要对应的」）

用户给了一套 15 文件的标语库 (860 条), 实测它**零真实接入点**:
包在根目录 `slogans/` 而 docstring 写 `tuan_cli.ui.slogans`,
13 处「接入」全是 docstring 示例, `pick("totally.unknown")` 静默飘
`'Here.'`, 日语 `bg.progress` 拿到英文。本轮把它接进同一套体系,
完整对应表见 `SLOGAN_MAPPING.md`。

### 净化层抽取（本引擎的唯一改动）

前两轮 (§10 / §11) 做成的净化层抽到
`tuan_cli/ui/slogans/_clean.py`, 本模块改为 **re-export 同一批函数
对象**:

```
runtime_slogans.sanitize_verb is _clean.sanitize_verb   → True
runtime_slogans.display_cols  is _clean.display_cols    → True
runtime_slogans._fit_headline is _clean._fit_headline   → True
```

原因: 新标语库 1108 条词条也要进终端, 再写一套净化就是**第三套宽度/净化
真值** —— 正是 §11.3 刚消灭的东西。`mapping.audit().sanitizer_shared`
把「同一出口」变成运行时断言。**139 例回归全部照常通过**,
公共 API 一个没少, 事件驱动 / 三态活性 / 并发不变量全部不变。

### 阶段纳入对应表

`mapping.PHASE_EVENTS` 给本引擎的 5 个 PHASE 各绑定一个真实事件
(`booting→session.start` / `waiting_model→model.waiting` /
`streaming→model.streaming` / `running_tool→tool.exploring` /
`retrying→turn.retry`)。`verbs_for_phase()` 提供桥, 但**刻意不改写
`_pool()`**: 换词池会破坏既有 139 例回归。

### 安全边界不变

`stall` 仍是启发式可观测提示, 不是安全闸门; `SECURITY_EVENTS` 里的
6 类结构化告警 `pick_for_event` 一律返回空, 不会被俏皮话降级。

验证: `tests/test_slogan_mapping.py` 36 例 + 本文件 139 例 =
175 passed; `verify_mapping.py` 26 项纯 stdlib 独立验证全绿。


---

## 13. 对应关系在运行时闭环（本引擎零改动）

上一轮把 860 条标语接成 18 事件 ↔ 16 上下文的静态表; 本轮实测发现
TUI 留痕**没有 `entry_id`**、错误被 `except Exception` 静默吞掉、
全局日志跨实例互串、审计与分发各有一处 O(n²)/O(n) 热路径。
完整复现与修复见 `SLOGAN_MAPPING.md` §11。

**本引擎本轮零改动**: 事件驱动、三态活性、D1 并发不变量、
净化层 re-export (`sanitize_verb is _clean.sanitize_verb`)、
139 例回归全部照常通过。改动集中在 `ui/slogans/mapping.py`、
`ui/slogans/picker.py` 与 `tui/tui.py` 的标语分发接线。

具体: 留痕补 `entry_id` 并可按 `mapping.entry_for()` 反查;
`_slogan_error()` 让未知事件必留痕, `strict=True` 才向上抛;
日志按 `owner` 分桶 + `RLock`; `_BY_ID`/`_BY_TEXT` O(1) 索引;
`Counter` + 构建时缓存的净化审计; `rng`/`now` 注入使分发可回放。
`PHASE_EVENTS` 与共享事件组 (`SloganEntry.events`) 的归属歧义也补齐。

验证: 194 passed + 42 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。
`stall` 仍是启发式可观测提示, 不是安全闸门; 本轮未改任何裁决。


---

## 14. 闭环补漏（本引擎零改动）

上一轮把对应关系在运行时做实；本轮实测发现刚修完的代码里还留着五个
真实缺陷（净化后索引 miss 假成功、owner 桶无界、错误只留一层痕、
`_MAX_WINDOWS` 小于真实 key 空间、索引不变量形同虚设）。完整复现与
修复见 `SLOGAN_MAPPING.md` §12。

**本引擎本轮零改动**：事件驱动、三态活性、D1 并发不变量、
净化层 re-export（`sanitize_verb is _clean.sanitize_verb`）、
139 例回归全部照常通过。改动集中在 `ui/slogans/mapping.py`、
`ui/slogans/picker.py` 与 `tui/tui.py` 的标语分发接线。

具体：`_BY_CLEAN` 净化后索引 + `index-miss` fail-closed 计数 +
净化撞车检测 + 不变量加严；`_dispatch_log` 改 LRU 有界桶 +
`release_owner()` + `close()` 释放；`record_error()` 让错误在 TUI 与
全局日志两层一致；`_MAX_WINDOWS` 按真实维度算（384 > 320）。

验证：215 passed + 52 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。
`stall` 仍是启发式可观测提示，不是安全闸门；本轮未改任何裁决。


---

## 15. 自愈 / 证据保全 / 字段净化（本引擎零改动）

前三轮把对应关系做实；本轮实测发现刚修完的代码里还留着六个真实
缺陷（累计 miss 永久污染 audit 且恢复要丢日志、`close()` 删掉
`session.exit`、LRU 只读不刷新、日志字段未净化、`clipped` 与净化后
索引口径冲突、分发侧二次按码点截断）。完整复现与修复见
`SLOGAN_MAPPING.md` §13。

**本引擎本轮零改动**：事件驱动、三态活性、D1 并发不变量、
净化层 re-export（`sanitize_verb is _clean.sanitize_verb`）、
139 例回归全部照常通过。改动集中在 `ui/slogans/_clean.py`（拆出
`_clean_once` 并新增 `sanitize_log_field`）、`mapping.py` 与 `tui.py`。

注意 `_clean.py` 的拆分**不改变 `sanitize_verb` 的行为**：它仍调用
`_sanitize_once`（现在是 `_clean_once` + 簇边界截断），幂等与列宽
契约不变；`sanitize_log_field` 复用 `_clean_once` 但按 120 码点限长，
不参与宽度计算，因此不产生第三套宽度真值。

验证：234 passed + 64 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。
`stall` 仍是启发式可观测提示，不是安全闸门；本轮未改任何裁决。


---

## 16. owner 归一 / 淘汰留痕（本引擎零改动）

前四轮把对应关系做实；本轮实测又发现五个真实缺陷（public 入参
`owner` 全链路未净化、`sanitize_log_field` 的 `limit` 脏值抛异常、
LRU 被动淘汰静默丢整桶、`close()` 与 `take_owner_log()` 两套实现、
`_slogan_sealed` 写无锁）。完整复现与修复见 `SLOGAN_MAPPING.md` §14。

**本引擎本轮零改动**：事件驱动、三态活性、D1 并发不变量、
净化层 re-export（`sanitize_verb is _clean.sanitize_verb`）、
139 例回归全部照常通过。改动集中在 `ui/slogans/_clean.py`
（新增 `_coerce_log_limit`）、`ui/slogans/mapping.py` 与 `tui/tui.py`。

注意 `_clean.py` 本轮**只改了 `sanitize_log_field` 的 `limit` 校验**，
`sanitize_verb` / `_clean_once` / `_sanitize_once` / `_fit_headline`
行为一律不变；`norm_owner` 复用的仍是同一份 `sanitize_log_field`，
不产生第三套净化真值。

特别记录一条：修 owner 净化时初版把 key 拼成 74 码点，二次归一又
被 64 上限截断并重算指纹，导致**查询链路静默断裂**；改为定长
`owner:<fp16>` 后才严格幂等。净化层改动必须连带验证查询侧。

验证：256 passed + 73 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。
`stall` 仍是启发式可观测提示，不是安全闸门；本轮未改任何裁决。


---

## 17. 共用净化核心的连续 ESC 处理（本引擎文件零改动）

前五轮把对应关系做实；本轮实测发现日志字段净化「先粗切再清理」
丢尾部合法内容、连续 ESC 串吞掉尾部字符、淘汰痕与 decision
时钟不一致、`last_reason` 掩盖桶内错误信号。完整复现与修复见
`SLOGAN_MAPPING.md` §15。

**本引擎文件本轮零改动**，但必须说明一处**行为变化**：
`runtime_slogans` re-export 的 `_clean.sanitize_verb` 与
`sanitize_log_field` 共用 `_clean_once`，而本轮给 `_clean_once`
新增了 `_ESC_RUN_RE`（连续 2+ 个 ESC 整体删，排在 OSC/CSI 之后）。
因此 `sanitize_verb` 对**连续 ESC 输入**更保真：实测
`'\x1b'*900+'END'` 从 `'ND'` 变为 `'END'`；
`'\x1b\x1b[31m'` 仍为 `''`（未误伤 CSI）。
`sanitize_verb('abc\x1b') == 'abc'`、`_fit_headline`、
`display_cols`、列宽与幂等契约一律不变；139 例既有回归全绿。

另外 `sanitize_log_field` 去掉了 `raw[:lim*4]` 粗切、改为先清理后
截断并加 `_SCAN_CAP=65536` 扫描上限 —— 这不是第三套宽度真值，
只是同一份 `_clean_once` 的调用顺序与 DoS 边界。

**候选 A（孤立 ESC 残留）实测不成立**：`_CTRL_RE` 的 `\x0e-\x1f`
已含 0x1b，孤立 ESC 一直被删，本轮**未为它改任何代码**。

验证：276 passed + 80 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。
`stall` 仍是启发式可观测提示，不是安全闸门；本轮未改任何裁决。


---

## 18. 共用净化核心的 ESC+ 引导（本引擎文件零改动）

前六轮把对应关系做实；本轮实测发现上一轮 ESC_RUN 修复有覆盖缺口
（连续 ESC 串 + 真 CSI/OSC + 尾部文本仍吞首字符）、public 时钟入参
裸奔、owner 整串 sha1 无上界、淘汰缺累计证据。完整复现与修复见
`SLOGAN_MAPPING.md` §16。

**本引擎文件本轮零改动**，但共享的 `_clean_once` 把 OSC/CSI 正则
引导从 `` 改成 `+`。因此 re-export 的 `sanitize_verb` 对
「连续 ESC + 真序列」更保真：实测 `'[31mRED'` 从 `'ED'`
变为 `'RED'`。单 ESC 序列、孤立 ESC、列宽计算、`_fit_headline`、
`display_cols` 与幂等契约一律不变；139 例既有回归全绿。

**四个候选实测不成立、未修**：3 次不动点从未误杀正常文本、开头
组合标记已清、lone surrogate owner 不撞车、`record_error` 的 kind
已被净化。只加回归锁住既有正确行为。

验证：300 passed + 88 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。
`stall` 仍是启发式可观测提示，不是安全闸门；本轮未改任何裁决。


---

## 19. 本轮净化层零改动：两个保真度候选判定「不该修」

前七轮把对应关系做实；本轮实测又发现两个**确实成立**的保真度
现象，但**决定不改**：

- **未终止 OSC 吞光整行**：`']8;;https://evil.example'+'OK'`
  与 `sanitize_verb(']0;title TAIL')` 都返回空串。ECMA-48 里
  OSC 必须由 BEL/ST 终止，无终止符时后续字节规范上全属参数，
  整段删是规范正确的。实测「想修」的副作用：终止符必需 +
  4096 上限会让 904 码点的**参数残留文本**进入日志（放宽净化），
  而 `sanitize_log_field` 按 120 码点截断后尾部 `END` **仍不可达**。
- **ZWJ emoji 被拆散**：`👩‍💻 -> 👩💻`。核查 1695 条词条
  **ZWJ / VS16 / ESC 全部为 0**，修它要放宽 Cf 清理并连带改
  `_clusters` / `display_cols` / 500 串宽度交叉回归 ——
  实际标语零收益、安全与宽度真值风险为正。

**本引擎文件与 `_clean.py` 本轮逐字节未改**，二者 re-export 的
`sanitize_verb` 行为完全不变；139 例既有回归全绿。回归里新增
两条断言把上述判断变成可执行证据，防止以后误「修」。

本轮真正落地的改动在 `ui/slogans/mapping.py`：桶内 `_DISPATCH_CAP`
裁剪留痕与累计决策数（见 `SLOGAN_MAPPING.md` §17）。
验证：319 passed + 97 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。
`stall` 仍是启发式可观测提示，不是安全闸门；本轮未改任何裁决。
