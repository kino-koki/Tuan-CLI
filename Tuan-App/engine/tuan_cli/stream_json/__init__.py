"""tuan_cli.stream_json — Claude Code stream-json 线协议适配层（转写自 TS 引擎）。

面向 electron/bridge-server.cjs 壳的 NDJSON 线协议：
    stdout 信封: system/init, system/compact_boundary, system/task_*,
                stream_event, assistant, user, result(success/error)
    输入契约:   {"type":"user","message":{"role":"user","content":...},"uuid":...}

模块布局（由上级冻结，并行转写）:
    schema.py     消息 dataclass + NDJSON 序列化/解析 (schema 域)
    translate.py  内部流事件 → Anthropic 形状信封  (headless 域)
    headless.py   持久 stdin 循环驱动器           (headless 域)
    __main__.py   CLI 入口 (对齐 cli.tsx argv)    (headless 域)

目标环境: Python 3.10+ / Windows / CLI 本地引擎角色。
"""
