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
