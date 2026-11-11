"""hook 出站/入站文本的**单一净化真值源**（B3 续轮 XV）。

B3 XIV 在 ``hooks/lifecycle.py`` 里建了 ``_clean_str``，用于 lifecycle
payload 与 hook reason。XV 真跑复现（N3/N3b）：``manager`` 的三类非进程
hook（url / prompt / subagent）走的是**另一条链路**，失败 detail 与
hook stdout 的 reason 完全没过净化 ——

    kind=error detail=Prompt hook 模型调用失败: api_key=ghp_... \\x1b]8;;
    https://evil.example\\x07\\u202eboom

这段文本原样进 ``HookDecision.reason``，再经 ``ToolResult.content``
回显到用户终端。前十几轮给日志 / 执行层错误 / 标语层 / lifecycle
建过的脱敏契约，在这条链路一条都没接。

本模块把 XIV 的实现抽成**共享函数对象**，``lifecycle._clean_str`` 与
``manager._parse_decision`` / ``nonprocess.execute`` 全部调它，
不产生第三套净化真值。刻意**不改** ``security_utils.redact_sensitive``
全局语义：那会误伤文档里的 ``ghp_...`` 占位串与既有审计口径。

复用两份既有真值，顺序「先清控制字符，再脱敏」：

- ``ui.slogans._clean.sanitize_log_field`` —— OSC/CSI/bidi/Cf/Cc 清理
- ``core.security_utils.redact_sensitive`` —— ENV 行 / key=value /
  Bearer / sk- / JWT

本地补一条裸 GitHub PAT 规则（XIV A′ 的四次修正全部保留在此）。

XV 把 XIV 的 ``lifecycle._clean_str`` 与 ``manager._parse_decision``
统一收到这里：三处调用的是**同一个函数对象**，``lifecycle._clean_str``
保留名字只为兼容 XIV 既有回归与 validate 自检。

许可：纯 Python 独立实现，零源码复制。
"""
from __future__ import annotations

import re
from typing import Any

from tuan_cli.core import security_utils as _SU
from tuan_cli.ui.slogans import _clean as _CL

# A′（XIV 四次自查，全部保留）：
# 1) ``\b`` 前边界让 ``xghp_<36 chars>``（token 与文本粘连）匹配不到；
# 2) 字符类不含下划线，带下划线的 token 形态仍漏；
# 3) 无上限 ``{20,}`` 把 token 后面紧邻的普通文本一并吃掉
#    （``BLOCKED<token>END -> BLOCKED[REDACTED]``）；
# 4) 因此 classic PAT 精确 36 位字母数字分支优先，宽松分支设 80 上界。
# 仍要求 20+ 字符，文档占位 ``ghp_...`` / ``ghp_REAL_SECRET_VALUE``
# 不会被误伤。
SECRET_TOKEN_RE = re.compile(
    r"(?:ghp_[A-Za-z0-9]{36}"
    r"|github_pat_[A-Za-z0-9_]{20,80}"
    r"|ghp_[A-Za-z0-9_]{20,80})")

MAX_HOOK_TEXT = 4096


def safe_hook_text(raw: Any, limit: int = 400) -> str:
    """把任意（可能外部可控的）hook 文本净化成可回显 / 可审计的字符串。

    - 非 ``str`` 一律返回空串（**绝不 ``str()`` 未知对象**，避免 repr
      泄露或 ``__str__`` 抛异常把错误路径掀翻）。
    - 剥控制字符序列 → 脱敏凭据 → 限长；净化自身绝不抛异常。
    - ``limit`` 脏值回落默认 400，不抛异常（与 XIV ``_clean_str`` 同口径）。
    """
    if not isinstance(raw, str) or not raw:
        return ""
    try:
        out = _CL.sanitize_log_field(raw, MAX_HOOK_TEXT)
        out = _SU.redact_sensitive(out)
        out = SECRET_TOKEN_RE.sub("[REDACTED]", out)
        cap = (limit if isinstance(limit, int) and not isinstance(limit, bool)
               and 0 < limit <= MAX_HOOK_TEXT else 400)
        if len(out) > cap:
            # A′（XV）：XIV 的 ``out[:cap].rstrip() + "…"`` 实际长度是
            # cap+1，违反「有界」承诺（N6 实测 4097 > 4096）。改为
            # cap-1 + 省略号，严格 <= cap；rstrip 只会更短。
            out = out[:max(0, cap - 1)].rstrip() + "…"
        return out
    except Exception:  # noqa: BLE001 - 净化自身绝不让 hook 通道再抛
        return ""


# 已知边界（XIV 文档已登记，XV 保留、不粉饰）：宽松 token 分支
# ``[A-Za-z0-9_]{20,80}`` 没有右边界，token **紧邻**普通文本时
# （``ghp_<36>END``）会把 ``END`` 一并遮蔽。精确 36 位 classic PAT
# 分支优先，因此真实 classic token 单独出现不受影响；取舍是
# 「宁可多抹，不漏一个」。``validate()`` 的 probe 刻意用**空格分隔**
# 验证保真，不把这条已知边界包装成通过。
def validate() -> list:
    """真跑自检（不只检查函数存在）。"""
    problems: list = []
    probe = ("START\x1b]8;;https://evil.example\x07\u202e"
             "ghp_" + "A" * 36 + " GITHUB_TOKEN=ghp_" + "B" * 36)
    cleaned = safe_hook_text(probe)
    if "ghp_" in cleaned or "\x1b" in cleaned or "\u202e" in cleaned:
        problems.append("safe_hook_text 未清除凭据/控制字符")
    if not cleaned.startswith("START"):
        problems.append("safe_hook_text 把前部普通文本吞掉")
    if not safe_hook_text("ghp_" + "A" * 36 + " TAIL").endswith("TAIL"):
        problems.append("safe_hook_text 把有分隔符的尾部文本吞掉")
    if safe_hook_text(cleaned) != cleaned:
        problems.append("safe_hook_text 不幂等")
    if safe_hook_text(object()) != "" or safe_hook_text(None) != "":
        problems.append("safe_hook_text 非字符串输入未 fail-closed")
    if safe_hook_text("x" * 100, limit=float("nan")) == "":
        problems.append("safe_hook_text 脏 limit 处理异常")
    return problems
