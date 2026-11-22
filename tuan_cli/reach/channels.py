# -*- coding: utf-8 -*-
"""tuan-reach 内置频道 —— 每个 channel = 匹配规则 + 有序 backend 回退链。

自研实现, 零第三方依赖 (stdlib urllib / xml.etree); 可选依赖 (yt-dlp)
缺失时自动落到下一后端。频道集:
  web       通用网页 (SSRF 防护直读)
  github    仓库元数据 + README (API → raw 回退)
  rss       RSS/Atom 订阅源
  youtube   YouTube 视频 (yt-dlp → oembed 免 key 元数据)
  bilibili  B 站视频 (公开 API → 页面 og 标签回退)
"""
from __future__ import annotations

import base64
import gzip
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple

from .base import Backend, Channel

_UA = "Mozilla/5.0 (tuan-watch; tuan-reach) AppleWebKit/537.36"
_TIMEOUT = 20


# ---------------------------------------------------------------- http 基座

def http_get(url: str, timeout: int = _TIMEOUT, headers: Dict[str, str] = None) -> Tuple[int, bytes, Dict[str, str]]:
    """极简 HTTP GET: 返回 (status, body_bytes, resp_headers)。异常上抛。"""
    hdrs = {"User-Agent": _UA, "Accept-Encoding": "gzip"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
            try:
                data = gzip.decompress(data)
            except OSError:
                pass
        return resp.status, data, dict(resp.headers)


def _html_to_text(html: str) -> str:
    """去 script/style 与标签, 保留可读文本 (够 doctor/og 用, 非全文抓取)。"""
    html = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def _meta_og(html: str, keys: Tuple[str, ...]) -> Dict[str, str]:
    """从 HTML 提取 og:/twitter: meta 标签。"""
    out: Dict[str, str] = {}
    for m in re.finditer(r'<meta[^>]+(?:property|name)=["\']([^"\']+)["\'][^>]*content=["\']([^"\']*)', html, re.I):
        k = m.group(1).lower()
        if any(k.endswith(x) for x in keys) and m.group(2):
            out[k] = m.group(2)
    return out


def _ssrf_guard(url: str) -> None:
    """复用 tools.web 的 SSRF 防护 (拦内网/保留地址)。"""
    try:
        from ..tools.web import _check_ssrf
        blocked = _check_ssrf(url)
        if blocked:
            raise ValueError(f"SSRF 拦截: {blocked}")
    except ImportError:
        pass  # 防护模块缺失时退化为无守卫 (不理想, 但保持能力可用)


# ---------------------------------------------------------------- web

def _web_fetch(target: str) -> Tuple[bool, str, Dict[str, Any]]:
    _ssrf_guard(target)
    status, data, hdrs = http_get(target)
    ctype = (hdrs.get("Content-Type") or "").lower()
    if "html" in ctype or data[:1] == b"<":
        text = _html_to_text(data.decode("utf-8", errors="replace"))
    else:
        text = data.decode("utf-8", errors="replace")
    if status != 200:
        return False, "", {"status": status, "reason": f"HTTP {status}"}
    return True, text[:15000], {"status": status, "content_type": ctype}


# ---------------------------------------------------------------- github

_GH_REPO_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)", re.I)


def _gh_api(target: str) -> Tuple[bool, str, Dict[str, Any]]:
    m = _GH_REPO_RE.search(target)
    if not m:
        return False, "", {"reason": "URL 中未识别到 owner/repo"}
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    _ssrf_guard(f"https://api.github.com/repos/{owner}/{repo}")
    _st, data, _h = http_get(f"https://api.github.com/repos/{owner}/{repo}")
    info = json.loads(data.decode("utf-8", errors="replace"))
    if not isinstance(info, dict) or info.get("message"):
        return False, "", {"reason": f"API: {info.get('message', '未知错误')}"}
    parts = [
        f"仓库: {info.get('full_name', '?')}",
        f"描述: {info.get('description') or '(无)'}",
        f"Stars: {info.get('stargazers_count', 0)}  Forks: {info.get('forks_count', 0)}  "
        f"Open Issues: {info.get('open_issues_count', 0)}",
        f"语言: {info.get('language') or '?'}  License: {(info.get('license') or {}).get('spdx_id', '?')}",
        f"主页: {info.get('homepage') or '无'}  更新: {info.get('pushed_at') or '?'}",
    ]
    # README (base64) 附加
    try:
        _st2, rd, _h2 = http_get(f"https://api.github.com/repos/{owner}/{repo}/readme")
        rj = json.loads(rd.decode("utf-8", errors="replace"))
        content = rj.get("content")
        if content:
            md = base64.b64decode(content).decode("utf-8", errors="replace")
            parts.append("\n--- README (节选) ---\n" + md[:6000])
    except Exception:  # noqa: BLE001 - README 拿不到不影响主体
        pass
    return True, "\n".join(parts), {"owner": owner, "repo": repo}


def _gh_raw(target: str) -> Tuple[bool, str, Dict[str, Any]]:
    m = _GH_REPO_RE.search(target)
    if not m:
        return False, "", {"reason": "URL 中未识别到 owner/repo"}
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    for branch in ("main", "master"):
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
        try:
            _st, data, _h = http_get(url, timeout=10)
        except Exception:  # noqa: BLE001
            continue
        if _st == 200:
            return True, f"README ({branch}):\n{data.decode('utf-8', errors='replace')[:8000]}", {
                "owner": owner, "repo": repo, "branch": branch}
    return False, "", {"reason": "main/master 分支 README 均不可达"}


# ---------------------------------------------------------------- rss

def _rss_fetch(target: str) -> Tuple[bool, str, Dict[str, Any]]:
    _ssrf_guard(target)
    _st, data, _h = http_get(target)
    root = ET.fromstring(data)
    items: List[Dict[str, str]] = []

    def _txt(el: Any) -> str:
        return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""

    channel = root.find("channel")
    if channel is not None:  # RSS 2.0
        title = _txt(channel.find("title"))
        for it in channel.findall("item")[:20]:
            items.append({"title": _txt(it.find("title")),
                          "link": _txt(it.find("link")),
                          "date": _txt(it.find("pubDate")),
                          "summary": _txt(it.find("description"))[:300]})
    else:  # Atom
        ns = "{http://www.w3.org/2005/Atom}"
        title = _txt(root.find(f"{ns}title"))
        for it in root.findall(f"{ns}entry")[:20]:
            link = it.find(f"{ns}link")
            items.append({"title": _txt(it.find(f"{ns}title")),
                          "link": (link.get("href") if link is not None else ""),
                          "date": _txt(it.find(f"{ns}updated")),
                          "summary": _txt(it.find(f"{ns}summary"))[:300]})
    if not items and not title:
        return False, "", {"reason": "不是有效的 RSS/Atom 源"}
    lines = [f"订阅源: {title} (共列 {len(items)} 条)"]
    for it in items:
        lines.append(f"  - {it['title'] or '(无标题)'}  {it.get('date', '')}"
                     f"\n    {it.get('link', '')}"
                     + (f"\n    {it['summary']}" if it.get("summary") else ""))
    return True, "\n".join(lines), {"items": len(items)}


# ---------------------------------------------------------------- youtube

_YT_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{6,})", re.I)


def _yt_ytdlp(target: str) -> Tuple[bool, str, Dict[str, Any]]:
    from ..videowatch._ff import ytdlp_available, _run
    if not ytdlp_available():
        return False, "", {"reason": "yt-dlp 未安装"}
    rc, out, err = _run(["yt-dlp", "--no-playlist", "--skip-download",
                         "--print", "%(title)s\t%(channel)s\t%(duration_string)s\t%(view_count)s", target],
                        timeout=120)
    if rc != 0 or not out.strip():
        return False, "", {"reason": (err or "yt-dlp 失败")[-200:]}
    title, channel, dur, views = (out.strip().split("\t") + ["", "", "", ""])[:4]
    return True, (f"YouTube 视频\n标题: {title}\n频道: {channel}\n"
                  f"时长: {dur}\n播放: {views}"), {}


def _yt_oembed(target: str) -> Tuple[bool, str, Dict[str, Any]]:
    vid_m = _YT_RE.search(target)
    if not vid_m:
        return False, "", {"reason": "未识别到视频 ID"}
    url = ("https://www.youtube.com/oembed?url="
           + urllib.parse.quote(f"https://www.youtube.com/watch?v={vid_m.group(1)}", safe="")
           + "&format=json")
    _st, data, _h = http_get(url, timeout=10)
    oj = json.loads(data.decode("utf-8", errors="replace"))
    if not isinstance(oj, dict) or not oj.get("title"):
        return False, "", {"reason": "oembed 无数据"}
    return True, (f"YouTube 视频 (oembed 免 key 元数据)\n标题: {oj.get('title')}\n"
                  f"频道: {oj.get('author_name')}\n缩略图: {oj.get('thumbnail_url')}"), {}


# ---------------------------------------------------------------- bilibili

_BILI_RE = re.compile(r"bilibili\.com/video/(BV[\w]+)", re.I)


def _bili_api(target: str) -> Tuple[bool, str, Dict[str, Any]]:
    m = _BILI_RE.search(target)
    if not m:
        return False, "", {"reason": "未识别到 BV 号"}
    url = ("https://api.bilibili.com/x/web-interface/view?bvid="
           + urllib.parse.quote(m.group(1)))
    _st, data, _h = http_get(url, headers={"Referer": "https://www.bilibili.com/"})
    j = json.loads(data.decode("utf-8", errors="replace"))
    d = (j or {}).get("data") or {}
    if j.get("code") != 0 or not d:
        return False, "", {"reason": f"API code={j.get('code')} {j.get('message', '')}"}
    return True, (
        f"B站视频\n标题: {d.get('title')}\nUP主: {d.get('owner', {}).get('name', '?')}\n"
        f"播放: {d.get('stat', {}).get('view', 0)}  弹幕: {d.get('stat', {}).get('danmaku', 0)}  "
        f"点赞: {d.get('stat', {}).get('like', 0)}\n"
        f"时长: {d.get('duration', 0)}s\n简介: {str(d.get('desc', ''))[:500]}"), {}


def _bili_og(target: str) -> Tuple[bool, str, Dict[str, Any]]:
    _ssrf_guard(target)
    _st, data, _h = http_get(target, headers={"Referer": "https://www.bilibili.com/"})
    metas = _meta_og(data.decode("utf-8", errors="replace"), ("og:title", "og:description"))
    if not metas:
        return False, "", {"reason": "页面无 og 标签"}
    return True, f"B站视频 (og 标签)\n" + "\n".join(f"{k}: {v}" for k, v in metas.items()), {}


# ---------------------------------------------------------------- 频道表

def _is_rss(target: str) -> bool:
    low = target.lower()
    return any(k in low for k in (".xml", "/rss", "/feed", "rss=", "feed="))


def build_channels() -> List[Channel]:
    """构造内置频道 (每次调用全新实例, 便于测试注入)。"""
    return [
        Channel(
            name="github",
            description="GitHub 仓库 (元数据 + README)",
            match=lambda t: "github.com" in t.lower(),
            backends=[Backend("api", _gh_api, "GitHub REST API (免 key, 限速内)"),
                      Backend("raw", _gh_raw, "raw.githubusercontent.com README 兜底")],
            probe_target="https://github.com/torvalds/linux",
        ),
        Channel(
            name="youtube",
            description="YouTube 视频 (yt-dlp → oembed)",
            match=lambda t: bool(_YT_RE.search(t)),
            backends=[Backend("yt-dlp", _yt_ytdlp, "yt-dlp 全量元数据 (需安装)"),
                      Backend("oembed", _yt_oembed, "oembed 免 key 元数据兜底")],
            probe_target="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        Channel(
            name="bilibili",
            description="B站视频 (公开 API → og 标签)",
            match=lambda t: "bilibili.com" in t.lower(),
            backends=[Backend("api", _bili_api, "B站公开 API (免 key)"),
                      Backend("og", _bili_og, "页面 og 标签兜底")],
            probe_target="https://www.bilibili.com/video/BV1GJ411x7h7",
        ),
        Channel(
            name="rss",
            description="RSS / Atom 订阅源",
            match=_is_rss,
            backends=[Backend("direct", _rss_fetch, "直接拉取并解析 XML")],
            probe_target="",
        ),
        Channel(
            name="web",
            description="通用网页 (SSRF 防护直读)",
            match=lambda t: True,
            backends=[Backend("direct", _web_fetch, "urllib 直读 + 正文化")],
            probe_target="https://example.com",
        ),
    ]


__all__ = ["build_channels", "http_get"]
