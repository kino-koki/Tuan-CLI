#!/usr/bin/env python3
"""发布前体检 (pre-release check) —— 一条命令确认 v0.3.3 可以安全发往 PyPI。

背景: PyPI 首发不可逆 (包名一旦被占就不能转让), 所以上传前把每一条
能静态验证的东西都验一遍, 避免"传上去才发现少文件/版本号对不上"。

用法:
    python scripts/release_check.py              # 全量体检
    python scripts/release_check.py --skip-build # 只查已构建好的 dist/ 产物
    python scripts/release_check.py --publish URL  # 体检通过后直接上传到该仓库

退出码: 0 = 全绿可发布; 1 = 有 FAIL 项, 不要上传。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
IS_WIN = os.name == "nt"

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stdout.isatty() or IS_WIN and not os.environ.get("WT_SESSION"):
    GREEN = RED = YELLOW = DIM = RESET = ""

_results: list[tuple[str, str, str]] = []  # (status, label, detail)


def record(status: str, label: str, detail: str = "") -> bool:
    _results.append((status, label, detail))
    icon = {"PASS": f"{GREEN}✓{RESET}", "FAIL": f"{RED}✗{RESET}", "WARN": f"{YELLOW}!{RESET}"}[status]
    line = f"  {icon} {label}"
    if detail:
        line += f"  {DIM}{detail}{RESET}"
    print(line)
    return status != "FAIL"


def head(title: str) -> None:
    print(f"\n{title}")


def _has_setuptools() -> bool:
    """当前解释器是否可用 setuptools (决定 sdist 验证能否离线跑)。"""
    import importlib.util

    try:
        return importlib.util.find_spec("setuptools") is not None
    except Exception:  # noqa: BLE001
        return False


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------- 1. 版本一致性
def check_version() -> str:
    head("1. 版本号单一真源")
    with open(ROOT / "pyproject.toml", "rb") as fh:
        cfg = tomllib.load(fh)
    proj = cfg["project"]
    pkg_ver = proj["version"]
    record("PASS", "pyproject.toml version", pkg_ver)

    # version.py 是运行时唯一真源
    # 注意: 必须行首锚定 —— 该文件顶部的说明文档里就写着历史版本
    # (`- 主包 tuan_cli.__version__ = "0.3.1"`), 不锚定会误匹配到文档字符串。
    src = (ROOT / "tuan_cli" / "version.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', src, re.M)
    if not m:
        record("FAIL", "tuan_cli/version.py 解析", "找不到 __version__")
        return pkg_ver
    code_ver = m.group(1)
    record(
        "PASS" if code_ver == pkg_ver else "FAIL",
        "tuan_cli/version.py", f"{code_ver} ({'与 pyproject 一致' if code_ver == pkg_ver else '与 pyproject 不一致!'})",
    )

    # CHANGELOG 必须有该版本的小节
    cl = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    has = f"## [{pkg_ver}]" in cl
    record("PASS" if has else "FAIL", f"CHANGELOG 有 [{pkg_ver}] 小节")

    # 文档版本一致性:
    #   FAIL —— 文档里根本没提当前版本 (徽章没跟上), 或提到了比当前更新的版本;
    #   WARN —— 出现了更旧的版本号 (可能是历史记录, 需人工扫一眼)。
    cur = pkg_ver
    cur_parts = tuple(int(x) for x in cur.split("."))
    docs = sorted(ROOT.glob("README*.md")) + [ROOT / "CAPABILITY-MATRIX.md"]
    docs = [d for d in docs if d.exists()]
    missing, newer, older = [], [], []
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        found = re.findall(r"\bv?(\d+\.\d+\.\d+)\b", text)
        if not found:
            continue
        uniq = sorted(set(found))
        if cur not in uniq:
            missing.append(f"{doc.name}(未提及 {cur})")
        for v in uniq:
            parts = tuple(int(x) for x in v.split("."))
            if len(parts) != 3:
                continue
            if parts > cur_parts:
                newer.append(f"{doc.name}:{v}")
            elif parts < cur_parts:
                older.append(f"{doc.name}:{v}")
    record(
        "FAIL" if missing else "PASS",
        "文档均提及当前版本",
        "; ".join(missing) if missing else f"{len(docs)} 个文档均含 {cur}",
    )
    record(
        "FAIL" if newer else "PASS",
        "文档无超前版本号",
        "; ".join(newer) if newer else "无",
    )
    record(
        "WARN" if older else "PASS",
        "文档中的历史版本号 (需人工确认是否有意保留)",
        ", ".join(older) if older else "无",
    )
    return pkg_ver


# ---------------------------------------------------------------- 2. 产物构建
def build(version: str) -> list[Path]:
    head("2. 构建 wheel + sdist")
    builder = ROOT / "_build_artifacts.py"
    if not builder.exists():
        record("WARN", "未找到 _build_artifacts.py", "跳过构建 (用已存在的 dist/)")
        return sorted((ROOT / "dist").glob("*"))
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    arts: list[Path] = []
    for kind, name in (
        ("wheel", f"tuan_cli-{version}-py3-none-any.whl"),
        ("sdist", f"tuan_cli-{version}.tar.gz"),
    ):
        target = dist / name
        if target.exists():
            target.unlink()
        # 产物必须由 stdout 落盘 (部分沙箱下 Python 无法直接建文件)
        with open(target, "wb") as fh:
            proc = subprocess.run([PY, str(builder), kind], stdout=fh, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            record("FAIL", f"构建 {kind}", (proc.stderr or "").strip()[:200])
            continue
        ok = target.exists() and target.stat().st_size > 0
        record("PASS" if ok else "FAIL", f"构建 {kind}",
               f"{name} ({target.stat().st_size // 1024} KB)" if ok else "文件未生成")
        if ok:
            arts.append(target)
    return arts


# ---------------------------------------------------------------- 3. 元数据校验
def check_metadata(arts: list[Path]) -> None:
    head("3. PyPI 元数据校验 (twine check)")
    if not arts:
        record("FAIL", "没有可校验的产物")
        return
    proc = run([PY, "-m", "twine", "check", *[str(a) for a in arts]])
    out = (proc.stdout + proc.stderr).strip()
    record("PASS" if proc.returncode == 0 else "FAIL", "twine check",
           "" if proc.returncode == 0 else out[:300])
    for a in arts:
        if a.name.endswith(".whl"):
            with zipfile.ZipFile(a) as z:
                names = z.namelist()
                meta = z.read(next(n for n in names if n.endswith("METADATA"))).decode("utf-8")
            mv = re.search(r"^Metadata-Version:\s*(\S+)", meta, re.M)
            lic = "License-Expression" in meta
            old_lic = bool(re.search(r"^License:\s", meta, re.M))
            # PEP 639: License-Expression 需 metadata>=2.4, 且不能与旧式 License: 并存
            bad = lic and (not mv or mv.group(1) < "2.4" or old_lic)
            record("FAIL" if bad else "PASS", f"wheel 元数据 (PEP 639)",
                   f"Metadata-Version {mv.group(1) if mv else '?'}"
                   + ("  ← License-Expression 与版本/旧式 License 字段冲突" if bad else ""))
            need = ["tuan_cli/", "tuan_cli/resources/", "tuan_cli/version.py"]
            missing = [n for n in need if not any(x.startswith(n) for x in names)]
            record("FAIL" if missing else "PASS", "wheel 内容完整", f"缺: {missing}" if missing else f"{len(names)} 个条目")
            junk = [x for x in names if x.endswith((".pyc", ".pyo")) or "__pycache__" in x or ".toolchain" in x or x.startswith("Tuan/")]
            record("FAIL" if junk else "PASS", "wheel 无垃圾文件", f"发现: {junk[:5]}" if junk else "无 __pycache__/工具链/桌面端")


# ---------------------------------------------------------------- 4. 干净环境安装
def check_install(arts: list[Path], version: str) -> None:
    head("4. 干净虚拟环境安装 + 冒烟测试")
    wheel = next((a for a in arts if a.name.endswith(".whl")), None)
    sdist = next((a for a in arts if a.name.endswith(".tar.gz")), None)
    if not wheel:
        record("FAIL", "缺少 wheel, 无法安装验证")
        return
    tmp = Path(tempfile.mkdtemp(prefix="tuan_release_check_"))
    try:
        venv = tmp / "venv"
        proc = run([PY, "-m", "venv", str(venv)])
        if proc.returncode != 0:
            record("FAIL", "创建临时 venv", (proc.stderr or "")[:200])
            return
        # Windows: Scripts/python.exe; POSIX: bin/python
        pyexe = venv / ("Scripts/python.exe" if IS_WIN else "bin/python")
        proc = run([str(pyexe), "-m", "pip", "install", "-q", "--disable-pip-version-check", str(wheel)])
        record("PASS" if proc.returncode == 0 else "FAIL", "pip install wheel",
               "" if proc.returncode == 0 else (proc.stderr or "")[:300])
        if proc.returncode != 0:
            return
        proc = run([str(pyexe), "-m", "tuan_cli", "--version"])
        got = proc.stdout.strip()
        ok = proc.returncode == 0 and version in got
        record("PASS" if ok else "FAIL", "tuan --version", got or (proc.stderr or "")[:200])
        proc = run([str(pyexe), "-m", "tuan_cli", "--help"])
        record("PASS" if proc.returncode == 0 else "FAIL", "tuan --help")
        proc = run([str(pyexe), "-m", "tuan_cli", "doctor"])
        record("PASS" if proc.returncode == 0 else "WARN", "tuan doctor",
               "" if proc.returncode == 0 else (proc.stdout + proc.stderr)[:200])

        if sdist:
            # 两种安装路径自适应:
            #   ① 当前解释器有 setuptools → --no-build-isolation, 完全离线可复现;
            #   ② 没有 → 走 pip 默认隔离构建 (会从 PyPI 拉构建依赖, 依赖网络)。
            # 失败时区分「网络问题」与「产物问题」: 前者只 WARN, 后者 FAIL。
            tgt = tmp / "sdist_target"
            cmd = [PY, "-m", "pip", "install", "-q", "--no-deps", "--target", str(tgt), str(sdist)]
            if _has_setuptools():
                cmd.insert(4, "--no-build-isolation")
            proc = run(cmd)
            if proc.returncode == 0:
                installed = tgt / "tuan_cli" / "version.py"
                ok = installed.exists()
                if ok:
                    txt = installed.read_text(encoding="utf-8", errors="ignore")
                    ok = version in txt
                record("PASS" if ok else "FAIL", "sdist 可安装且版本正确",
                       "" if ok else "sdist 装出来缺文件或版本不符")
            else:
                blob = (proc.stderr or "") + (proc.stdout or "")
                net = any(k in blob for k in (
                    "SSLError", "SSLEOFError", "ConnectionError", "Failed to establish",
                    "Temporary failure in name resolution", "read timed out",
                    "Could not fetch", "Network is unreachable",
                ))
                record(
                    "WARN" if net else "FAIL",
                    "sdist 安装验证" + ("跳过 (网络不可达, 非产物问题)" if net else "失败"),
                    blob.strip().splitlines()[-1][:200] if blob.strip() else "",
                )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 5. 仓库状态
def check_repo(version: str) -> None:
    head("5. 仓库状态")
    proc = run(["git", "-C", str(ROOT), "status", "--porcelain"])
    dirty = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    tracked_dirty = [ln for ln in dirty if not ln.startswith("??")]
    record("PASS" if not tracked_dirty else "FAIL", "无未提交的跟踪文件改动",
           f"{len(tracked_dirty)} 项" if tracked_dirty else f"(仅 {len(dirty) - len(tracked_dirty)} 个未跟踪文件, 不影响发布)")
    proc = run(["git", "-C", str(ROOT), "ls-files"])
    files = proc.stdout.splitlines()
    bad = [f for f in files if f.startswith((".toolchain/", "Tuan/", "Tuan-App/"))
           or f.endswith((".pyc", ".pem", ".key", ".env")) or "__pycache__" in f]
    record("FAIL" if bad else "PASS", "仓库无工具链/桌面端/凭据入库", f"{len(bad)} 项异常" if bad else f"{len(files)} 个跟踪文件")
    proc = run(["git", "-C", str(ROOT), "tag", "-l", f"v{version}"])
    record("PASS" if proc.stdout.strip() else "WARN", f"git tag v{version}",
           proc.stdout.strip() or "尚未打标签 (可发后再打)")


# ---------------------------------------------------------------- 6. PyPI 可用性
def check_pypi(name: str) -> None:
    head("6. PyPI 包名占用")
    try:
        import urllib.request

        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=15) as r:
            import json

            data = json.load(r)
            vs = sorted(data.get("releases", {}).keys())
            record("WARN", f"PyPI 上 '{name}' 已存在", f"已有版本: {', '.join(vs) or '(无)'}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            record("PASS", f"PyPI 包名 '{name}' 可用", "尚无发布记录 (首发)")
        else:
            record("WARN", "PyPI 查询失败", f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001
        record("WARN", "PyPI 查询失败 (离线?)", type(e).__name__)


# ---------------------------------------------------------------- 汇总
def summarize() -> int:
    head("体检汇总")
    fails = [r for r in _results if r[0] == "FAIL"]
    warns = [r for r in _results if r[0] == "WARN"]
    for st, label, detail in fails:
        print(f"  {RED}FAIL{RESET} {label}  {detail}")
    for st, label, detail in warns:
        print(f"  {YELLOW}WARN{RESET} {label}  {detail}")
    total = len(_results)
    if fails:
        print(f"\n{RED}✗ {len(fails)}/{total} 项未通过 —— 先修掉再上传。{RESET}")
        return 1
    print(f"\n{GREEN}✓ 全绿 ({total} 项检查, {len(warns)} 项提醒){RESET} —— 可以上传 PyPI。")
    return 0


def publish(url: str | None) -> int:
    if not url:
        return 0
    head("7. 上传 PyPI")
    arts = sorted((ROOT / "dist").glob("*"))
    if not arts:
        print(f"  {RED}dist/ 为空, 无可上传产物{RESET}")
        return 1
    cmd = [PY, "-m", "twine", "upload", "--repository-url", url, *[str(a) for a in arts]]
    print(f"  {DIM}{' '.join(cmd)}{RESET}")
    proc = run(cmd)
    print(proc.stdout + proc.stderr)
    record("PASS" if proc.returncode == 0 else "FAIL", "twine upload")
    return 0 if proc.returncode == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Tuan-CLI 发布前体检")
    ap.add_argument("--skip-build", action="store_true", help="只校验已构建好的 dist/")
    ap.add_argument("--publish", metavar="URL", help="体检通过后上传到该仓库 URL")
    args = ap.parse_args()

    print(f"{DIM}Tuan-CLI 发布前体检{RESET}")
    version = check_version()
    arts = [] if args.skip_build else build(version)
    if args.skip_build:
        arts = sorted((ROOT / "dist").glob("*"))
        record("PASS" if arts else "FAIL", "使用已有 dist/ 产物", f"{len(arts)} 个文件")
    check_metadata(arts)
    check_install(arts, version)
    check_repo(version)
    with open(ROOT / "pyproject.toml", "rb") as fh:
        check_pypi(tomllib.load(fh)["project"]["name"])
    rc = summarize()
    if rc == 0 and args.publish:
        rc = publish(args.publish)
    return rc


if __name__ == "__main__":
    sys.exit(main())
