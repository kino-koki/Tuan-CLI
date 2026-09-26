"""Auto Memory 自动记忆提取器 (对标 Claude Code Auto Memory)。

在 Agent 回合结束 (Stop) / 工具调用后 (PostToolUse) 自动分析当前回合的用户消息,
用规则+关键词启发式 (不调用额外 LLM, 零成本) 抽取四类记忆:

- user:      用户偏好 (语言/风格/工具偏好)
- feedback:  用户纠正/反馈 (指出上次做法有误、禁止某做法)
- project:   项目决策/约定 (技术栈选择、配置变更)
- reference: 参考事实/链接 (文档地址、版本号)

抽取结果经去重后写入 MemoryStore, 并发出审计事件 memory.auto_extracted。
可通过配置 memory.auto_extract = false 关闭 (默认开启)。
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .store import DEFAULT_MEMORY_KIND, MEMORY_KINDS, MemoryStore

log = logging.getLogger("qingxiaotuan.memory.auto")


# 关键词规则表: 顺序即优先级 (feedback 最强, 先判)。
# 每条规则: (kind, [正则片段], 可选前置窗口截断)
# 中文为主, 兼顾英文。规则命中即归类, 不做语义理解。
_FEEDBACK_PATTERNS = [
    r"不对", r"错了", r"搞错了", r"弄错了", r"不是这样", r"不是这[种样]",
    r"别用", r"不要用", r"别再", r"不要[这样那]", r"改成", r"应该用", r"应该是",
    r"上次你", r"你之前", r"刚才你", r"你写错", r"你搞错", r"错误",
    r"不是说", r"不该", r"别搞", r"停止使用",
    r"that'?s wrong", r"not correct", r"don'?t use", r"wrong", r"instead( of)?",
    r"should( be)?", r"no[,，]\s*use", r"not\s+use", r"please\s+don'?t",
]
_USER_PATTERNS = [
    r"我喜欢", r"我偏好", r"我习惯", r"我想用", r"我更愿意", r"我希望",
    r"我倾向", r"我个人", r"请用", r"请帮我用", r"默认用", r"喜欢用", r"偏好",
    r"我[想要].*?用", r"以后都", r"以后[请帮]?",
    r"i prefer", r"i like", r"i want you to", r"please use", r"always use",
    r"i'?d rather", r"default to",
]
_PROJECT_PATTERNS = [
    r"我们决定", r"项目决定", r"我们采用", r"本项目", r"约定", r"规范[是为]",
    r"统一用", r"决定用", r"采用", r"技术栈", r"项目[里中]", r"本仓库",
    r"we decided", r"we use", r"the project uses", r"we'?ve chosen",
    r"let'?s use", r"decided to", r"our project",
]
_REFERENCE_PATTERNS = [
    r"https?://", r"www\.", r"文档[地址是为]", r"地址[是为在]", r"链接[是为]",
    r"api\s*地址", r"版本[是为]?\s*\d", r"\d+\.\d+\.\d+", r"\d+\.\d+",
    r"文档见", r"见文档", r"参考[文档资料]", r"readme",
]


@dataclass
class ExtractedMemory:
    """单条提取出的记忆 (未落盘前)。"""
    kind: str
    text: str
    source: str = "auto"

    def as_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "source": self.source}


class AutoMemoryExtractor:
    """规则启发式记忆提取器。线程安全; 写入走后台线程不阻塞主循环。"""

    #: 单条记忆最大长度, 避免把整段对话塞进去
    MAX_TEXT_LEN = 200

    def __init__(self, store: Optional[MemoryStore] = None, enabled: bool = True) -> None:
        self.store = store
        self.enabled = bool(enabled)
        self._bg_threads: List[threading.Thread] = []

    # ------------------------------------------------------------------ 分类

    def classify(self, text: str) -> Optional[str]:
        """根据用户消息内容判定记忆分类; 无信号返回 None。"""
        if not text or not text.strip():
            return None
        low = text.lower()
        # 过短 / 纯指令式 (无偏好/纠正/决策信号) 不抽
        stripped = text.strip()
        if len(stripped) < 4:
            return None

        def hit(patterns: List[str]) -> bool:
            for p in patterns:
                try:
                    if re.search(p, low):
                        return True
                except re.error:
                    continue
            return False

        # 优先级: feedback > user > project > reference
        if hit(_FEEDBACK_PATTERNS):
            return "feedback"
        if hit(_USER_PATTERNS):
            return "user"
        if hit(_PROJECT_PATTERNS):
            return "project"
        if hit(_REFERENCE_PATTERNS):
            return "reference"
        return None

    # ------------------------------------------------------------------ 抽取

    @staticmethod
    def _clean_text(text: str, kind: str) -> str:
        """把用户消息裁剪成一句简洁记忆陈述。"""
        t = text.strip()
        # 截断到合理长度
        if len(t) > AutoMemoryExtractor.MAX_TEXT_LEN:
            t = t[:AutoMemoryExtractor.MAX_TEXT_LEN].rstrip() + "…"
        # 去掉句尾语气词/问号
        t = re.sub(r"[。\.]+\s*$", "", t)
        return t

    def extract(self, user_text: str, assistant_text: str = "") -> List[ExtractedMemory]:
        """分析一回合对话, 返回提取到的记忆列表 (仅基于用户消息)。"""
        results: List[ExtractedMemory] = []
        if not user_text or not self.enabled:
            return results
        # 按句子切分, 逐句判定 (一句话里可能含多个信号, 取最强一句)
        sentences = re.split(r"[。！？!?\n;；]+", user_text)
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            kind = self.classify(sent)
            if kind is None:
                continue
            cleaned = self._clean_text(sent, kind)
            if len(cleaned) < 4:
                continue
            results.append(ExtractedMemory(kind=kind, text=cleaned))
        return results

    # ------------------------------------------------------------------ 写入

    def process_turn(
        self,
        user_text: str,
        assistant_text: str = "",
        kernel: Any = None,
    ) -> List[Dict[str, Any]]:
        """处理一回合: 抽取 → 去重 → 落盘 → 发审计事件。同步调用 (测试友好)。

        Returns:
            实际写入的记忆条目列表 (含 id); 被去重/关闭时为空。
        """
        if not self.enabled or self.store is None:
            return []
        extracted = self.extract(user_text, assistant_text)
        if not extracted:
            return []
        written: List[Dict[str, Any]] = []
        for em in extracted:
            new_id = self.store.add_auto_memory(em.text, kind=em.kind, source="auto")
            if new_id is not None:
                written.append({"id": new_id, **em.as_dict()})
        if written and kernel is not None:
            try:
                kernel.emit("memory.auto_extracted", {
                    "count": len(written),
                    "items": written,
                })
            except Exception:  # noqa: BLE001
                log.debug("memory.auto_extracted 审计事件发送失败")
        return written

    def process_turn_async(
        self,
        user_text: str,
        assistant_text: str = "",
        kernel: Any = None,
    ) -> None:
        """后台线程处理一回合, 不阻塞 Agent 主循环。异常隔离。"""
        if not self.enabled or self.store is None:
            return

        def _runner() -> None:
            try:
                self.process_turn(user_text, assistant_text, kernel=kernel)
            except Exception as exc:  # noqa: BLE001
                log.debug("Auto Memory 后台提取失败: %s", exc)

        t = threading.Thread(target=_runner, daemon=True, name="auto-memory")
        t.start()
        # 保留弱引用列表, 避免 join 拖累退出; daemon=True 进程退出自动回收
        self._bg_threads.append(t)
        if len(self._bg_threads) > 8:
            self._bg_threads = self._bg_threads[-8:]


def build_extractor(kernel: Any = None) -> Optional[AutoMemoryExtractor]:
    """从 kernel 构造 AutoMemoryExtractor (读取 memory.auto_extract 开关)。"""
    if kernel is None:
        return None
    store = kernel.get("memory_store")
    if store is None:
        return None
    config = kernel.get("config")
    enabled = True
    if config is not None:
        try:
            enabled = bool(config.get("memory.auto_extract", True))
        except Exception:  # noqa: BLE001
            enabled = True
    return AutoMemoryExtractor(store=store, enabled=enabled)
