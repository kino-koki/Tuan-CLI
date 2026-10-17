"""品牌化补丁: 漏网的 Anthropic/claude(小写) 可见文案与数据。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(r"E:\Qingxiaotuan Agent CLI\claude-desktop-app")
LOG: list[str] = []


def rep(rel: str, old: str, new: str) -> None:
    p = ROOT / rel
    if not p.exists():
        LOG.append(f"MISS {rel}")
        return
    t = p.read_text(encoding="utf-8", errors="replace")
    n = t.count(old)
    if n == 0:
        LOG.append(f"WARN {rel}: 未命中 {old!r}")
        return
    p.write_text(t.replace(old, new), encoding="utf-8")
    LOG.append(f"OK   {rel}: {n} 处 {old!r} -> {new!r}")


# 1. 数据文件: Anthropic / 小写 claude (上一轮只替换了大写 Claude)
for rel in [
    "src/data/inspirations.json",
    "src/data/artifacts/_index.json",
    "src/data/artifacts/remixed-c33e575f.json",
    "public/artifacts/code/_index.json",
]:
    rep(rel, "Anthropic", "Tuan-Chat")
    rep(rel, "claude", "Tuan-Chat")

# 2. DirectoryModal / directoryStore 可见描述文案
rep("src/components/customize/DirectoryModal.tsx",
    "load outreach sequences faster with Apollo context directly in Claude.",
    "load outreach sequences faster with Apollo context directly in Tuan-Chat.")
rep("src/components/customize/directoryStore.ts",
    "description: 'Start a guided skill draft with Claude and jump back into the main Customize workspace when you are ready to refine it.'",
    "description: 'Start a guided skill draft with Tuan-Chat and jump back into the main Customize workspace when you are ready to refine it.'")
rep("src/components/customize/directoryStore.ts",
    "title: 'Create with Claude'",
    "title: 'Create with Tuan-Chat'")

# 3. 充值页可见文案
rep("public/code-recharge.html",
    "充值后立即到账，可用于 Claude API 调用",
    "充值后立即到账，可用于 Tuan-Chat API 调用")

print("\n".join(LOG))
print(f"=== 完成 {len([l for l in LOG if l.startswith('OK')])} 处替换 ===")
