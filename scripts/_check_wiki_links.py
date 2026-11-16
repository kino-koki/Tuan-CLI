"""临时: wiki 断链检查 - 所有 wiki 内部链接的 target 必须存在。"""
import pathlib
import re
import sys

wiki = pathlib.Path("wiki")
broken = []
for md in sorted(wiki.glob("*.md")):
    text = md.read_text(encoding="utf-8")
    for m in re.finditer(r'\[([^\]]*)\]\(([^)]+)\)', text):
        link = m.group(2)
        if link.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = (wiki / link).resolve() if not link.startswith("wiki/") \
            else (wiki / link[len("wiki/"):]).resolve()
        if not target.exists():
            broken.append((md.name, link, m.group(1)[:30]))

if broken:
    print(f"发现 {len(broken)} 个断链:")
    for src, link, label in broken:
        print(f"  {src}: [{label}]({link})")
    sys.exit(1)
print("OK: 无断链")
