# -*- coding: utf-8 -*-
"""MotionHarness (mh) 命令行 runner —— 供 Web 工作台的代码动画工作台调用。

设计要点 (fail-closed):
  * 永不使用 ``shell=True`` —— 子进程 argv 一律是列表, 调用 ``mh.cmd`` 全路径。
  * 子进程 PATH 首位插入 Node 22 目录 (mh 需要 Node 22; 服务器宿主可能跑在 Node 20)。
  * 严格路径护栏: 项目目录必须位于 ``<workspace>/.tuan/mh/`` 下, ``..`` / 绝对路径
    一律拒绝, 防止渲染输出逃逸到工作区之外。
  * ``scene_js`` 仅做**静态字符串校验** (必须含 ``prepareFrame`` + ``export default``,
    非空), 永不 ``eval`` / ``exec`` —— 动画逻辑由 mh 自己在 Node 进程里跑。
  * render / preview 跑在后台线程 (渲染可达分钟级), 写入进程内 job 表供前端轮询;
    硬超时后 ``taskkill /T`` 杀整棵进程树, 防孤儿 Node 进程占 CPU。
  * 不打印任何 token / 凭证; stdout/stderr 仅保留尾部 ~4KB 供诊断。

环境变量:
  * ``TUAN_MH_HOME``  默认 ``I:\\MotionHarness``       —— mh 项目根
  * ``TUAN_MH_NODE``  默认 ``I:\\node-v22.15.0-win-x64`` —— Node 22 目录 (前置到 PATH)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 常量 / 配置
# ---------------------------------------------------------------------------

_DEFAULT_MH_HOME = r"I:\MotionHarness"
_DEFAULT_MH_NODE = r"I:\node-v22.15.0-win-x64"

#: 渲染硬超时 (秒); 超时后 kill 整棵进程树。
_RENDER_TIMEOUT_SEC = 600
#: 预览/关键帧硬超时 (秒)。
_PREVIEW_TIMEOUT_SEC = 120
#: 每个 job 保留的 stdout/stderr 尾部字节数。
_TAIL_BYTES = 4096
#: job 表容量上限, 超出按 started_at 淘汰最老的。
_JOB_CAP = 50

# 进程内 job 注册表: {job_id: job_dict}; 多个 HTTP 工作线程会读, 后台线程会写。
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()

# 后台线程里跑的 subprocess 调用: 测试可 monkeypatch 这两个符号以 mock 子进程。
Popen = subprocess.Popen
RunFn = subprocess.run


# ---------------------------------------------------------------------------
# mh 可用性探测
# ---------------------------------------------------------------------------

def resolve_mh() -> Dict[str, Any]:
    """定位 ``mh.cmd`` + Node 22 目录。返回 ``{ok, mh_cmd, node_dir, reason}``。

    * 优先使用 ``<TUAN_MH_HOME>\\node_modules\\.bin\\mh.cmd``;
    * 找不到再退化到系统 PATH 上的 ``mh`` / ``mh.cmd``;
    * 都没有 → ``ok=False`` 并给出 reason (供 /api/mh/status 直接展示)。
    """
    mh_home = os.environ.get("TUAN_MH_HOME") or _DEFAULT_MH_HOME
    node_dir = os.environ.get("TUAN_MH_NODE") or _DEFAULT_MH_NODE
    bin_dir = Path(mh_home) / "node_modules" / ".bin"
    candidates = [
        bin_dir / "mh.cmd",
        bin_dir / "mh",
        Path(mh_home) / "mh.cmd",
        Path(mh_home) / "mh",
    ]
    for cand in candidates:
        if cand.is_file():
            return {"ok": True, "mh_cmd": str(cand), "node_dir": node_dir,
                    "mh_home": mh_home, "reason": ""}
    # 退化: 系统 PATH
    which = shutil.which("mh") or shutil.which("mh.cmd")
    if which:
        return {"ok": True, "mh_cmd": which, "node_dir": node_dir,
                "mh_home": mh_home, "reason": ""}
    return {"ok": False, "mh_cmd": "", "node_dir": node_dir, "mh_home": mh_home,
            "reason": f"未在 {bin_dir} 或 PATH 上找到 mh (需先安装 MotionHarness CLI)"}


def mh_available() -> bool:
    """mh CLI 是否可用 (轻量包装, 供所有端点快速 fail-closed)。"""
    return bool(resolve_mh().get("ok"))


def _child_env(node_dir: str) -> Dict[str, str]:
    """构造子进程 env: 把 Node 22 目录**前置**到 PATH, 防宿主 Node 20 抢占。"""
    env = dict(os.environ)
    paths = [node_dir] if node_dir else []
    existing = env.get("PATH") or env.get("Path") or ""
    if existing:
        paths.append(existing)
    new_path = os.pathsep.join(paths)
    env["PATH"] = new_path
    if "Path" in env and env["Path"] != new_path:
        env["Path"] = new_path
    return env


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

    这里只做**字符串包含**判断, 不解析 JS 也不执行 —— mh 自己在 Node 沙箱里跑。
    额外硬拒 ``eval(`` / ``Function(`` 开头的明显危险形态作为冗余护栏 (mh 端
    还会再拒一次, 这里只挡掉显式滥用)。
    """
    if not isinstance(scene_js, str) or not scene_js.strip():
        return "scene_js 不能为空"
    if "prepareFrame" not in scene_js:
        return "scene_js 必须包含 prepareFrame 函数"
    if "export default" not in scene_js:
        return "scene_js 必须包含 export default"
    # 显式危险调用: 仅作为冗余护栏 (mh 端才是真正的执行沙箱)
    lowered = scene_js.lower()
    if "eval(" in lowered or "child_process" in lowered:
        return "scene_js 含有禁止的调用 (eval / child_process)"
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
    """调用 ``mh new <dir>`` 在 ``<base_dir>/.tuan/mh/<id>`` 脚手架一个新项目。

    成功返回 ``{project_id, project_dir, mh_json_path}``; 失败抛 RuntimeError。
    """
    res = resolve_mh()
    if not res.get("ok"):
        raise RuntimeError(res.get("reason") or "mh 不可用")
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
    argv: List[str] = [res["mh_cmd"], "new", str(proj)]
    try:
        proc = RunFn(argv, capture_output=True, text=True,
                     env=_child_env(res["node_dir"]), cwd=str(root),
                     timeout=60, errors="replace")
    except FileNotFoundError as exc:
        raise RuntimeError(f"mh 启动失败: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"mh new 超时: {exc}") from exc
    if proc.returncode != 0:
        # mh new 失败: 保留目录供诊断, 把 stderr 抛回调用方
        tail = (proc.stderr or "")[-_TAIL_BYTES:]
        raise RuntimeError(f"mh new 失败 (exit={proc.returncode}): {tail}")
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
# 后台 job (render / preview)
# ---------------------------------------------------------------------------

def _prune_jobs_locked() -> None:
    """调用方需持有 _JOBS_LOCK; 按 started_at 淘汰最老的 job 直到容量合规。"""
    if len(_JOBS) <= _JOB_CAP:
        return
    ordered = sorted(_JOBS.items(), key=lambda kv: kv[1].get("started_at", 0))
    for key, _job in ordered[: len(_JOBS) - _JOB_CAP]:
        _JOBS.pop(key, None)


def _kill_tree(proc: "subprocess.Popen[Any]") -> None:
    """杀掉进程树 (Windows 上 taskkill /T; 其他平台 terminate → kill)。"""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:  # noqa: BLE001 - 杀进程失败不再抛, 避免阻塞收尾
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _start_job(kind: str, argv: List[str], env: Dict[str, str], cwd: str,
               timeout: int, out_path: Optional[str] = None) -> str:
    """启动后台 job; 立即返回 job_id, 完成状态由 ``GET /api/mh/job?id=`` 轮询。"""
    job_id = uuid.uuid4().hex[:12]
    job: Dict[str, Any] = {
        "id": job_id,
        "kind": kind,
        "status": "running",
        "argv": list(argv),
        "out_path": out_path or "",
        "returncode": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "error": "",
        "started_at": time.time(),
        "finished_at": None,
        "timeout_sec": timeout,
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job
        _prune_jobs_locked()

    def _worker() -> None:
        stdout_tail = ""
        stderr_tail = ""
        returncode: Optional[int] = None
        error_msg = ""
        try:
            # Popen + communicate(timeout) → 超时 kill 树
            proc = Popen(argv, cwd=cwd, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         shell=False)
            try:
                out_b, err_b = proc.communicate(timeout=timeout)
                stdout_tail = (out_b or b"").decode("utf-8", errors="replace")[-_TAIL_BYTES:]
                stderr_tail = (err_b or b"").decode("utf-8", errors="replace")[-_TAIL_BYTES:]
                returncode = proc.returncode
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                try:
                    out_b, err_b = proc.communicate(timeout=10)
                except Exception:  # noqa: BLE001
                    out_b, err_b = b"", b""
                stdout_tail = (out_b or b"").decode("utf-8", errors="replace")[-_TAIL_BYTES:]
                stderr_tail = (err_b or b"").decode("utf-8", errors="replace")[-_TAIL_BYTES:]
                returncode = proc.returncode if proc.returncode is not None else -1
                error_msg = f"超时 ({timeout}s), 进程树已终止"
        except FileNotFoundError as exc:
            error_msg = f"mh 启动失败 (可执行文件不存在): {exc}"
            returncode = -1
        except Exception as exc:  # noqa: BLE001
            error_msg = f"执行异常: {exc}"
            returncode = -1

        with _JOBS_LOCK:
            cur = _JOBS.get(job_id)
            if cur is None:
                return
            cur["returncode"] = returncode
            cur["stdout_tail"] = stdout_tail
            cur["stderr_tail"] = stderr_tail
            cur["finished_at"] = time.time()
            if error_msg:
                cur["status"] = "error"
                cur["error"] = error_msg
            elif returncode == 0:
                cur["status"] = "done"
            else:
                cur["status"] = "error"
                cur["error"] = f"mh {kind} 失败 (exit={returncode})"

    thread = threading.Thread(target=_worker, daemon=True,
                              name=f"mh-{kind}-{job_id}")
    thread.start()
    return job_id


def render(project_dir: str, out_path: str, opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """后台 ``mh render <out.mp4>``; 返回 ``{job_id}``。

    opts 支持: ``fps`` (覆盖 mh.json.fps), ``codec`` (例如 ``h264``) —— 通过
    ``--fps`` / ``--codec`` 传给 mh; 其它键忽略。
    """
    res = resolve_mh()
    if not res.get("ok"):
        return {"ok": False, "error": res.get("reason") or "mh 不可用"}
    opts = opts or {}
    argv: List[str] = [res["mh_cmd"], "render", out_path]
    fps = opts.get("fps")
    if isinstance(fps, (int, float)) and not isinstance(fps, bool) and fps > 0:
        argv += ["--fps", str(fps)]
    codec = str(opts.get("codec") or "").strip()
    if codec and all(c.isalnum() or c in "-_" for c in codec):
        argv += ["--codec", codec]
    job_id = _start_job("render", argv, _child_env(res["node_dir"]),
                        project_dir, _RENDER_TIMEOUT_SEC, out_path=out_path)
    return {"ok": True, "job_id": job_id}


def preview(project_dir: str, times: List[float], contact_sheet: bool = False) -> Dict[str, Any]:
    """后台 ``mh preview --times '[...]' [--contact-sheet]``; 返回 ``{job_id}``。"""
    res = resolve_mh()
    if not res.get("ok"):
        return {"ok": False, "error": res.get("reason") or "mh 不可用"}
    safe_times: List[float] = []
    for t in (times or []):
        if isinstance(t, (int, float)) and not isinstance(t, bool):
            safe_times.append(float(t))
    if not safe_times:
        return {"ok": False, "error": "times 必须是非空数字数组"}
    times_json = json.dumps(safe_times)
    argv: List[str] = [res["mh_cmd"], "preview", "--times", times_json]
    if contact_sheet:
        argv.append("--contact-sheet")
    job_id = _start_job("preview", argv, _child_env(res["node_dir"]),
                        project_dir, _PREVIEW_TIMEOUT_SEC)
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
