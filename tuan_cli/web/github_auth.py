# -*- coding: utf-8 -*-
"""GitHub OAuth 2.0 设备流 (RFC 8628) + 身份读取 —— 供 Web 工作台登录用。

设计要点:
  * 仅标准库 ``urllib.request`` 发网络请求, 短超时 + fail-closed (出错抛异常,
    绝不挂住请求线程)。
  * 设备流响应解析复用 ``tuan_cli.ports.oauth.error_classification`` 里的
    纯函数 (parse_device_authorization / classify_poll_result), 不重复造轮子。
  * token 不打日志、不进任何返回体; 只在本地 web_auth.json 里给当前用户自己用。

注意: GitHub 设备流需要一个已注册 OAuth App 的 client_id。constants.py 里默认
是占位符, 部署方通过环境变量 ``TUAN_GITHUB_CLIENT_ID`` 提供真实 client_id。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Optional

from ..ports.oauth.constants import GITHUB_DEVICE_FLOW_CONFIG
from ..ports.oauth.error_classification import (
    classify_poll_result,
    parse_device_authorization,
)
from ..ports.oauth.errors import OAuthError
from ..ports.oauth.types import DeviceAuthorization, TokenInfo

_GITHUB_API = "https://api.github.com"
_GITHUB_API_VERSION = "2022-11-28"
_USER_AGENT = "tuan_cli-web"
_HTTP_TIMEOUT = 10  # 秒: 设备流 + 身份接口都用短超时, 出错快速失败


# ================================================================ 底层 HTTP 封装

def _http_post_form(url: str, fields: Dict[str, str], timeout: int = _HTTP_TIMEOUT) -> Dict[str, Any]:
    """POST application/x-www-form-urlencoded, Accept JSON, 返回解析后的 JSON dict。

    非 2xx 或非 JSON 一律抛 :class:`OAuthError` (fail-closed)。
    """
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": _USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
    except urllib.error.HTTPError as exc:
        # GitHub 对错误 token 请求也会回 JSON 错误体, 这里读出来交给上层分类。
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except Exception as exc:  # noqa: BLE001 - 网络/DNS/TLS 层失败
        raise OAuthError(f"GitHub 设备流网络错误: {exc}") from exc
    return _decode_json(raw, status)


def _decode_json(raw: str, status: int) -> Dict[str, Any]:
    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise OAuthError(f"GitHub 返回非 JSON 响应 (HTTP {status})") from exc
    if not isinstance(data, dict):
        raise OAuthError(f"GitHub 返回非对象响应 (HTTP {status})")
    return data


def _http_get_json(url: str, token: str, timeout: int = _HTTP_TIMEOUT) -> Dict[str, Any]:
    """带 Bearer token 的 GET, 返回 JSON dict; 非 200 抛 :class:`OAuthError`。"""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
            "User-Agent": _USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
    except urllib.error.HTTPError as exc:
        raise OAuthError(f"GitHub API {url} 失败 (HTTP {exc.code})") from exc
    except Exception as exc:  # noqa: BLE001
        raise OAuthError(f"GitHub API 网络错误: {exc}") from exc
    if status != 200:
        raise OAuthError(f"GitHub API {url} 失败 (HTTP {status})")
    return _decode_json(raw, status)


# ================================================================ 设备流三步

def start_device_flow(config: Optional[Dict[str, str]] = None) -> DeviceAuthorization:
    """第 1 步: 向 GitHub 申请设备授权码 (user_code + verification_uri)。

    请求体只有 client_id + scope, 不在本函数里轮询 —— 轮询由 poll_for_token 负责。
    """
    cfg = config or GITHUB_DEVICE_FLOW_CONFIG
    payload = _http_post_form(
        cfg["device_code_url"],
        {"client_id": cfg["client_id"], "scope": "read:org"},
    )
    # 复用 ports/oauth 的解析 (校验 user_code/device_code/verification_uri 等必填字段)。
    try:
        return parse_device_authorization(payload)
    except OAuthError:
        # GitHub 缺少 verification_uri_complete 时的宽松回退 (该字段 RFC 8628 非强制)。
        return _device_auth_lenient(payload)


def _device_auth_lenient(data: Dict[str, Any]) -> DeviceAuthorization:
    raw_user_code = data.get("user_code")
    user_code = raw_user_code if isinstance(raw_user_code, str) else ""
    raw_device_code = data.get("device_code")
    device_code = raw_device_code if isinstance(raw_device_code, str) else ""
    raw_verification_uri = data.get("verification_uri")
    verification_uri = raw_verification_uri if isinstance(raw_verification_uri, str) else ""
    if not user_code or not device_code:
        raise OAuthError("GitHub 设备授权响应缺少 user_code/device_code")
    raw_expires = data.get("expires_in")
    expires_in = int(raw_expires) if isinstance(raw_expires, (int, float)) else None
    raw_interval = data.get("interval")
    interval = int(raw_interval) if isinstance(raw_interval, (int, float)) else 5
    return DeviceAuthorization(
        user_code=user_code,
        device_code=device_code,
        verification_uri_complete="",
        verification_uri=verification_uri,
        expires_in=expires_in,
        interval=interval,
    )


def _token_from_payload(payload: Dict[str, Any]) -> TokenInfo:
    """把 GitHub token 响应转成 TokenInfo。

    GitHub 设备流**不返回** refresh_token, 故不能直接用 ports/oauth 里严格要求
    refresh_token 的 parse_token_response; 这里只校验 access_token, 其余字段从缺。
    """
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthError("GitHub token 响应缺少 access_token")
    raw_expires_in = payload.get("expires_in")
    expires_in = int(raw_expires_in) if isinstance(raw_expires_in, (int, float)) else 0

    raw_scope = payload.get("scope")
    raw_token_type = payload.get("token_type")
    return TokenInfo(
        access_token=access_token,
        refresh_token="",
        expires_at=int(time.time()) + expires_in if expires_in else 0,
        scope=raw_scope if isinstance(raw_scope, str) else "",
        token_type=raw_token_type if isinstance(raw_token_type, str) else "bearer",
        expires_in=expires_in,
    )


def poll_for_token(
    device_auth: DeviceAuthorization,
    timeout: int = 300,
    on_interval: Optional[Callable[[int], None]] = None,
    config: Optional[Dict[str, str]] = None,
) -> TokenInfo:
    """第 2 步: 轮询 token 端点直到用户在浏览器里完成授权 / 超时 / 被拒。

    - 尊重 GitHub 返回的 ``interval`` 并处理 ``slow_down`` (每次 +5s)。
    - ``authorization_pending`` 继续等; ``expired_token`` / ``access_denied`` 终止。
    - 超过本地 wall-clock ``timeout`` 秒抛 :class:`OAuthError`。
    """
    cfg = config or GITHUB_DEVICE_FLOW_CONFIG
    interval = max(1, int(device_auth.interval or 5))
    deadline = time.monotonic() + timeout

    while True:
        if time.monotonic() >= deadline:
            raise OAuthError("GitHub 设备授权本地等待超时")
        if on_interval is not None:
            on_interval(interval)
        time.sleep(interval)

        payload = _http_post_form(
            cfg["token_url"],
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": cfg["client_id"],
                "device_code": device_auth.device_code,
            },
        )
        # 成功: 直接用 _token_from_payload (GitHub 无 refresh_token, 不能走严格解析)。
        if isinstance(payload.get("access_token"), str) and payload.get("access_token"):
            return _token_from_payload(payload)
        # 失败/等待: 借 classify_poll_result 分流 pending / expired / denied /
        # 未知错误。GitHub 错误回 200 + {"error"}, 需先映射到 classify 期望的 status。
        result = classify_poll_result(_error_status(payload), payload)
        if result.kind == "pending":
            if result.error_code == "slow_down":
                interval += 5  # RFC 8628 §3.5: slow_down 后本轮起 +5s
            continue
        if result.kind == "expired":
            raise OAuthError("GitHub 设备码已过期, 请重新发起登录")
        if result.kind == "denied":
            raise OAuthError("用户在 GitHub 上拒绝了授权")
        raise OAuthError(f"GitHub 设备流轮询失败: {result.error_code} {result.description}")


def _error_status(payload: Dict[str, Any]) -> int:
    """把 GitHub token 错误响应映射到一个能被 classify_poll_result 识别的 status。

    GitHub 设备流错误回 200 + {"error": "..."}, 而 classify_poll_result 期望
    非 200 的错误 status; 这里把已知错误码映射成 400, 让分类函数正确分流。
    """
    err = payload.get("error") if isinstance(payload.get("error"), str) else ""
    if err in ("authorization_pending", "slow_down", "expired_token", "access_denied"):
        return 400
    return 500  # 未知错误 → 触发 classify_poll_result 抛 OAuthError (含错误文本)


def poll_once(device_code: str, config: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """单次轮询 token 端点 (供 Web /api/auth/github/poll 用, 前端负责反复调用)。

    返回结构:
      * {"status": "pending"}          —— 用户还没输完码 (含 slow_down)
      * {"status": "ok", "token": ...} —— 授权成功, token 交上层建会话
      * {"status": "expired"}          —— device_code 过期, 前端需重新 start
      * {"status": "denied"}           —— 用户拒绝
    抛 OAuthError 表示未知/服务端错误 (上层回 500)。
    """
    cfg = config or GITHUB_DEVICE_FLOW_CONFIG
    payload = _http_post_form(
        cfg["token_url"],
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": cfg["client_id"],
            "device_code": device_code,
        },
    )
    if isinstance(payload.get("access_token"), str) and payload.get("access_token"):
        return {"status": "ok", "token": _token_from_payload(payload)}
    result = classify_poll_result(_error_status(payload), payload)
    if result.kind == "pending":
        return {"status": "pending"}
    if result.kind == "expired":
        return {"status": "expired"}
    if result.kind == "denied":
        return {"status": "denied"}
    raise OAuthError(f"GitHub 设备流轮询失败: {result.error_code} {result.description}")


def fetch_github_identity(token: str, include_orgs: bool = True) -> Dict[str, Any]:
    """第 3 步: 用 access_token 读当前用户身份 (login/id/name/avatar_url [+ orgs])。"""
    user = _http_get_json(f"{_GITHUB_API}/user", token)
    orgs: list = []
    if include_orgs:
        try:
            raw_orgs = _http_get_json(f"{_GITHUB_API}/user/orgs?per_page=100", token)
            if isinstance(raw_orgs, list):
                for o in raw_orgs:
                    if isinstance(o, dict) and isinstance(o.get("login"), str):
                        orgs.append(o["login"])
        except OAuthError:
            # orgs 读取失败不阻断登录 (token 可能没有 read:org 权限)。
            orgs = []
    return {
        "login": user.get("login") if isinstance(user.get("login"), str) else "",
        "id": user.get("id") if isinstance(user.get("id"), int) else 0,
        "name": user.get("name") if isinstance(user.get("name"), str) else "",
        "avatar_url": user.get("avatar_url") if isinstance(user.get("avatar_url"), str) else "",
        "orgs": orgs,
    }


__all__ = [
    "start_device_flow",
    "poll_for_token",
    "poll_once",
    "fetch_github_identity",
]
