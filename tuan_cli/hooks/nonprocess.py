"""B3 续轮 XV｜url / prompt / subagent 三类 **非进程 hook 的等价故障闭合表**。

## 为什么需要它（先实测复现，不是读代码猜）

XII 给 command hook 建了 ``exit_semantics.classify()`` 逐事件真值表，
XIII 接了 13 个生产触发点，XIV 修了 lifecycle 出站通道的失败闭合与
脱敏。但 ``manager._exit_gate`` 只读 ``self._tls.last_exit`` ——
**三类非进程 hook 从来不写它**（没有进程 rc），于是：

- **N1**：HTTP 200 空 body / 非 JSON body → ``block=False``、
  ``failures()=[]``、**审计 0 条**。装了拦截器、服务器正常响应，
  运维却完全看不到它跑过。对照 command hook 空 stdout 至少有一条
  ``exit_code_semantics`` 审计。「成功但无裁决」在三类 hook 上是
  **零留痕的静默**。
- **N2**：配置 ``timeout=0.5s``，慢速 drip server 每 0.3s 发 1 字节，
  实测 ``_exec_http`` 耗时 **2.71s**（5.4 倍）且 ``block=False``、
  ``failures()=[]``。``urlopen(timeout=)`` 是 **socket 级**超时，不是
  整体墙钟；command hook 有看门狗强杀整棵进程树，三类 hook 什么都没有。
- **N3**：模型异常消息 ``api_key=ghp_... \\x1b]8;;...\\x07\\u202e``
  原样进 ``HookDecision.reason``（再经 ``ToolResult.content`` 回显）；
  HTTP 成功返回 reason 里的 token / RLO 同样原样采纳。XIV 净化只覆盖
  lifecycle 链路。
- **N4**：``urlopen`` 默认跟随 302，实测 hook 配置的 URL 会静默把 POST
  改 GET 发到**另一个主机**（第二 server 收到 501）。这是 URL 白名单
  与 SSRF 边界缺口。
- **N6**：prompt hook 返回 500000 字符，``reason`` 原样 500000 字符进
  决策对象；三类 hook 的 stdout 无界。

## 本模块做什么

1. ``execute()`` 是三类 hook 的**唯一权威执行入口**：真墙钟有界、
   拒绝重定向、stdout 限长、失败 detail 与 reason 统一过
   ``core.safe_text.safe_hook_text``（与 XIV lifecycle 共用同一函数对象）。
2. ``ChannelOutcome`` 把三类 hook 的事实结构化（status / kind /
   equivalent_rc / elapsed / bounded / detached / audit_events），
   写进 ``manager._tls.last_channel``。
3. ``classify_channel()`` 把通道故障映射为**等价 rc**，然后**复用**
   ``exit_semantics.classify()`` 这一份既有真值表 —— 不新建第二套逐事件
   策略。于是 33 个官方事件在 command 与三类 hook 上得到同一裁决，
   ``on_failure=block/ask/allow`` 的既有语义逐值不变。

## 刻意不做的事

- **不擅自放宽或收紧安全**：等价 rc 是 1（非 2 的非零），逐事件裁决
  完全交给既有 ``classify()``。command rc=1 与 url HTTP 500 同结果，
  有真跑对照回归。
- **不假装能强杀线程**：prompt / subagent 的模型调用 / Agent 运行无法
  中断，超时后主线程立即返回失败裁决，**后台 daemon 线程仍在跑但结果
  被丢弃**，``detached=True`` 如实登记。HTTP 走 ``read1`` + deadline +
  ``resp.close()``，是真停。
- **不改既有 command hook 路径**：``_exec_command`` / ``_exit_gate`` 的
  command 分支逐字节零改动。

许可：纯 Python 独立实现，零源码复制。
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

from tuan_cli.core.safe_text import MAX_HOOK_TEXT, safe_hook_text

from . import exit_semantics as XS

HOOK_TYPES = ("url", "prompt", "subagent")
MAX_STDOUT = MAX_HOOK_TEXT          # 4096 码点，与净化真值同一上界
FAILURE_KINDS = (
    "timeout", "http_error", "redirect_blocked", "invalid_spec",
    "no_kernel", "no_model", "error",
)


@dataclass(frozen=True)
class ChannelOutcome:
    """一次非进程 hook 执行的结构化事实（``_exit_gate`` 据此裁决）。"""

    event: str
    hook_type: str
    status: str                 # ok / ok_no_decision / failure
    stdout: Optional[str]       # 已净化 + 限长；失败时 None
    failure_kind: str = ""
    failure_detail: str = ""    # 已净化
    stderr: str = ""            # 已净化，供 XS.classify 当 stderr
    equivalent_rc: int = 0
    elapsed_ms: int = 0
    bounded: bool = True        # 调用方是否真被墙钟有界
    detached: bool = False      # 超时后后台线程仍在跑（结果丢弃）
    truncated: bool = False
    redirect_followed: bool = False
    audit_events: List[Tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "event": self.event, "hook_type": self.hook_type,
            "status": self.status, "failure_kind": self.failure_kind,
            "equivalent_rc": self.equivalent_rc,
            "elapsed_ms": self.elapsed_ms, "bounded": self.bounded,
            "detached": self.detached, "truncated": self.truncated,
            "redirect_followed": self.redirect_followed,
            "stdout_len": len(self.stdout or ""),
        }


def _ok(event: str, hook_type: str, stdout: str, elapsed: float,
        audits: List[Tuple[str, str]], *, truncated: bool = False) -> ChannelOutcome:
    """成功路径：区分「有裁决输出」与「成功但无裁决」（N1 的核心）。"""
    no_decision = not stdout.strip()
    if not no_decision:
        try:
            data = json.loads(stdout)
            if not isinstance(data, dict):
                no_decision = True
                audits.append(("channel_non_json_stdout",
                               "stdout 不是 JSON 对象，按无裁决留痕"))
        except (ValueError, TypeError):
            no_decision = True
            audits.append(("channel_non_json_stdout",
                           "stdout 不是可解析 JSON，按无裁决留痕"))
    if truncated:
        audits.append(("channel_stdout_truncated",
                       "stdout 超过 %d 码点上限，已截断" % MAX_STDOUT))
    if no_decision:
        audits.append(("channel_no_decision",
                       "%s hook 正常响应但无有效裁决（结构化留痕，不静默）"
                       % hook_type))
    return ChannelOutcome(
        event=event, hook_type=hook_type,
        status="ok_no_decision" if no_decision else "ok",
        stdout=stdout, equivalent_rc=0,
        elapsed_ms=int(elapsed * 1000), truncated=truncated,
        audit_events=list(audits))


def _fail(event: str, hook_type: str, kind: str, detail: str,
          elapsed: float, audits: List[Tuple[str, str]], *,
          detached: bool = False, bounded: bool = True) -> ChannelOutcome:
    assert kind in FAILURE_KINDS, kind
    clean = safe_hook_text(detail, 400)
    audits.append(("channel_failed", "%s: %s" % (kind, clean)))
    return ChannelOutcome(
        event=event, hook_type=hook_type, status="failure",
        stdout=None, failure_kind=kind, failure_detail=clean,
        stderr=clean, equivalent_rc=1,
        elapsed_ms=int(elapsed * 1000),
        bounded=bounded, detached=detached,
        audit_events=list(audits))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """N4：禁止 urlopen 默认跟随 3xx。

    返回 ``None`` 让 ``HTTPErrorProcessor`` 抛 ``HTTPError(code)``，
    由 ``execute()`` 归到 ``redirect_blocked``。实测旧版 302 会把 POST
    改 GET 发到另一个主机，URL 白名单形同虚设。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _read_bounded(resp: Any, deadline: float) -> Tuple[bytes, bool, bool]:
    """真墙钟有界读取。

    优先 ``read1``（单次底层 recv，不等读满）—— 慢速 drip 每发一字节就
    返回一次，主线程随即检查 deadline。没有 ``read1`` 时退化 ``read``
    并靠 socket timeout 兜，如实返回 ``soft=True``。
    """
    buf = bytearray()
    read1 = getattr(resp, "read1", None)
    truncated = False
    soft = read1 is None
    reader = read1 if read1 is not None else resp.read
    try:
        while len(buf) <= MAX_STDOUT:
            chunk = reader(4096)
            if not chunk:
                break
            buf.extend(chunk)
            if time.monotonic() > deadline:
                raise TimeoutError("整体墙钟超时（非进程 hook）")
            if len(buf) > MAX_STDOUT:
                truncated = True
                break
    except (socket.timeout, TimeoutError):
        raise
    except OSError as exc:
        raise TimeoutError("读取中断: %s" % type(exc).__name__) from None
    return bytes(buf[:MAX_STDOUT]), truncated, soft


def _run_http(spec: Any, payload: Dict[str, Any], timeout: float,
              t0: float, deadline: float,
              audits: List[Tuple[str, str]]) -> ChannelOutcome:
    url = str(getattr(spec, "url", "") or "")
    if not url.lower().startswith(("http://", "https://")):
        return _fail(spec.event, "url", "invalid_spec",
                     "HTTP hook URL scheme 只允许 http/https", time.monotonic() - t0,
                     audits)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json",
                 "User-Agent": "tuan_cli-hook"},
        method="POST")
    opener = urllib.request.build_opener(_NoRedirect)
    sock_timeout = max(0.05, min(timeout, 1.0))
    try:
        with opener.open(req, timeout=sock_timeout) as resp:
            status = getattr(resp, "status", getattr(resp, "code", 200))
            if not (200 <= int(status) < 300):
                return _fail(spec.event, "url", "http_error",
                             "HTTP %s" % status, time.monotonic() - t0, audits)
            raw, truncated, soft = _read_bounded(resp, deadline)
            if soft:
                audits.append(("channel_soft_timeout",
                               "响应对象无 read1，墙钟靠 socket timeout 兜"))
            text = safe_hook_text(raw.decode("utf-8", errors="replace"),
                                  MAX_STDOUT)
    except urllib.error.HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if 300 <= code < 400:
            audits.append(("channel_redirect_blocked",
                           "拒绝跟随 %d 重定向（URL 白名单/SSRF 边界）" % code))
            return _fail(spec.event, "url", "redirect_blocked",
                         "HTTP %d 重定向被拒绝" % code,
                         time.monotonic() - t0, audits)
        return _fail(spec.event, "url", "http_error",
                     "HTTP %d %s" % (code, exc.reason),
                     time.monotonic() - t0, audits)
    except (TimeoutError, socket.timeout):
        return _fail(spec.event, "url", "timeout",
                     "HTTP hook 超过 %.2fs 墙钟被中断" % timeout,
                     time.monotonic() - t0, audits)
    except Exception as exc:  # noqa: BLE001
        return _fail(spec.event, "url", "error",
                     "%s: %s" % (type(exc).__name__, exc),
                     time.monotonic() - t0, audits)
    return _ok(spec.event, "url", text, time.monotonic() - t0, audits,
               truncated=truncated)


def _bounded_call(fn, timeout: float, t0: float, audits: List[Tuple[str, str]],
                  event: str, hook_type: str, label: str) -> ChannelOutcome:
    """prompt / subagent 的有界等待。

    **如实**：Python 无法强杀一个正在 ``model.chat`` / ``agent.run`` 的
    线程。超时后主线程立即返回失败裁决，后台 daemon 线程继续跑完但结果
    丢弃（``detached=True``）。这是「调用方不挂死」，**不是**强杀。
    """
    box: Dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["exc"] = exc

    th = threading.Thread(target=run, daemon=True,
                          name="tuan-hook-%s-%s" % (hook_type, event))
    th.start()
    th.join(max(0.05, timeout))
    if th.is_alive():
        audits.append(("channel_detached_timeout",
                       "%s 线程无法强杀；结果丢弃，后台继续跑完" % label))
        return _fail(event, hook_type, "timeout",
                     "%s 超过 %.2fs（调用方已返回，后台线程残留）"
                     % (label, timeout), time.monotonic() - t0, audits,
                     detached=True)
    if "exc" in box:
        exc = box["exc"]
        return _fail(event, hook_type, "error",
                     "%s: %s" % (type(exc).__name__, exc),
                     time.monotonic() - t0, audits)
    raw = box.get("result")
    if raw is None:
        return _fail(event, hook_type, "error", "%s 无返回" % label,
                     time.monotonic() - t0, audits)
    raw_text = raw if isinstance(raw, str) else str(type(raw))
    # A′（XV）：prompt / subagent 路径此前只截断、不设 truncated，
    # 运维看不到「输出被截过」。与 HTTP 路径同一标记。
    truncated = len(raw_text) > MAX_STDOUT
    text = safe_hook_text(raw_text, MAX_STDOUT)
    return _ok(event, hook_type, text, time.monotonic() - t0, audits,
               truncated=truncated)


def _run_prompt(spec: Any, payload: Dict[str, Any], kernel: Any,
                timeout: float, t0: float,
                audits: List[Tuple[str, str]]) -> ChannelOutcome:
    if kernel is None:
        return _fail(spec.event, "prompt", "no_kernel",
                     "Prompt hook: 无内核，模型不可用",
                     time.monotonic() - t0, audits)
    model = kernel.get("model_adapter")
    if model is None:
        return _fail(spec.event, "prompt", "no_model",
                     "Prompt hook: 无可用模型适配器",
                     time.monotonic() - t0, audits)
    prompt = str(getattr(spec, "prompt_text", "") or "")
    for key, val in payload.items():
        ph = "{" + key + "}"
        if ph in prompt:
            prompt = prompt.replace(
                ph, val if isinstance(val, str)
                else json.dumps(val, ensure_ascii=False))

    def call():
        result = model.chat([{"role": "user", "content": prompt}],
                            stream=False)
        if hasattr(result, "content"):
            return result.content or ""
        return str(result) if result else ""

    return _bounded_call(call, timeout, t0, audits, spec.event, "prompt",
                         "Prompt 模型调用")


def _run_subagent(spec: Any, payload: Dict[str, Any], kernel: Any,
                  workspace: str, timeout: float, t0: float,
                  audits: List[Tuple[str, str]]) -> ChannelOutcome:
    if kernel is None:
        return _fail(spec.event, "subagent", "no_kernel",
                     "Subagent hook: 无内核，无法创建隔离 Agent",
                     time.monotonic() - t0, audits)

    def call():
        from ..app import create_agent
        sub = None
        try:
            sub = create_agent(kernel, workspace or "")
            context = json.dumps(payload, ensure_ascii=False)[:3000]
            instr = str(getattr(spec, "prompt_text", "") or "")
            task = (instr + "\n\n上下文: " + context if instr
                    else "处理以下事件: " + context)
            result = sub.run(task, stream=False, max_iterations=5)
            return result[:3000] if result else ""
        finally:
            from .triggers import close_agent_session
            close_agent_session(sub)

    return _bounded_call(call, timeout, t0, audits, spec.event, "subagent",
                         "Subagent 运行")


def execute(spec: Any, payload: Dict[str, Any], kernel: Any,
            workspace: str, default_timeout: float = 30.0) -> ChannelOutcome:
    """三类非进程 hook 的唯一权威执行入口。绝不抛异常。"""
    event = str(getattr(spec, "event", "") or "")
    hook_type = str(getattr(spec, "hook_type", "") or "")
    t0 = time.monotonic()
    audits: List[Tuple[str, str]] = []
    if hook_type not in HOOK_TYPES:
        return _fail(event, hook_type or "unknown", "invalid_spec",
                     "未知非进程 hook 类型", time.monotonic() - t0, audits)
    try:
        timeout = float(getattr(spec, "timeout", default_timeout))
    except (TypeError, ValueError):
        timeout = default_timeout
    if not (timeout > 0) or timeout != timeout or timeout in (float("inf"),):
        timeout = default_timeout
    timeout = min(timeout, 300.0)
    deadline = t0 + timeout
    try:
        if hook_type == "url":
            return _run_http(spec, payload, timeout, t0, deadline, audits)
        if hook_type == "prompt":
            return _run_prompt(spec, payload, kernel, timeout, t0, audits)
        return _run_subagent(spec, payload, kernel, workspace, timeout, t0,
                             audits)
    except Exception as exc:  # noqa: BLE001 - 执行器绝不掀翻 hook 流水线
        return _fail(event, hook_type, "error",
                     "execute 兜底: %s" % type(exc).__name__,
                     time.monotonic() - t0, audits)


def classify_channel(event: str, outcome: ChannelOutcome, *,
                     tuan_policy: str = "block"):
    """把通道故障映射成**等价 rc**，复用 ``exit_semantics.classify()``。

    这是「等价故障闭合表」的全部：不新建第二套逐事件策略，33 个官方
    事件在 command 与三类 hook 上得到同一裁决。``on_failure`` 的
    block/ask/allow 语义逐值不变。

    唯一附加规则：``ok_no_decision``（N1）把 ``json_ignored`` 置 True，
    让 ``run_event`` / ``run_decision`` / ``run_pre`` 既有的
    ``exit_json_ignored`` 分支写一条结构化留痕 —— 不再零审计静默。
    """
    v = XS.classify(event, outcome.equivalent_rc, outcome.stderr,
                    tuan_policy=tuan_policy)
    if outcome.status == "ok_no_decision" and not v.block:
        return replace(v, json_ignored=True, reason="")
    return v


def validate() -> list:
    """真跑自检：等价表与既有真值表逐事件一致、净化出口有效。"""
    problems: list = []
    from tuan_cli.core import safe_text as ST
    problems.extend("safe_text: " + p for p in ST.validate())
    if len(HOOK_TYPES) != 3:
        problems.append("HOOK_TYPES 必须覆盖三类非进程 hook")

    def fake(status: str, rc: int, stderr: str = "") -> ChannelOutcome:
        return ChannelOutcome(event="PreToolUse", hook_type="url",
                              status=status, stdout=None,
                              equivalent_rc=rc, stderr=stderr)

    for event in sorted(XS.OFFICIAL_EVENTS)[:12]:
        base = XS.classify(event, 1, "boom", tuan_policy="block")
        ch = classify_channel(event, fake("failure", 1, "boom"),
                              tuan_policy="block")
        if (ch.block, ch.code_path, ch.json_may_override) != (
                base.block, base.code_path, base.json_may_override):
            problems.append("等价表与 XS.classify 不一致: %s" % event)
    nd = classify_channel("PreToolUse", fake("ok_no_decision", 0),
                          tuan_policy="block")
    if nd.block or not nd.json_ignored:
        problems.append("ok_no_decision 未产生结构化留痕")
    allow = classify_channel("PreToolUse", fake("failure", 1, "x"),
                             tuan_policy="allow")
    if allow.block:
        problems.append("on_failure=allow 被等价表错误闭合")
    if not safe_hook_text("ghp_" + "A" * 36):
        problems.append("safe_hook_text 对纯 token 返回异常")
    return problems
