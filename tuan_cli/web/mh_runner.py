# -*- coding: utf-8 -*-
"""视频渲染 runner —— 纯 Python 自研实现 (不依赖外部 mh CLI)。

历史: 早期封装外部 ``mh.cmd`` (VibeMG vibe-motion-graphics, Node 22 进程)。
现完全替换为 :mod:`tuan_cli.web.code_anim_render` (Pillow 逐帧 + ffmpeg 管道编码),
用户开箱即用, 无需先装 mh CLI / Node 22。

公开 API 形状保持不变 (server.py / 前端 / 测试无感知):
  * resolve_mh() → {ok, mh_cmd, node_dir, mh_home, reason}
  * scaffold_project() → {project_id, project_dir, mh_json_path}
  * read_project() → {mh_json, mh_json_raw, scene_js}
  * write_scene_js() / write_mh_json() → {ok, error?}
  * render() / preview() → {ok, job_id}
  * get_job() / list_jobs() → job dict

内部执行: mh.json 格式 = code_anim_render.validate_project 兼容的 project_json
(width/height/fps/duration/nodes/audio)。render 走 _renderer.render_video
(线程池 job 表), preview 走 _renderer.render_contact_sheet。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import code_anim_render as _renderer

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 渲染硬超时 (秒); 超时后 worker 线程标记 error (不杀进程, 无子进程可杀)。
_RENDER_TIMEOUT_SEC = 600
#: 预览/接触表硬超时 (秒)。
_PREVIEW_TIMEOUT_SEC = 120
#: 每个 job 保留的 stdout/stderr 尾部字节数。
_TAIL_BYTES = 4096
#: job 表容量上限, 超出按 started_at 淘汰最老的。
_JOB_CAP = 50

# 进程内 job 注册表: {job_id: job_dict}; 多个 HTTP 工作线程会读, 后台线程会写。
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# 渲染后端可用性探测 (自研: ffmpeg + Pillow)
# ---------------------------------------------------------------------------

def resolve_mh() -> Dict[str, Any]:
    """探测自研渲染后端 (ffmpeg)。返回 ``{ok, mh_cmd, node_dir, mh_home, reason}``。

    保持旧 API 形状 (server /api/mh/status 展示用):
      * ``ok``          = ffmpeg + Pillow 都可用 (自研渲染的两块基石)
      * ``mh_cmd``      = ffmpeg 路径 (诊断展示)
      * ``node_dir``    = "" (无外部 Node)
      * ``mh_home``     = 渲染项目根 (``<ws>/.tuan/mh``)
      * ``reason``      = 不可用原因
    """
    import shutil
    # 顺序: TUAN_FFMPEG → 自研 find_ffmpeg (含 imageio-ffmpeg) → PATH
    ffmpeg = os.environ.get("TUAN_FFMPEG") or _renderer.find_ffmpeg() or shutil.which("ffmpeg") or ""
    ok = bool(ffmpeg) and _renderer._pillow_available()
    reason = "" if ok else (
        "自研渲染需要 ffmpeg (设置 TUAN_FFMPEG 或加入 PATH)" +
        ("" if _renderer._pillow_available() else " + Pillow"))
    return {
        "ok": ok,
        "mh_cmd": ffmpeg,
        "node_dir": "",
        "mh_home": "",
        "reason": reason,
    }


def mh_available() -> bool:
    """渲染后端是否可用 (轻量包装, 供所有端点快速 fail-closed)。"""
    return bool(resolve_mh().get("ok"))



# ---------------------------------------------------------------------------
# 路径护栏
# ---------------------------------------------------------------------------

def _mh_root(workspace: str) -> Path:
    """返回 ``<workspace>/.tuan/mh`` 根目录 (resolve, 不自动创建)。"""
    return (Path(workspace or ".").resolve() / ".tuan" / "mh")


def resolve_project_dir(workspace: str, project_id: str) -> Optional[Path]:
    """把 project_id 解析到 ``<workspace>/.tuan/mh/<project_id>``。

    project_id 必须是单段目录名 (无 ``/`` ``\\`` ``..``), 否则返回 None;
    解析后必须仍在 mh 根之下 (防符号链接 / 大小写逃逸)。
    """
    pid = (project_id or "").strip()
    if not pid or pid in {".", ".."}:
        return None
    if "/" in pid or "\\" in pid or ".." in pid or ":" in pid:
        return None
    root = _mh_root(workspace)
    target = (root / pid).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def resolve_media_path(workspace: str, rel: str) -> Optional[Path]:
    """把 media 相对路径解析到 mh 根之下; 越界返回 None。"""
    raw = (rel or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ".." in raw.split("/"):
        return None
    root = _mh_root(workspace)
    target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


# ---------------------------------------------------------------------------
# scene_js / mh_json 静态校验 (永不 eval)
# ---------------------------------------------------------------------------

def validate_scene_js(scene_js: str) -> Optional[str]:
    """返回错误消息 (None = 通过)。要求非空 + 含 ``prepareFrame`` + ``export default``。

    审计 P1-20: 旧实现只做原始字符串包含判断 —— 注释里写上 ``prepareFrame``
    / ``export default`` 两个词即可通过, 而 ``import("child"+"_process")``、
    ``globalThis["Function"]``、``p.binding("spawn_sync")`` 这类拆写全部漏判。
    现在先剥离注释, 再在**去空白后的扁平文本**上做危险能力检查 (mh 端 Node
    沙箱仍是真正的执行边界, 这里是冗余护栏, 但不再形同虚设)。
    """
    if not isinstance(scene_js, str) or not scene_js.strip():
        return "scene_js 不能为空"
    if "prepareFrame" not in scene_js:
        return "scene_js 必须包含 prepareFrame 函数"
    if "export default" not in scene_js:
        return "scene_js 必须包含 export default"
    # 剥掉块注释 / 行注释后, 在去空白的扁平小写文本上做危险能力匹配
    import re as _re
    stripped = _re.sub(r"/\*.*?\*/", " ", scene_js, flags=_re.S)
    stripped = _re.sub(r"//[^\n]*", " ", stripped)
    flat = _re.sub(r"\s+", " ", stripped).lower()
    # 显式危险调用 / 能力: 动态执行、进程边界、模块加载、不可控回调
    deny = ("eval(", "child_process", "node:child", "import(", "require(",
            ".binding(", "globalthis", "webworker", "process.exit(")
    for d in deny:
        if d in flat:
            return f"scene_js 含有禁止的调用/能力 ({d})"
    # 字符串拼接拆写的执行原语: "child"+"_process" / "ev"+"al" 这类形态
    if _re.search(r"['\"]\s*\+\s*['\"]", flat) and (
            "function" in flat or "eval" in flat or "exec" in flat
            or "child" in flat or "process" in flat):
        return "scene_js 含有疑似拆写的动态执行/进程访问"
    return None


def validate_mh_json(mh_json: Dict[str, Any]) -> Optional[str]:
    """校验 mh.json 基本字段: width/height/fps/duration 必须是 > 0 的数字。"""
    if not isinstance(mh_json, dict):
        return "mh_json 必须是 JSON 对象"
    for key in ("width", "height", "fps", "duration"):
        val = mh_json.get(key)
        if not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0:
            return f"mh_json.{key} 必须是 > 0 的数字"
    return None


# ---------------------------------------------------------------------------
# 同步操作: scaffold / read / write
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, text: str) -> None:
    """tmp + rename 原子写, 防渲染中读到半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def scaffold_project(base_dir: str, name: Optional[str] = None) -> Dict[str, Any]:
    """在 ``<base_dir>/.tuan/mh/<id>`` 脚手架一个新项目 (纯 Python, 无 mh new)。

    生成初版 ``mh.json`` (code_anim_render 兼容的 project_json: width/height/
    fps/duration/nodes) + 占位 ``src/scene.js`` (前端编辑器兼容)。成功返回
    ``{project_id, project_dir, mh_json_path}``; 后端不可用抛 RuntimeError。
    """
    res = resolve_mh()
    if not res.get("ok"):
        raise RuntimeError(res.get("reason") or "渲染后端不可用")
    root = _mh_root(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    # 项目 id: 8 位随机短 id; 若提供了 name 则用作可读前缀 (仍带 id 后缀防冲突)
    pid = uuid.uuid4().hex[:8]
    if name:
        safe = "".join(c for c in str(name).strip() if c.isalnum() or c in "-_")[:24]
        if safe:
            pid = f"{safe}-{pid}"
    proj = (root / pid).resolve()
    proj.relative_to(root)  # 触发越界保护
    proj.mkdir(parents=True, exist_ok=False)
    # 初版 project_json: 一个 3 秒 720p 的最小可用示例 (背景 + 标题)
    default_json: Dict[str, Any] = {
        "width": 1280,
        "height": 720,
        "fps": 30,
        "duration": 3.0,
        "nodes": [
            {"type": "bg", "start": 0.0, "end": 3.0,
             "color": "#10121a", "color2": "#1a1d2e"},
            {"type": "title", "start": 0.2, "end": 2.8,
             "text": name or "Tuan Motion", "color": "#e8eaf0", "size": 64},
        ],
    }
    try:
        _atomic_write(proj / "mh.json",
                      json.dumps(default_json, ensure_ascii=False, indent=2))
        # 占位 scene.js: 兼容前端编辑器 (读 j.scene_js 展示); 实际渲染不执行它
        placeholder = ("// 自研后端: 动画由 mh.json 的 nodes 描述, 本文件仅作展示兼容。\n"
                       "// prepareFrame / export default 保留以满足前端校验。\n"
                       "function prepareFrame(ctx, frame) {}\n"
                       "export default { prepareFrame };\n")
        _atomic_write(proj / "src" / "scene.js", placeholder)
    except (OSError, PermissionError) as exc:
        raise RuntimeError(f"写项目文件失败: {exc}") from exc
    return {
        "project_id": proj.name,
        "project_dir": str(proj),
        "mh_json_path": str(proj / "mh.json"),
    }


def read_project(project_dir: str) -> Dict[str, Any]:
    """读取 ``mh.json`` + ``src/scene.js``; 文件缺失返回空串, 不抛。"""
    pdir = Path(project_dir)
    mh_json_path = pdir / "mh.json"
    scene_path = pdir / "src" / "scene.js"
    mh_json_text = ""
    scene_js = ""
    try:
        if mh_json_path.is_file():
            mh_json_text = mh_json_path.read_text(encoding="utf-8")
    except (OSError, PermissionError):
        mh_json_text = ""
    try:
        if scene_path.is_file():
            scene_js = scene_path.read_text(encoding="utf-8")
    except (OSError, PermissionError):
        scene_js = ""
    parsed: Any = None
    if mh_json_text:
        try:
            parsed = json.loads(mh_json_text)
        except json.JSONDecodeError:
            parsed = None
    return {
        "mh_json": parsed if isinstance(parsed, dict) else {},
        "mh_json_raw": mh_json_text,
        "scene_js": scene_js,
    }


def write_scene_js(project_dir: str, scene_js: str) -> Dict[str, Any]:
    """静态校验 + 原子写 ``src/scene.js``。失败返回 ``{ok:False, error}``。"""
    err = validate_scene_js(scene_js)
    if err:
        return {"ok": False, "error": err}
    target = Path(project_dir) / "src" / "scene.js"
    try:
        _atomic_write(target, scene_js)
    except (OSError, PermissionError) as exc:
        return {"ok": False, "error": f"写 scene.js 失败: {exc}"}
    return {"ok": True, "scene_js": scene_js}


def write_mh_json(project_dir: str, mh_json: Dict[str, Any]) -> Dict[str, Any]:
    """校验 + 原子写 ``mh.json``。失败返回 ``{ok:False, error}``。"""
    err = validate_mh_json(mh_json)
    if err:
        return {"ok": False, "error": err}
    target = Path(project_dir) / "mh.json"
    try:
        _atomic_write(target, json.dumps(mh_json, ensure_ascii=False, indent=2))
    except (OSError, PermissionError) as exc:
        return {"ok": False, "error": f"写 mh.json 失败: {exc}"}
    return {"ok": True, "mh_json": mh_json}


# ---------------------------------------------------------------------------
# 后台 job (render / preview) —— 走自研 code_anim_render 线程池
# ---------------------------------------------------------------------------

def _prune_jobs_locked() -> None:
    """调用方需持有 _JOBS_LOCK; 按 started_at 淘汰最老的 job 直到容量合规。"""
    if len(_JOBS) <= _JOB_CAP:
        return
    ordered = sorted(_JOBS.items(), key=lambda kv: kv[1].get("started_at", 0))
    for key, _job in ordered[: len(_JOBS) - _JOB_CAP]:
        _JOBS.pop(key, None)


def _start_job(kind: str, project_dir: str, out_path: Optional[str],
               worker: Callable[[], Dict[str, Any]]) -> str:
    """启动后台渲染线程; 立即返回 job_id, 状态由 ``GET /api/mh/job?id=`` 轮询。

    自研实现: worker 在 daemon 线程跑 (调 code_anim_render.render_video 等),
    不 spawn Node 进程, 不需要 taskkill。job dict 字段与旧版保持兼容
    (id/kind/status/out_path/returncode/stdout_tail/stderr_tail/error/started_at/
    finished_at/result)。前端轮询读 status/returncode/out_rel/stderr_tail/result。
    """
    job_id = uuid.uuid4().hex[:12]
    job: Dict[str, Any] = {
        "id": job_id,
        "kind": kind,
        "status": "running",
        "argv": [],           # 不再用 argv (自研无子进程); 保留字段以兼容测试读 argv
        "out_path": out_path or "",
        "returncode": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "error": "",
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job
        _prune_jobs_locked()

    def _thread_main() -> None:
        returncode = 0
        error_msg = ""
        result_dict: Any = None
        stderr_tail = ""
        try:
            result_dict = worker()
        except Exception as exc:
            error_msg = str(exc)
            returncode = 1
        with _JOBS_LOCK:
            cur = _JOBS.get(job_id)
            if cur is None:
                return
            cur["returncode"] = returncode
            cur["stderr_tail"] = stderr_tail
            cur["finished_at"] = time.time()
            cur["result"] = result_dict
            if error_msg:
                cur["status"] = "error"
                cur["error"] = error_msg
            elif returncode == 0:
                cur["status"] = "done"
                # 从 result 提取 out_path (code_anim_render 返回 out_path)
                if isinstance(result_dict, dict) and result_dict.get("out_path"):
                    cur["out_path"] = result_dict["out_path"]
            else:
                cur["status"] = "error"
                cur["error"] = f"{kind} 失败 (exit={returncode})"

    thread = threading.Thread(target=_thread_main, daemon=True,
                              name=f"mh-{kind}-{job_id}")
    thread.start()
    return job_id


def render(project_dir: str, out_path: str,
           opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """后台渲染视频 (自研 code_anim_render); 返回 ``{ok, job_id}``。

    project_dir 里需有 ``mh.json`` (code_anim_render.validate_project 兼容)。
    opts 支持 ``fps`` (覆盖 mh.json.fps); ``codec`` 字段忽略 (自研用 libx264)。
    """
    res = resolve_mh()
    if not res.get("ok"):
        return {"ok": False, "error": res.get("reason") or "渲染后端不可用"}
    pdir = Path(project_dir)
    mh_json_path = pdir / "mh.json"
    try:
        project_json = json.loads(mh_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"读 mh.json 失败: {exc}"}
    err = _renderer.validate_project(project_json)
    if err:
        return {"ok": False, "error": err}
    opts = opts or {}
    fps_override = opts.get("fps")
    fps = int(fps_override) if isinstance(fps_override, (int, float)) \
        and not isinstance(fps_override, bool) and fps_override > 0 \
        else int(project_json.get("fps") or 30)
    workspace = str(pdir.parent.parent.parent)  # <ws>/.tuan/mh/<pid> → <ws>
    job_id = _start_job(
        "render", project_dir, out_path,
        lambda: _renderer.render_video(
            project_json, out_path, fps=fps, workspace=workspace))
    return {"ok": True, "job_id": job_id}


def preview(project_dir: str, times: List[float],
            contact_sheet: bool = False) -> Dict[str, Any]:
    """后台接触表预览 (自研 code_anim_render); 返回 ``{ok, job_id}``。

    在 project_dir 下生成 ``preview-<ts>.png`` 接触表 (多时间点缩略图网格)。
    """
    res = resolve_mh()
    if not res.get("ok"):
        return {"ok": False, "error": res.get("reason") or "渲染后端不可用"}
    safe_times = [float(t) for t in (times or [])
                  if isinstance(t, (int, float)) and not isinstance(t, bool)]
    if not safe_times:
        return {"ok": False, "error": "times 必须是非空数字数组"}
    pdir = Path(project_dir)
    mh_json_path = pdir / "mh.json"
    try:
        project_json = json.loads(mh_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"读 mh.json 失败: {exc}"}
    err = _renderer.validate_project(project_json)
    if err:
        return {"ok": False, "error": err}
    ts = int(time.time())
    out_name = f"preview-{ts}.png"
    out_path = str(pdir / out_name)
    job_id = _start_job(
        "preview", project_dir, out_path,
        lambda: _renderer.render_contact_sheet(project_json, safe_times, out_path))
    # 前端 onDone 读 job.out_rel 拼 /api/mh/media (与 render 一致)
    with _JOBS_LOCK:
        cur = _JOBS.get(job_id)
        if cur is not None:
            cur["out_rel"] = f"{pdir.name}/{out_name}"
    return {"ok": True, "job_id": job_id}


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """查询单个 job 状态 (深拷贝, 防调用方改内部表)。"""
    with _JOBS_LOCK:
        job = _JOBS.get((job_id or "").strip())
        return dict(job) if job else None


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """最近的 jobs (按 started_at 倒序, 截断到 limit)。"""
    with _JOBS_LOCK:
        ordered = sorted(_JOBS.values(), key=lambda j: j.get("started_at", 0),
                         reverse=True)
        return [dict(j) for j in ordered[: max(1, min(limit, 100))]]


# ---------------------------------------------------------------------------
# 测试辅助: 重置内部 job 表
# ---------------------------------------------------------------------------

def _reset_jobs() -> None:
    """清空 job 表 (测试隔离用)。"""
    with _JOBS_LOCK:
        _JOBS.clear()


__all__ = [
    "resolve_mh",
    "mh_available",
    "scaffold_project",
    "read_project",
    "write_scene_js",
    "write_mh_json",
    "validate_scene_js",
    "validate_mh_json",
    "resolve_project_dir",
    "resolve_media_path",
    "render",
    "preview",
    "get_job",
    "list_jobs",
    "_reset_jobs",
]
