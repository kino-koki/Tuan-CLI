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
