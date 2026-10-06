# 子项目 B（诚信/营销修复 + 全量质量修复）实现计划

> **For agentic workers:** 按任务逐条执行。本计划由 writing-plans 生成。
> 设计依据：`docs/superpowers/specs/2026-10-06-honesty-and-quality-remediation-design.md`

**Goal:** 把对外宣称与仓库内可核实事实对齐，并在行为不变前提下降低结构性风险。

**Architecture:** B1 只改文档与新增核对脚本；B2 为纯重构，以现有测试为契约。

**Tech Stack:** Python 3.10+，pytest 9，mypy；文档为 Markdown。

**约束：** 行为不变；全量测试保持全绿；mypy 保持 0 错误；**每次 git 提交前需用户确认**。

---

## 已核实的关键事实（2026-10-06）

- `ALL_PROVIDERS` = **51**，与 README "51 家供应商" **一致**（无需改数字）。
- `MODEL_LISTS` 合计 **1165** 条模型条目，与 "1100+ 内置模型" 一致。
- `README.md:232` 已含"诚信契约"（Claude 列探针失败即标 N/A），**保留**。
- 夸大集中：`docs/gap_analysis_20260927.md`（"第一且唯一" ×2）、`gap_analysis_20260926.md`、`competitive_analysis_20260927.md`、`compact_survival_guide.md`、`QXT.md`。

---

## Task 1：数字核对脚本（可复现证据）

**Files:**
- Create: `scripts/verify_doc_numbers.py`
- Test: `tests/test_verify_doc_numbers.py`

- [ ] **Step 1: 写失败测试**

```python
from scripts.verify_doc_numbers import collect_numbers, check_consistency

def test_collect_numbers_reads_catalog():
    nums = collect_numbers()
    assert nums["providers"] == 51
    assert nums["models"] >= 1100

def test_check_consistency_passes_on_repo():
    assert check_consistency() == []
```

- [ ] **Step 2: 运行确认失败**
  `pytest tests/test_verify_doc_numbers.py -v` → FAIL（模块不存在）

- [ ] **Step 3: 实现脚本**（从 `qingxiaotuan.models.provider_catalog` 读取真值，扫描 README 断言，返回不一致列表）

- [ ] **Step 4: 运行确认通过**
  `pytest tests/test_verify_doc_numbers.py -v` → PASS

- [ ] **Step 5: 提交**（待用户确认）

---

## Task 2：`docs/gap_analysis_20260927.md` 去夸大

**Files:** Modify `docs/gap_analysis_20260927.md:3-9`、`:32`、`:47`

- [ ] **Step 1:** 头部声明改为显式自评口径：新增"本报告为**项目自评**，非第三方评测；评分基于公开信息与作者判断，**可能高估本项目**；信源见 `competitive_analysis_20260927.md`。"
- [ ] **Step 2:** 将 `🏆 **第一且唯一**` 改为限定表述：`🏆 本次对比集合内唯一`（限定在 Claude Code / Kimi Code / Codex CLI 三家内，可核实）。
- [ ] **Step 3:** 将正文 `:47` 的"第一且唯一"同步改为限定表述。
- [ ] **Step 4:** 复核图例中"领先"定义已限定为"竞品未做或做得更弱"（保留）。
- [ ] **Step 5:** 提交（待用户确认）

---

## Task 3：`docs/gap_analysis_20260926.md` 同步

- [ ] **Step 1:** 同 Task 2 的头部自评声明。
- [ ] **Step 2:** 检索并收敛绝对化表述。
- [ ] **Step 3:** 提交（待用户确认）

---

## Task 4：`docs/competitive_analysis_20260927.md` 信源与口径

- [ ] **Step 1:** 确认每条竞品信息带信源标签（官方/第三方/推测）。
- [ ] **Step 2:** 结论区加"自评、非第三方"限定。
- [ ] **Step 3:** 提交（待用户确认）

---

## Task 5：`QXT.md` 与自评 HTML

- [ ] **Step 1:** `QXT.md` 检索并收敛绝对化表述（不改规则本身）。
- [ ] **Step 2:** `qxt-全面测评-20260927.html` 顶部加"自评"横幅声明。
- [ ] **Step 3:** 提交（待用户确认）

---

## Task 6：B1 收尾验证

- [ ] **Step 1:** 运行 `python scripts/verify_doc_numbers.py` → 无不一致。
- [ ] **Step 2:** 运行全量 `pytest` → 全绿（B1 不应影响测试）。
- [ ] **Step 3:** 提交（待用户确认）

---

## Task 7（B2a）：`ext/safety_engine.py` 按职责拆文件

- [ ] **Step 1:** 记录现有 `__all__` 与公开符号。
- [ ] **Step 2:** 拆为 `safety_normalize.py` / `safety_redline.py` / `safety_score.py`，原文件保留转发导出。
- [ ] **Step 3:** 运行安全相关测试 → 全绿。
- [ ] **Step 4:** 提交（待用户确认）

## Task 8（B2a）：`arch/` 层定位澄清 + `sandbox` 文档 + `shell.py` 旁路核查

- [ ] **Step 1:** `ARCHITECTURE.md` 标注 `arch/` 为兼容/测试层。
- [ ] **Step 2:** `sandbox` 默认策略与降级行为写入文档 + 日志。
- [ ] **Step 3:** 核查 `tools/shell.py` 所有执行路径均过 `_pre_exec_guard`，补回归测试。
- [ ] **Step 4:** 提交（待用户确认）

## Task 9（B2b）：`core/agent.py` 拆分

- [ ] **Step 1:** 拆出 Goal / Vision / 记忆 子模块，主类保留编排。
- [ ] **Step 2:** 全量测试 → 全绿。
- [ ] **Step 3:** 提交（待用户确认）

## Task 10（B2b）：`cli/cmd_slash.py` / `cli/parser.py` 拆分

- [ ] **Step 1:** 按命令域拆模块，parser 保持入口兼容。
- [ ] **Step 2:** 全量测试 → 全绿。
- [ ] **Step 3:** 提交（待用户确认）

---

## Self-Review

- **Spec coverage:** B1 全部改动清单 → Task 1-6；B2a → Task 7-8；B2b → Task 9-10。无遗漏。
- **Placeholder scan:** 无 TBD；Step 3 的脚本实现以要点描述，实现时给出完整代码。
- **Type consistency:** `collect_numbers()` / `check_consistency()` 在测试与实现中命名一致。
