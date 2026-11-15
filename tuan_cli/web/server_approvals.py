"""WebServer 的审批 mixin: SSE 上的确认请求与超时策略。"""

import threading
import uuid

from ._common import (
    _ACTIVE_CHAT,
    _APPROVALS,
    _APPROVALS_LOCK,
    analyze_command,
)


class ServerApprovalsMixin:
    # ---------------- 权限审批 (危险工具确认) ----------------
    def _ask_approval(self, prompt: str) -> bool:
        """危险操作确认回调: 向前端推审批弹窗并阻塞等待; 超时/无 UI → fail-closed 拒绝。"""
        q = _ACTIVE_CHAT.get(threading.get_ident())
        if q is None:
            return False  # 无 UI 上下文 → 默认拒绝 (fail-closed)
        req_id = uuid.uuid4().hex[:8]
        ev = threading.Event()
        with _APPROVALS_LOCK:
            _APPROVALS[req_id] = {"event": ev, "result": False}
        q.put(("approval", {"id": req_id, "prompt": str(prompt),
                            "verdict": analyze_command(str(prompt))}))
        got = ev.wait(timeout=300)
        with _APPROVALS_LOCK:
            rec = _APPROVALS.pop(req_id, None)
        return bool(rec and rec.get("result")) if got else False


    def resolve_approval(self, req_id: str, decision: str) -> bool:
        """前端审批结果回填 (allow / deny)。"""
        with _APPROVALS_LOCK:
            rec = _APPROVALS.get(req_id)
            if rec is None:
                return False
            rec["result"] = str(decision).lower() in ("allow", "yes", "true", "1")
            rec["event"].set()
        return True
