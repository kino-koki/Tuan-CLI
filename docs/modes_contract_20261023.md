# 五模式开发 · 共享接口契约（feat/modes-20261023）

> 本文件是 9 个并行 subagent 的**唯一接口契约**。所有实现必须严格遵循此处的签名与文件名。
> 每个 subagent **只允许写自己拥有的文件**（见 §9 归属表），其余一律只读。
> 环境：`F:\Tuan-CLI`，解释器 `.venv\Scripts\python`。
> **git 未安装**：不得执行任何 git 命令，不要尝试提交。

---

## 1. 四条红线（不可违背）

1. 全量失败数不得超过 3，且只能是这 3 个历史遗留：
   `test_cli_safe_bench_report.py::test_cmd_bench_quick_with_fake_runners`、
   `test_rewind.py::test_list_and_restore_previous`、
   `test_tui_fixes.py::TestTuiBridge::test_attach_ui_replaces_singleton`。
2. **不得修改** `ext/safety_redline.py`、`ext/safety_score.py`、`ext/security_gate.py` 的**判定逻辑本体**；
   `security_gate.py` 只允许**新增 `mode` 入参做附加过滤**（追加式，不改既有分支结论）。
3. 所有能力开关必须在**配置层/代码层真实生效**，不得只靠提示词。
4. 模式名只能用 `感通 / 灵码 / 闲聊 / 无界 / 协同`，ID 只能用
   `gantong / lingma / chat / boundless / collaboration`。

## 2. 命名红线

- `tuan_cli/resources/modes/**` 下**严禁出现**字符串 `灵感`、`无限`、`工作模式`。
- `standard` / `yolo` / `plan` 作为**英文旧别名保留**（这是 §2.1 的明确要求），但只作别名，不作为新模式名。
- 中文展示名固定：`感通`、`灵码`、`闲聊`、`无界`、`协同`。

## 3. 目录骨架

```
tuan_cli/modes/
  __init__.py        # 导出 ModeRegistry / switch_mode / mode_policy / build_mode_prompts
  registry.py
  switcher.py
  policy.py
  prompts.py
tuan_cli/resources/modes/
  gantong/{mode.yaml, prompts/system.md, prompts/memory.md, prompts/guard.md}
  lingma/...
  chat/...
  boundless/...
  collaboration/...
tuan_cli/cli/
  cmd_mode.py                 # tuan mode list/show/switch/current
  cmd_slash_tier.py           # slash_command_tier + tier 表
tests/
  test_modes_registry.py
  test_modes_switch.py
  test_modes_policy.py
  test_modes_prompts.py
  test_modes_security.py
  test_slash_tier.py
```

## 4. registry.py（Owner: S1）

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class ModeSpec:
    id: str                 # "gantong" | "lingma" | "chat" | "boundless" | "collaboration"
    name: str               # "感通" | "灵码" | "闲聊" | "无界" | "协同"
    level: int              # 0..4  (L0 闲聊 / L2 协同 / L3 感通,灵码 / L4 无界)
    risk: str               # "低" | "中" | "高" | "极高"
    desc: str               # 一句话定位
    loop: str               # "reactive" | "plan_execute" | "devloop" | "react" | "auto"
    platform: str           # 平台策略一句话
    tags: tuple = ()        # 关键能力标签

class ModeRegistry:
    ALL_IDS: tuple = ("gantong", "lingma", "chat", "boundless", "collaboration")
    #: 英文旧三档别名（§2.1 强制保留）。禁止加入任何中文旧名。
    LEGACY_ALIASES: dict = {"standard": "collaboration", "yolo": "boundless", "plan": "chat"}

    def __init__(self, extra: Optional[Iterable[ModeSpec]] = None) -> None: ...
    def list(self) -> list:                  # 5 条, 按 ALL_IDS 顺序
    def get(self, mode_id: str) -> "ModeSpec":   # 未知 ID 抛 ValueError
    def is_valid(self, mode_id) -> bool
    def ids(self) -> tuple
    def resolve(self, name_or_id: str) -> str
        # 规范 ID / 中文名 / 英文旧别名 -> 规范 ID；不可解析抛 ValueError
        # 接受大小写不敏感
```

**固定数据**（各 subagent 必须一致）：

| id | name | level | risk | loop |
|---|---|---|---|---|
| gantong | 感通 | 3 | 高 | react |
| lingma | 灵码 | 3 | 高 | devloop |
| chat | 闲聊 | 0 | 低 | reactive |
| boundless | 无界 | 4 | 极高 | auto |
| collaboration | 协同 | 2 | 中 | plan_execute |

**配置层**（S1 拥有）：
- `config/defaults.py` 的 `"mode"` 段改为：
  ```python
  "mode": {
      "current": "chat",
      "default": "chat",          # 向后兼容旧键（旧值 standard/yolo/plan 需被 resolve 归一）
      "locked": False,
      "allow_switch": [],
      "yolo_require_confirm": [], # 保留！loader.py:577 仍在读
  }
  ```
- `config.schema.json` 的 `"mode"` 段：新增 `current`（enum 五 ID，default `"chat"`）、`locked`、`allow_switch`；
  `default` 的 enum 扩为 8 个值（五新 ID + standard/yolo/plan）；保留 `yolo_require_confirm`。
- `config/validate.py`：非法模式 ID **明确报错**，不静默回落。

## 5. switcher.py（Owner: S2）

```python
@dataclass(frozen=True)
class ModeSwitchResult:
    ok: bool
    from_id: str
    to_id: str
    reason: str
    disclosure: str = ""        # 风险披露文本（空=无需披露）
    needs_confirm: bool = False # 需要二次确认

def check_transition(src: str, dst: str, *, platform: str = "desktop",
                     locked: bool = False, force: bool = False) -> tuple:
    """纯函数，返回 (allowed: bool, reason: str)。必须单独可测，不触配置/事件。"""

def switch_mode(target, *, current=None, platform="desktop", force=False,
                config=None, emit=True) -> ModeSwitchResult
    """状态机：resolve → check_transition → 持久化 → 发事件 → 落审计。
    config=None 时用加载器默认；config 需有 .get(path)/.set_user(path,value)。"""

def get_current_mode(config=None) -> str      # 返回规范 ID，历史值经 resolve 归一
def set_current_mode(mode_id: str, config=None) -> None
```

**切换规则（必须逐条实现）**：

| 规则 | 判定 |
|---|---|
| R1 | `chat` → 任意：需显式切换，**禁止自动升级权限**（自动调用路径下拒绝） |
| R2 | `collaboration` → `lingma`/`gantong`：只提示不自动切 |
| R3 | `gantong`/`lingma` → `boundless`：需风险披露 + 二次确认，`force=False` 时拒绝 |
| R4 | `boundless` → 任意：随时降级，立即收紧 |
| R5 | 任意 → `chat`：允许，立即收回除「对话 + 记忆沙箱 + TTS」外的一切能力 |
| R6 | `boundless` 在 `android`（或非桌面白名单平台）：**直接拒绝，不给确认机会** |
| R7 | `mode.locked=True`：除 `boundless` 降级外一律拒绝 |

**持久化**：`config.set_user("mode.current", <规范ID>)`。
**事件**：`core.events` 发 `mode.changed`，字段 `from` / `to` / `reason` / `ts`。
**审计**：`audit.store` 追加 `mode_switch` 条目。
事件与审计**必须容错**（`emit=False` 或 import 失败时静默降级，不得抛错）。

## 6. policy.py（Owner: S3）

```python
@dataclass(frozen=True)
class ModePolicy:
    mode_id: str
    level: int
    allowed_tools: tuple = ()     # 空 = 不限（由其他层决定）
    denied_tools: tuple = ()
    shell_enabled: bool = False
    mcp_enabled: bool = False
    network_enabled: bool = False
    file_read: bool = False
    file_write: bool = False
    memory_write: bool = False
    tts_enabled: bool = False
    external_send_draft_only: bool = False
    desktop_only: bool = False
    platform_block: tuple = ()    # e.g. ("android",)
    confirm_required: tuple = ()  # 需确认的操作类别

def mode_policy(mode_id: str, platform: str = "desktop") -> ModePolicy
def list_capability_matrix(mode_id: str) -> list          # [(能力, 状态), ...] 供 `tuan mode show`
```

**能力矩阵（§5.3–§5.7 逐条落死）**：

| 项 | chat | collaboration | gantong | lingma | boundless |
|---|---|---|---|---|---|
| file_read | ❌ 物理禁用 | ✅ | ✅ | ✅ | ✅(桌面)/❌(android) |
| file_write | ❌ 物理禁用 | ✅ 审计 | ✅ 审计 | ✅ 审计 | 同左 |
| shell | ❌ 物理禁用 | ❌ | 受限白名单 | ✅ 审计+确认 | 桌面✅/移动❌ |
| mcp | ❌ 物理禁用 | 仅办公类 | 仅认证类 | 仅代码类 | 桌面白名单/移动❌ |
| network | ❌ 物理禁用 | 受限需确认 | 受限官方后端 | 受限需确认 | 桌面✅/移动❌ |
| memory_write | 仅沙箱 | 沙箱 | 沙箱可回滚 | 沙箱 | 审计 |
| tts_enabled | ✅ | ❌ | ❌ | ❌ | ❌ |
| external_send_draft_only | — | ✅ | — | — | — |
| platform_block | () | () | () | () | ("android",) |

> **chat 模式的物理禁用是红线验收项**：必须由 `denied_tools` / `shell_enabled=False` 等字段表达，
> 且在 S9 的 `core/allowed_tools.py` 接线后**真实拦截**。

## 7. prompts.py + 资源文件（Owner: S4 / S5 / S6）

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ModePrompts:
    mode_id: str
    system: str
    memory: str
    guard: str

def build_mode_prompts(mode_id: str) -> ModePrompts   # 三件套任一为空 -> raise ValueError
def load_mode_resource(mode_id: str, rel: str) -> str
```

- 资源路径：`tuan_cli/resources/modes/<id>/prompts/{system,memory,guard}.md`
- 内容**逐字照抄** `26.10.23全天代办.md` §4.1–§4.5 的三件套（含 markdown 代码块内的正文，去掉外层 ```markdown 围栏）。
- 每个模式另需 `mode.yaml`（§3 表数据 + `desc`）。
- 锚点校验：感通含 `72 份` 与 `companies`；灵码含 `不承诺`；闲聊含 `物理禁用`；无界含 `硬红线`；协同含 `草稿`。

## 8. CLI / slash 五通路（Owner: S7）

- `tuan_cli/cli/cmd_mode.py`：`def cmd_mode(args) -> int`，子命令 `list` / `show` / `switch` / `current`。
  `switch` 支持 `--force`、`--platform`、`--allow`（无二次确认交互时打印披露文本）。
  `show` 必须打印**能力矩阵**（调 `list_capability_matrix`）。
- `cli/parser_commands.py`：新增 `mode` 顶级子命令（照 `model` 的写法）。
- `cli/commands.py`：注册 `cmd_mode`。
- `cli/cmd_slash.py`：`/mode` 改为五档 + `/mode list` + `/mode <id>`；`_CMD_META["/mode"]` 改为
  `"切换运行模式 (感通/灵码/闲聊/无界/协同, 旧 standard/yolo/plan 仍可用)"`；
  `/help` 按 `slash_command_tier` 分组、核心层置顶。
- `cli/cmd_chat.py`：`tuan chat --mode <id>`（会话级；`--save` 持久化）。
- **`SLASH_COMMAND_NAMES` 全集必须严格保持 55 个，一个不多一个不少。**
- **`/plan` 保留原行为**（`agent.plan_mode` 切换），同时 `/plan` 与 `chat` 模式互为别名不冲突。

## 9. 文件归属表（严格）

| ID | 拥有文件 |
|---|---|
| S1 | `tuan_cli/modes/__init__.py`、`registry.py`、`config/defaults.py`、`config.schema.json`、`config/validate.py`、`tests/test_modes_registry.py` |
| S2 | `tuan_cli/modes/switcher.py`、`tests/test_modes_switch.py` |
| S3 | `tuan_cli/modes/policy.py`、`tests/test_modes_policy.py` |
| S4 | `tuan_cli/modes/prompts.py`、`tests/test_modes_prompts.py` |
| S5 | `tuan_cli/resources/modes/{gantong,lingma,boundless}/**` |
| S6 | `tuan_cli/resources/modes/{chat,collaboration}/**`、全部 5 个 `mode.yaml`、`MANIFEST.in` |
| S7 | `cli/cmd_mode.py`、`cli/parser_commands.py`、`cli/commands.py`、`cli/cmd_slash.py`、`cli/cmd_chat.py` |
| S8 | `cli/cmd_slash_tier.py`、`tui/tui.py`（仅 `_SlashCompleter`）、`cli/cmd_onboarding.py`、`cli/cmd_tutorial.py`、`tests/test_slash_tier.py` |
| S9 | `ext/security_gate.py`（仅加 `mode` 入参）、`core/allowed_tools.py`、`core/command_guard.py`、`core/auto_mode.py`、`core/loop_registry.py`、`memory/auto_extractor.py`、`tests/test_modes_security.py` |

**S8 与 S7 的接缝**：`cmd_slash_tier.py` 暴露
```python
CORE_SLASH: tuple
EXPERT_SLASH: tuple
HIDDEN_SLASH: tuple
def slash_command_tier(name: str) -> str      # "core" | "expert" | "hidden"
def tiered_slash_groups() -> dict             # {"核心": [...], "专家": [...]}
```
S7 从 `tuan_cli.cli.cmd_slash_tier` import 使用；S8 不碰 `cmd_slash.py`。

## 10. 每个 subagent 的通用约束

- **先读后写**：改任何既有文件前先 `read`。
- **注释用中文**（与仓库风格一致）。
- **不要运行全量 pytest**（很慢且互相干扰）。只跑自己的测试文件：
  `.venv\Scripts\python -m pytest tests\<你的文件> -q --no-header -p no:cacheprovider`
  临时目录用 `--basetemp=.scratch/<你的ID>` 避免与其他 subagent 抢占。
- **不要创建或删除 git 目录**，不要 `rm` 仓库文件。
- 新增测试用 `tmp_path` / `monkeypatch` 隔离，不写真实用户配置。
- 完成后报告：改了哪些文件、新增测试数、测试输出、遗留问题。
