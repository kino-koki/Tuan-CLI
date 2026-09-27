# 技能蒸馏闭环使用指南 (SkillDistiller Distill Loop)

> 适用版本: v0.2.017+
> 这是 qxt 技能系统的核心超越点: **一次成功的多步任务结束后, qxt 主动提议把它沉淀成可复用技能,
> 你确认一次, 下次遇到相似任务它会自动命中。**

Claude Code 只写 memory 笔记、Kimi Code 的 sub-skill.review/consolidate 是人工触发、
Codex 没有自动蒸馏 —— qxt 把这条链路做成了端到端可演示。

---

## 1. 它是怎么工作的

```
你完成一个多步任务 (≥3 个工具调用)
        │
        ▼
DistillLoop.maybe_propose()  ── 自动检测可复用模式
        │
        ▼
质量门控: 名称非空 / 描述≥10字 / 正文≥3步   ── 不通过就不打扰你
        │
        ▼
弹出提议: "检测到可复用工作流, 是否存为技能? [y/n/编辑]"
        │  y
        ▼
skill_save 写入 <home>/skills/<slug>.md  (source=auto-distill, 同名=refine)
        │
        ▼
下次相似任务: activate_for_task() 因标签匹配 + use_count 自动激活
```

实现位置: `qingxiaotuan/self_improve/distill_loop.py`。
它是纯逻辑模块 (不直接读 UI), 交互层把提议渲染给用户、把 `y/n` 回传。

---

## 2. 配置项

| 配置键 | 默认 | 说明 |
|---|---|---|
| `self_improve.auto_propose` | `true` | 任务结束后是否自动提议存为技能 |
| `self_improve.min_tool_calls` | `3` | 触发提议所需的最少成功工具调用数 |

关闭自动提议 (仍可手动 `/distill`):

```
qxt config set self_improve.auto_propose false
```

---

## 3. 日常使用

### 3.1 自动提议 (默认)

正常在 qxt 里干活。当你连续成功地调用了 ≥3 个工具完成一件事后,
qxt 会提示:

```
检测到可复用工作流, 建议存为技能:
  名称: 给 FastAPI 路由加鉴权并跑通测试
  描述: 完成「...」时沉淀的可复用工作流, 涉及 3 个工具的协作顺序
  标签: code-editing, testing, ...
  来源工具: read_file, edit_file, run_tests
  步骤数: 3
是否存为技能? [y/n/编辑]
```

- `y` → 写入技能库, 下次自动命中。
- `n` → 丢弃, 不再就同一模式打扰你。
- `编辑` → 先改名/改描述再保存。

### 3.2 手动触发 `/distill`

任何时候想对"刚做完的这一轮"做蒸馏分析, 在 REPL 里输入:

```
/distill
```

它会复用内核的 `self_improve` 服务跑一轮蒸馏, 报告新蒸馏出的技能名。

---

## 4. 演示脚本 (90 秒 demo)

把下面的流程跑一遍, 就能录出"蒸馏提议 → 确认 → 下次自动命中"的主线 demo:

```text
# 第 1 步: 完成一次多步任务 (qxt 会在结束时提议)
你: 读 main.py, 给 /login 路由加上 token 校验, 然后跑 pytest 确认通过

# 第 2 步: 看到提议后按 y
#    → 终端提示已写入技能 fastapi-auth-test

# 第 3 步: 开新会话, 给一个相似但措辞不同的任务
你: 帮我保护一下 /admin 接口, 改完跑测试看看
#    → qxt 在系统提示里自动激活 fastapi-auth-test 技能 (标签 code-editing/testing 命中)
```

验证"下次自动命中"也可以直接用 Python:

```python
from qingxiaotuan.skills.manager import SkillManager
mgr = SkillManager(home)           # 与确认时同一个 home
hits = mgr.activate_for_task("保护 /admin 接口并跑测试")
assert hits and hits[0].source == "auto-distill"
```

---

## 5. 质量门控

不是每个多步任务都值得变成技能。提议必须同时满足:

1. **名称非空**
2. **描述 ≥ 10 字** (太短无法被语义检索命中)
3. **正文 ≥ 3 个有序步骤** (`1. ... 2. ... 3. ...`)

任一不满足, `maybe_propose()` 直接返回 `None`, 不弹提示。
门控函数: `distill_loop.quality_gate(proposal)`。

---

## 6. 与现有 AutoDistiller 的关系

- `self_improve/auto_distiller.py`: 从**长期事件流**里反复出现的高频成功模式蒸馏
  (跨会话、按统计频率, 落盘到 `<home>/skills/distilled/`)。
- `self_improve/distill_loop.py` (本指南): 针对**刚结束的单次多步任务**做即时提议,
  经用户确认后直接进 `<home>/skills/` 主技能库。

两者互补: 长期统计靠 AutoDistiller, 单次"这件事做得顺、存下来"靠 DistillLoop。

---

## 7. 相关命令速查

| 命令 | 作用 |
|---|---|
| `/distill` | 手动对当前会话触发蒸馏分析 |
| `/skills` | 列出全部技能 (标注 project/user/builtin) |
| `/skills audit` | 审计: 僵尸/元数据不全/frontmatter 合法性 |
| `/skills consolidate` | 检测相似技能 (dry-run, 不改盘) |
| `qxt skills list` | CLI 列出全部技能及来源 |
| `qxt skills import <path>` | 从 Claude Code/Codex 技能目录导入 |
| `qxt skills audit` | CLI 审计报告 |
| `qxt skills consolidate [--apply]` | CLI 合并 (默认 dry-run) |
| `qxt skills lint <name>` | 检查单个技能 |
