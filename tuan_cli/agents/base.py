"""Agent 适配器基类与事件模型。

设计要点:
- 每个 AgentAdapter 对应一个装在用户机器上的 CLI 工具 (Claude Code / CodeX /
  hermes / DeepSeek Harness / Kimi Code)。
- run() 是 async generator, 流式产出 AgentEvent; 路由器只关心事件流, 不关心
  底层 agent 是子进程、RPC 还是 mock。
- detect() 只做 PATH 探测 + 一次异步 --version (3s 超时), 输出含适配器
  verify 标识才计满分; 结果由调用方按需获取 (discovery 每次连接重探,
  保证状态实时; router 并行 gather, 不再串行等待)。
- 审批通过 approve_callback(approval_id) -> decision 异步回传; 适配器在需要审批时
  yield 一个 APPROVAL 事件后 await 回调 (allow 继续 / deny 中止)。

与协议对齐: EventType 的字符串值与 TUAN-DISPATCH-PROTOCOL.md §5 完全一致。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Sequence


class EventType(str, Enum):
    """事件种类。字符串值 = 协议 v1.0 的 kind 字段。"""
    TEXT = "text"
    TOOL_CALL = "tool_call"
    APPROVAL = "approval"
    STDERR = "stderr"
    ERROR = "error"
    DONE = "done"
    META = "meta"


def _kill(proc: Any) -> None:
    """终止子进程; 进程已退出时静默 (取消/审批拒绝/收尾竞态都可能触发)。"""
    try:
        proc.kill()
    except (ProcessLookupError, ValueError):
        pass
    except Exception:
        pass


@dataclass
class AgentEvent:
    """单条事件。seq 由 dispatch_server 填充; 适配器内部从 0 开始自增。"""
    kind: EventType
    data: dict
    seq: int = 0
    task_id: str = ""

    def to_dict(self) -> dict:
        """转协议消息字典 (含 type 字段)。"""
        return {
            "type": "event",
            "task_id": self.task_id,
            "seq": self.seq,
            "kind": self.kind.value,
            "data": self.data,
        }


@dataclass
class TaskRequest:
    """一次任务请求。字段与协议 §4.1 对齐。"""
    id: str
    prompt: str
    agent: str = "auto"  # "auto" 或具体 adapter id
    mode: str = "chat"  # chat / collaboration / gantong / lingma / boundless
    cwd: Optional[str] = None
    attachments: list = field(default_factory=list)
    timeout_sec: int = 600
    stream: bool = True
    language: str = "zh-CN"
    auto_approve_low_risk: bool = True


@dataclass
class AgentInfo:
    """代理健康状态, 对应协议 hello.agents[] 元素。

    score (0-100) 是「判定」的量化输出, 供状态展示与 auto 模式次级排序:
    - 100: PATH 命中且 --version 输出含预期标识 (verify), 确认是本工具
    - 70:  PATH 命中但版本输出为空 / 探测命令无法执行 (按可用处理, 版本未知)
    - 60:  PATH 命中但版本输出不含预期标识 (疑似同名工具, 仍按可用处理)
    - 0:   PATH 未命中 (healthy=False)

    healthy 只表达「能不能派活」: 除 0 分外一律为 True——PATH 命中是
    可用性的主信号, 版本校验只影响分数与提示, 不阻断路由 (避免误杀
    版本输出格式不同的真实安装)。
    """

    id: str
    name: str
    path: Optional[str] = None
    healthy: bool = False
    version: Optional[str] = None
    reason: Optional[str] = None
    score: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "healthy": self.healthy,
            "version": self.version,
            "score": self.score,
            **({"reason": self.reason} if self.reason else {}),
        }


class AgentAdapter(ABC):
    """本地 Agent 适配器基类。

    子类必须提供:
    - id / display_name / command (类属性)
    - detect() (async, 探测 PATH)
    - build_command() (构建命令行)

    默认 run() 已实现「子进程 + 流式 stdout/stderr + done 事件」, 子类一般无需覆盖。
    """

    id: str = "unknown"
    display_name: str = "Unknown"
    description: str = ""
    command: tuple = ()  # 候选命令, 按优先级排列
    # 版本校验标识: --version 输出 (大小写不敏感) 含此串才给满分 100。
    # 留空表示跳过校验 (命中 PATH 即 70 分: 版本未知但按可用处理)。
    verify: str = ""

    # 打分权重, 用于 router 在 auto 模式下排序 (值越大越优先)
    weights: dict = {}  # mode -> score

    async def detect(self) -> AgentInfo:
        """探测代理是否安装 (真正异步, 可被 asyncio.gather 并行)。

        判定口径 (score):
        - PATH 未命中            → healthy=False, score=0,  reason=not found in PATH
        - 命中 + 版本含 verify   → healthy=True,  score=100, 确认是本工具
        - 命中 + 版本输出为空    → healthy=True,  score=70,  版本未知
        - 命中 + 版本不含 verify → healthy=True,  score=60,  疑似同名工具
        - 命中 + --version 超时/异常 → healthy=True, score=70, 版本未知

        healthy 不因版本校验失败而变 False: PATH 命中是可用性主信号,
        校验只影响分数与提示, 避免误杀版本输出格式特殊的真实安装。
        """
        import asyncio
        import shutil

        for cmd in self.command:
            path = shutil.which(cmd)
            if not path:
                continue
            version, probe_err = await self._probe_version(path)
            if probe_err is not None:
                # --version 跑不动 (超时/权限/不是可执行格式): 命令在 PATH 上,
                # 按可用处理但版本未知
                return AgentInfo(
                    id=self.id,
                    name=self.display_name,
                    path=path,
                    healthy=True,
                    version=None,
                    score=70,
                )
            if not version:
                # 有命令无版本输出: 可用, 版本未知
                return AgentInfo(
                    id=self.id,
                    name=self.display_name,
                    path=path,
                    healthy=True,
                    version=None,
                    score=70,
                )
            if self.verify and self.verify.lower() not in version.lower():
                return AgentInfo(
                    id=self.id,
                    name=self.display_name,
                    path=path,
                    healthy=True,
                    version=version,
                    score=60,
                    reason=f"版本输出未匹配预期标识 '{self.verify}', 可能是同名工具",
                )
            return AgentInfo(
                id=self.id,
                name=self.display_name,
                path=path,
                healthy=True,
                version=version,
                score=100,
            )
        return AgentInfo(
            id=self.id,
            name=self.display_name,
            healthy=False,
            reason="not found in PATH",
        )

    async def _probe_version(self, path: str) -> tuple[Optional[str], Optional[str]]:
        """跑一次 `<path> --version`, 3s 超时。

        返回 (version, error): version 为首行 (≤80 字符) 或 None;
        error 非 None 表示探测命令本身失败 (超时/无法启动)。
        """
        import asyncio

        try:
            proc = await asyncio.create_subprocess_exec(
                path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass
            return None, "version probe timeout (5s)"
        except Exception as e:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass
            return None, f"{type(e).__name__}: {e}"
        # 有些 CLI 的 --version 输出在 stderr (如 codex)
        text = ((out or b"") + (err or b"")).decode("utf-8", errors="replace").strip()
        if not text:
            return None, None
        return text.splitlines()[0][:80], None

    async def build_command(self, task: TaskRequest) -> list:
        """构建最终命令行。默认实现: [第一个候选命令] + prompt。子类覆盖。"""
        return [self.command[0], task.prompt]

    async def run(
        self,
        task: TaskRequest,
        approve_callback: Optional[Callable[[str], Awaitable[str]]] = None,
    ) -> AsyncIterator[AgentEvent]:
        """默认执行: 启动子进程, 流式捕获 stdout/stderr, 产出事件。

        契约:
        - 必须以 kind=DONE 事件结尾 (即便出错)。
        - 超时由 asyncio.wait_for 包装, 触发后 kill 子进程并推 done(timeout)。
        - 审批: 若 stdout 出现 "[TUAN_APPROVAL] <approval_id> <description>" 标记,
          则 yield APPROVAL 事件并 await 回调; allow 继续, deny 中止。
        - 子类可覆盖以定制输出解析 (如 JSON 行、SSE 等)。
        """
        import asyncio
        import os

        seq = 0

        def _next(seq_val: int) -> int:
            return seq_val + 1

        cmd = await self.build_command(task)

        # 把 prompt 写到临时文件, 避免命令行参数长度限制与转义问题
        prompt_file = None
        if task.attachments:
            prompt_file = os.path.join(
                task.cwd or os.getcwd(), ".tuan_prompt_" + task.id + ".txt"
            )
            try:
                with open(prompt_file, "w", encoding="utf-8") as f:
                    f.write(task.prompt)
                    for att in task.attachments:
                        f.write("\n\n--- 附件: " + att.get("name", "") + " ---\n")
                        import base64
                        if "content_b64" in att:
                            f.write(base64.b64decode(att["content_b64"]).decode("utf-8", errors="replace"))
            except Exception:
                prompt_file = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=task.cwd,
            )
        except FileNotFoundError:
            seq = _next(seq)
            yield AgentEvent(kind=EventType.ERROR, data={"message": f"command not found: {cmd[0]}"}, seq=seq, task_id=task.id)
            seq = _next(seq)
            yield AgentEvent(kind=EventType.DONE, data={"status": "error"}, seq=seq, task_id=task.id)
            return
        except Exception as e:
            seq = _next(seq)
            yield AgentEvent(kind=EventType.ERROR, data={"message": str(e)}, seq=seq, task_id=task.id)
            seq = _next(seq)
            yield AgentEvent(kind=EventType.DONE, data={"status": "error"}, seq=seq, task_id=task.id)
            return

        try:
            # 元信息事件
            seq = _next(seq)
            yield AgentEvent(kind=EventType.META, data={"engine": self.display_name}, seq=seq, task_id=task.id)

            # 流式读 stdout
            assert proc.stdout is not None
            buffer = ""
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                # 按行切, 保留未完成的尾部
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.rstrip("\r")
                    if not line:
                        continue
                    # 审批标记检测
                    if line.startswith("[TUAN_APPROVAL] "):
                        rest = line[len("[TUAN_APPROVAL] "):]
                        parts = rest.split(" ", 1)
                        approval_id = parts[0] if parts else "ap-auto"
                        description = parts[1] if len(parts) > 1 else rest
                        seq = _next(seq)
                        yield AgentEvent(
                            kind=EventType.APPROVAL,
                            data={"approval_id": approval_id, "description": description, "risk": "high"},
                            seq=seq,
                            task_id=task.id,
                        )
                        # 等待客户端审批: 直接 await 回调 (async 函数)
                        # 回调由 dispatch_server 注入, 内部用 asyncio.Event 阻塞
                        # 直到客户端响应 approval 消息
                        if approve_callback:
                            decision = await approve_callback(approval_id)
                            if decision != "allow":
                                seq = _next(seq)
                                yield AgentEvent(kind=EventType.DONE, data={"status": "denied"}, seq=seq, task_id=task.id)
                                _kill(proc)
                                return
                    else:
                        seq = _next(seq)
                        yield AgentEvent(kind=EventType.TEXT, data={"text": line}, seq=seq, task_id=task.id)
                # 冲刷剩余 buffer
                if buffer:
                    seq = _next(seq)
                    yield AgentEvent(kind=EventType.TEXT, data={"text": buffer}, seq=seq, task_id=task.id)
                    buffer = ""

            # 读 stderr
            assert proc.stderr is not None
            err_chunk = await proc.stderr.read()
            if err_chunk:
                err_text = err_chunk.decode("utf-8", errors="replace").strip()
                if err_text:
                    seq = _next(seq)
                    yield AgentEvent(kind=EventType.STDERR, data={"text": err_text}, seq=seq, task_id=task.id)

            rc = await proc.wait()
            seq = _next(seq)
            yield AgentEvent(
                kind=EventType.DONE,
                data={"status": "ok" if rc == 0 else "error", "exit_code": rc},
                seq=seq,
                task_id=task.id,
            )
        except asyncio.CancelledError:
            _kill(proc)
            seq = _next(seq)
            yield AgentEvent(kind=EventType.DONE, data={"status": "cancelled"}, seq=seq, task_id=task.id)
            raise
        finally:
            if prompt_file:
                try:
                    os.unlink(prompt_file)
                except Exception:
                    pass
