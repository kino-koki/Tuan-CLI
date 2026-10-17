"""Tuan-Chat 品牌化替换 —— 白名单逐行精确替换。

原则:
  - 只改用户可见品牌文本 + 系统提示词 + 元数据
  - 保留: 代码标识(prop/函数名/action)、Anthropic 协议字段(env/format/header)、
          CSS 类名、ClaudeLogo/claude-thinking 动画、字体名、engine/src(Bun 引擎)、
          测试输入数据
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(r"E:\Qingxiaotuan Agent CLI\claude-desktop-app")
LOG: list[str] = []


def edit_lines(rel: str, edits: dict[int, tuple[str, str]]) -> None:
    """按行号做精确替换(不换行, 行号稳定)。"""
    p = ROOT / rel
    if not p.exists():
        LOG.append(f"MISS {rel}")
        return
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    for ln, (old, new) in edits.items():
        if old not in lines[ln - 1]:
            LOG.append(f"WARN {rel}:{ln} 未命中: {old!r}")
            continue
        lines[ln - 1] = lines[ln - 1].replace(old, new, 1)
        LOG.append(f"OK   {rel}:{ln}: {old!r} -> {new!r}")
    p.write_text("".join(lines), encoding="utf-8")


def edit_text(rel: str, old: str, new: str) -> None:
    p = ROOT / rel
    if not p.exists():
        LOG.append(f"MISS {rel}")
        return
    text = p.read_text(encoding="utf-8", errors="replace")
    if old not in text:
        LOG.append(f"WARN {rel}: 未命中: {old[:60]!r}")
        return
    p.write_text(text.replace(old, new), encoding="utf-8")
    LOG.append(f"OK   {rel}: 全局替换 {old[:40]!r} -> {new[:40]!r}")


# ============ 1. 元数据 / 入口 ============
edit_lines("package.json", {
    5: ("Claude Desktop - AI assistant with native capabilities",
        "Tuan-Chat - AI assistant powered by the Qingxiaotuan engine"),
    26: ('"productName": "Claude Desktop"', '"productName": "Tuan-Chat"'),
    101: ("Claude Desktop uses your microphone for voice dictation.",
          "Tuan-Chat uses your microphone for voice dictation."),
})
# appId 品牌化
edit_text("package.json", '"appId": "com.claude.desktop"', '"appId": "com.tuan.chat"')

edit_lines("index.html", {
    2: ('<html lang="en">', '<html lang="zh-CN">'),
    7: ("<title>Claude</title>", "<title>Tuan-Chat</title>"),
})

# ============ 2. 系统提示词(引擎身份) ============
OLD_IDENTITY_UTILS = """<identity>
You are an AI assistant running in a desktop application called Claude Desktop. The app is built on top of the Claude Code engine, so you have the same powerful tool capabilities that Claude Code has — file operations (Read/Write/Edit), shell execution (Bash), code search (Glob/Grep), web tools (WebSearch/WebFetch), sub-agents (Task), Skills, and more — but the product you are powering is a general-purpose desktop assistant for everyday users, not a coding CLI.

Treat the user the way claude.ai would: with warmth, curiosity, presence, and depth. At the same time, when the user actually wants something built, read, run, or changed on disk — including handing you an entire code project to read or modify — do that work decisively and competently. Conversation-first does NOT mean code-shy.

You are NOT Kiro. You are NOT made by Amazon, AWS, or any Amazon product. You have no connection to Kiro. Do not create .kiro directories, do not produce Kiro-style configs, do not refer to yourself as Kiro under any circumstances.

Default to 简体中文 when the user writes in Chinese. Match the user's language otherwise.

Do not claim to be Claude or created by Anthropic unless the active model actually is a Claude-family model. If the active model is something else, describe yourself generically as the assistant in Claude Desktop.
</identity>"""

NEW_IDENTITY_UTILS = """<identity>
You are Tuan-Chat（青小团）, the desktop AI assistant running in the Tuan-Chat application. The app is powered by the Qingxiaotuan engine — a pure-Python agent with powerful tool capabilities: file operations (Read/Write/Edit), shell execution (Bash), code search (Glob/Grep), web tools (WebSearch/WebFetch), sub-agents (Task), Skills, and more — built as a general-purpose desktop assistant for everyday users, not a coding CLI.

Treat the user with warmth, curiosity, presence, and depth. At the same time, when the user actually wants something built, read, run, or changed on disk — including handing you an entire code project to read or modify — do that work decisively and competently. Conversation-first does NOT mean code-shy.

Default to 简体中文 when the user writes in Chinese. Match the user's language otherwise.

You are Tuan-Chat（青小团）. Do not claim to be Claude or created by Anthropic unless the active model actually is a Claude-family model. If the active model is something else, describe yourself generically as the assistant in Tuan-Chat.
</identity>"""

edit_text("electron/system-prompt-utils.cjs", OLD_IDENTITY_UTILS, NEW_IDENTITY_UTILS)

OLD_IDENTITY_TXT = """<identity>
You are Claude, created by Anthropic, running in a desktop application called Claude Desktop. The app is built on top of the Claude Code engine, so you have the same powerful tool capabilities that Claude Code has — file operations (Read/Write/Edit), shell execution (Bash), code search (Glob/Grep), web tools (WebSearch/WebFetch), sub-agents (Task), Skills, and more — but the product you are powering is a general-purpose desktop assistant for everyday users, not a coding CLI.

Treat the user the way you would on claude.ai: with warmth, curiosity, presence, and depth. At the same time, when the user actually wants something built, read, run, or changed on disk — including handing you an entire code project to read or modify — do that work decisively and competently. Conversation-first does NOT mean code-shy.

You are NOT Kiro. You are NOT made by Amazon, AWS, or any Amazon product. You have no connection to Kiro. Do not create .kiro directories, do not produce Kiro-style configs, do not refer to yourself as Kiro under any circumstances.

Default to 简体中文 when the user writes in Chinese. Match the user's language otherwise.
</identity>"""

NEW_IDENTITY_TXT = """<identity>
You are Tuan-Chat（青小团）, the desktop AI assistant running in the Tuan-Chat application. The app is powered by the Qingxiaotuan engine — a pure-Python agent with powerful tool capabilities: file operations (Read/Write/Edit), shell execution (Bash), code search (Glob/Grep), web tools (WebSearch/WebFetch), sub-agents (Task), Skills, and more — built as a general-purpose desktop assistant for everyday users, not a coding CLI.

Treat the user with warmth, curiosity, presence, and depth. At the same time, when the user actually wants something built, read, run, or changed on disk — including handing you an entire code project to read or modify — do that work decisively and competently. Conversation-first does NOT mean code-shy.

Default to 简体中文 when the user writes in Chinese. Match the user's language otherwise.
</identity>"""

edit_text("electron/system-prompt.txt", OLD_IDENTITY_TXT, NEW_IDENTITY_TXT)

# 测试断言同步(实现变了, 断言里 Claude Desktop 文案跟随新身份块)
edit_lines("electron/system-prompt-utils.test.cjs", {
    29: ("/running in a desktop application called Claude Desktop/",
         "/running in the Tuan-Chat application/"),
    30: ("'self-hosted prompt should keep the Claude Desktop product context'",
         "'self-hosted prompt should keep the Tuan-Chat product context'"),
})

# ============ 3. bridge 可见文案 ============
edit_lines("electron/bridge-server.cjs", {
    361: ("path.join(app.getPath('documents'), 'Claude Desktop')",
          "path.join(app.getPath('documents'), 'Tuan-Chat')"),
    2671: ("`You can return to Claude Desktop now. ${connectorId} was handed off to Composio for authentication.`",
           "`You can return to Tuan-Chat now. ${connectorId} was handed off to Composio for authentication.`"),
    2672: ("`Composio reported that the ${connectorId} connection did not finish cleanly. Return to Claude Desktop to retry.`",
           "`Composio reported that the ${connectorId} connection did not finish cleanly. Return to Tuan-Chat to retry.`"),
})

# ============ 4. 组件可见文案 ============
edit_lines("src/components/MainContent.tsx", {
    143: ("label: 'Claude’s choice'", "label: 'Tuan-Chat 推荐'"),
    228: ("return '请先允许 Claude 使用麦克风，然后再试一次。';",
          "return '请先允许 Tuan-Chat 使用麦克风，然后再试一次。';"),
    4394: ("Claude is AI and can make mistakes. Please double-check responses.",
           "Tuan-Chat is AI and can make mistakes. Please double-check responses."),
    4564: ("Plan Mode — Claude is planning, not executing",
           "Plan Mode — Tuan-Chat is planning, not executing"),
    4588: ("Claude needs your input", "Tuan-Chat needs your input"),
})
edit_lines("src/components/Sidebar.tsx", {
    555: ("label: 'Gift Claude'", "label: 'Gift Tuan-Chat'"),
})
edit_lines("src/components/ChatsPage.tsx", {
    363: ("<span>{chats.length} chats with Claude</span>",
          "<span>{chats.length} chats with Tuan-Chat</span>"),
})
edit_lines("src/components/CoworkPage.tsx", {
    42: ("subtitle: 'The more Claude knows your setup, the more it can do.'",
         "subtitle: 'The more Tuan-Chat knows your setup, the more it can do.'"),
    47: ("title: 'Customize Claude to your role'", "title: 'Customize Tuan-Chat to your role'"),
    53: ("title: 'Ask Claude to create something'", "title: 'Ask Tuan-Chat to create something'"),
})
edit_lines("src/components/CustomizePage.tsx", {
    786: ("Create with Claude", "Create with Tuan-Chat"),
    916: ("Skills, connectors, and plugins shape how Claude works with you.",
          "Skills, connectors, and plugins shape how Tuan-Chat works with you."),
    932: ("Let Claude read and write to the tools you already use.",
          "Let Tuan-Chat read and write to the tools you already use."),
    952: ("Teach Claude your processes, team norms, and expertise.",
          "Teach Tuan-Chat your processes, team norms, and expertise."),
    1005: ('placeholder="# Skill Title\\n\\nInstructions for Claude..."',
           'placeholder="# Skill Title\\n\\nInstructions for Tuan-Chat..."'),
})
edit_lines("src/components/GitBashRequiredModal.tsx", {
    86: ("已安装但未生效？请尝试关闭并重新打开 Claude Desktop。",
         "已安装但未生效？请尝试关闭并重新打开 Tuan-Chat。"),
})
edit_lines("src/components/ProjectsPage.tsx", {
    434: (": \"Add instructions to tailor Claude's responses\"}",
          ": \"Add instructions to tailor Tuan-Chat's responses\"}"),
    581: ("Projects help organize your work and leverage knowledge across multiple conversations. Upload docs, code, and files to create themed collections that Claude can",
          "Projects help organize your work and leverage knowledge across multiple conversations. Upload docs, code, and files to create themed collections that Tuan-Chat can"),
})
edit_lines("src/components/Onboarding.tsx", {
    183: ("欢迎使用 Claude Desktop", "欢迎使用 Tuan-Chat"),
    258: ("使用自己的 API Key，可接入 Claude、GPT、GLM、Gemini 等任意兼容模型。",
          "使用自己的 API Key，可接入 DeepSeek、GPT、GLM、Gemini 等任意兼容模型。"),
    280: ("由作者提供的 Claude API 服务 — 价格实惠，即开即用，无需配置。",
          "由作者提供的 Tuan-Chat API 服务 — 价格实惠，即开即用，无需配置。"),
    306: ("Claude 将在此文件夹中读写项目文件。", "Tuan-Chat 将在此文件夹中读写项目文件。"),
})
edit_lines("src/components/UpgradePlan.tsx", {
    335: ("'Claude Opus 4.6 深度推理'", "'深度推理模型'"),
    336: ("'Claude Sonnet 4.6 快速响应'", "'快速响应模型'"),
    387: ("所有套餐功能完全相同，仅额度不同 — 支持 Claude Opus 4.6 / Sonnet 4.6 / GPT-5.4 等模型，含 Extended Thinking 深度推理、联网搜索、文档生成、代码执行、文件上传与分析",
          "所有套餐功能完全相同，仅额度不同 — 支持深度推理 / 快速响应等模型，含 Extended Thinking 深度推理、联网搜索、文档生成、代码执行、文件上传与分析"),
})
edit_lines("src/utils/artifactRenderer.ts", {
    84: ('return { content: [{ text: "This artifact requires the Claude API to function. Click \'Customize\' to try it in a new conversation." }] };',
          'return { content: [{ text: "This artifact requires the Tuan-Chat API to function. Click \'Customize\' to try it in a new conversation." }] };'),
})
edit_lines("constants.ts", {
    3: ('"利用Claude API中转搭建对话网站"', '"利用Tuan-Chat API搭建对话网站"'),
    11: ('"自建agent调用Claude API"', '"自建agent调用Tuan-Chat API"'),
})
edit_lines("src/constants.ts", {
    3: ('"利用Claude API中转搭建对话网站"', '"利用Tuan-Chat API搭建对话网站"'),
    11: ('"自建agent调用Claude API"', '"自建agent调用Tuan-Chat API"'),
})

# ============ 5. 连接器目录(connectorCatalog: 纯描述文案) ============
cat_p = ROOT / "src/components/customize/connectorCatalog.ts"
text = cat_p.read_text(encoding="utf-8", errors="replace")
n = text.count("Claude")
new_text = text.replace("Claude", "Tuan-Chat")
# 只处理描述字符串中的 Claude; 但 connectorCatalog 里 'Claude' 全为描述文案(已核对)
cat_p.write_text(new_text, encoding="utf-8")
LOG.append(f"OK   connectorCatalog.ts: 替换 {n} 处 Claude -> Tuan-Chat")

# ============ 6. ConnectorDetailsPanel / DirectoryModal 可见文案 ============
edit_lines("src/components/customize/ConnectorDetailsPanel.tsx", {
    155: ('? `Claude config: ${mcpConfigPath}`', '? `Tuan-Chat config: ${mcpConfigPath}`'),
    167: ('? `Claude config: ${mcpConfigPath}`', '? `Tuan-Chat config: ${mcpConfigPath}`'),
    168: ("'Install writes this connector into your Claude MCP configuration so the connection feels native to the app.'}",
          "'Install writes this connector into your Tuan-Chat MCP configuration so the connection feels native to the app.'}"),
    187: ('<DetailCard title="What Claude can do with this app">',
          '<DetailCard title="What Tuan-Chat can do with this app">'),
    201: ("'GitHub is fully wired with a native OAuth flow in this app, so this panel can move from discovery to connection without leaving Claude Desktop.'",
          "'GitHub is fully wired with a native OAuth flow in this app, so this panel can move from discovery to connection without leaving Tuan-Chat.'"),
    205: ("'This connector now supports an in-app MCP install path. You can add or remove the server from Claude config here, then complete any provider-side OAuth from the resulting MCP flow.'",
          "'This connector now supports an in-app MCP install path. You can add or remove the server from Tuan-Chat config here, then complete any provider-side OAuth from the resulting MCP flow.'"),
    206: ("'This build now keeps the app catalog and setup context inside Claude first. External websites are still available as a deliberate next step, but clicking the app card no longer ejects you from the connector experience.'}",
          "'This build now keeps the app catalog and setup context inside Tuan-Chat first. External websites are still available as a deliberate next step, but clicking the app card no longer ejects you from the connector experience.'}"),
})
edit_lines("src/components/customize/DirectoryModal.tsx", {
    349: ("<span>Create with Claude</span>", "<span>Create with Tuan-Chat</span>"),
    881: ("Download Claude for Desktop", "Download Tuan-Chat"),
    940: ("Anthropic &amp; Partners", "Tuan-Chat &amp; Partners"),
})

# ============ 7. 数据文件(inspirations / artifacts) ============
for rel in [
    "src/data/inspirations.json",
    "src/data/artifacts/_index.json",
    "src/data/artifacts/remixed-0e6f226e.json",
    "src/data/artifacts/remixed-0f4e84bc.json",
    "src/data/artifacts/remixed-1e716a42.json",
    "src/data/artifacts/remixed-25a43927.json",
    "src/data/artifacts/remixed-27e36ad3.json",
    "src/data/artifacts/remixed-2af221b6.json",
    "src/data/artifacts/remixed-2c85cf8a.json",
    "src/data/artifacts/remixed-2c91cdd9.json",
    "src/data/artifacts/remixed-34806888.json",
    "src/data/artifacts/remixed-379c977a.json",
    "src/data/artifacts/remixed-3d81ba29.json",
    "src/data/artifacts/remixed-3ec41265.json",
    "src/data/artifacts/remixed-3fab54a6.json",
    "src/data/artifacts/remixed-5a70b8ed.json",
    "src/data/artifacts/remixed-5b2cefd8.json",
    "src/data/artifacts/remixed-66739932.json",
    "src/data/artifacts/remixed-7d9ae635.json",
    "src/data/artifacts/remixed-83bb8762.json",
    "src/data/artifacts/remixed-8eda3673.json",
    "src/data/artifacts/remixed-90adb753.json",
    "src/data/artifacts/remixed-9a273750.json",
    "src/data/artifacts/remixed-9d238552.json",
    "src/data/artifacts/remixed-9d2fe22e.json",
    "src/data/artifacts/remixed-a36033d5.json",
    "src/data/artifacts/remixed-ac6871a2.json",
    "src/data/artifacts/remixed-acf0e4fd.json",
    "src/data/artifacts/remixed-b367b675.json",
    "src/data/artifacts/remixed-b7b2fa37.json",
    "src/data/artifacts/remixed-ba9cb443.json",
    "src/data/artifacts/remixed-badc0925.json",
    "src/data/artifacts/remixed-bc57bf10.json",
    "src/data/artifacts/remixed-be6430eb.json",
    "src/data/artifacts/remixed-c33e575f.json",
    "src/data/artifacts/remixed-c9e8652f.json",
    "src/data/artifacts/remixed-dcc8728e.json",
    "src/data/artifacts/remixed-de47f141.json",
    "src/data/artifacts/remixed-e18e1879.json",
    "src/data/artifacts/remixed-ef17943a.json",
    "src/data/artifacts/remixed-f03a4c44.json",
    "src/data/artifacts/remixed-f080f347.json",
    "src/data/artifacts/remixed-f0ae5ea8.json",
    "src/data/artifacts/remixed-f3ec9231.json",
    "src/data/artifacts/remixed-fc64414e.json",
    "src/data/artifacts/remixed-fe21310a.json",
    "public/artifacts/code/_index.json",
]:
    if (ROOT / rel).exists():
        edit_text(rel, "Claude", "Tuan-Chat")
    # public/artifacts/code/remixed-* 与 src/data/artifacts 同步, 批量做一次
PUB_ART = ROOT / "public/artifacts/code"
if PUB_ART.exists():
    for f in PUB_ART.glob("*.json"):
        txt = f.read_text(encoding="utf-8", errors="replace")
        if "Claude" in txt or "Anthropic" in txt:
            f.write_text(txt.replace("Claude", "Tuan-Chat").replace("Anthropic", "Tuan-Chat"), encoding="utf-8")
            LOG.append(f"OK   public/artifacts/code/{f.name}: Claude/Anthropic -> Tuan-Chat")

# ============ 8. 元数据与技能文件 ============
edit_lines("metadata.json", {
    2: ('"name": "Claude UI Clone"', '"name": "Tuan-Chat UI"'),
    3: ('"description": "A 1:1 pixel-perfect recreation of the Claude web interface frontend."',
        '"description": "Tuan-Chat desktop application powered by the Qingxiaotuan engine."'),
})
edit_lines("electron/skills/skill-creator/SKILL.md", {
    25: ("1. What should this skill enable Claude to do?", "1. What should this skill enable Tuan-Chat to do?"),
})
edit_lines("electron/skills/skill-creator/eval-viewer/viewer.html", {
    637: ("<p>Your feedback has been saved. Go back to your Claude Code session and tell Claude you're done reviewing.</p>",
          "<p>Your feedback has been saved. Go back to your Tuan-Chat session and tell Tuan-Chat you're done reviewing.</p>"),
})

print("\n".join(LOG))
print(f"\n=== 完成, {len([l for l in LOG if l.startswith('OK')])} 处替换, "
      f"{len([l for l in LOG if l.startswith('WARN')])} 处未命中, "
      f"{len([l for l in LOG if l.startswith('MISS')])} 处文件缺失 ===")
