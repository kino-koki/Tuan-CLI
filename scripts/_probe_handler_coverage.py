"""临时探针 v3: 每个叶子子命令 (path[-1]) vs handler 分发覆盖。

对每个无子命令的叶子子命令, 注册值 = path[-1] (它被注册的名字)。
handler = func (含父级继承), 检查源码里是否有
'sub == "path[-1]"' / '{dest} == "path[-1]"' / in (...)/ startswith 分支。
识别注册但 handler 内部分发未覆盖的真实死命令。
"""
import inspect
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tuan_cli.cli.parser import build_parser, _resolve_func  # noqa: E402


def walk(parser, prefix=(), parent_dest=None, parent_func=None):
    for action in parser._actions:
        if not hasattr(action, "choices") or not isinstance(action.choices, dict):
            continue
        dest = getattr(action, "dest", None)
        for name, sub in action.choices.items():
            path = prefix + (name,)
            func = sub._defaults.get("func") or parent_func
            has_children = any(
                hasattr(a, "choices") and isinstance(a.choices, dict)
                for a in sub._actions
            )
            yield path, dest, func, sub, has_children
            if has_children:
                yield from walk(sub, path, dest, func)


def handler_source(func):
    try:
        return inspect.getsource(_resolve_func(func))
    except Exception:
        return ""


issues = []
checked = 0
top = build_parser()
for path, dest, func, sub, has_children in walk(top):
    if has_children or not dest or not dest.endswith("_cmd"):
        continue
    if not func:
        continue
    src = handler_source(func)
    if not src:
        continue
    val = path[-1]
    checked += 1
    # 查常见分发变量: sub / {dest} / cmd / command / action
    found = False
    for var in ("sub", dest, "cmd", "command", "action"):
        if bool(re.search(rf'{var}\s*==\s*"{val}"', src)) or \
           bool(re.search(rf'{var}\s*in\s*\([^)]*"{val}"', src)) or \
           bool(re.search(rf'{var}\s*\.startswith\("{val}', src)):
            found = True
            break
    if not found:
        issues.append((" ".join(path), dest, val))

print(f"检查了 {checked} 个叶子子命令的 handler 分支")
if issues:
    print(f"\n发现 {len(issues)} 个注册但分支未覆盖:")
    for path, dest, val in issues:
        print(f"  - tuan {path!r} (dest={dest}, 缺分支: {val})")
    sys.exit(1)
print("OK: 全部叶子注册值在 handler 内部分发中有覆盖")
