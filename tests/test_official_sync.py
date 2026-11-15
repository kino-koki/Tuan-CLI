"""tuan_cli/models/official_sync.py 测试 (联网同步各供应商官方模型清单)。

覆盖: _parse_models 各官方响应 schema 归一 / is_stale 到期判断 /
sync_models_online 成功合并与失败降级 (monkeypatch registry._fetch_json)。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

import pytest

from tuan_cli.models import local_catalog, official_sync


# ---------------------------------------------------------------- _parse_models


def test_parse_models_models_list_of_dict():
    """openai 风格 {'models': [{'id': 'a'}, {'id': 'b'}]} -> ['a','b']。"""
    data = {"models": [{"id": "lfm-2.5-2.6b"}, {"id": "lfm-2.5-30b-a3b"}]}
    assert official_sync._parse_models(data, {"parse": "models[].id"}) == [
        "lfm-2.5-2.6b", "lfm-2.5-30b-a3b"]


def test_parse_models_data_list_of_dict():
    """openai_responses 风格 {'data': [{'id': 'x'}]} -> ['x']。"""
    data = {"data": [{"id": "sakana-namazu"}]}
    assert official_sync._parse_models(data, {"parse": "data[].id"}) == ["sakana-namazu"]


def test_parse_models_plain_string_list():
    """纯字符串列表 (如 data[])。"""
    data = {"data": ["m1", "m2"]}
    assert official_sync._parse_models(data, {"parse": "data[]"}) == ["m1", "m2"]


def test_parse_models_non_dict_returns_empty():
    assert official_sync._parse_models([], {"parse": "data[].id"}) == []
    assert official_sync._parse_models(None, {"parse": "data[].id"}) == []


def test_parse_models_missing_key_returns_empty():
    assert official_sync._parse_models({"foo": []}, {"parse": "data[].id"}) == []


def test_parse_models_skips_non_str_id():
    data = {"data": [{"id": "ok"}, {"id": 123}, "plain", {"no_id": 1}]}
    assert official_sync._parse_models(data, {"parse": "data[].id"}) == ["ok", "plain"]


# ---------------------------------------------------------------- is_stale


def test_is_stale_no_catalog(tmp_path):
    """无本地目录 -> 视为过期 (应同步)。"""
    assert official_sync.is_stale(home=tmp_path) is True


def test_is_stale_fresh(tmp_path):
    """generated_at 为当前时间 -> 未过期。"""
    from datetime import datetime, timezone
    local_catalog.refresh_catalog(tmp_path)
    data = local_catalog.load_catalog(tmp_path)
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    local_catalog.write_catalog(data, tmp_path)
    assert official_sync.is_stale(home=tmp_path) is False


def test_is_stale_old(tmp_path):
    """generated_at 为 8 天前 -> 过期。"""
    from datetime import datetime, timedelta, timezone
    local_catalog.refresh_catalog(tmp_path)
    data = local_catalog.load_catalog(tmp_path)
    data["generated_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    local_catalog.write_catalog(data, tmp_path)
    assert official_sync.is_stale(home=tmp_path) is True


def test_is_stale_bad_ts(tmp_path):
    """无法解析的时间 -> 视为过期。"""
    local_catalog.refresh_catalog(tmp_path)
    data = local_catalog.load_catalog(tmp_path)
    data["generated_at"] = "not-a-timestamp"
    local_catalog.write_catalog(data, tmp_path)
    assert official_sync.is_stale(home=tmp_path) is True


def test_is_stale_force_max_age_zero():
    assert official_sync.is_stale(max_age=0) is True


# ------------------------------------------------------- sync_models_online


def _make_fake_fetch(payload):
    """构造 registry._fetch_json 的替身: 返回固定 payload dict。"""
    def fake(url, *, ttl_seconds=3600):
        return payload
    return fake


def test_sync_online_success_merges(tmp_path, monkeypatch):
    """成功拉取 -> 合并进 local_catalog.model_lists, 保留 |free/|paid 标注。"""
    monkeypatch.setattr(
        "tuan_cli.ecosystem.registry._fetch_json",
        _make_fake_fetch({"models": [{"id": "lfm-2.5-2.6b"}, {"id": "lfm-2.5-30b-a3b"}]}),
    )
    # 预置旧清单 (带标注) 验证标注保留
    local_catalog.refresh_catalog(tmp_path)
    data = local_catalog.load_catalog(tmp_path)
    data["model_lists"]["liquid"] = ["lfm-2.5-2.6b|free"]
    local_catalog.write_catalog(data, tmp_path)

    results = official_sync.sync_models_online(home=tmp_path)
    summary = results.pop("_summary")
    assert summary["ok"] == len(official_sync.OFFICIAL_MODEL_ENDPOINTS)
    assert results["liquid"]["ok"] is True
    assert results["liquid"]["count"] == 2

    loaded = local_catalog.load_catalog(tmp_path)
    assert "lfm-2.5-2.6b|free" in loaded["model_lists"]["liquid"]  # 旧标注保留
    assert "lfm-2.5-30b-a3b|paid" in loaded["model_lists"]["liquid"]


def test_sync_online_failure_keeps_existing(tmp_path, monkeypatch):
    """拉取失败 (None/异常) -> 跳过该供应商, 保留既有清单, 不覆盖为空。"""
    monkeypatch.setattr("tuan_cli.ecosystem.registry._fetch_json", _make_fake_fetch(None))
    results = official_sync.sync_models_online(home=tmp_path)
    summary = results.pop("_summary")
    assert summary["ok"] == 0
    for provider, r in results.items():
        assert r["ok"] is False, f"{provider} 应失败"


def test_sync_online_empty_payload_skips(tmp_path, monkeypatch):
    """响应非对象 / 空 -> 跳过, 不写坏。"""
    monkeypatch.setattr("tuan_cli.ecosystem.registry._fetch_json", _make_fake_fetch({"data": []}))
    results = official_sync.sync_models_online(home=tmp_path)
    summary = results.pop("_summary")
    assert summary["ok"] == 0
    assert all(not r["ok"] for r in results.values())
