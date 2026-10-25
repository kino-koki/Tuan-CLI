"""扫描 tuan_cli 自带 skill，导出名称/描述/来源清单到前端静态 JSON。"""
import json
import re
from pathlib import Path

# 基于脚本自身位置解析，避免写死盘符/绝对路径：
#   scripts/ -> Tuan-App/ -> Tuan-CLI/（仓库根）
ROOT = Path(__file__).resolve().parents[2] / "tuan_cli" / "resources" / "skills" / "builtin"
out = []

def frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    d = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d

# 顶层单个技能 md（排除子目录包）
for md in sorted(ROOT.glob("*.md")):
    text = md.read_text(encoding="utf-8", errors="ignore")
    fm = frontmatter(text)
    h = re.search(r"^#\s+(.+)$", text, re.M)
    name = fm.get("name") or (h.group(1).strip() if h else md.stem)
    desc = fm.get("description") or ""
    out.append({
        "id": md.stem,
        "name": name,
        "desc": desc,
        "source": "内置",
        "pack": "",
    })

# 技能包（含 SKILL.md）
for skillmd in sorted(ROOT.glob("*/SKILL.md")):
    text = skillmd.read_text(encoding="utf-8", errors="ignore")
    fm = frontmatter(text)
    pack = skillmd.parent.name
    h = re.search(r"^#\s+(.+)$", text, re.M)
    out.append({
        "id": pack,
        "name": fm.get("name") or h.group(1).strip() if h else pack,
        "desc": fm.get("description") or "",
        "source": "内置",
        "pack": pack,
    })

target = Path(__file__).resolve().parents[1] / "public" / "data" / "skills.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {len(out)} skills -> {target}")
