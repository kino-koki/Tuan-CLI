"""Registry 客户端 —— 从 Tuan-Skills / Tuan-Craft 远程仓库拉取清单与包。

两个远程仓库在用户 GitHub 上公开维护:
- Tuan-Skills  : https://github.com/kino-koki/Tuan-Skills
                 专用 Skills 注册中心, 用户可上传/拉取 skill 合集
- Tuan-Craft   : https://github.com/kino-koki/Tuan-Craft
                 为 Tuan 的「感通」模式打造的组件工坊

协议极其简单 (避免中心化 package registry 的运维负担):
1. 仓库根放 ``registry.json`` (skills) 或 ``craft-index.json`` (components)
2. 条目给出 ``name`` / ``version`` / ``description`` / ``author`` / ``sha``
   以及源码路径 ``path`` (仓库内相对路径, 对 sparse-checkout 友好)
3. 安装有两条路径: git sparse-checkout (首选) + GitHub zip archive (回退)

离线/弱网: 拉不到 registry 就直接回退 builtin 播种, 不阻断。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..version import __version__


# ---- 注册表地址 ----
# 使用 raw.githubusercontent.com 直取 JSON, 避免 GitHub API 限频 & 无需鉴权。
_REGISTRY_BASE = "https://raw.githubusercontent.com/kino-koki"
_SKILLS_REGISTRY = f"{_REGISTRY_BASE}/Tuan-Skills/main/registry.json"
_CRAFT_REGISTRY = f"{_REGISTRY_BASE}/Tuan-Craft/main/craft-index.json"

# 本地 registry 缓存 (TTL 1h), 避免每次 list 都打网络
_REGISTRY_CACHE_DIR = Path.home() / ".cache" / "tuan" / "registry"


@dataclass
class RegistryEntry:
    """registry.json 单条 (skill 或 craft 组件)。"""

    name: str
    version: str
    description: str = ""
    author: str = ""
    sha: str = ""             # 内容指纹 (通常等于 SKILL.md hash)
    path: str = ""            # 仓库内相对路径, 例如 "skills/code-review"
    kind: str = "skill"       # skill | craft
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any], *, kind: str = "skill") -> "RegistryEntry":
        return cls(
            name=d["name"],
            version=d.get("version", "0.1.0"),
            description=d.get("description", ""),
            author=d.get("author", ""),
            sha=d.get("sha", ""),
            path=d.get("path", d["name"]),
            kind=kind,
            tags=list(d.get("tags", [])),
        )


def _fetch_json(url: str, *, ttl_seconds: int = 3600) -> Optional[Dict[str, Any]]:
    """拉 JSON 注册表, 先查本地缓存 (TTL)。失败返回 None。"""
    cache_key = hashlib.sha1(url.encode()).hexdigest()
    cache_file = _REGISTRY_CACHE_DIR / f"{cache_key}.json"
    _REGISTRY_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 缓存有效则直接返回
    if cache_file.exists():
        age = os.path.getmtime(cache_file)
        now = __import__("time").time()
        if now - age < ttl_seconds:
            try:
                return json.loads(cache_file.read_text("utf-8"))
            except Exception:
                pass

    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"tuan-cli/{__version__}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
        cache_file.write_bytes(raw)
        return json.loads(raw)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        # 网络失败 → 若有过期缓存则降级, 没有就返回 None
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text("utf-8"))
            except Exception:
                pass
        return None


def list_skills() -> List[RegistryEntry]:
    """列出 Tuan-Skills 远程注册的所有 skill。"""
    data = _fetch_json(_SKILLS_REGISTRY)
    if not data:
        return []
    items = data.get("skills", []) if isinstance(data, dict) else data
    return [RegistryEntry.from_dict(it, kind="skill") for it in items]


def list_craft() -> List[RegistryEntry]:
    """列出 Tuan-Craft 组件工坊的所有组件。"""
    data = _fetch_json(_CRAFT_REGISTRY)
    if not data:
        return []
    items = data.get("components", []) if isinstance(data, dict) else data
    return [RegistryEntry.from_dict(it, kind="craft") for it in items]


def _git_available() -> bool:
    return shutil.which("git") is not None


def install_via_git_sparse(entry: RegistryEntry, dest: Path, *,
                            repo_url: str, branch: str = "main") -> bool:
    """用 git sparse-checkout 安装单个 skill/craft 到 dest/<entry.path 的最后一级>。

    避免完整 clone 整个仓库, 只取一个子目录。前提是 dest 的父目录存在。
    """
    if not _git_available():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 子目录名 (去掉层级, 取最后一段)
    leaf = Path(entry.path).name or entry.name
    target = dest.parent / leaf
    target.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "init", "-q", str(target)],
            check=True, capture_output=True, timeout=15,
        )
        subprocess.run(
            ["git", "-C", str(target), "remote", "add", "origin", repo_url],
            check=True, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "-C", str(target), "config", "core.sparseCheckout", "true"],
            check=True, capture_output=True, timeout=10,
        )
        # sparse-checkout 文件
        sc_file = target / ".git" / "info" / "sparse-checkout"
        sc_file.parent.mkdir(parents=True, exist_ok=True)
        sc_file.write_text(f"{entry.path}\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(target), "pull", "--depth=1", "origin", branch],
            check=True, capture_output=True, timeout=60,
        )
        # 把 sparse 检出的子目录内容平铺到 target 根
        src_dir = target / entry.path
        if src_dir.is_dir():
            for item in src_dir.iterdir():
                item.rename(target / item.name)
            # 清掉空的路径残留
            try:
                src_dir.rmdir()
                # 向上清理 parent 链 (如 "skills" 目录空了)
                p = src_dir.parent
                while p != target and p.is_dir() and not any(p.iterdir()):
                    p.rmdir()
                    p = p.parent
            except OSError:
                pass
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        # 清理半成品
        try:
            shutil.rmtree(target)
        except OSError:
            pass
        return False


def install_via_zip(entry: RegistryEntry, dest: Path, *,
                    repo_url: str, branch: str = "main") -> bool:
    """zip archive 回退路径: GitHub 仓库 archive → 解压 → 取子目录。

    适用于 git 不可用/被墙的环境。下载到临时目录, 成功后原子 rename 到目标。
    """
    import zipfile
    archive_url = f"{repo_url}/archive/refs/heads/{branch}.zip"
    tmp_dir = Path(tempfile.mkdtemp(prefix="tuan-registry-"))
    try:
        req = urllib.request.Request(archive_url, headers={"User-Agent": f"tuan-cli/{__version__}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            zip_bytes = resp.read()
        zip_path = tmp_dir / "repo.zip"
        zip_path.write_bytes(zip_bytes)

        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_dir)

        # GitHub zip 会在仓库根加一层 "<owner>-<repo>-<sha>/"
        top = next((d for d in tmp_dir.iterdir() if d.is_dir() and d.name != "repo.zip"), None)
        if not top:
            return False
        src_dir = top / entry.path
        if not src_dir.is_dir():
            return False

        leaf = Path(entry.path).name or entry.name
        target = dest.parent / leaf
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src_dir, target)
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            shutil.rmtree(tmp_dir)
        except OSError:
            pass


def install(entry: RegistryEntry, dest_root: Path, *,
            prefer: str = "auto") -> bool:
    """安装 registry 条目到 dest_root 下。prefer: git | zip | auto。"""
    repo_map = {
        "skill": ("https://github.com/kino-koki/Tuan-Skills.git",
                  "https://github.com/kino-koki/Tuan-Skills"),
        "craft": ("https://github.com/kino-koki/Tuan-Craft.git",
                  "https://github.com/kino-koki/Tuan-Craft"),
    }
    git_url, web_url = repo_map.get(entry.kind, repo_map["skill"])

    if prefer == "auto":
        prefer = "git" if _git_available() else "zip"

    if prefer == "git":
        ok = install_via_git_sparse(entry, dest_root, repo_url=git_url)
        if ok:
            return True
        # git 失败就回退 zip
        return install_via_zip(entry, dest_root, repo_url=web_url)
    else:
        return install_via_zip(entry, dest_root, repo_url=web_url)


def clear_cache() -> None:
    """清除本地 registry 缓存 (强制下次 list 重新拉取)。"""
    if _REGISTRY_CACHE_DIR.exists():
        try:
            shutil.rmtree(_REGISTRY_CACHE_DIR)
        except OSError:
            pass


__all__ = [
    "RegistryEntry",
    "list_skills",
    "list_craft",
    "install",
    "clear_cache",
]
