# Good First Issues（好入门议题）

> 目标：让外部贡献者**第一次提交就能成功**。每个议题都给出文件范围、验收标准和提交约定。
> 认领方式：在 GitHub issue 下留言即可；被认领的议题会标注「in progress」。
> 提交约定（摘要，完整见 [TUAN.md](../TUAN.md)）：conventional commits、改动必须带测试、
> 发版前跑 `python -m pytest tests/ -q` 与 `python -m mypy tuan_cli`、**未经明确要求不 push**。

## 入门级（无领域知识要求，1–2 小时）

### 1. Provider 目录结构契约测试
- **范围**：`tuan_cli/models/provider_catalog.py`、`tuan_cli/models/model_lists.py`
- **做什么**：为 59 个 ProviderPreset 写结构校验测试——字段完整（provider/model/api_key_env/category）、
  无重复 id、命名规范（snake_case）、`category="本地部署"` 的 preset 不要求 key。
- **为什么有价值**：目录漂移是模型无关工具的头号维护问题；这组测试是契约的「第一道闸门」。
- **验收**：`tests/test_provider_catalog_contract.py` 通过；故意破坏一个字段能测出失败。

### 2. README 多语言漂移核查
- **范围**：`README_zh-CN.md`（master）+ 其余 9 份翻译
- **做什么**：对比各翻译与 master 的章节结构/关键数字（版本号、命令名、bench 数字），
  列出漂移清单并修正；修复须保持「本地化而非机翻」的既有风格。
- **为什么有价值**：10 语言是项目门面；漂移直接伤害海外开发者信任。
- **验收**：提交一份「漂移清单」diff 或直接修正的翻译更新。

### 3. TUI 窄终端场景测试扩展
- **范围**：`tuan_cli/tui/`、`tests/test_tui_*.py`
- **做什么**：补充窄终端（<80 列）下的溢出/换行/裁剪用例：命令面板、状态栏、欢迎盒、错误态。
- **为什么有价值**：TUI 是主要交互面，窄终端是真实用户环境。
- **验收**：新增用例覆盖至少 3 个未覆盖的窄终端场景，全绿。

### 4. i18n 键完整性测试扩展
- **范围**：`tuan_cli/i18n/locales/*.py`、既有键完整性测试
- **做什么**：把「10 语言键完整」的既有检查扩展为**键值质量检查**（占位符匹配、无遗留英文占位）。
- **为什么有价值**：本地化质量是 10 语言承诺的兑现方式。
- **验收**：新断言能抓到至少一个真实的键值缺陷（或证明当前全部合格并写明）。

## 中级（需对项目结构有基本了解，半天–1 天）

### 5. `examples/` 示例集（3 例）
- **范围**：新建 `examples/`，引用现有能力
- **做什么**：三个可跑通的场景脚本 + 说明：
  1. 安全拦截演示（触发硬红线 → 展示拦截/审计落盘）；
  2. 生态互操作（`tuan ecosystem scan` + import 一次技能）；
  3. 离线模型（`tuan models local` + Ollama 对话）。
- **为什么有价值**：新手的「第一次成功体验」90% 来自示例。
- **验收**：三个脚本在干净环境按 README 步骤可复现。

### 6. 安全基准 CI 友好导出
- **范围**：`bench/`、`.github/workflows/security-ci.yml`
- **做什么**：`tuan safe bench` 结果增加 `--json` 输出；CI 把每次结果追加到可读的
  `bench/results/` 时间序列，替代「只看 pass/fail」。
- **为什么有价值**：安全数字的**趋势**比单点快照更能建立信任。
- **验收**：`--json` 输出字段与 README 表格 1:1 对应，CI 能生成趋势片段。

### 7. `tuan doctor` 兼容性体检
- **范围**：`tuan_cli/cli/cmd_doctor.py`、`config.schema.json`
- **做什么**：在 `tuan doctor` 中新增「配置/插件兼容性体检」：加载用户 `~/.tuan/config.yaml`
  与 schema 对比，报告未知键、类型不匹配、已废弃键（对应阶段二路线图）。
- **为什么有价值**：为 1.0 的 API 冻结铺路的迁移工具。
- **验收**：构造坏配置能给出可操作的修复建议，而非报错。

### 8. wheel 干净环境冒烟
- **范围**：`.github/workflows/`（新增 job）
- **做什么**：CI 中用干净 venv `pip install tuan-cli`（从 wheel）→ `tuan --print run "Hi"` 冒烟 →
  确认 `resources/**` 被打包、内置技能可发现。
- **为什么有价值**：`pip install` 后「装完即用」是 README 承诺，需要自动化背书。
- **验收**：job 绿；故意从 package-data 移除一个资源能被测出。

## 提交约定速查

```bash
python -m pytest tests/ -q          # 全量测试（默认跳过 slow）
python -m pytest -m slow            # 隔离验证测试
python -m mypy tuan_cli             # 类型门禁
tuan safe bench --quick             # 安全基准快速自检（改动安全引擎时必跑）
```

- 提交信息：`feat(scope): 中文描述` / `fix(scope): ...` / `test(scope): ...` / `docs: ...`
- 改动范围：只动议题点名的文件；不顺手重构。
- 完成标准：测试通过 + 行为验证后，在 issue 贴出测试输出。
