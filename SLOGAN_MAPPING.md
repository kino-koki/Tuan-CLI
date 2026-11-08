# 标语 ↔ 真实运行时事件：一一对应表

> 本轮按「**每个标语都要对应的**」执行。对应不是一句口号，而是
> `mapping.audit()` 在运行时逐条计算的九项不变量；任何一项非零，
> `audit().ok` 就是 `false`，`pick_for_event` 不会假装对应上了。

---

## 1. 先复现：原库的真实状态

这 15 个文件（860 条标语）此前**没有任何一条对应任何事件**。实测证据：

| # | 检查 | 实测结果 |
|---|---|---|
| 1 | 包位置 | 文件在仓库**根目录** `slogans/`，但 `__init__.py` 与 `picker.py` 的 docstring 全写 `from tuan_cli.ui.slogans import ...` —— 这个路径当时**不存在** |
| 2 | 真实接入点 | 全仓搜索 `import slogans` / `SloganPicker` / `for_state(`，命中 **13 处，全部是 docstring 示例文本**；真实 `import` 语句 **0 行** |
| 3 | 未知上下文 | `pick("totally.unknown", lang="zh-CN")` → `'Here.'`。一条**没有任何对应事件**的标语被随机飘到界面上 |
| 4 | 跨语种泄漏 | `pick("bg.progress", lang="ja")` → `'Still at it.'`（英文）。`extra.LOCALES` 只有 `zh-CN` / `en` 两个语种，**8 语种 × 6 扩展场景 = 48 个组合全无本地词条** |
| 5 | 空池 | `de:together` 为 0 条本语种词条（德语用户拿英文协作语）；`en:explore` 空但英文会合并通用池，不构成泄漏 |
| 6 | 并发 | `_windows` 是模块级裸 `dict`、`SloganPicker._last` 是实例裸 `dict`；UI / 模型 / 工具 / 动画多线程同时取词时是复合读写（与 `runtime_slogans` 深度轮 D1 同类） |
| 7 | LRU 名不副实 | 清理是 `pop(next(iter(_windows)))`（**FIFO**），与 docstring「清理最久未用」不符；池大小一变就把整个窗口**重建**，避重历史丢失（实测 `is same object? False`） |
| 8 | 频率节制 | `SloganPicker(min_interval=-1 / NaN / Inf)` 全部被接受；`Inf` 让 spinner **永远不换词**，`NaN` 让每帧都换；无 `clock` 注入，不可确定性测试 |
| 9 | 小池 | `_choose` 对 1~2 条池仍白抽 12 次 |
| 10 | 内置文案过宽 | 3 条内置词条超过 40 列上限，走统一净化出口会被**截成半句**：`No por mucho madrugar amanece más temprano.` → `…más tempra`；`Água mole em pedra dura, tanto bate até que fura.` → `…até` |

`stats()` 当时是 `300 + 60 + 500 = 860` 条，规模不小，但**零对应**。

---

## 2. 一一对应表（18 事件 ↔ 16 上下文）

| 事件 | 上下文 | 真实触发点 |
|---|---|---|
| `session.start` | `startup` | 会话启动 / 欢迎横幅就绪 |
| `model.waiting` | `thinking` | 已提交，等模型首个 token |
| `model.streaming` | `thinking` | 流式分片到达（结果仍未交付，**显式共享** `thinking`） |
| `turn.error` | `error` | 回合内可恢复错误 |
| `undo.applied` | `undo` | 撤销生效 |
| `turn.completed` | `done` | 回合完成 / 分隔线 |
| `tool.exploring` | `explore` | 工具在探索文件与代码 |
| `session.idle` | `idle` | 空闲位 / 等待输入 |
| `user.collab` | `together` | 协作提示（非裁决） |
| `guard.notice` | `guard` | **非拦截**的谨慎提示 |
| `session.exit` | `signoff` | 退出 / 收工 |
| `model.switched` | `model.switch` | 切换模型或供应商完成 |
| `budget.warning` | `budget.warn` | 接近上下文 / 费用预算上限 |
| `background.started` | `bg.start` | 后台 / 长任务派发 |
| `background.progress` | `bg.progress` | 后台任务进行中（>30s） |
| `remote.paired` | `pairing` | 手机扫码 / 远端配对成功 |
| `memory.written` | `memory.write` | 自动写入记忆 |
| `turn.retry` | `undo` | 回炉重试（**显式共享** `undo` 的「重来一次」） |

**多对一是显式共享，不是遗漏**：`model.streaming` 与 `model.waiting` 同属
「结果还没交付」，`turn.retry` 与 `undo.applied` 同属「重来一次」。
`CONTEXT_EVENTS` 给 16 个上下文各指定**唯一主事件**，反查不歧义。

### 活性引擎也纳入同一张表

`runtime_slogans` 的 5 个 PHASE 各有独立事件，不再是与标语库互不知情的
第二套系统：

| PHASE | 事件 |
|---|---|
| `booting` | `session.start` |
| `waiting_model` | `model.waiting` |
| `streaming` | `model.streaming` |
| `running_tool` | `tool.exploring` |
| `retrying` | `turn.retry` |

`verbs_for_phase(phase, lang)` 提供一座桥，但**刻意不改写**
`runtime_slogans._pool()` —— 那个引擎的事件驱动、三态活性、并发不变量
已过多轮验证，换词池会破坏既有 139 例回归。

### 安全事件**没有**标语

```
security.blocked · security.redline · permission.denied
confirm.required · sandbox.degraded · hook.failed
```

用户库设计稿原文「**不要动：安全拦截的结构化告警（那是降级，不是优化）**」
在 `mapping.SECURITY_EVENTS` 里变成可执行的 fail-closed 契约：
这些事件 `pick_for_event` 一律返回空文案 + `reason="security-notice"`，
`audit().unsafe_bindings` 会检查它们绝不被绑上标语。

---

## 3. 全量注册表：每条标语都能回答「我由哪个事件触发」

`build_registry()` 遍历 10 语种 × 16 上下文的所有候选词条，为每条生成：

```python
SloganEntry(
    id="ja:bg.progress:003:a1b2c3d4",   # lang:context:index:sha8，稳定可回放
    lang="ja", context="bg.progress",
    event="background.progress",         # 由 CONTEXT_EVENTS 反查
    index=3, text="...",
    origin="locale-extra",               # locale / locale-patch / locale-extra
                                         # universal / extra-universal
)
```

`entry_for(id)` 可反查；`dispatch_log()` 记录最近 64 次分发决策
（只含事件 / 上下文 / 原因 / 来源 / 序号，**不记任何用户上下文**）。

---

## 4. 九项不变量（`audit().ok` 的硬判据）

| 项 | 含义 | 本轮结果 |
|---|---|---|
| `orphan_slogans` | 标语没有有效事件 | **0** |
| `events_without_pool` | 事件绑定的上下文在任何语种都无词条 | **0** |
| `contexts_without_event` | 上下文没有主事件 | **0** |
| `events_without_context` | 事件没绑定有效上下文 | **0** |
| `locale_gaps` | (语种, 上下文) 无**本语种**词条 | **0** |
| `empty_pools` | 某个组合池为空 | **0** |
| `duplicate_ids` | 稳定 id 重复 | **0** |
| `unsafe_bindings` | 安全事件被绑了标语 | **0** |
| `phase_gaps` | 活性引擎 PHASE 没对应事件 | **0** |
| `clipped_slogans` | 词条过不了统一净化出口 / 超宽 | **0** |
| `sanitizer_shared` | 活性引擎与标语库共用**同一个函数对象** | **True** |

另有 `thin_pools`（本语种词条 < 3，共 10 个）**如实披露但不算失败**：
有本语种词条就说明对应上了，数量少是文案风格取舍，不为好看硬凑。

`audit()` 当前输出：

```
ok=True  total_slogans=1695  total_events=18  total_contexts=16
total_languages=10  sanitizer_shared=True  thin_pools=10
```

> `total_slogans=1695` 是注册表条目数（含各语种共享的英文兜底词条），
> 不等于去重后的词条总数 1108。口径如实标注，不混用。

---

## 5. 补齐了什么

| 补池 | 数量 | 解决 |
|---|---|---|
| `extra_locales.py` | 8 语种 × 6 场景 × 5 条 = **240** | 48 个组合第一次有本语种词条 |
| `locales/patches.py` PATCHES | **5** | `de:together` 唯一空主体池 |
| `locales/patches.py` REPLACEMENTS | **3** | 3 条超长内置文案换成语义完整的短版（不被截成半句） |

`stats()`：`universal 300 / extra 60 / locales 500 / extra_locales 240 /
locale_patches 8 = 1108` 条源词条。

**刻意不改** 10 个语种文件与 `universal.py` / `extra.py`：它们的 docstring
写明了各自的分布统计，改写会让那些说明变成假文档。补池单独成文件，
`extra.py`「不改动主体编号与数量」的纪律继续成立。

### 本地优先

`audit()` 保证「有本语种词条」还不够 —— 普通 `pick()` 是在
「本语种 + 英文兜底」合并池里随机抽，实测日语 `model.switched` 仍会抽到
`Handed over.`。新增 `pick_local_first()`：本地组单独成池优先取，
`SloganDecision.origin` 如实标注来源，不假装本地化。

实测 9 语种 × 6 事件 × 100 轮 = **5400 次分发，`locale` 5400 / 英文兜底 0**。

---

## 6. 严格分发与安全边界

```python
from tuan_cli.ui.slogans.mapping import pick_for_event, audit

assert audit().ok
d = pick_for_event("tool.exploring", lang="ja")
# SloganDecision(event=..., context="explore", text="...", origin="locale")
```

- **未知事件抛 `UnboundSloganEvent`**，绝不静默回落 `idle` 飘一句无关标语；
  旧 `pick()` 的历史兼容行为保留但 docstring 明确标注「非生产接线」。
- **安全事件返回空**，结构化告警不被俏皮话替换或稀释。
- **净化出口不可用则 fail-closed** 返回空，不渲染未净化文案。

### 净化层只有一份

前两轮把 `runtime_slogans` 的净化层做成了 bidi / 零宽 / ESC /
变体选择符 / grapheme / 幂等 的完整边界。新标语库的 1108 条词条也要进
终端，若再写一套就是**第三套真值来源**。因此抽到
`tuan_cli/ui/slogans/_clean.py`，活性引擎只 re-export 同一批函数对象：

```
runtime_slogans.sanitize_verb is _clean.sanitize_verb   → True
runtime_slogans.display_cols  is _clean.display_cols    → True
```

`audit().sanitizer_shared` 把这条变成可断言的不变量，不是文档承诺。

---

## 7. picker 的六个真实缺陷修复

| 缺陷 | 修复 |
|---|---|
| 裸 `dict` 无锁 | `_windows` / `SloganPicker._last` 全部 `RLock` 线性化 |
| FIFO 冒充 LRU | `OrderedDict` + `move_to_end` + `popitem(last=False)` |
| 尺寸变化整窗重建 | 保留已有历史，`deque(list(win), maxlen=new)` |
| 小池白抽 12 次 | ≤2 条直接短路（实测调用次数 13 → 1） |
| `min_interval` 接受 `-1/NaN/Inf/"5"/True` | 严格类型 + `isfinite` + 非负；可注入 `clock` |
| 未知上下文静默回落 | 新增 `pick_strict()` 抛异常；生产走 `pick_for_event` |

---

## 8. 真实接入（不再是只有 docstring）

包落到**正确路径** `tuan_cli/ui/slogans/`，根目录 `slogans/` 的 15 个文件
改成薄兼容垫片（re-export），旧引用不崩且词库只有一份、不会各自漂移。

`QxtTUI` 新增 `_slogan_dispatch(event)` 与 `slogan_for(event)`，在已有的
真实生命周期点分发：

| 生命周期点 | 事件 |
|---|---|
| `begin_tool` | `tool.exploring` |
| `stream_assistant` | `model.streaming`（1s 节流，**不影响**活性引擎按每个分片记账） |
| `_run_submit` 结束 | `turn.completed` |
| `close` | `session.exit` |

分发日志有界 64 条、脱敏（只记事件 / 上下文 / 原因 / 来源）。

**刻意不替换任何既有 i18n 文案**：前几轮刚修好的状态口径与 139 例回归
不该为了显示一句俏皮话被掀掉。这里建立的是可验证的「事件 → 标语」
对应关系与留痕；需要渲染时由调用方显式 `slogan_for(event)`。
`slogan_for` 对安全事件永远返回空。

---

## 9. 验证

```
tests/test_slogan_mapping.py   36 例全绿
tests/test_runtime_slogans.py  139 例全绿（净化层抽取后零回归）
合计                           175 passed
verify_mapping.py              26 项纯 stdlib 独立验证全绿
verify_deep.py                 22 项全绿（上一轮）
verify_deep2.py                20 项全绿（上一轮）
py_compile                     全部通过
```

纯 stdlib 验证刻意不依赖 pytest / prompt_toolkit / rich / wcwidth / i18n，
环境重置也能复现对应关系。

---

## 10. 如实边界

1. **共享映射不是遗漏**：`model.streaming` / `turn.retry` 与另一事件共享
   上下文，理由写在表里；`CONTEXT_EVENTS` 仍给每个上下文唯一主事件。
2. **英文兜底词条仍在注册表里**：每条都有 `event`（非孤儿），但
   `pick_for_event` 本地优先，实测 5400 次分发 0 次落到兜底。
3. **10 个 `thin_pools` 未补**：有本语种词条即视为对应，不为凑数硬加文案。
4. **3 条超长原文被替换**：理由是渲染时会被截成半句；原文与短版
   都记在 `patches.REPLACEMENTS` 里，可复核。
5. **TUI 只建立分发与留痕，未替换既有文案**：标语要真正显示在某个 UI
   位置，需调用方显式用 `slogan_for()`；本轮没有擅自改欢迎横幅或完成行。
6. **安全告警不降级**是运行时契约（返回空 + `audit` 断言），不是注释。
7. 不是真机 TUI 长跑；Windows / 终端能力组合未实测。
8. 根目录历史包改成了垫片（**未删除任何文件**）；本地副本与远端主线的
   实质分叉仍在，前几轮 `local_fork_unmerged/` 的改动仍未合并。
9. 第三方自适应红队仍未做；静态基准与自造 fuzz 不能当对抗证明。
10. Claude Code / OpenAI Codex 相关归属仍按 `NOTICE` 第 9–15 条；
    本轮 240 条补池与短诊断文案为原创，**无新增第三方素材**。


---

## 11. 运行时闭环：表对应上了，留痕却把对应关系丢了

上一轮建好了静态对应表 (`audit().ok = True`)，本轮**先实测再修**，
发现对应关系在**运行时**其实没闭合 —— 六个真实缺陷：

| # | 实测复现 | 影响 |
|---|---|---|
| 1 | `QxtTUI._slogan_log` 只记 `(event, context, reason, origin)`，**没有 `entry_id`** | 运维看到「刚才分发了 tool.exploring」，却无法反查「显示了哪条标语」。表是静态的，留痕是断的 |
| 2 | `_slogan_dispatch` 用 `except Exception: return None` | 拼错事件时 `pick_for_event` 明明抛 `UnboundSloganEvent`，TUI 却什么都不记、静默返回 `None` —— 上一轮刚建立的严格契约在接线处被吃掉 |
| 3 | `mapping._dispatch_log` 是**全局裸 list 单例** | 实测两个 TUI 实例的日志混在一起；`reset_dispatch_log()` 会清掉另一个会话的记录 |
| 4 | `audit()` 用 `ids.count(i)` 判重复，O(n²) = 287 万次比较；且每次对 1695 条重跑 `sanitize_verb` | 单次 38.4 ms / 20 次 763.7 ms |
| 5 | `pick_for_event` 每次 `for e in registry()` 线性扫 1695 条反查 `entry_id` | 2000 次分发 58.9 ms |
| 6 | 随机源不可注入 | 上一轮给 `SloganPicker` 加了 `clock`，但分发链路仍用模块级 `random`；「刚才显示了哪条」无法确定性回放 |

另外挖出一处**归属歧义**：`SloganEntry.event` 只记主事件
(`CONTEXT_EVENTS["thinking"] = "model.waiting"`)，而 `model.streaming`
也映射到 `thinking`。运行时由 `model.streaming` 触发的标语，反查出来
却显示 `model.waiting` —— 共享映射在「每个标语都要对应的」上留了个洞。

### 修复

**留痕闭环**：`_slogan_row()` 现在记 7 元组，含 `entry_id` / `owner` /
`at_ms`；`slogan_trace()` 返回结构化字典，可直接
`mapping.entry_for(row["entry_id"])` 反查到触发事件组。
`row[0]` 仍是 event，既有生命周期回归零改动。

**错误不再静默**：`_slogan_dispatch` 单独捕获 `UnboundSloganEvent`
与其它异常，两者都走 `_slogan_error()` 记 `error:<kind>` 留痕，
`slogan_errors()` 可直接查。`strict=True` 时异常**向上抛**，
把严格契约完整暴露给开发/测试；生产默认 `False`（生命周期回调不该
掀掉整个 UI），但**绝不静默吞掉**。
`slogan_for()` 未知事件仍返回空串，但空串既表示「安全事件」也表示
「出错」—— 现在靠 `slogan_trace()` 的 `reason` 区分，不靠猜。

**按 owner 分域**：`SloganDecision.owner` + `_dispatch_log: Dict[owner, list]`，
每个 TUI 实例一个 `"tui:<id>"` 作用域；`dispatch_log(owner)` /
`reset_dispatch_log(owner)` 可只查/只清指定会话。无参调用仍返回全量
（兼容旧调用）。日志、注册表、TUI 留痕各加 `RLock`。

> **如实标注并发边界**：用 `setswitchinterval(1e-6)` + 12 线程压测，
> **没有复现出日志长度超限**（观测峰值仍是 64）—— CPython 的 GIL 让
> list 操作碰巧没撕裂。加锁不是「修了已观测的故障」，是**消除对 GIL
> 实现细节的依赖**、并让「快照不返回内部可变对象」成为契约。
> 这一点不包装成战果。

**O(1) 索引**：`_BY_ID` / `_BY_TEXT` 在 `_ensure_index_locked()` 里
一次性构建（加锁幂等），`entry_for` / `entry_for_text` 都是 O(1)。
`pick_for_event` 改走 `entry_for_text(lang, context, text)`，源码里
不再出现线性遍历。`index_stats()` 可核验索引规模。

**审计降复杂度**：`ids.count(i)` → `Counter`（O(n²) → O(n)）；
1695 条词条的净化检查挪到索引构建时算一次并缓存进 `_CLIPPED_IDS`，
`audit()` 只读结果。词条是静态常量，语义不变。新增第 11 项不变量
`index_consistent`（索引规模一致 + 每个注册项的 `events` 含主事件）。

实测（同机同环境）：

```
20 次 audit()      763.7 ms -> 355.6 ms
2000 次分发         58.9 ms ->  33.1 ms
```

> 20 次 audit 没有降到个位数毫秒，剩余开销是 10 语种 × 16 上下文的
> `pool_entries()` 组装，如实留着，不伪称根治。

**共享事件组**：`SloganEntry.events` 列出**所有**能触发该上下文的事件
（含主事件），`event` 仍是唯一主事件（向后兼容）。
`model.streaming` 现在能正确归属到它触发的那条标语。
`audit().index_consistent` 断言 `e.event in e.events`。

**可确定性回放**：`pick_for_event(..., rng=..., now=..., owner=...)`，
`rng` 贯通到 `picker._choose`。注入 rng 时用**一次性局部避重窗口** ——
实测两个独立 rng 依次分发时，第二个因共享全局窗口里已有 `items[0]`
被拒 12 次，`choice` 调用从 1 变成 13，回放失效。生产路径
（`rng=None`）完全不变，仍走加锁的全局 LRU 窗口。

### 验证

```
tests/test_slogan_mapping.py + test_runtime_slogans.py   194 passed
tests/verify_slogan_mapping.py                           42 项纯 stdlib 全绿
verify_deep.py / verify_deep2.py                         22 / 20 项全绿
```

### 如实边界（续 §10）

11. TUI 仍只建立分发与留痕，**未替换任何既有 i18n 文案**；要显示标语需
    调用方显式 `slogan_for(event)`。
12. `strict=True` 是开发/测试开关，生产默认关闭；生产不崩但错误**必留痕**。
13. 并发加锁未对应到已复现的故障（见上方说明）。
14. 20 次 audit 仍有 355.6 ms 的 `pool_entries` 开销，未做第二层缓存 ——
    加缓存会让「审计结果」依赖词池缓存时间点，跟前几轮拒绝给活性判定
    加文件系统缓存是同一个理由。
15. 本轮**不改** `fully_superior`、99 模块基线、任何对齐指标，未新增
    CLI 子命令、未新增事件（18 个不变）、未新增标语词条（1108 条不变）。
    全部是「把已有对应关在运行时做实」的深度工作。


---

## 12. 闭环补漏：静默 miss、无界桶、单层错误留痕、避重失效

上一轮把对应关系在运行时做实了。本轮**先实测再修**，发现刚修完的代码
里还留着五个真实缺陷 —— 都属「上一轮修对了方向，但留了半截」。

| # | 实测复现 | 影响 |
|---|---|---|
| A | `_BY_TEXT` 用**原始** `e.text` 建索引，`pick_for_event` 拿**净化后** text 反查 | 当前 `clipped=0`（所有词条恰好无需净化）让两者碰巧一致。注入一条含 ZWSP 的词条后实测：`reason='ok'` 但 `entry_id=''` —— 对应关系在运行时**静默断裂且不告警** |
| B | `_dispatch_log` 按 owner 分桶但**只限每桶长度 64，不限桶数** | 2000 个会话各分发一次 → 2000 个桶长期驻留；`QxtTUI.close()` 没有释放路径 |
| C | TUI `_slogan_error()` 只写实例 `_slogan_log` | 实测拼错事件后 `slogan_errors()` 有 1 条，而 `mapping.dispatch_log()` 里错误相关 **0 条** —— 只看全局日志的运维完全漏掉 |
| D | `_MAX_WINDOWS = 64` 小于真实 key 空间 | 10 语种 × 16 上下文 × 2 种窗口 = **320** 个 key。实测遍历一轮后起始 key 窗口被驱逐 **3/3** 次，避重形同虚设 |
| E | `audit().index_consistent` 只要求 `by_text > 0` | 几乎恒真，索引缺一大半也会通过 |

### 修复

**A · 净化后索引 + miss fail-closed.** 新增 `_BY_CLEAN`（净化后文案 → 注册项）
供分发使用，`_BY_TEXT`（原始文案）保留给兼容 API 与上一轮的独立验证。
`entry_for_clean()` 是运行时唯一反查出口。池里出现注册表没有的词时，
不再返回假的 `"ok"`，而是 `reason="index-miss"` + **空文案** + `_INDEX_MISSES`
计数 —— 宁可不显示，也不渲染一条反查不到出处的标语。
同时检测**净化后撞车**（两条不同词条净化成同一句，运行时无法区分），
记入 `_CLEAN_COLLISIONS`。

**B · 桶数也有上界.** `_dispatch_log` 改 `OrderedDict` + `_MAX_OWNERS=128`
LRU，`_record()` 淘汰最久未用的会话；新增 `release_owner()`、
`dispatch_log_stats()`、`reset_runtime_counters()`。`QxtTUI.close()`
现在显式释放自己的桶（实例内 `_slogan_log` 仍在，`slogan_trace()`
照常可查）。实测 2000 个会话后 `owners=128 / decisions=128`。

**C · 错误双层留痕.** `mapping.record_error()` 把 `error:<kind>` 同步进
全局日志，TUI `_slogan_error()` 调它；`slogan_errors()` 与
`dispatch_log(owner)` 现在一致。6 类安全事件仍是 `security-notice`，
**不与 `error:*` 混**。`strict=True` 抛异常时也照样两层留痕。

**D · 窗口上限按真实维度算.** `_MAX_WINDOWS` 从魔数 64 改为
`len(LANGUAGES) * (主体 + 扩展上下文) * 2 + 64 = 384`，仍有上界不无界增长。
实测遍历全部 320 个 key 后 `len(_windows)=320`，起始窗口存活、避重历史仍在。

**E · 不变量加严.** `index_consistent` 现在要求三份索引规模与注册表
**全等**、`clipped=0`、无净化撞车、运行时零 miss、每个注册项声明了
完整触发事件组；`AuditReport` 新增 `clean_collisions` /
`runtime_index_misses` / `dispatch_stats` 并纳入 `ok` 与 `as_dict()`。
`reset_runtime_counters()` 供测试隔离。

### 验证

```
tests/test_slogan_mapping.py + test_runtime_slogans.py   215 passed
tests/verify_slogan_mapping.py                           52 项纯 stdlib 全绿
verify_deep.py / verify_deep2.py                         22 / 20 项全绿
```

### 性能口径（不粉饰）

```
index_stats   registry/by_id/by_text/by_clean = 1695 / 1695 / 1695 / 1695
              clipped=0  clean_collisions=0  index_misses=0
冷启动首次 audit()       303.9 ms   (含 1695 条净化 + 三份索引构建)
热态 20 次 audit()        37.4 ms
含冷启动的 20 次 audit()  53.1 ms   (同进程内 _clean 的 lru_cache 已热)
```

上一轮报告写「20 次 audit 763.7 → 355.6 ms」，本轮出现 53.1 ms
是**测量口径差异**（首次冷构建 vs 缓存热态），不是本轮做了性能优化。
本轮反而给索引构建多加了 1695 次 dict 写入与碰撞检测，**不宣称性能提升**。

### 如实边界（续 §11）

16. 本轮**不改** 18 个事件、16 个上下文、1108 条词条、`fully_superior`、
    99 模块基线、任何对齐指标、CLI 子命令数；零新增文件、零删除。
17. `index-miss` 的 fail-closed 是「不显示标语」，不影响任何安全裁决；
    它只保证「显示出来的每一句都能反查到出处」。
18. `release_owner()` 释放的是 **mapping 全局桶**；实例内
    `_slogan_log` 仍随对象生命周期驻留，长生命周期宿主需自行丢弃 TUI 对象。
19. `_MAX_OWNERS=128` 与 `_MAX_WINDOWS=384` 是有界折中：极端多会话场景
    下最久未用的历史仍会被淘汰，这是明确取舍，不宣称「永不丢历史」。
20. 并发压测仍未复现 list 撕裂（同 §11 说明）；不是真机长跑；分叉改动
    仍未合并；第三方自适应红队仍未做。


---

## 13. 自愈、证据保全、日志字段净化、单一渲染出口

前三轮把对应关系从静态表做到了运行时可反查、可回放、有界、
fail-closed。本轮**先实测再修**，发现刚修完的代码里还留着六个
真实缺陷 —— 都是「方向对了，但语义留了半截」。

| # | 实测复现 | 影响 |
|---|---|---|
| A | 制造一次 `index-miss` 后把数据源修好、连续 20 次正常分发，`audit().ok` **仍是 False** | `_INDEX_MISSES` 是累计值，一次已修复的历史错误让健康状态永久报不健康；而唯一恢复手段 `reset_runtime_counters()` 强绑 `reset_dispatch_log()` —— 想恢复审计必须**丢掉全部运行时留痕**（实测 `decisions: 21 → 0`） |
| B | `close()` 先记 `session.exit` 再 `release_owner()` 删桶 | 实例 `slogan_trace()` 里有 `session.exit`，全局 `dispatch_log(owner)` 为空 —— 两层口径不一致，运维永远看不到会话退出 |
| C | 填满 128 个桶后对 `s-0` 高频只读 50 次，再触发驱逐 | `s-0` 被淘汰。上一轮只有**写入**刷新 LRU，读取不计入 recency，活跃只读会话被当成最久未用 |
| D | `record_error()` 传入 5030 码点含 `ESC ]8;;` 超链接 + `U+202E` RLO 的串 | 原样写进两层日志。控制字符会被日志查看器 / 终端解释；`event` 是 public API 入参，`slogan_for()` 拼错时同样受影响；`UnboundSloganEvent` 的异常消息也会进 traceback |
| E | 注入一条含 ZWSP 的词条：分发 `reason='ok'` / `entry_id` 正确 / `text='探索中'`，但 `audit().ok=False` | 净化后索引建成后「文案需净化」已不破坏反查，可 `clipped` 仍一律判 fatal —— 会阻止合法新词条加入 |
| F | `pick_for_event` 在 `sanitize_verb(raw)` 之后又补了按码点切前 `max_cols` 个字符 | `sanitize_verb` 本身已在 grapheme **簇边界**截断并保证列宽；二次按码点截断会切断簇，且让分发文案与 `_BY_CLEAN` 的 `sanitize_verb(e.text)` key 口径不一致，超长词条静默 `index-miss` |

### 修复

**A · 连续 miss 自愈，累计证据与日志都保留。** 新增
`_UNRESOLVED_MISSES`（自最近一次成功反查以来的**连续** miss）；
成功反查一次即归零。`_INDEX_MISSES` 保留为累计历史证据，永不自动清零。
`audit().ok` 与 `index_consistent` 改看 `unresolved_misses`，不再看累计。
新增 `acknowledge_runtime_misses()` 显式确认（返回数量，**不动累计、
不动日志**）。`reset_runtime_counters(include_dispatch_log=False)`
默认**不再清日志**，需要连日志清时显式传 `True`。

实测：一次 miss → `ok=False`；数据源恢复后一次成功分发 → `ok=True`，
累计仍 1、日志仍 2 条。

**B · 会话退出证据封存。** `close()` 先把含 `session.exit` 的整桶快照
存进实例 `_slogan_sealed`，再 `release_owner()` 释放全局桶（桶数仍
有界）。新增 `slogan_closed_trace()` 返回与 `slogan_trace()` 同结构的
快照；`mapping.take_owner_log(owner)` 提供「取走快照 + 释放」的通用
API。实测 `dispatch_log(owner) == ()` 仍成立，但封存快照里
`session.exit` 可见。

**C · 读也算最近使用。** `dispatch_log(owner)` 指定 owner 时
`move_to_end`；**无参全量读刻意不刷新**（否则一次全量读把所有桶刷成
最近使用，淘汰策略直接失效）。实测高频只读 `s-0` 存活、真·最久未用
的 `s-1` 被淘汰；全量读场景下 `s-0` 仍按真实写入顺序淘汰。

**D · 日志字段统一净化。** `_clean.py` 把 `_sanitize_once` 拆成
`_clean_once`（纯 Unicode 清理，不截断）与截断部分；新增
`sanitize_log_field(raw, limit=120)`：与 `sanitize_verb` **共用同一份
`_clean_once` 清理核心**，差别只在长度约束（UI 文案按 40 显示列宽、
grapheme 簇边界；日志字段按 120 码点，不参与宽度计算）—— 不产生
第三套净化真值。`record_error()` 净化 `event`/`kind`/`context`，
`UnboundSloganEvent` 消息同样净化，TUI `_slogan_error()` 改用
`record_error()` 返回的已净化字段，标语库整体不可用时降级路径也先过
`_clean` 再写，绝不写原始串。实测 5030 码点注入 → 121 码点、ESC/RLO/OSC8
全部清除；两层留痕的 `event` 完全一致。

**E · 信息项与 fatal 分开。** `_CLIPPED_IDS` 降为**信息项**（文案需净化
但能正确反查）；新增 `_UNRENDERABLE_IDS`（净化后为空 / 仍超宽）与
既有 `_CLEAN_COLLISIONS` 为 fatal。`AuditReport` 新增
`sanitized_slogans` / `unrenderable_slogans` / `unresolved_misses`，
`ok` 与 `as_dict()` 同步；`clipped_slogans` 保留为兼容字段但不再参与
`ok`。实测注入 ZWSP 词条后 `ok=True`、`sanitized=1`、
`unrenderable=()`、分发仍正确反查；注入全控制字符词条仍 `ok=False`。

**F · 单一渲染出口。** 去掉分发侧二次按码点截断，分发与 `_BY_CLEAN`
索引构建都只调 `sanitize_verb`。实测超长 (`"很长的标语"*30`) 词条
分发 `reason='ok'`、`entry_id` 正确、`text == sanitize_verb(raw)`、
`display_cols <= 40`；源码结构断言禁止 `[:max_cols]` 回归。

### 验证

```
tests/test_slogan_mapping.py + test_runtime_slogans.py   234 passed
tests/verify_slogan_mapping.py                           64 项纯 stdlib 全绿
verify_deep.py / verify_deep2.py                         22 / 20 项全绿
```

### 实测数字（同机同环境）

```
index_stats  registry/by_id/by_text/by_clean = 1695 x4
             clipped=0  unrenderable=0  clean_collisions=0
             index_misses=0  unresolved_misses=0
一次 miss    ok=False / unresolved=1
恢复后       ok=True / 累计证据=1 / 日志 2 条 (都没丢)
注入串       5030 码点 -> 121 码点, ESC/RLO/OSC8 全清
LRU 读       高频只读 s-0 存活, s-1 被淘汰
```

### 如实边界（续 §12）

21. 本轮**不改** 18 个事件、16 个上下文、1108 条词条、`fully_superior`、
    99 模块基线、任何对齐指标、CLI 子命令数；零新增文件、零删除。
    `runtime_slogans` 引擎本轮零改动。
22. `unresolved_misses` 是**连续**语义：间歇性 miss 会被随后的成功
    归零，累计 `_INDEX_MISSES` 才是完整历史。这是明确取舍，不宣称
    「任何一次历史 miss 都永久告警」。
23. `slogan_closed_trace()` 只保全 `close()` 那一刻的桶快照；
    LRU 淘汰掉的**其它**会话历史仍不保留（128 桶上界不变）。
24. `sanitize_log_field` 按码点限长 120，不按显示列宽 —— 日志不参与
    终端渲染；但它与 UI 文案共用 `_clean_once`，**不是**第二套净化真值。
25. `_MAX_OWNERS=128` / `_MAX_WINDOWS=384` 仍是有界折中；并发压测
    仍未复现 list 撕裂；不是真机长跑；TUI 仍未替换任何既有 i18n
    文案；分叉改动仍未合并；第三方自适应红队仍未做。


---

## 14. owner 全链路归一、被动淘汰留痕、单一释放出口

前四轮把对应关系从静态表做到了可反查、可回放、有界、fail-closed、
可自愈。本轮**先实测再修**，又发现五个真实缺陷 —— 其中一个是
**修 A 的过程中自己引入、再被实测抓回来的**，这条最值钱。

| # | 实测复现 | 影响 |
|---|---|---|
| A | `pick_for_event(owner=注入 5033 码点含 OSC 8 + U+202E RLO 的串)` | `SloganDecision.owner`、桶 key、`slogan_trace()` 输出**全部原样带控制字符**。D4 净化了 event/kind/context，偏偏漏了 public 入参 `owner` 这一路 |
| A′ | **修 A 时自己引入**：初版把净化后 65 码点文案 + 8 位指纹拼成 74 码点 key | `norm_owner` 不幂等 —— 74 码点超过 64 上限，二次归一又截断并**重算指纹**；`_record` 存的 key 与查询侧算出的对不上，实测 `dispatch_log(evil)` 返回 **0** 而 `dispatch_log(d.owner)` 返回 1。等于修净化反而把查询链路打断 |
| B | `sanitize_log_field("abc", limit=None / nan / inf)` 分别抛 TypeError / ValueError / OverflowError；`limit='5'` / `True` / `-1` 被悄悄接受 | public API 因脏配置直接崩，与 `runtime_slogans.load_config` 对 `stall_ms` 的严格类型口径不一致 |
| C | 128 桶填满后第 129 个会话挤掉 `s-0`（含 `turn.completed` 共 2 条），`dispatch_log('s-0')` 空且**无任何痕迹** | D4 只给显式 `close()` 封存了快照，LRU **被动淘汰**仍是无声黑洞，含完成事件的整桶凭空消失 |
| D | `close()` 自己拼「`dispatch_log(owner)` + `release_owner()`」两步，而 `take_owner_log()` 已是「pop + return」单一出口 | 两套实现会漂移（前者顺带刷新 LRU，后者不会），D4 刚修的语义存在分叉面 |
| E | `_slogan_sealed` 写在 `_slogan_lock` 外，而 `slogan_closed_trace()` 读有锁；`slogan_closed_trace()` 里 `keys = (...)` 定义后从未使用 | 半截的并发契约 + 死代码 |

### 修复

**A · `norm_owner()` 全链路归一，且严格幂等。** 所有写入
（`pick_for_event` / `record_error` / `_record`）与所有查询
（`dispatch_log` / `release_owner` / `take_owner_log` /
`reset_dispatch_log`）共用**同一个**归一函数：

- **干净输入零改动**：`sanitize_log_field(raw) == raw` 时原样返回，
  所以既有 `owner='s-0'` / `tui:%x` 全部不变，测试与调用方零迁移；
- **脏串归一定长指纹 key**：`owner:<sha1(raw)[:16]>` 仅 22 码点，
  干净且远小于 64 上限，因此 `norm_owner(norm_owner(x)) ==
  norm_owner(x)` **严格幂等**。这是 A′ 逼出来的设计：不再把净化后
  的长文案拼进 key。不同脏串不撞车（64 bit 指纹）。
- 代价如实写：脏 owner 原串不进日志 —— 这正是净化的目的。

实测：`5033 → 22` 码点、ESC/RLO/OSC8 全清、`norm_owner(n)==n`、
`dispatch_log(evil)` 与 `dispatch_log(d.owner)` 都命中同一桶、
`slogan_trace()` 里 owner 干净。

**B · `limit` 严格类型校验。** 新增 `_coerce_log_limit()`：显式拒绝
bool / 非数值 / 非有限浮点 / 非正值，夹在 `[8, 4096]`，脏值一律
回落默认 120 而**绝不抛异常**。实测 `None` / `nan` / `inf` / `-1` /
`True` / `'5'` / `0` / `99999` / `8.0` 全部返回 `'abc'`；
`limit=20` 时 200 字词串截到 21 码点并以 `…` 收尾；
`sanitize_verb` 行为完全不变。

**C · 被动淘汰不再静默。** 新增 `EvictionRecord`（owner / dropped /
last_reason / at_ms，**不含文案、不含 entry_id**）与有界
`_EVICTED`（`deque(maxlen=64)`）。`_record()` 的 `popitem(last=False)`
处记一条；`evicted_owner_log()` 返回快照，`dispatch_log_stats()`
增 `evicted_recent` / `evicted_cap`，`audit().as_dict()` 自动带上。

**刻意不复活决策内容** —— 那会让 128 桶上界形同虚设。现在
「谁被淘汰 / 丢了几条 / 最后一条 reason」可见，证据丢失至少
**可观测**；`evicted_recent` 是观测项，**不参与 `audit().ok`**
（淘汰是正常有界行为，不是故障）。`reset_dispatch_log()` 全清时
连淘汰痕一起清，保证测试隔离。

**D · 单一释放出口。** `close()` 收敛到
`mapping.take_owner_log(owner)` 一步，`release_owner()` 保留兼容但
不再被 close 调用。源码结构断言禁止两套实现回归。

**E · 并发契约补全。** `_slogan_sealed` 的写放进 `_slogan_lock`
（与读一致）；删掉 `slogan_closed_trace()` 里未使用的 `keys` 变量。

### 验证

```
tests/test_slogan_mapping.py + test_runtime_slogans.py   256 passed
tests/verify_slogan_mapping.py                           73 项纯 stdlib 全绿
verify_deep.py / verify_deep2.py                         22 / 20 项全绿
```

三处既有**静态源码断言**同步到新实现（`close` 改查
`take_owner_log`、LRU 改查 `move_to_end(key)`）——不是放宽策略，
是让断言继续指向真实实现。

### 实测数字（同机同环境）

```
index_stats   1695×4 / clipped=0 / unrenderable=0 / collisions=0
              index_misses=0 / unresolved_misses=0
脏 owner      5033 -> 22 码点, 幂等=True, ESC/RLO/OSC8 全清
写入/查询     同一归一 key, dispatch_log(evil) 命中
被动淘汰      EvictionRecord(owner='s-0', dropped=2,
                            last_reason='ok', at_ms>0)
stats         owners=128 / decisions=128 /
              evicted_recent=1 / evicted_cap=64
limit 脏值    None / nan / inf / -1 / True / '5' 全返回 'abc'
```

### 如实边界（续 §13）

26. 本轮**不改** 18 个事件、16 个上下文、1108 条词条、`fully_superior`、
    99 模块基线、任何对齐指标、CLI 子命令数；零新增文件、零删除。
    `runtime_slogans` 引擎本轮零改动。
27. **A′ 是本轮修 A 时自己引入、再被实测抓回来的**，不是原有缺陷。
    记录在此是为了说明「净化层改动必须连带验证查询链路」——
    key 归一这类改动一旦不幂等，写入与查询会静默分叉。
28. 脏 owner 归一为 `owner:<fp16>`，**原串不进日志**，可读性下降是
    明确取舍；干净 owner 零改动。
29. 淘汰记录只保留**最近 64 次**、且不复活决策内容；更早的被动
    淘汰仍不可查。`evicted_recent` 是观测项，不参与 `audit().ok`。
30. `_EVICTED` 与 owner 桶共用 `_dispatch_lock`；并发压测**仍未复现**
    list 撕裂（同 §11），加锁是消除对 GIL 实现细节的依赖，不是修了
    已观测故障。
31. `_slogan_sealed` 写加锁后仍只是实例内快照；LRU 淘汰的其它会话
    历史仍不保留（128 桶上界不变）。不是真机长跑；TUI 仍未替换
    任何既有 i18n 文案；分叉改动仍未合并；第三方自适应红队仍未做。


---

## 15. 先清理后截断、注入时钟贯穿、淘汰痕摘要

前五轮把对应关系做到了可反查、可回放、有界、fail-closed、可自愈、
owner 全链路归一。本轮仍**先实测再修**，结果有一个候选**根本不成立**——
这比修成五个更值得写下来。

### 候选 A：实测不成立，**未修**

怀疑 `_CTRL_RE` 不含 `0x1b`，孤立 ESC（无后续参数字节）会残留。
实测 `sanitize_verb('abc\x1b') == 'abc'`、`'\x1b' -> ''`、
`'ok\x1b\x1b' -> 'ok'`，全部干净。原因：`_CTRL_RE` 的字符类
`\x0e-\x1f` 覆盖 0x1b（十进制 27），孤立 ESC 一直被删。
**没有为它改任何一行代码**，只加了两条回归把既有正确行为锁住，
防止以后有人误当成洞去「修」而破坏它。

### 五个真实缺陷（全部先实测复现）

| # | 实测 | 影响 |
|---|---|---|
| B | `sanitize_log_field('\x00'*1000+'OK', 120)` 返回 **空串** | 旧实现 `raw[:lim*4]` **先粗切再清理**：limit=120 只扫前 480 码点，前部垃圾吃满额度，尾部唯一合法内容 `OK` 被整段丢弃 |
| B′ | **修 B 后暴露**：`sanitize_log_field('\x1b'*900+'END')` 返回 `'ND'` | 连续 ESC 串中最后一个与 `E` 拼成 `ESC E`（NEL）被 `_ESC_SEQ_RE` 吞掉；这是 ECMA-48 的固有歧义在垃圾串上的放大 |
| C | 注入 `now=1000.0` 触发淘汰：`decision.at_ms=1000000`，`EvictionRecord.at_ms=76564` | 同一事件两个时间戳来自两套时钟（注入 vs `time.monotonic()`），前几轮刚建的**可确定性回放**断了一半 |
| H | 桶内 `ok / error:boom / ok` 被淘汰，痕迹只有 `last_reason='ok'` | 运维完全看不出被丢弃的会话曾有一条错误；`dropped=3` 但错误信号被掩盖 |
| D | `'a'*64` 原样返回，`'a'*65` → `owner:<fp16>` | `norm_owner` 旧 docstring 写「干净输入零改动」，对 >64 码点的**纯 ASCII 干净串**不精确；功能无变化，是口径问题 |
| E | 2 MiB 干净 owner 归一耗时 1.7 ms，且每次写入/查询都全串 sha1 | 线性成本、无硬上限；**不修**，如实记录为已知边界 |

### 修复

**B · 先清理后截断 + 扫描上限。** 去掉 `raw[:lim*4]` 粗切，改为
先 `_clean_once` 迭代到不动点、再按 `lim` 截断。实测
`_clean_once` 对 64KiB ≈ 17 ms、1MiB ≈ 0.32–0.37 s、2MiB ≈ 0.66–0.68 s，
因此加 `_SCAN_CAP = 65536`：**64KiB 以内保证先清理后截断**，
超出才粗切再清理（DoS 防护）。截断结果仍是 `[lim 码点 + '…']`，
二次调用严格幂等。实测 `'\x00'*1000+'OK' -> 'OK'`、
`'\x00'*300+'A'+'\x00'*300+'B' -> 'AB'`。

**B′ · 连续 ESC 串整体删。** 新增 `_ESC_RUN_RE = \x1b{2,}`，
排在 OSC/CSI **之后**：以 `[`/`]` 引导的真序列已先被剥掉，
剩下的连续 ESC 不可能是有效序列引导（ECMA-48 以单个 ESC 起始）。
实测 `'\x1b'*900+'END' -> 'END'`，且
`'\x1b\x1b[31m' -> ''`、`'\x1b\x1b\x1b[31m' -> ''`（没误伤 CSI）、
`'\x1b]8;;evil\x07OK' -> 'OK'`。
**单个** `\x1bEND` 仍是 `'ND'` —— 那是 ECMA-48 固有歧义，本轮**未改**；
ESC 已清除、不会回显控制序列，因此无安全风险，只是保真度边界。
测试只断言「无控制字符」，不把 `'ND'` 固化成期望值。

**C · 注入时钟贯穿。** `_record(d, at_ms=None)` 接受调用方时钟，
`pick_for_event` 的 5 个分支与 `record_error` 全部传 `at`；
`EvictionRecord.at_ms` 与 `SloganDecision.at_ms` 同源。实测注入
`now=1000.0` 时淘汰痕 `at_ms=1000000`，两次回放的
`(owner, dropped, at_ms, reason_counts)` 完全一致；
不注入时仍产出正的 `time.monotonic()` 毫秒值。

**H · `reason_counts` 摘要。** `EvictionRecord` 新增
`Tuple[Tuple[str,int],...]`，按 reason 计数并排序（确定性）。
实测桶内 `ok / error:boom / ok` 淘汰后
`reason_counts=(('error:boom',1),('ok',2))`、`last_reason` 仍是
`'ok'`，但错误信号不再丢失；`sum(counts) == dropped`。
摘要**不含文案与 entry_id**，`audit().ok` 不受影响
（淘汰是正常有界行为）。

**D · 口径精确化。** 新增 `OWNER_LIMIT = 64` 常量，docstring 改为
「干净且 ≤ `OWNER_LIMIT` 码点零改动」，并写明 65 码点以上的纯
ASCII 干净串也会归指纹。功能零变化（写入/查询仍命中同一 key），
加 64/65 边界测试锁住。

### 验证

```
tests/test_slogan_mapping.py + test_runtime_slogans.py   276 passed
tests/verify_slogan_mapping.py                           80 项纯 stdlib 全绿
verify_deep.py / verify_deep2.py                         22 / 20 项全绿
```

既有静态源码断言**一条都没放宽**；本轮没有因改实现去改旧断言。

### 实测数字（同机同环境）

```
'\x00'*1000+'OK'    -> 'OK'      (旧: '')
'\x1b'*900+'END'    -> 'END'     (旧: 'ND')
'\x1b\x1b[31m'      -> ''        (未误伤 CSI)
注入 now=1000.0     decision.at_ms = EvictionRecord.at_ms = 1000000
reason_counts       (('error:boom', 1), ('ok', 2))
index_stats         1695×4 / clipped=0 / unrenderable=0 / collisions=0
                    index_misses=0 / unresolved_misses=0
OWNER_LIMIT         64 / 64 原样 / 65 归指纹
_clean_once         64KiB≈17ms  1MiB≈0.32–0.37s  2MiB≈0.66–0.68s
```

### 如实边界（续 §14）

32. 本轮**不改** 18 个事件、16 个上下文、1108 条词条、
    `fully_superior`、99 模块基线、任何对齐指标、CLI 子命令数；
    零新增文件、零删除。`tui.py` 与 `runtime_slogans.py` 文件本轮
    **零改动**；但二者 re-export 的 `_clean.sanitize_verb` 因
    `_clean_once` 新增 ESC_RUN 而对「连续 ESC 输入」更保真，
    其余行为不变（139 例既有回归全绿）。
33. **候选 A 实测不成立、未修**，不包装成成果。写下来是因为
    「先实测再修」的意义一半在于避免修不存在的问题。
34. `_SCAN_CAP=65536` 是显式 fail-closed 边界：超过 64KiB 的输入
    **仍先粗切**，尾部合法内容可能救不回（实测
    `'\x00'*70000+'OK' -> ''`）。不宣称「任意长度都保真」。
35. **单个** `ESC` + 可打印字母的 ECMA-48 歧义未解决
    （`'\x1bEND' -> 'ND'`）；ESC 已清除故无安全风险，只是保真度边界。
36. `E` 未修：`norm_owner` 对超长 owner 仍做全串 sha1，实测
    2 MiB ≈ 1.7 ms；不宣称已消除该线性成本。
37. `reason_counts` 只汇总 reason 字符串，不含文案/entry_id；
    只保留最近 64 次淘汰、不复活决策内容；`evicted_recent`
    仍是观测项，不参与 `audit().ok`。
38. 并发压测仍未复现 list 撕裂；不是真机长跑；TUI 仍未替换
    任何既有 i18n 文案；分叉改动仍未合并；第三方自适应红队
    仍未做；**不宣称性能提升**（`_clean_once` 对超长输入反而
    因去掉粗切多扫了字符，靠 `_SCAN_CAP` 兜住）。


---

## 16. ESC+ 引导、时钟严格化、有界摘要、累计淘汰证据

前六轮把对应关系做到了可反查、可回放、有界、fail-closed、可自愈、
owner 全链路归一、先清理后截断。本轮仍**先实测再修**：四个真实缺陷，
四个候选**实测不成立、未修**，外加一个**本轮自己引入又自己抓回来**
的缺陷。全部不扩广度。

### 四个真实缺陷（全部先实测复现）

| # | 实测 | 影响 |
|---|---|---|
| A | `'\x1b\x1b]8;;evil\x07OK' -> 'K'`、`'\x1b\x1b[31mRED' -> 'ED'`、`'\x1b\x1b[?25lHIDE' -> 'IDE'` | **上一轮 ESC_RUN 修复的覆盖缺口**。上一轮只测了 `'\x1b\x1b[31m' -> ''`（无可打印尾巴）就宣称「真序列已先被剥掉」。实际 OSC/CSI 正则从 ESC 串**最后一个** ESC 开始匹配，前面留下孤立 ESC，被 `_ESC_SEQ_RE` 与尾部第一个可打印字符拼成假序列吞掉 |
| B | `now=nan` 抛 ValueError、`now=inf` 抛 OverflowError、`now='1000'` 产出 4000 位天文数字；`record_error(at_ms='1000')` 把**字符串**存进 `SloganDecision.at_ms`，`True` 被当成 1 | public 时钟入参一路裸奔，与 `load_config` / `_coerce_log_limit` 的严格类型口径不一致；字符串参与 `*1000` 还是内存/CPU 放大 |
| D | 1 MiB owner 归一 ≈ 12.7 ms，`hashlib.sha1(raw.encode(...))` 对**整串**做，无上界 | 上一轮明确留的边界；每次写入/查询都付整串编码成本 |
| F | 淘汰缓冲滚动后 `stats` 只有 `evicted_recent=64`，答不出「进程里总共淘汰过多少次」 | `_INDEX_MISSES` 做过「连续 / 累计」双层口径，淘汰痕没做 |

### 本轮自己引入、又被实测抓回的缺陷（A′）

修 B 时写成 `_coerce_ms(...) or _fallback_ms()`。实测 `now=0` →
`at_ms=1072138`（真实时钟）而不是 `0`，`at_ms=0` 同样被吞，
淘汰痕 `at_ms` 也跟着错。**合法 0 被当成 falsy**。
改为显式 `ms is None` 判断后 `now=0 -> 0`、`now=1 -> 1000`、
`now=1000.0 -> 1000000`、淘汰痕 `at_ms=0` 全部正确。
这与深度轮 5 的 A′ 是同一类教训：**把校验结果直接当布尔用，
合法零值就会掉进兜底分支**。

### 四个候选实测不成立、未修

| 候选 | 实测 | 结论 |
|---|---|---|
| C | 组合标记链 10×、变体选择符链 20×、bidi+ZWSP 20×、嵌套 Cf/Cc 20×、ZWSP 1–20× 全部保留尾部合法文本；3 次不动点从未把正常文本判空 | **不成立**，未改；加回归锁住 |
| C2 | 怀疑开头组合标记造成 zalgo 视觉混淆，实测 `'\u0301'*3+'OK' -> 'OK'`、`'\u034f'*5+'OK' -> 'OK'`、`'\u200d'*3+'OK' -> 'OK'` | **不成立**，已清；未改 |
| E | `norm_owner('s\ud800A') != norm_owner('s\ud800B')`，且两者都幂等、输出不含 surrogate | **不成立**，`encode(replace)` 未造成撞车；未改 |
| G | `record_error(kind=含 OSC8 + RLO 的串)` → `reason='error:BOOM'`，无控制字符 | **不成立**，D4 已净化；未改 |

### 修复

**A · OSC/CSI 允许 `ESC+` 引导。** `_OSC_RE` / `_CSI_RE` 的开头
`\x1b` 改成 `\x1b+`，整段「连续 ESC 串 + 真序列」一次剥掉，
不再留下孤立 ESC。顺序仍是 OSC → CSI → ESC_RUN → ESC_SEQ → CTRL。
实测五个 case 全部恢复尾部原文：
`'...\x07OK' -> 'OK'`、`'\x1b\x1b[31mRED' -> 'RED'`、
`'\x1b\x1b[?25lHIDE' -> 'HIDE'`、`'\x1b\x1b]0;title\x07TAIL' -> 'TAIL'`、
`'\x1b\x1b\x1b]8;;evil\x07END' -> 'END'`。
单 ESC 行为**不变**（`'\x1b]8;;evil\x07OK' -> 'OK'`、
`'\x1b[31mRED\x1b[0m' -> 'RED'`、`'\x1b\x1b[31m' -> ''`）；
单个 `'\x1bEND' -> 'ND'` 的 ECMA-48 固有歧义**仍未改**（ESC 已清除，
无安全风险）。全部幂等。

**B · `_coerce_ms(value, is_seconds)`。** 拒绝 bool / 非数值 /
非有限 / 负值 / 超上界（`now` ≤ 1e12 秒、`at_ms` ≤ 1e15 毫秒），
脏值返回 `None` → 回落**真实单调时钟**。三个入口
（`pick_for_event`、`record_error`、`_record` 的淘汰痕）统一。
实测 9 种脏值全部产出合法正 `int`、不抛异常、不产生字符串/天文数字；
合法注入回放不变；**合法 0 不被吞**。

**D · `owner` 有界摘要。** 新增 `OWNER_SCAN_CAP = 4096`：
超过上界改用「头 2048 + 总长 + 尾 2048」参与 sha1，不再整串编码。
实测两个仅尾部不同的 100k 串仍不撞车、输出仍 22 码点且严格幂等、
写入/查询命中同一桶；64KiB → 8 MiB 输入耗时均 ≈ 12–14 ms
（**与长度无关**，但这是 `_SCAN_CAP=65536` 的固定扫描上限，
不等于「只扫 4096」）。
如实边界：共享前 2048、后 2048 且总长相同、仅**中间**不同的两个
超长串会撞到同一 key —— 有界摘要的固有碰撞面，不宣称
「任意两个不同串绝不撞」。

**F · 累计淘汰证据。** 新增 `_EVICT_TOTAL` + `evicted_total()` +
`dispatch_log_stats()['evicted_total']` + `audit().as_dict()` 自动携带。
与 `_INDEX_MISSES` 对齐：环形缓冲只答「最近 64 条」，累计值答
「总共多少次」，**不因缓冲滚动丢失**、**不参与 `audit().ok`**
（淘汰是正常有界行为）。只有显式 `reset_dispatch_log()` 全清
（测试隔离）才归零；`reset_runtime_counters()` 默认不清、
指定单 owner 释放也不清。

### 验证

```
tests/test_slogan_mapping.py + test_runtime_slogans.py   300 passed
tests/verify_slogan_mapping.py                           88 项纯 stdlib 全绿
verify_deep.py / verify_deep2.py                         22 / 20 项全绿
```

既有静态源码断言**一条都没放宽**；只有本轮新写的一条断言
（检查 `or _fallback_ms()` 不在源码里）被注释文字误伤，改成检查
`is None` 分支的实际代码，不是放宽策略。

### 实测数字（同机同环境）

```
A   '\x1b\x1b]8;;evil\x07OK' -> 'OK'   (旧 'K')
    '\x1b\x1b[31mRED'        -> 'RED'  (旧 'ED')
    '\x1b\x1b[?25lHIDE'      -> 'HIDE' (旧 'IDE')
B   now=nan/inf/'1000'/True/-1/1e300 -> 合法正 int, 不抛异常
A'  now=0 -> 0, now=1 -> 1000, now=1000.0 -> 1000000
D   100k+'A' vs 100k+'B' 不撞 / 幂等 / 22 码点
    64KiB→8MiB 归一均 ≈12–14 ms (固定上限)
F   evicted_recent=64, evicted_total=114, audit ok=True
index_stats  1695×4 / clipped=0 / unrenderable=0 / collisions=0
             index_misses=0 / unresolved_misses=0
```

### 如实边界（续 §15）

39. 本轮**不改** 18 个事件、16 个上下文、1108 条词条、
    `fully_superior`、99 模块基线、任何对齐指标、CLI 子命令数；
    零新增文件、零删除。`tui.py` 与 `runtime_slogans.py` 文件
    本轮**零改动**（本轮推送不包含它们）。
40. **A′ 是本轮修 B 时自己引入、再被实测抓回来的**，不是原有缺陷；
    与 §14 的 A′ 同类：校验结果别直接当布尔用。
41. **A 是上一轮 ESC_RUN 修复的覆盖缺口**，不是全新洞 ——
    上一轮只测了无尾巴的 case 就宣称覆盖，本轮补五个带尾巴的。
42. **单个** `\x1bEND` 的 ECMA-48 歧义仍未解决；ESC 已清除故无
    安全风险，只是保真度边界。
43. `_SCAN_CAP=65536` 之外仍先粗切；D 的有界摘要对「仅中间段
    不同」的超长 owner 存在碰撞面，不宣称零碰撞。
44. 脏时钟注入回落真实时钟，**不保证这类调用的回放确定性**；
    可回放性只对合法注入成立。
45. `evicted_total` 是信息项，不参与 `audit().ok`；只保留
    64 条明细、不复活决策内容。
46. 并发压测仍未复现 list 撕裂；不是真机长跑；TUI 仍未替换
    任何既有 i18n 文案；分叉改动仍未合并；第三方自适应红队
    仍未做；**不宣称性能提升**（D 只是把无界成本改成固定上限）。


---

## 17. 这一轮只修两个证据缺口，其余八个候选判定「不该动」

前七轮把对应关系做到了可反查、可回放、有界、fail-closed、可自愈、
owner 全链路归一、先清理后截断、ESC+ 引导、时钟严格化。本轮仍是
**先实测再修**，但结果和前几轮不一样：**测了 8 个候选，真正该动的
只有 2 个**，其余 6 个要么是 ECMA-48 规范歧义、要么是工程上不该动
的取舍、要么是前几轮已如实记录的边界。

把「不该修」的判断写成可执行证据，比多修一个洞更有价值 —— 否则
每轮都能找到「看起来像 bug」的现象，改着改着就把前七轮收口的
安全边界重新打开。

### 两个真实缺口（C / H）

| # | 实测 | 影响 |
|---|---|---|
| C | 造一条 `error:boom` 后灌 84 条决策：`dispatch_log('s0')` 里 **error 消失**，而 `evicted_recent=0`、`evicted_total=0` —— **根本没有发生淘汰** | `_DISPATCH_CAP=64` 的 `del bucket[:-cap]` 静默裁掉早期决策。上一轮的 `EvictionRecord.reason_counts` 只在淘汰时汇总「当前桶」，**覆盖不到这一层** |
| H | `dispatch_log_stats()['decisions']` 恒等于各桶当前留存条数之和，裁剪后永远 ≤ `max_owners × cap` | 答不出「进程里总共分发过多少次决策」，与 §16 的 `evicted_total` 同类缺口 |

**C′（本轮自引入又抓回）**：`_accumulate_trim_reasons` 初版写
`len(_TRIMMED_REASONS) >= CAP` 才归 `<other>`，实测 200 个不同 kind
后产出 **65** 个键（64 个具体 + `<other>`），上限失效。改成按
「具体 reason 种类」计数，`<other>` 作为额外一个桶，总数恒
≤ `CAP + 1`。这是连续第三轮出现「修校验时自己引入 off-by-one /
falsy 吞零值」，已单独记录。

### 六个候选判定「不该动」

| 候选 | 实测 | 为什么不修 |
|---|---|---|
| **A** 未终止 OSC 吞光整行 | `'\x1b]8;;https://evil.example'+'OK' -> ''`、`'\x1b]0;title'+'TAIL' -> ''`；`sanitize_verb` 同源也被吞（G） | ECMA-48 里 OSC 必须由 BEL/ST 终止，**无终止符时后续字节规范上全属参数**，整段删是规范正确的。尝试修（终止符必需 + 4096 上限）会把 4096 之后的**参数残留文本**放进日志（实测残留 904 码点），反而放宽净化；且 `sanitize_log_field` 最终按 120 码点截断，尾部 `END` **仍不可达**。收益为零、风险为正 |
| **B** ZWJ emoji 被拆散 | `👩\u200d💻 -> 👩💻`、`👨\u200d👩\u200d👧 -> 👨👩👧`、彩虹旗/爱心火也拆 | 核查 1695 条词条：**含 ZWJ 0 条、VS16 0 条、ESC 0 条**。修它要放宽 Cf 清理（保留 ZWJ）并连带改 `_clusters` / `display_cols` / 500 串宽度交叉回归 / 幂等契约，而 bidi isolate、RLO、ZWSP 必须继续删。**实际标语零收益，安全与宽度真值风险为正** |
| **D** `reason_counts` 含外部串 | 注入 `'\x1b]8;;x\x07\u202eBAD'` → `('error:BAD', 1)`，无控制字符 | D4 已净化 kind，**不成立** |
| **E** 粗切边界切掉尾部 | `'\x00'*65530+'\u0301'*3+'OK' -> 'OK'`，但 `n=65533` → `''` | 合法文本落在 `_SCAN_CAP=65536` 窗口外，是 **§15 已如实记录的显式 fail-closed 边界**，不是新缺陷 |
| **F** `sanitize_verb` 丢尾部 | `'\x00'*1000+'OK' -> 'OK'`，`'a'*500+'END'` 只剩前 40 列 | 前者说明它也是先清理后截断；后者是**设计内的列宽截断**，不是缺陷 |
| **G** 两个出口同病 | `sanitize_verb('\x1b]0;title TAIL') == ''`，`runtime_slogans.sanitize_verb is _clean.sanitize_verb` → True | 是 A 的同源证据，共用 `_clean_once` 本就是前几轮刻意收口的「单一净化真值」，不该拆开 |

### 修复（不动净化层一行）

- **C · 桶裁剪留痕**：新增 `_DECISIONS_TOTAL` / `_BUCKET_TRIMS` /
  `_TRIMMED_DECISIONS` / `_TRIMMED_REASONS`（全局，种类上限 64）/
  `_TRIMMED_BY_OWNER`（与桶同生命周期）。`_record` 的
  `del bucket[:-cap]` 改为先取 `dropped`，累加三层证据。
  `EvictionRecord` 新增 `trimmed_dropped` /
  `trimmed_reason_counts`（带默认值，兼容既有构造），会话被 LRU
  淘汰时把该 owner 的裁剪摘要**一起带走**。
  新增 `bucket_trim_stats()`；`dispatch_log_stats()` 增
  `decisions_total` / `bucket_trims` / `trimmed_decisions`，
  `audit().as_dict()` 自动携带。
- **H · 累计决策数**：`_DECISIONS_TOTAL` 在每次 `_record` 时递增，
  含被裁、被淘汰的决策；只有显式 `reset_dispatch_log()` 全清才归零。

实测（灌 84 条 + 一条 error）：

```
桶内 error 消失 (len=64), evicted_recent=0, evicted_total=0
decisions_total=86  decisions=64  bucket_trims=22  trimmed_decisions=22
bucket_trim_stats.reason_counts=(('error:boom',1),('ok',21))
淘汰后 EvictionRecord(owner='s0', dropped=64, last_reason='ok',
  reason_counts=(('ok',64),),
  trimmed_dropped=22,
  trimmed_reason_counts=(('error:boom',1),('ok',21)))
audit ok=True
```

全部是**信息项**，不参与 `audit().ok`（裁剪是正常有界行为）。
`release_owner()` / `take_owner_log()` 显式释放时丢弃该 owner 的
per-owner 摘要，但**全局累计仍保留** —— 这个不对称如实写在
`bucket_trim_stats()` 的 docstring 里。

### 验证

```
tests/test_slogan_mapping.py + test_runtime_slogans.py   319 passed
tests/verify_slogan_mapping.py                           97 项纯 stdlib 全绿
verify_deep.py / verify_deep2.py                         22 / 20 项全绿
```

既有静态源码断言**一条都没放宽**；本轮没有因改实现去改旧断言。
新加的回归里，`test_A_attempted_fix_would_leak_osc_parameters`
把「想修会放宽净化」变成**可执行证据**，而不只是文档里的辩解；
`test_B_registry_contains_no_zwj_variation_or_esc` 把「收益为零」
变成对 1695 条词条的运行时断言。

### 如实边界（续 §16）

47. 本轮**不改** 18 个事件、16 个上下文、1108 条词条、
    `fully_superior`、99 模块基线、任何对齐指标、CLI 子命令数；
    零新增文件、零删除。
48. **`_clean.py` / `tui.py` / `runtime_slogans.py` 本轮逐字节未改**，
    都不在推送清单里。A/B 两个保真度候选**确认成立但没有修**，
    理由与实测证据见上表；这是明确的工程取舍，不是遗漏。
49. **C′ 是本轮自引入、被新增回归抓回来的上限 off-by-one**，
    不是原有缺陷。
50. 裁剪证据的 per-owner 摘要只在 **LRU 淘汰**时随
    `EvictionRecord` 带走；显式释放的会话不带走，全局累计仍保留。
    `bucket_trim_stats()` 的全局摘要**不归属到具体 owner**。
51. 全局 reason 摘要最多 64 种具体 reason + 1 个 `<other>`；
    `<other>` 会合并尾部种类，不保留原始分布。
52. 未终止 OSC 的 ECMA-48 规范歧义**未解决**；短 UI 文案里的
    ZWJ emoji 仍会拆散；`_SCAN_CAP=65536` 之外仍先粗切。
    三者都已有回归把「当前正确行为」锁住，防止以后误改。
53. 并发压测仍未复现 list 撕裂；不是真机长跑；TUI 仍未替换
    任何既有 i18n 文案；分叉改动仍未合并；第三方自适应红队
    仍未做；**不宣称性能提升**（本轮给裁剪路径多加了 Counter
    更新，是有界常数开销，未做基准对比）。


---

## 18. public 入参的最后两块裸地：event 类型守卫与脏 owner 隔离

前八轮把对应关系做到了可反查、可回放、有界、fail-closed、可自愈、
owner 全链路归一、裁剪留痕、累计证据。本轮继续「先实测再修」，但把
镜头对准了**前八轮一直没扫到的 public 入参类型面** —— 不是找新的
净化洞，而是找「调用方一个笔误就能拿到错误结果、却没有任何报错」
的静默折叠。

### 两个真缺陷

| # | 实测 | 影响 |
|---|---|---|
| **N1** | `pick_for_event(['a'])` → `TypeError: unhashable type: 'list'`；`{'x':1}` 同理 | `event` 在查 `SECURITY_EVENTS` / `EVENT_BINDINGS` **之前**没有任何类型守卫。与 `record_error` 先净化再结构化拒绝的口径不一致；TUI `_slogan_dispatch` 的 `except UnboundSloganEvent` 接不住它，落到 `except Exception` 只记 `error:TypeError`，`strict=True` 开发模式期望的严格契约被绕过 |
| **N2** | `norm_owner` 旧实现 `if not isinstance(raw, str) or not raw: return ""`，把 `None / 123 / True / b'bytes' / list / dict / float` **全部静默折叠成空 key** | 实测七个不同脏 owner 共用一个桶、污染「不传 owner」调用方的默认桶；更糟的是 `dispatch_log(None)` 是「全量」语义而 `dispatch_log(123)` 查的是空桶，同一次运行分别返回 **9 条和 8 条** —— 一个笔误就拿到完全错误的日志集合，无报错、无留痕 |

### 四个候选判定「不该修」

| 候选 | 实测 | 结论 |
|---|---|---|
| `lang` 非字符串 | `resolve_lang(123/True/b'x'/list/float)` 静默回落默认语种，分发仍 `ok` | 只影响选词语种，不影响分桶/裁决；修它要改 picker（另一文件），收益低。**未修**，加回归锁住 |
| `record_error` 的 event / kind 非字符串 | 全部得到 `<invalid-event>` / `error:invalid-field`，无控制字符 | D4 已净化，**已正确** |
| `sanitize_log_field` / `sanitize_verb` 非字符串 | 一律返回 `''` | 既有 fail-closed 契约，**未修** |
| `owner=None` 与 `''` 同桶、`dispatch_log(None)` 全量 | 文档明确写明的兼容契约 | **未修**；本轮只把「非字符串脏值」与「无 owner」分开，不动这两条 |

### 修复

**N1 · 查表前的类型守卫。** `pick_for_event` 开头加
`if not isinstance(event, str): raise UnboundSloganEvent(...)`，消息用
**固定占位** `<invalid-event>`，刻意**不调用 `str(raw)`** —— 否则超长
或带控制字符的外部串会进 traceback。九种非字符串输入（含不可 hash
的 list / dict / tuple / frozenset）现在统一走同一个结构化异常；
18 个合法事件的行为零变化。

**N2 · 固定隔离桶 + 入口计数留痕。**

- `norm_owner`：`None` 仍返回 `''`（表示「无 owner」），其余非字符串
  返回 `_INVALID_OWNER_KEY = "owner:invalid"`。该键干净、13 码点、
  远小于 `OWNER_LIMIT`，因此 `norm_owner` **严格幂等**，写入侧与查询侧
  自动对上 —— 实测 `dispatch_log(d.owner)` 现在能查到脏值日志
  （旧版查的是空桶）。
- `_coerce_owner(raw)`：只在 `pick_for_event` / `record_error` **入口**
  调用，对非 str 调用 `_note_invalid_owner()`；查询侧
  （`dispatch_log` / `release_owner` / `take_owner_log`）继续用
  `norm_owner`，**不重复计数**（实测 20 轮查询后计数仍为 1）。
- `_note_invalid_owner()`：类型名来自 `type(raw).__name__`，是 public
  可控字符串（自定义类名可含 ESC / RLO / 超长），必须过同一份净化
  核心并限长 32；种类上限 32，超出归 `<other>`。
- `dispatch_log_stats()` 新增 `invalid_owner_calls` /
  `invalid_owner_types`（脱敏、排序、加锁快照），
  `audit().as_dict()` 自动携带。返回类型注解从 `Dict[str, int]` 改为
  `Dict[str, object]`（含 tuple）。
- `reset_dispatch_log()` 全清时归零；`reset_runtime_counters()` 默认
  不清、指定单 owner 释放也不清 —— 与前几轮所有累计证据的语义一致。

### 实测数字（同机同环境）

```
修复前  pick_for_event(['a']) -> TypeError: unhashable type: 'list'
修复后  -> UnboundSloganEvent("<invalid-event>")
修复前  9 个脏/空/real owner -> dispatch_log(None)=9, dispatch_log(123)=8,
        dispatch_log("")=8, owners=2
修复后  owners=3, decisions=9, invalid_owner_calls=6,
        types=(('bool',1),('bytes',1),('dict',1),('float',1),('int',1),('list',1))
        dispatch_log(None)=9, dispatch_log(123)=6,
        dispatch_log("")=2, dispatch_log("real")=1
        norm_owner('owner:invalid') == 'owner:invalid'  (严格幂等)
        audit ok=True

自引入边界实测（本轮未出现需要回修的自引入缺陷，但逐个量过）:
  A' 20 轮查询后 invalid_owner_calls 仍为 1
  B' 自定义类名含 OSC8+RLO+500 个 A -> 脱敏后 33 码点且无控制字符
  C' 60 种类型 -> 具体 32 种 + '<other>' = 33 项, calls=60
  D' reset_runtime_counters / 单 owner reset 不清, 全清归零
  E' 0 / False / 0.0 / [] / {} / () 等 falsy 非 str 同样隔离
```

### 验证

```
tests/test_slogan_mapping.py + test_runtime_slogans.py   343 passed
tests/verify_slogan_mapping.py                           105 项纯 stdlib 全绿
verify_deep.py / verify_deep2.py                         22 / 20 项全绿
```

**一条既有源码级断言因行为变更同步到新契约，不是放宽**：
`t_d5_owner_normalization` 原断言 `owner = norm_owner(owner)` 在源码里；
入口改走 `_coerce_owner` 后改为同时检查 `def norm_owner` /
`def _coerce_owner` / `owner = _coerce_owner(owner)` / 两处调用，
并保留 `norm_owner(None) == ""` 等全部运行时断言。其余既有断言
一条未动、一条未放宽。

### 如实边界（续 §17）

54. 本轮**不改** 18 个事件、16 个上下文、1108 条词条、
    `fully_superior`、99 模块基线、任何对齐指标、CLI 子命令数；
    零新增文件、零删除。
55. **`_clean.py` / `tui.py` / `runtime_slogans.py` /
    `test_runtime_slogans.py` 逐字节未改**，都不在推送清单里。
    本轮唯一改动的运行时代码是 `ui/slogans/mapping.py`。
56. **行为变更（仅针对错误用法）**：非字符串 `owner` 从默认桶移到
    `owner:invalid` 隔离桶；正常字符串 owner、`None`、`''` 零变化。
    依赖「传数字也照样进默认桶」的调用方需改传字符串。
57. **固定键的固有碰撞面**：若调用方真的把字符串
    `"owner:invalid"` 当 owner 用，会与脏值桶撞（已加回归锁住这个
    事实）。不宣称零碰撞。
58. `invalid_owner_types` 最多 32 种具体类型 + 1 个 `<other>`；
    后者合并尾部种类、不保留原始分布。类型名经净化限长，超长类名
    只保留前 32 码点 + 省略号。
59. 计数只在两个入口发生，`dispatch_log` / `release_owner` /
    `take_owner_log` 等查询侧不重复计；全局累计只有显式
    `reset_dispatch_log()` 全清才归零。
60. **本轮没有出现需要回修的自引入缺陷**（连续三轮 A′ 后第一次），
    但 A′–E′ 五个边界都做了实测，见上表。不把这写成「零缺陷」，
    只写「本轮实测未发现」。
61. 并发压测仍未复现 list 撕裂；不是真机长跑；TUI 仍未替换
    任何既有 i18n 文案；分叉改动仍未合并；第三方自适应红队
    仍未做；**不宣称性能提升**（入口多了一次 isinstance 与有界
    Counter 更新，未做基准对比）。


---

## 19. 换镜头：引擎本体的 public 入参面（前九轮只改了 mapping.py）

前九轮几乎都在改 ``ui/slogans/mapping.py``，``tuan_cli/tui/
runtime_slogans.py`` 逐字节未动 —— 而它正是「给转圈的英文挂上中文后，
我发现它在摸鱼」那个 B 站视频梗的本地化实现本体：事件驱动标语、
分阶段活性预算、「疑似摸鱼」诊断。本轮把同一套「先实测再修」的方法
搬过去，**不扩广度**（18 个事件、16 个上下文、1108 条词条、
``fully_superior``、99 模块基线、所有对齐指标、CLI 子命令数全不变）。

### 最毒的一个：异常路径的半更新（P1）

D1 用 ``RLock`` 解决了**并发**撕裂，但锁防不住**异常路径**。
``note_activity`` 的顺序是「写 ``_last_event_at`` / ``_phase`` /
``_current`` / ``_seq`` → 最后 ``_record_locked`` 里 ``int(at*1000)``」。
实测：

```
e.note_activity('streaming', now=1000.0)      # 健康状态
e.note_activity('running_tool', now=math.nan) # 抛 ValueError
before: (1000.0, 1, 'streaming', '正在边想边说')
after : (nan,    2, 'running_tool', '正在跑命令')   ← 状态已半更新
e.liveness()   -> ValueError   (UI 会崩)
e.snapshot()   -> ValueError   (UI 会崩)
```

``_last_event_at=nan`` 之后，``liveness`` 的 ``int((at-nan)*1000)``
永久抛异常。也就是说：**一个 public 时钟入参的脏值，能让整个 TUI
渲染循环停摆**。这是本轮最值钱的发现，不是「多了个报错」。

同一条路径上还实测出：``now='1000'`` 抛底层 ``TypeError``、
``inf`` 抛 ``OverflowError``、``True`` 被悄悄当成 1 秒、
``1e308`` 是**合法有限值**却在 ``int(at*1000)`` 处溢出成 inf、
注入 ``clock=lambda: 'x'`` / ``clock`` 抛异常同样掀掉调用方。
引擎侧从来没做过深度轮 7 给 mapping 做过的严格校验。

### 六个真缺陷

| # | 实测 | 影响 |
|---|---|---|
| **P1** | 见上；``now=nan`` 异常后状态半更新，``liveness`` / ``snapshot`` 永久抛 | 脏时钟入参让 UI 崩，且 D1 的锁完全没覆盖异常路径 |
| **P2** | ``note_progress(kind=evil)`` 后 ``EventRecord.kind`` 原样保留 530 码点含 OSC 8 + RLO | ``kind`` 会经 ``Liveness.evidence`` 进诊断输出；``mapping.record_error`` 早已净化 kind，引擎这边漏了 |
| **P3** | ``mode = str(raw_mode)`` 后 ``source=f"invalid:mode={mode}"`` 把 settings.json 里 5000 码点含 ESC/RLO 的串原样带出 | ``Liveness.source`` / ``snapshot()["source"]`` / ``render`` 全带未净化外部串 |
| **P4** | ``reset()`` 用 ``self._clock()``，而 ``note_activity(now=...)`` 走注入时钟：``[1000000, 1001000, 1000000]`` **时间倒退**；真实 monotonic 下是「1000 秒」与「1945 秒」两套时间源 | 证据链不可回放。这是深度轮 6 在 mapping 层修过的「淘汰痕与 decision 时钟不同源」的引擎版 |
| **P7** | ``note_activity(detail=None/123)`` → ``_record_locked`` 里 ``len(detail)`` 抛 ``TypeError``；``detail=['a']`` 则被 ``_detail_class`` 当字符串遍历、得出误导性 ``class='ascii'`` | public 入参类型面，同样会掀掉 UI |
| **P8** | ``load_config(123)`` / ``(['a'])`` 直接抛底层 ``TypeError`` | ``p = _settings_path(path)`` 在 ``try`` **之外**，而 docstring 明确写「绝不因为配置写错就让 TUI 崩」（except 里明明有 TypeError，只是位置不对） |

### 四个候选判定「不该修」

| 候选 | 实测 | 结论 |
|---|---|---|
| **P5** | ``phase`` 为 ``None/123/list/dict/tuple/bytes/nan/未知串`` 一律兜底 ``waiting_model``，不可 hash 类型也不抛 | 既有 fail-safe 契约，phase 不进日志原文；修它要改内部状态机语义，收益低。**未修** |
| **P6** | 字符串 ``detail`` 只记 ``len`` + 字符类别、不记原文（20 万码点也只留一个整数） | D3 已正确，是脱敏契约本身。**未修** |
| **P9** | 未知阶段键（含 5000 码点脏串）返回固定 ``invalid:budget-phase`` | 检查在 ``__post_init__`` 之前，原文根本进不了 source。**已正确** |
| **P10** | ``sanitize_verb(123) == ''`` | 既有 fail-closed 契约。**未修** |

另外把「``liveness`` / ``render`` / ``snapshot`` 仍是纯读」也写成回归，
防止以后为了对齐又从渲染循环里记活性 —— 那正是 D4 反复反对的
「定时空转装忙」。

### 修复（只改一个运行时文件）

- **统一时钟入口 ``_now(value)``**：``_coerce_now_value`` 只接受有限
  实数秒、拒绝 ``bool`` / 非数值 / 非有限 / 负数 / 超过
  ``_MAX_NOW_SECONDS=1e9``（夹上界的理由是 ``int(at*1000)`` 溢出，
  不是业务上限）。优先级：合法 ``now`` > 合法注入 ``clock`` >
  ``time.monotonic()``；注入 clock 抛异常也接住。**校验在所有字段
  写入之前**完成，这是消除异常路径半更新的关键。``0`` 是合法零值，
  显式判 ``is None``（深度轮 7 踩过 ``or fallback()`` 吞零的坑）。
  ``note_activity`` / ``note_progress`` / ``liveness`` / ``render`` /
  ``snapshot`` 五个出口全部走它。
- **P2**：``note_progress(kind)`` 过 ``sanitize_log_field(kind, 40)``，
  非法回落 ``"progress"``；与 ``_clean`` 同一净化真值，不新造第二套。
- **P3**：新增 ``_safe_source()``，所有 ``source`` 出口统一净化限长
  120；``mode`` 非字符串直接拒绝、字符串过同一净化真值限长 40；
  ``phase_budgets_ms`` 的键与 ``str(p)`` 同样净化。合法配置
  ``source == str(p)`` 零变化。
- **P4**：``reset()`` 优先沿用 ``_last_event_at`` 的时钟（并对
  nan/inf 残留做防御），全新引擎才回落 ``_now(None)``。证据链
  完全同源、单调，``kind="reset"`` 本身已足够标记回合边界。
  **不改 ``reset()`` 签名**，既有调用零变化。
- **P7**：``detail`` 非字符串收敛成 ``""``（与 D3「绝不记原文」一致）。
- **P8**：``p = _settings_path(path)`` 挪进 ``try``。

### 实测数字（同机同环境）

```
修复前  now=nan -> ValueError + 状态 (nan, 2, 'running_tool', ...)，
        liveness/snapshot 均抛 ValueError
修复后  now=nan -> 回落注入 clock 1000.0，事件完整生效，
        liveness/snapshot 均 healthy，零异常
        now=0 -> _last_event_at=0.0（合法零值不被吞）
        now=1e308 -> 回落 1000.0（不再 int(inf) 溢出）
        clock=lambda:'x' / clock 抛异常 -> 回落 time.monotonic()

P2  kind 530 码点含 OSC8+RLO -> 41 码点、无控制字符
P3  source 5021 码点含 ESC/RLO -> 54 码点、无控制字符
P4  evidence [1000000,1001000,1000000]（倒退）
        -> [1000000,1001000,1001000]（单调、同源）
    真实时钟下 [1000000,1945418] -> [1000000,1000000]
P7  detail=None/123/list -> 长度 0 / class empty，不再抛
P8  load_config(123) -> 'builtin'，不再抛
```

### 验证

```
tests/test_runtime_slogans.py + test_slogan_mapping.py   376 passed
   （172 runtime_slogans + 204 slogan_mapping）
tests/verify_slogan_mapping.py                           117 项纯 stdlib 全绿
verify_deep.py / verify_deep2.py                         22 / 20 项全绿
```

**既有断言一条未动、一条未放宽**。新增回归里
``test_no_half_updated_state_on_dirty_now`` 把 P1 的「异常路径撕裂」
变成可执行证据；``test_string_detail_still_only_records_shape`` 把
「不该修」的 P6 锁成运行时断言。独立验证脚本新增引擎检查，已实测
在屏蔽 ``pytest / rich / prompt_toolkit / wcwidth`` 后仍可导入
（``tuan_cli.tui`` 用 PEP 562 惰性导出），不破坏纯 stdlib 约束。

### 如实边界（续 §18）

62. 本轮**不改** 18 个事件、16 个上下文、1108 条词条、
    ``fully_superior``、99 模块基线、任何对齐指标、CLI 子命令数；
    零新增文件、零删除。
63. **本轮唯一改动的运行时代码是
    ``tuan_cli/tui/runtime_slogans.py``**，与前九轮正好反过来：
    ``mapping.py`` / ``_clean.py`` / ``tui.py`` /
    ``ui/slogans/__init__.py`` / ``test_slogan_mapping.py``
    逐字节未改，都不在推送清单。净化层本轮仍零改动。
64. **行为变更仅针对错误用法**：脏 ``now`` / 脏 ``clock`` / 非字符串
    ``detail`` / 非字符串 ``kind`` / 脏 ``path`` 从「抛异常或带原文」
    变成「净化/回落/拒绝」；合法 ``now``、合法配置、合法 ``kind``、
    字符串 ``detail``、``reset()`` 签名零变化。
65. ``_coerce_now_value`` 把 ``now`` 夹在 ``[0, 1e9]`` 秒；超出
    （含合法但极大的有限值）回落真实时钟。这是为了
    ``int(at*1000)`` 不溢出，**不是**业务时间上限，也不宣称支持
    任意量级的单调时钟。
66. ``reset()`` 沿用最后事件时钟，因此 reset 与最后一条事件证据的
    ``at_ms`` 可能相同；回合边界靠 ``kind="reset"`` 区分。不传
    ``now`` 的调用方与注入时钟混用时，本轮保证**不倒退、不同源混写
    进同一条链**，但「两套时钟」的根因仍靠调用方自律。
67. P5 / P6 / P9 / P10 四个候选**确认属既有契约、判定不该修**，
    都有回归锁住当前行为；不是遗漏。
68. **本轮实测未发现需要回修的自引入缺陷**（连续第二次），但
    零值、极大有限值、clock 抛异常、非 str kind、reset 残留 nan、
    ``Decimal`` 六个边界都量过；不写成「零缺陷」，只写「实测未发现」。
69. 并发压测仍未复现 list 撕裂；不是真机长跑；TUI 仍未替换
    任何既有 i18n 文案；分叉改动仍未合并；第三方自适应红队
    仍未做；**不宣称性能提升**（入口多一次数值校验与净化调用，
    未做基准对比）。


---

## 20. 注入契约与配置切换锚点：上一轮修完入参面，这一轮修「谁被换掉了」

上一轮把引擎 public 入参面收口（异常路径半更新、未净化诊断）。
本轮把镜头对准两件更隐蔽的事：**注入对象被静默换掉**，以及
**配置切换打断 D1 的撕裂检测锚点**。仍然只挖深度：18 个事件、
16 个上下文、1108 条词条、`fully_superior`、99 模块基线、所有
对齐指标、CLI 子命令数全不变；零新增文件、零删除。

### D（最值钱）：`reload()` 让同一个 seq 对应两个文案

D1 用 `EventRecord` 里的 `(seq, verb)` 配对当作**并发撕裂检测的锚点**：
一个 seq 只能对应一个文案。旧 `reload()` 把 `self._current = ""`，
却**不推进 seq、不记证据**；而 `render()` 在 `not self._current` 时
会显示新词池首条。实测：

```
事件后    seq=1  current='正在刷屏'   evidence.verb='正在刷屏'
reload 后 seq=1  current=''          evidence.verb='正在刷屏'
render.text='重装后的词'   view.seq=1
>>> 同一个 seq=1 对应两个文案，D1 锚点被配置切换直接打断
```

更隐蔽的是第二次 `reload()` 返回 `(False, "unchanged")`，却照样
清空 `current` 造成**静默换词** —— 名字叫 unchanged，屏幕却变了。

修复后把配置切换视作一次**可审计的状态转移**：

- `unchanged` 是**真正的 no-op**（不清 current、不动 seq、不记证据、
  不碰缓存）；
- `changed` 时新文案取新词池首条（**确定性、不调 rng**，避免把
  配置重载伪装成随机 spinner 事件），推进 `seq`、记一条
  `kind="reload"` 证据，其 `verb` 与屏幕显示**严格相等**；
- 证据时间戳沿用 `_last_event_at`（与深度轮 10 P4 的 `reset()`
  同源），不把真实单调时钟和注入时钟混进同一条链。

实测：`seq 1→2`、`current = evidence.verb = render.text = '重装后的词'`、
连续 5 次 reload 的新文案恒为词池首条 `A`、真实时钟下证据
`[1000000, 1000000]` 不再出现 `[1000000, 1945418]` 两套时间源。
**这不是 D4 禁止的「从动画循环记活性」** —— reload 是显式配置
事件，D4 反对的是定时空转装忙，两者不矛盾。

### A：`__init__` 的 `or` 吞掉 falsy 但完全合法的注入对象

旧实现 `config or load_config()` / `rng or random.Random()`。实测
注入一个 `__bool__=False` 的 `SpinnerVerbsConfig` 子类和一个
`__len__=0` 的自制随机源：

```
config.source  'INJECTED'  -> 'builtin'      （注入配置被换掉）
注入 rng.choice 调用次数   0                 （确定性回放失效）
两个同构引擎 current       不相同             （随机源被换成全局 Random）
```

这是深度轮 7 A′（`_coerce_ms(...) or fallback()` 吞掉合法 `0`）
的**第三次同源**。改成显式 `is None` 后：注入对象原样保留、
`rng.choice` 调用 1 次、两个同构引擎文案一致、`None` 仍回落出厂值。

**`lang` 刻意不改**：实测 `slogan_bank("")` 会回落到**英文**词库，
若把 `lang or _current_language()` 也改成 `is None`，`lang=''`
反而从「本机 zh-CN」变成英文 —— 空串表示「未指定」是既有兼容
契约，改它是行为退化。判定「不该修」，加回归锁住。

### B：`load_config` 静默截断 205 → 200 条自定义词

旧实现 `raw_verbs[:200]`。实测写入 205 条 `verbs` 只生效 200 条，
第 205 条凭空消失，而 `source` 是**正常路径**、没有任何提示 ——
与深度轮 10 P8「静默忽略是危险的假安全感」同类。200 是防 DoS
上限，但不该悄悄生效：**超限整段拒绝**，返回
`invalid:too-many-verbs`，让用户明确知道要减到 200 以内。
200 条以内零变化（`source == str(p)`、`V199` 仍在）。

### C：`mode=default` 下自定义词全不可渲染时被静默忽略

旧实现只在 `append/replace` 下检查空词池。实测
`{"mode":"default","verbs":[123,None,['a'],{},True]}` 净化后一条
不剩，但 `source` 仍是**正常路径** —— 用户以为自定义了标语，
实际全用内置词库且毫不知情。现在「写了自定义词却一条都不可渲染」
对**所有** mode 一律用既有的 `invalid:empty-verbs` 拒绝（**复用
既有 source**，不改任何既有断言口径）。混合场景
`[123, "好词", None, "\x1b..."]` 仍只保留好词 `("好词",)`。

### 四个候选判定「不该修」

| 候选 | 实测 | 结论 |
|---|---|---|
| `lang` 的 `or` | `slogan_bank('')` 回落英文；改成 `is None` 会让 `lang=''` 从 zh-CN 变英文 | 既有兼容契约，改它是退化 → **未修** |
| `phase_budgets_ms` 的 `[:10]` 截断 | 合法阶段键上限 `len(PHASES)=5 < 10`，截断**不可达**；5 个合法键全部生效 | 不可达代码，无实际风险 → **未修** |
| `snapshot()` 写 `_pools` | `liveness`/`render` 不写（`_current` 非空时 `_pool` 不被调用），`snapshot()` 填 5 个；结果确定、幂等、纯内存 | 无害缓存写 → **未修**，但补严上一轮回归（见下） |
| `evidence_seq` 饱和语义 | deque(maxlen=16)，25 条事件后恒为 16，名字像全局序号其实是窗口内条数 | 兼容字段 → **未修**，文档澄清 |

**上一轮回归不够严的自我修正**：`test_liveness_is_still_pure_read`
检查了 `seq/current/evidence` 三个字段，却**漏了 `_pools`**，
于是「完全纯读」的说法其实不准确。本轮新增
`test_snapshot_populates_pools_deterministically` 把这个事实锁成
可执行断言（5 个池、两次 snapshot 结果相同、`_pool()` 命中一致），
而不是继续含糊地宣称纯读。这不是修 bug，是补上一轮欠的口径。

### 一条既有断言同步到新契约，不是放宽

`test_reload_success_is_atomic_and_clears_stale_verb` 原断言
`snapshot()["current"] == ""`；修复后配置切换会绑定新文案，
改为同时要求 `current == "新词条"`、池大小 1、
`evidence[-1].kind == "reload"`、`verb == "新词条"`、
`seq` 相等、`render(True).text == "新词条"` —— **断言更强**。
上轮独立脚本 `verify_deep.py::t_reload` 的同一条断言同步到同一
新契约。其余既有断言一条未动、一条未放宽。

### 验证

```
tests/test_runtime_slogans.py + test_slogan_mapping.py   404 passed
   （200 runtime_slogans + 204 slogan_mapping）
tests/verify_slogan_mapping.py                           126 项纯 stdlib 全绿
verify_deep.py / verify_deep2.py                         22 / 20 项全绿
```

新增回归里 `test_anchor_is_aligned_after_reload` 把 D 的
`(seq, verb)` 不变量变成可执行证据；四个「不该修」候选各有
独立回归锁住当前行为。独立验证脚本新增 9 项引擎检查，
仍保持屏蔽 `pytest / rich / prompt_toolkit / wcwidth` 后可导入
（`tuan_cli.tui` 用 PEP 562 惰性导出）。

### 如实边界（续 §19）

70. 本轮**不改** 18 个事件、16 个上下文、1108 条词条、
    `fully_superior`、99 模块基线、任何对齐指标、CLI 子命令数；
    零新增文件、零删除。
71. **本轮唯一改动的运行时代码仍是
    `tuan_cli/tui/runtime_slogans.py`**；`mapping.py` / `_clean.py` /
    `tui.py` / `ui/slogans/__init__.py` / `test_slogan_mapping.py`
    逐字节未改，都不在推送清单。净化层连续两轮零改动。
72. **两处行为变更，都如实标注**：
    (a) 超过 200 条 `verbs` 从「静默生效前 200 条」变成
    **整段拒绝** `invalid:too-many-verbs`；依赖 201+ 条自定义词
    的部署需拆分或减少词条。
    (b) `reload()` 成功后 `current` 从 `""` 变成新词池首条且
    `seq` +1、多一条 `kind="reload"` 证据；失败 / unchanged /
    合法 `now` / 正常 spinner 事件路径零变化。
73. **A 只修 `config` 和 `rng` 两处 `or`**，没有顺手改 `lang` ——
    有实测依据的行为退化风险，不是遗漏。
74. **四个候选确认判定「不该修」**，其中 `phase_budgets_ms` 的
    `[:10]` 是**不可达代码**（合法键上限 5），不是「暂时没修」。
75. **本轮实测未发现需回修的自引入缺陷**（连续第三次），但
    `lang=""`、200/201 边界、5 个合法 budget 键、
    unchanged no-op、真实时钟 vs 注入时钟、全新引擎 reload、
    确定性首条七个边界都量过；不写成「零缺陷」。
76. 并发压测仍未复现 list 撕裂；不是真机长跑；TUI 仍未替换
    任何既有 i18n 文案；分叉改动仍未合并；第三方自适应红队
    仍未做；**不宣称性能提升**（入口多一次 `is None` 与长度
    检查，reload 多一次词池计算，未做基准对比）。
