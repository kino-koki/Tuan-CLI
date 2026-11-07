"""与 Codex ``tui/src/cli.rs`` 对齐的 CLI 参数模型。

上游逐字段（clap ``Args``）：
  - ``prompt`` 可选初始提示；
  - ``strict_config`` 默认 false（config.toml 有未识别字段就报错）；
  - ``resume_picker / resume_last / resume_session_id / resume_show_all /
    resume_include_non_interactive`` 是内部 skip 参数（由顶层子命令设置，
    **不作为公开 flag**）；
  - ``fork_picker / fork_last / fork_session_id / fork_show_all`` 同理；
  - ``no_alt_screen`` 默认 false（inline 模式保留 scrollback）；
  - ``no_daemon``、``web_search`` 默认 false；
  - ``approval_policy`` 可选；``config_overrides`` 是 skip。

**本轮最值钱的安全契约**在文件末尾 ``mark_tui_args``：

    cmd.mut_arg("dangerously_bypass_approvals_and_sandbox", |arg| {
        arg.conflicts_with("approval_policy")
    })
    .mut_arg("auto_review", |arg| arg.conflicts_with("approval_policy"))

也就是「危险地绕过审批与沙箱」和「指定审批策略」**不能共存**，
``auto_review`` 与 ``approval_policy`` 也不能共存。若本地 CLI 解析时
让两者静默共存，就是一个配置侧门：用户以为设了审批策略，实际被
绕过开关吃掉。本模块把这两条做成 fail-closed 的显式拒绝。

本地化修改（如实列出）：
  - clap derive -> dataclass + ``parse_args()``；只保留本项目存在的
    flag，OpenAI 专属的 resume/fork/daemon 记为 ``NOT_APPLICABLE_FLAGS``；
  - **冲突检测返回结构化问题列表并拒绝启动**（本地化增强：上游靠
    clap 报错退出，这里同样拒绝，且把原因写清便于审计）；
  - ``dangerously_bypass_approvals_and_sandbox`` 在 Tuan 对应
    ``--yolo``（本地化命名），冲突语义不变；
  - 新增 ``to_public_flags()``：内部 skip 参数**绝不**出现在公开
    flag 列表里（对齐上游 ``#[clap(skip)]`` 的可测契约）；
  - 未知 flag 一律拒绝（动态语言没有 clap 的编译期保护）。

许可：Apache-2.0（NOTICE 第 12 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Tuple

# 逐值对齐上游公开 flag 名
PUBLIC_FLAGS: FrozenSet[str] = frozenset({
    "prompt", "strict-config", "ask-for-approval", "search",
    "no-alt-screen", "no-daemon",
})

# 上游 #[clap(skip)] 的内部参数（不作为公开 flag）
INTERNAL_SKIP_ARGS: FrozenSet[str] = frozenset({
    "daemon_cli_executable", "resume_picker", "resume_last",
    "resume_session_id", "resume_show_all",
    "resume_include_non_interactive", "agents_overview",
    "fork_picker", "fork_last", "fork_session_id", "fork_show_all",
    "config_overrides",
})

# OpenAI 专属、本地 CLI 不需要（如实标注，不假装实现）
NOT_APPLICABLE_FLAGS: FrozenSet[str] = frozenset({
    "daemon_cli_executable", "agents_overview", "no-daemon", "search",
    "resume_picker", "resume_last", "resume_session_id",
    "resume_show_all", "resume_include_non_interactive",
    "fork_picker", "fork_last", "fork_session_id", "fork_show_all",
})

# 本地化命名映射：上游名 -> Tuan 名
BYPASS_UPSTREAM = "dangerously_bypass_approvals_and_sandbox"
BYPASS_LOCAL = "yolo"

# 上游两条冲突（逐条对齐 mark_tui_args）
CONFLICT_RULES: Tuple[Tuple[str, str, str], ...] = (
    (BYPASS_UPSTREAM, "approval_policy",
     "危险绕过审批与沙箱 不能与 指定审批策略 共存"),
    ("auto_review", "approval_policy",
     "auto_review 不能与 指定审批策略 共存"),
)


@dataclass
class Cli:
    """对齐上游 ``Cli`` 字段；默认逐值一致。"""

    prompt: str | None = None
    strict_config: bool = False
    approval_policy: str | None = None
    web_search: bool = False
    no_alt_screen: bool = False
    no_daemon: bool = False
    # 内部/危险开关（不进公开 flag）
    dangerously_bypass_approvals_and_sandbox: bool = False
    auto_review: bool = False
    config_overrides: Dict[str, str] = field(default_factory=dict)

    def validate(self) -> List[str]:
        """fail-closed 冲突检测 + 内部参数不可见检查。"""
        problems: List[str] = []
        if self.dangerously_bypass_approvals_and_sandbox \
                and self.approval_policy is not None:
            problems.append(CONFLICT_RULES[0][2])
        if self.auto_review and self.approval_policy is not None:
            problems.append(CONFLICT_RULES[1][2])
        # 本地化增强：两者同时开也拒绝（上游各自与 approval_policy 冲突，
        # 但两个绕过开关叠加同样是危险组合）
        if self.dangerously_bypass_approvals_and_sandbox and self.auto_review:
            problems.append("两个审批绕过开关不能同时启用")
        return problems

    def is_safe_to_start(self) -> bool:
        return not self.validate()

    def to_public_flags(self) -> Dict[str, object]:
        """对齐 ``#[clap(skip)]``：内部参数绝不出现在公开 flag 里。"""
        out: Dict[str, object] = {
            "strict-config": self.strict_config,
            "search": self.web_search,
            "no-alt-screen": self.no_alt_screen,
            "no-daemon": self.no_daemon,
        }
        if self.prompt is not None:
            out["prompt"] = self.prompt
        if self.approval_policy is not None:
            out["ask-for-approval"] = self.approval_policy
        assert not (set(out) & INTERNAL_SKIP_ARGS), \
            "内部 skip 参数泄漏到公开 flag"
        return out


def parse_args(argv: List[str]) -> Tuple[Cli, List[str]]:
    """最小解析器；返回 (Cli, 问题列表)。

    刻意不自动「修复」冲突：调用方看到问题列表就必须拒绝启动。
    """
    cli = Cli()
    problems: List[str] = []
    i = 0
    positional: List[str] = []
    while i < len(argv):
        a = argv[i]
        if a == "--strict-config":
            cli.strict_config = True
        elif a == "--search":
            cli.web_search = True
        elif a == "--no-alt-screen":
            cli.no_alt_screen = True
        elif a == "--no-daemon":
            cli.no_daemon = True
        elif a in ("--ask-for-approval", "-a"):
            if i + 1 >= len(argv):
                problems.append("--ask-for-approval 缺少取值")
            else:
                i += 1
                cli.approval_policy = argv[i]
        elif a == "--yolo" or a == f"--{BYPASS_UPSTREAM}":
            cli.dangerously_bypass_approvals_and_sandbox = True
        elif a == "--auto-review":
            cli.auto_review = True
        elif a.startswith("-"):
            problems.append(f"未识别的 flag {a!r}（拒绝静默忽略）")
        else:
            positional.append(a)
        i += 1
    if positional:
        cli.prompt = " ".join(positional)
    problems.extend(cli.validate())
    return cli, problems


def conflict_rules() -> List[Tuple[str, str, str]]:
    """可观测：供 parity 自检核销两条上游冲突规则。"""
    return list(CONFLICT_RULES)
