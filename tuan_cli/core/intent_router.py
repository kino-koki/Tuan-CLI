"""意图路由 (Intent Router) —— 每轮用户输入分类到意图类别, 路由到不同提示档与工具暴露。

现状 (填补的缺口)
----------------
已有 core/prompt_tier 按模型**上下文窗口**选档 (compact/full), 但同一模型在不同任务上
需要不同的提示词复杂度与工具暴露策略 —— 例如:
- "把 utils.py 里的 parse_date 函数改成支持时区" → 需要完整工作流 (理解 → 规划 → 编辑 → 测试)
- "Python 里怎么把字符串转成日期?" → 答疑, 不动文件, 不需要文件编辑工具
- "git status" → 简单命令, 一两步搞定
- "谢谢你, 辛苦了!" → 纯聊天, 任何工具都不需要

prompt_tier 看的是「模型能装多少」, intent_router 看的是「这一轮任务要多少」——
两者正交, 联合决定每轮实际下发的提示档与工具集。

四类意图
--------
- ``CODE_TASK``: 完整编码任务 (编辑/创建/重构/修复 + 涉及文件/代码)。COMPACT 或 FULL 档,
  必须暴露工具 (安全底线: 不因路由降级丢工具)。
- ``QUESTION``: 答疑/解释, 不动文件。MINI 或 COMPACT 档, 可跳过工具 (省 token)。
- ``COMMAND``: 简单直接动作 (git status / ls / cat 文件)。MINI 档足够, 暴露工具。
- ``CHAT``: 纯对话, 不需要工具。MINI 档, 跳过工具。

档位字符串约定
--------------
``RouteDecision.prompt_tier`` 取值: ``"MINI"`` | ``"COMPACT"`` | ``"FULL"`` | ``""``。
``""`` 表示「沿用 config 默认」, 由调用方回落到 ``_resolve_soul_tier`` 的既有逻辑。
agent 侧集成 (见 ``core/agent_prompt.py``) 会把 ``MINI``/``COMPACT`` 都映射到
``core.prompt_tier.COMPACT`` (现有内置 SOUL 只有 compact/full 两档, MINI 在此架构下
等价于 compact —— 真正的 MINI 模板可作为后续扩展)。

设计约束
--------
- 纯启发式 (无 ML 调用), 单次分类 < 5ms。
- 按 ``lru_cache`` 对输入文本 (等价于按 task_hash) 做记忆化, 避免重试同一输入时重复分类。
- 分类不确定时回退 ``CODE_TASK`` (COMPACT/FULL + 完整工具), 宁多勿少。
- 绝不因路由打坏安全: ``CODE_TASK`` 必须暴露工具; ``CHAT``/``QUESTION`` 才允许跳过。

与既有路由的关系
----------------
``core/model_router.py`` 按**任务难度**选模型 (provider/model),
``core/prompt_tier.py`` 按**上下文窗口**选提示档,
``core/auto_route.py`` 按**规划/执行阶段**在强/弱模型间切换,
本模块按**任务意图**决定提示档覆盖 + 工具暴露 + 工具轮次上限。
它们各管一维, 互不替代。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
import hashlib
import re


# ============================================================ 意图类别

class Intent(str, Enum):
    """用户单轮输入的意图类别。

    继承 ``str`` 便于日志/事件序列化 (``intent.value`` 与 ``str(intent)`` 一致)。
    """

    CODE_TASK = "code_task"
    QUESTION = "question"
    COMMAND = "command"
    CHAT = "chat"


@dataclass(frozen=True)
class RouteDecision:
    """一次意图路由决策 (不可变, 可哈希, 可缓存)。

    Attributes:
        intent: 识别出的意图类别。
        prompt_tier: 提示档覆盖 ("MINI" | "COMPACT" | "FULL" | ""), 空串表示沿用 config 默认。
        expose_tools: 是否向模型暴露工具清单。
        max_tool_rounds: 本轮最多允许的工具调用轮次 (0 = 不调用工具)。
        task_hash: 输入文本 SHA1 前 12 位, 供日志/调试定位 (也作缓存键语义)。
    """

    intent: Intent
    prompt_tier: str
    expose_tools: bool
    max_tool_rounds: int
    task_hash: str


# ============================================================ 关键词表

# 简单命令: 通常以这些 shell/CLI 命令开头且输入很短 (<= _COMMAND_MAX_LEN)。
# 注意大小写不敏感; 仅在「开头」命中才算命令, 中间出现视为代码任务上下文。
_COMMAND_HEAD_RE = re.compile(
    r"""^\s*
        (?:
            git | npm | pnpm | yarn | pip | pip3 | uv | poetry | cargo |
            docker | kubectl | make | cmake | python | python3 | node |
            cd | ls | dir | pwd | cat | head | tail | less | more |
            mkdir | rm | mv | cp | touch | chmod | chown |
            grep | find | rg | fd | sed | awk | which | where |
            curl | wget | ssh | scp | tar | zip | unzip |
            show | open | run | list | type | print | echo
        )\b""",
    re.IGNORECASE | re.VERBOSE,
)

# 命令档的长度上限: 超过此长度即使以命令词开头也升级为 code_task/question (避免
# 把 "git: how do I revert a merge commit on branch foo" 这类长问题误判为命令)。
_COMMAND_MAX_LEN: int = 50

# 编辑动词 (en): 表明用户想让代码/文件**发生变化**。
_EDIT_VERBS_RE = re.compile(
    r"""\b
        (?: edit | write | create | refactor | implement | fix | add | remove |
            delete | update | modify | change | rename | move | build |
            debug | patch | extend | rewrite | cleanup | clean\s?up |
            optimize | extract | inline | split | merge | integrate |
            install | uninstall | configure | setup | set\s?up | generate |
            make | turn | convert | port | migrate | translate | bump |
            upgrade | downgrade | pin | bump | toggle | enable | disable
        )\b""",
    re.IGNORECASE | re.VERBOSE,
)

# 编辑动词 (zh)。
_EDIT_VERBS_ZH = (
    "编辑", "编写", "写", "新建", "创建", "重构", "实现", "修复", "修", "添加", "加",
    "删除", "移除", "更新", "修改", "改", "换", "重命名", "搬", "调试", "打补丁",
    "补", "扩展", "重写", "整理", "优化", "抽取", "拆", "合并", "集成", "安装",
    "卸载", "配置", "生成", "转换", "迁移", "翻译", "升级", "降级", "启用", "禁用",
)

# 文件路径/代码标识 (en): .py/.js/... 或 显式路径分隔符。
_FILE_PATH_RE = re.compile(
    r"""(?:
            \b[\w./\\\-]+\.(?:py|js|ts|tsx|jsx|md|json|yaml|yml|toml|ini|cfg|html|css|scss|go|rs|java|kt|c|cpp|h|hpp|sh|bat|ps1|rb|php|swift|sql|vue|svelte)\b
            |
            (?:^|[\s"'(`])(?:\./|/|\.\.\\/)[\w./\\\-]+
            |
            (?:^|[\s"'(`])src/|tests?/|lib/|bin/|scripts?/|docs?/|app/|core/
        )""",
    re.IGNORECASE | re.VERBOSE,
)

# 代码结构标识: 出现这些 token 强烈暗示这是代码任务 (而非纯文本问答)。
_CODE_MARKER_RE = re.compile(
    r"""\b
        (?: function | class | def | method | variable | var | const | let |
            import | export | module | package | API | endpoint | route |
            component | hook | decorator | interface | type | enum |
            regex | SQL | schema | migration | config | env | CLI |
            bug | error | exception | traceback | stack\s?trace |
            TODO | FIXME | test | tests | unit | e2e
        )\b""",
    re.IGNORECASE | re.VERBOSE,
)

# 代码结构标识 (zh)。
_CODE_MARKER_ZH = (
    "函数", "方法", "类", "变量", "常量", "模块", "包", "接口", "组件", "钩子",
    "装饰器", "枚举", "正则", "配置", "命令行", "接口", "接口", "端点", "路由",
    "bug", "报错", "异常", "错误", "堆栈", "日志", "测试", "单测", "回归",
)

# 答疑动词/疑问词 (en): 开头命中或全句包含均可。
_QUESTION_START_RE = re.compile(
    r"""^\s*
        (?: how | why | what | when | where | which | who | whom | whose |
            is | are | can | could | should | would | will | do | does |
            did | may | might | shall | explain | describe | tell |
            define | compare | list | give | show\s+me\s+how |
            walk\s+me\s+through | help\s+me\s+understand
        )\b""",
    re.IGNORECASE | re.VERBOSE,
)

# 答疑动词 (zh)。
_QUESTION_START_ZH = (
    "什么", "为什么", "怎么", "怎样", "如何", "哪", "请问", "能否", "是否",
    "解释", "说明", "描述", "介绍", "讲讲", "谈谈", "什么是", "为什么是",
    "能不能", "可不可以", "会不会", "是不是", "有没有",
)

# 结尾问号: 强疑问信号。
_QUESTION_TAIL_RE = re.compile(r"[?？]\s*$")

# 聊天特征: 短句、无编辑动词、无文件路径、无代码标识、无强命令前缀。通常用于
# 寒暄/致谢/情绪表达/闲聊。这里用白名单式排除 —— 未命中其它三类且足够短就归 CHAT。
_CHAT_MAX_LEN: int = 40


# ============================================================ 分类器

def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    """子串命中任一 needle 即 True (中文按字匹配, 不需要词边界)。"""
    return any(n in text for n in needles)


def _task_hash(text: str) -> str:
    """输入文本 SHA1 前 12 位 —— 缓存键 / 日志定位用。"""
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:12]


@lru_cache(maxsize=512)
def classify_intent(user_input: str) -> Intent:
    """启发式意图分类器 (纯函数, 无 IO, <5ms)。

    优先级 (高 → 低):
    1. 空输入 → ``CHAT`` (无信号, 默认按对话处理, 不消耗工具预算)。
    2. 短命令模式 (shell/CLI 命令词开头 + 长度 <= 50) → ``COMMAND``。
    3. 编辑动词 (en/zh) + (文件路径 | 代码标识) → ``CODE_TASK``。
    4. 编辑动词单独出现 (无文件路径) 但输入长度 > 40 → ``CODE_TASK`` (长输入+编辑动词
       视为完整任务, 即使没显式给路径 —— 大概率会在后续轮次里指明文件)。
    5. 强疑问信号 (wh- 开头 / 中文疑问词 / 结尾问号) → ``QUESTION``。
    6. 短句 (<= 40 字符) 无任何编辑/代码标识 → ``CHAT``。
    7. 其余不确定 → ``CODE_TASK`` (安全兜底: 宁多勿少, 完整工具暴露)。

    ``lru_cache`` 兼作记忆化: 同一文本重试时直接命中缓存, 不再走正则。
    """
    text = (user_input or "").strip()
    if not text:
        return Intent.CHAT

    length = len(text)

    # 1. 短命令: shell/CLI 命令词开头 + 长度受限
    if length <= _COMMAND_MAX_LEN and _COMMAND_HEAD_RE.match(text):
        # 但若同时含明确编辑动词 (如 "fix git config") 且带文件路径, 升级 code_task
        if _EDIT_VERBS_RE.search(text) and _FILE_PATH_RE.search(text):
            return Intent.CODE_TASK
        return Intent.COMMAND

    has_edit = _EDIT_VERBS_RE.search(text) is not None or _contains_any(text, _EDIT_VERBS_ZH)
    has_path = _FILE_PATH_RE.search(text) is not None
    has_code = _CODE_MARKER_RE.search(text) is not None or _contains_any(text, _CODE_MARKER_ZH)

    # 2/3. 编辑动词 + (路径 或 代码标识) → CODE_TASK
    if has_edit and (has_path or has_code):
        return Intent.CODE_TASK
    # 4. 长输入 + 编辑动词 (即使没路径/代码标识, 大概率也是任务)
    if has_edit and length > 40:
        return Intent.CODE_TASK

    # 5. 强疑问信号
    starts_question = (
        _QUESTION_START_RE.match(text) is not None
        or text.startswith(_QUESTION_START_ZH)  # type: ignore[arg-type]
        or any(text.startswith(z) for z in _QUESTION_START_ZH)
    )
    ends_question = _QUESTION_TAIL_RE.search(text) is not None
    if starts_question or ends_question:
        return Intent.QUESTION

    # 6. 短句无强信号 → CHAT
    if length <= _CHAT_MAX_LEN and not has_edit and not has_path and not has_code:
        return Intent.CHAT

    # 7. 兜底: 分类不确定 → CODE_TASK (安全侧)
    return Intent.CODE_TASK


# ============================================================ 路由

def _tier_for_code_task(text: str, context_window: int) -> str:
    """编码任务选 COMPACT 还是 FULL: 越长/越复杂越倾向 FULL。

    经验规则:
    - 输入长度 > 200 字符 → 复杂任务倾向 FULL。
    - 同时命中多个编辑动词 (>= 2 种不同动词) → 复杂任务倾向 FULL。
    - 显式声明的大上下文窗口 (>= 128k) 也倾向 FULL (反正装得下)。
    - 其余 → COMPACT (省 token, 覆盖大多数中小型任务)。
    """
    if len(text) > 200:
        return "FULL"
    edit_hits = len(set(_EDIT_VERBS_RE.findall(text)))
    if edit_hits >= 2:
        return "FULL"
    try:
        if int(context_window) >= 128 * 1024:
            return "FULL"
    except (TypeError, ValueError):
        pass
    return "COMPACT"


@lru_cache(maxsize=512)
def route(user_input: str, context_window: int = 0) -> RouteDecision:
    """一站式路由: 意图 + 提示档 + 工具暴露 + 工具轮次上限。

    Args:
        user_input: 本轮用户原始输入 (去空白后分类)。
        context_window: 当前模型上下文窗口 (token); 仅用于 ``CODE_TASK`` 时
                        在 COMPACT/FULL 间选择, 其他意图不使用此参数。
                        0/负数视为「未知窗口」→ 按输入复杂度定档。

    Returns:
        冻结的 :class:`RouteDecision`, 调用方可安全缓存到 Agent 实例。
        ``task_hash`` 字段用于日志/事件去重。

    ``lru_cache`` 兼作记忆化: 同一 ``(text, window)`` 组合直接命中缓存, 满足
    "memoize by task_hash to avoid re-classification on retries" 的约束
    (文本相同 ⇒ task_hash 相同 ⇒ 缓存命中)。
    """
    text = (user_input or "").strip()
    intent = classify_intent(text)
    h = _task_hash(text)

    if intent is Intent.CODE_TASK:
        return RouteDecision(
            intent=intent,
            prompt_tier=_tier_for_code_task(text, context_window),
            expose_tools=True,   # 安全底线: 编码任务必须暴露工具
            max_tool_rounds=25,
            task_hash=h,
        )
    if intent is Intent.QUESTION:
        # 答疑类默认不暴露文件编辑工具 (省 token + 降低误操作面)。
        # 若后续需要检索增强 (如 grep/find), 由上层显式开启 —— 本层保持最小权限。
        return RouteDecision(
            intent=intent,
            prompt_tier="MINI",
            expose_tools=False,
            max_tool_rounds=0,
            task_hash=h,
        )
    if intent is Intent.COMMAND:
        return RouteDecision(
            intent=intent,
            prompt_tier="MINI",
            expose_tools=True,
            max_tool_rounds=3,
            task_hash=h,
        )
    # CHAT
    return RouteDecision(
        intent=intent,
        prompt_tier="MINI",
        expose_tools=False,
        max_tool_rounds=0,
        task_hash=h,
    )


def clear_cache() -> None:
    """清空记忆化缓存 (测试隔离 / 配置热切换时调用)。"""
    classify_intent.cache_clear()
    route.cache_clear()


__all__ = [
    "Intent",
    "RouteDecision",
    "classify_intent",
    "route",
    "clear_cache",
]