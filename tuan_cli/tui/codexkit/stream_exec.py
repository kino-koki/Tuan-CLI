"""A 线三个 pending：``streaming`` / ``async_question_reply`` /
``exec_command``。

按公开语义契约独立实现，零 Rust 源码复制。三条真实缺陷先复现再修：

1. **流式结束仍接受分片 / 渲染循环偷偷记活性**：延续
   ``runtime_slogans`` D4 契约 —— ``render()`` 必须纯读；本模块
   ``peek()`` 显式不写任何状态，并进探针断言。分片乱序/重复/done
   后写入都结构化拒绝，绝不静默拼接出错误输出。
2. **异步回复张冠李戴 / 模型自问自答**：延续 B3 的 Elicitation
   语义 —— 只接受**用户**对已登记问题的回复，过期/取消/重复
   /未登记 id 一律拒绝，**绝不代答、绝不覆盖已有答案**。
3. **命令用 `shell=True` 拼接**：外部输入含 ``;`` / ``$(...)`` 时
   变成第二条命令。本实现强制 ``argv`` 序列、拒绝 shell 元字符
   字符串、输出有上限、超时有上限。
"""
from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ============================================================ streaming
@dataclass(frozen=True)
class Chunk:
    seq: int
    text: str


class StreamAssembler:
    """流式分片状态机。

    - ``seq`` 严格递增；重复 seq 幂等丢弃，乱序（回退）显式拒绝；
    - ``finish()`` 后再 ``push()`` 一律拒绝；
    - ``peek()`` / ``render()`` **纯读**，不调用任何记账方法；
    - 分片文本净化控制字符与 bidi（与净化层同一口径的最小子集）；
    - 线程安全：``RLock`` 包住复合读写。
    """

    def __init__(self, max_chars: int = 1_000_000) -> None:
        self._lock = threading.RLock()
        self._parts: List[str] = []
        self._last_seq = -1
        self._done = False
        self._rejected: List[str] = []
        self._max_chars = max_chars

    # A′ 实测修正：只删 ESC 字节会留下 ``[31m`` 这类 CSI 参数文本，
    # 用户看到的是「净化过」的字符串里混着终端指令残片。先整段剥
    # ESC 序列（CSI / OSC / 两字符 ESC），再逐字符删控制/bidi。
    _ESC_SEQ_RE = re.compile(
        r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)"
        r"|\[[0-?]*[ -/]*[@-~]|[@-_P^_])")

    @classmethod
    def _clean(cls, text: str) -> str:
        stripped = cls._ESC_SEQ_RE.sub("", text)
        return "".join(
            ch for ch in stripped
            if not (ord(ch) < 32 or 0x7F <= ord(ch) < 0xA0
                    or 0x202A <= ord(ch) <= 0x202E
                    or 0x2066 <= ord(ch) <= 0x2069
                    or ord(ch) == 0x200B))

    def push(self, chunk: Chunk) -> bool:
        with self._lock:
            if self._done:
                self._rejected.append("after_finish")
                return False
            if not isinstance(chunk, Chunk) or not isinstance(chunk.seq, int) \
                    or isinstance(chunk.seq, bool) or chunk.seq < 0 \
                    or not isinstance(chunk.text, str):
                self._rejected.append("invalid_chunk")
                return False
            if chunk.seq == self._last_seq:
                return False                        # 幂等重传
            if chunk.seq < self._last_seq:
                self._rejected.append("out_of_order")
                return False
            clean = self._clean(chunk.text)
            if sum(len(x) for x in self._parts) + len(clean) > self._max_chars:
                self._rejected.append("overflow")
                return False
            self._parts.append(clean)
            self._last_seq = chunk.seq
            return True

    def finish(self) -> None:
        with self._lock:
            self._done = True

    # ---- 纯读：任何渲染入口都只准调这两个
    def peek(self) -> str:
        with self._lock:
            return "".join(self._parts)

    def render(self) -> str:
        return self.peek()

    @property
    def is_done(self) -> bool:
        with self._lock:
            return self._done

    def rejected(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(self._rejected)


def probe_streaming() -> dict:
    p: List[str] = []
    n = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            p.append(label)

    s = StreamAssembler()
    chk(s.push(Chunk(0, "你")), "首片失败")
    chk(s.push(Chunk(1, "好")), "第二片失败")
    chk(not s.push(Chunk(1, "好")), "重复 seq 未幂等")
    chk(s.peek() == "你好", "拼接结果不对")
    chk(not s.push(Chunk(0, "回退")), "乱序未拒绝")
    before = s.peek()
    for _ in range(5):
        s.render()
    chk(s.peek() == before, "render 不是纯读")
    chk(s.push(Chunk(2, "\x1b[31mRLO\u202e")), "净化分片写入失败")
    chk("RLO" in s.peek() and "\u202e" not in s.peek()
        and "[31m" not in s.peek(), "ESC 序列残片仍在输出里")
    s.finish()
    chk(not s.push(Chunk(3, "late")), "finish 后仍接受分片")
    chk("after_finish" in s.rejected(), "结束后拒绝未留痕")
    chk(s.peek() == before + "RLO", "finish 后输出被改")
    chk(not s.push(Chunk(True, "x")), "bool seq 未拒绝")
    s2 = StreamAssembler(max_chars=3)
    chk(s2.push(Chunk(0, "ab")) and not s2.push(Chunk(1, "cd")),
        "输出上限失效")
    return {"ok": not p, "checks": n, "evidence":
            "StreamAssembler: seq 单调/幂等/乱序拒绝/done 拒绝/净化/render 纯读/上限",
            "problems": p}


# ============================================================ async_question_reply
@dataclass(frozen=True)
class Question:
    qid: str
    text: str
    created_at: float

    @property
    def expired(self) -> bool:
        return False


class AsyncQuestionReply:
    """问题 -> 回复配对。

    - 只有 ``register()`` 登记过的问题才能收回复；
    - ``expire()`` / ``cancel()`` 后回复一律拒绝；
    - 重复回复拒绝且**不覆盖**已有答案；
    - ``answer_as_agent()`` 明确抛错 —— 模型不能自问自答
      （B3 Elicitation 契约）；
    - 注入时钟，脏值回落，超时按单调时长判定。
    """

    def __init__(self, ttl_secs: float = 30.0) -> None:
        self._lock = threading.RLock()
        self._ttl = ttl_secs if (isinstance(ttl_secs, (int, float))
                                 and not isinstance(ttl_secs, bool)
                                 and math.isfinite(ttl_secs)
                                 and ttl_secs > 0) else 30.0
        self._q: Dict[str, Question] = {}
        self._answers: Dict[str, str] = {}
        self._closed: set = set()
        self._rejections: List[str] = []

    def register(self, qid: str, text: str, created_at: float = 0.0) -> bool:
        with self._lock:
            if not isinstance(qid, str) or not qid or qid in self._q:
                return False
            t = created_at if (isinstance(created_at, (int, float))
                               and not isinstance(created_at, bool)
                               and math.isfinite(created_at)) else 0.0
            self._q[qid] = Question(qid, str(text), t)
            return True

    def reply(self, qid: str, answer: str, *, now: float = 0.0,
              from_user: bool = True) -> bool:
        with self._lock:
            if not from_user:
                self._rejections.append("agent_self_answer")
                return False
            q = self._q.get(qid)
            if q is None:
                self._rejections.append("unknown_qid")
                return False
            if qid in self._closed:
                self._rejections.append("closed")
                return False
            if qid in self._answers:
                self._rejections.append("duplicate")
                return False
            t = now if (isinstance(now, (int, float))
                        and not isinstance(now, bool)
                        and math.isfinite(now)) else q.created_at
            if t - q.created_at > self._ttl:
                self._rejections.append("expired")
                self._closed.add(qid)
                return False
            if not isinstance(answer, str):
                self._rejections.append("answer_type")
                return False
            self._answers[qid] = answer
            return True

    def cancel(self, qid: str) -> bool:
        with self._lock:
            if qid not in self._q:
                return False
            self._closed.add(qid)
            return True

    def answer_for(self, qid: str) -> Optional[str]:
        with self._lock:
            return self._answers.get(qid)

    def answer_as_agent(self, qid: str, answer: str) -> bool:
        """显式拒绝程序化代答（不是返回 False 就完事，留痕可查）。"""
        return self.reply(qid, answer, from_user=False)

    def rejections(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(self._rejections)


def probe_async_question_reply() -> dict:
    p: List[str] = []
    n = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            p.append(label)

    a = AsyncQuestionReply(ttl_secs=10.0)
    chk(a.register("q1", "确认写入?"), "登记失败")
    chk(not a.register("q1", "dup"), "重复 qid 未拒绝")
    chk(a.reply("q1", "yes", now=1.0), "用户回复被拒")
    chk(a.answer_for("q1") == "yes", "答案读取不对")
    chk(not a.reply("q1", "no", now=2.0), "重复回复未拒绝")
    chk(a.answer_for("q1") == "yes", "已有答案被覆盖")
    chk(not a.reply("unknown", "x"), "未登记 qid 未拒绝")
    chk(not a.answer_as_agent("q1", "self"), "模型代答被放行")
    chk("agent_self_answer" in a.rejections(), "代答未留痕")
    chk(a.register("q2", "超时?", created_at=0.0), "q2 登记失败")
    chk(not a.reply("q2", "late", now=11.0), "过期回复被放行")
    chk(a.answer_for("q2") is None, "过期回复写入了答案")
    chk(a.register("q3", "取消?", created_at=0.0), "q3 登记失败")
    chk(a.cancel("q3"), "取消失败")
    chk(not a.reply("q3", "x", now=1.0), "取消后回复被放行")
    chk(not a.reply("q1", 123), "非字符串答案未拒绝")
    chk(AsyncQuestionReply(ttl_secs="10")._ttl == 30.0, "脏 ttl 未回落")
    return {"ok": not p, "checks": n, "evidence":
            "AsyncQuestionReply: 登记/超时/取消/重复/不覆盖/绝不代答/脏时钟",
            "problems": p}


# ============================================================ exec_command
_SHELL_META = frozenset(";|&$`<>()\n\r\\\"'")
# A′ 实测修正：``sh -c x`` / ``python -c x`` 不含任何 shell 元字符，
# 但等于间接启用命令解释器。显式拒绝这类「间接执行器」。
_INDIRECT_SHELLS = frozenset({
    "sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh",
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh",
})
_INDIRECT_FLAGS = frozenset({"-c", "/c", "-Command", "-command"})


@dataclass(frozen=True)
class ExecCommand:
    """类型化命令：只接受 argv 序列，**永不** ``shell=True``。"""
    argv: Tuple[str, ...]

    @staticmethod
    def build(raw: Any) -> "ExecCommand":
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ValueError("argv 必须是非空序列")
        argv = tuple(str(x) for x in raw)
        if not argv[0] or any(not isinstance(x, str) or "\x00" in x for x in argv):
            raise ValueError("argv 含空值 / NUL")
        if any(c in _SHELL_META for a in argv for c in a):
            raise ValueError("argv 含 shell 元字符（拒绝拼接）")
        head = argv[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        if head in _INDIRECT_SHELLS or (
                len(argv) > 1 and argv[1] in _INDIRECT_FLAGS
                and head in {"python", "python3", "node", "perl", "ruby"}):
            raise ValueError("间接命令解释器被拒绝")
        return ExecCommand(argv)

    def uses_shell(self) -> bool:
        return False

    def display(self) -> str:
        return " ".join("[%s]" % a for a in self.argv)


def run_bounded(cmd: ExecCommand, runner: Any,
                *, timeout_secs: float = 5.0,
                max_output: int = 4096) -> dict:
    """执行边界：超时上限 + 输出上限 + 异常结构化，绝不裸抛。"""
    if not isinstance(cmd, ExecCommand):
        return {"ok": False, "reason": "not_typed"}
    if not (isinstance(timeout_secs, (int, float))
            and not isinstance(timeout_secs, bool)
            and math.isfinite(timeout_secs) and 0 < timeout_secs <= 120):
        return {"ok": False, "reason": "bad_timeout"}
    try:
        raw = runner(cmd.argv, timeout_secs)
    except TimeoutError:
        return {"ok": False, "reason": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": "runner:%s" % type(exc).__name__}
    text = raw if isinstance(raw, str) else str(raw)
    truncated = len(text) > max_output
    return {"ok": True, "output": text[:max_output],
            "truncated": truncated, "exit_code": 0}


def probe_exec_command() -> dict:
    p: List[str] = []
    n = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            p.append(label)

    cmd = ExecCommand.build(["git", "status", "--short"])
    chk(cmd.argv == ("git", "status", "--short"), "argv 不对")
    chk(cmd.uses_shell() is False, "uses_shell 说了谎")
    for bad in (["echo", "a;rm -rf /"], ["echo", "$(whoami)"],
                ["sh", "-c", "x"], ["echo", "a\nb"], "git status",
                [], ["echo\x00x"]):
        try:
            ExecCommand.build(bad)
            p.append("危险命令未被拒绝: %r" % (bad,))
        except ValueError:
            pass
        n += 1
    r = run_bounded(cmd, lambda argv, t: "ok")
    chk(r["ok"] and r["output"] == "ok", "正常执行失败")
    r2 = run_bounded(cmd, lambda argv, t: "x" * 9000)
    chk(r2["truncated"] and len(r2["output"]) == 4096, "输出上限失效")

    def slow(argv, t):
        raise TimeoutError()
    chk(run_bounded(cmd, slow)["reason"] == "timeout", "超时未结构化")

    def boom(argv, t):
        raise RuntimeError("x")
    chk(run_bounded(cmd, boom)["reason"].startswith("runner:"), "异常未结构化")
    chk(run_bounded(cmd, lambda a, t: "x", timeout_secs=float("inf"))["ok"] is False,
        "脏超时未拒绝")
    chk(run_bounded("not-typed", lambda a, t: "")["ok"] is False,
        "非类型化命令未拒绝")
    return {"ok": not p, "checks": n, "evidence":
            "ExecCommand: argv 强制/元字符拒绝/无 shell/输出与超时上限/异常结构化",
            "problems": p}
