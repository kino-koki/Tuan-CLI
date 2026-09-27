# -*- coding: utf-8 -*-
"""qxt models update 本地目录层测试 (qingxiaotuan/models/local_catalog.py)。

覆盖: 内置导出 / 写读回环 / 缺失与损坏回退 / 合并保用户自建 / 后台刷新。
"""
import json

import pytest

from qingxiaotuan.models import local_catalog
from qingxiaotuan.models.provider_catalog import (
    ALL_PROVIDERS, PROVIDER_BY_NAME, presets_from_catalog,
)


def test_export_catalog_has_all_builtin(tmp_path):
    """导出目录覆盖全部内置供应商, schema 版本正确。"""
    data = local_catalog.export_catalog()
    assert data["schema_version"] == local_catalog.SCHEMA_VERSION
    assert len(data["providers"]) == len(ALL_PROVIDERS)
    assert len(data["model_lists"]) >= 16  # 至少 16 家维护了精选模型清单


def test_write_load_roundtrip(tmp_path):
    """写盘后可原样读回, 供应商与模型数一致。"""
    data = local_catalog.export_catalog()
    path = local_catalog.write_catalog(data, tmp_path)
    assert path == local_catalog.catalog_file(tmp_path)
    loaded = local_catalog.load_catalog(tmp_path)
    assert loaded is not None
    assert len(loaded["providers"]) == len(data["providers"])
    assert loaded["schema_version"] == local_catalog.SCHEMA_VERSION


def test_load_missing_returns_none(tmp_path):
    """无本地文件 -> None (调用方回退内置)。"""
    assert local_catalog.load_catalog(tmp_path) is None


def test_load_corrupt_returns_none(tmp_path):
    """损坏 JSON -> None, 不抛异常。"""
    (tmp_path / local_catalog.CATALOG_FILENAME).write_text(
        "{ not json", encoding="utf-8")
    assert local_catalog.load_catalog(tmp_path) is None
    # schema 版本不符也回退
    (tmp_path / local_catalog.CATALOG_FILENAME).write_text(
        json.dumps({"schema_version": 999, "providers": []}),
        encoding="utf-8")
    assert local_catalog.load_catalog(tmp_path) is None


def test_merge_preserves_user_additions(tmp_path):
    """合并: 内置为基线, 用户自建 provider 保留, 同名条目本地优先。"""
    builtin = local_catalog.export_catalog()
    local = {
        "schema_version": local_catalog.SCHEMA_VERSION,
        "generated_at": "",
        "providers": [
            # 用户自建
            {"name": "my-gateway", "base_url": "http://127.0.0.1:9999/v1",
             "model": "my-model", "api_key_env": "MY_KEY", "desc": "自建网关"},
            # 覆盖内置 deepseek 的 base_url
            {"name": "deepseek", "base_url": "http://127.0.0.1:8888/v1",
             "model": "deepseek-chat", "api_key_env": "DEEPSEEK_API_KEY",
             "desc": "本地代理"},
        ],
        "model_lists": {"my-gateway": ["my-model"], "deepseek": ["deepseek-chat", "deepseek-reasoner"]},
    }
    merged = local_catalog.merge_catalog(builtin, local)
    names = [p["name"] for p in merged["providers"]]
    assert "my-gateway" in names          # 用户自建保留
    assert "deepseek" in names
    dk = next(p for p in merged["providers"] if p["name"] == "deepseek")
    assert dk["base_url"] == "http://127.0.0.1:8888/v1"  # 本地同名优先
    assert merged["model_lists"]["my-gateway"] == ["my-model"]
    assert merged["model_lists"]["deepseek"] == ["deepseek-chat", "deepseek-reasoner"]


def test_refresh_creates_file_and_summary(tmp_path):
    """refresh_catalog 首次运行即建立本地文件, 返回 (供应商数, 模型数)。"""
    n_p, n_m = local_catalog.refresh_catalog(tmp_path)
    assert n_p == len(ALL_PROVIDERS)
    assert n_m > 0
    assert local_catalog.catalog_file(tmp_path).exists()


def test_refresh_keeps_user_edits(tmp_path):
    """已存在本地文件时, refresh 不丢用户自建条目。"""
    user_gw = {"name": "my-gw2", "base_url": "http://x/v1", "model": "m",
               "api_key_env": "K", "desc": "自建"}
    (tmp_path / local_catalog.CATALOG_FILENAME).write_text(
        json.dumps({"schema_version": local_catalog.SCHEMA_VERSION,
                    "generated_at": "", "providers": [user_gw],
                    "model_lists": {"my-gw2": ["m"]}}),
        encoding="utf-8")
    n_p, _ = local_catalog.refresh_catalog(tmp_path)
    loaded = local_catalog.load_catalog(tmp_path)
    names = [p["name"] for p in loaded["providers"]]
    assert "my-gw2" in names
    assert n_p == len(ALL_PROVIDERS) + 1


def test_diff_no_local(tmp_path):
    """无本地文件时 diff 报告缺失。"""
    d = local_catalog.diff_catalog(tmp_path)
    assert d["local_exists"] is False
    assert d["missing_providers"] == len(ALL_PROVIDERS)


def test_presets_from_catalog_roundtrip(tmp_path):
    """从本地目录重建的 ProviderPreset 与内置同构 (抽查字段)。"""
    data = local_catalog.export_catalog()
    presets = presets_from_catalog(data)
    assert len(presets) == len(ALL_PROVIDERS)
    dk = next(p for p in presets if p.name == "deepseek")
    assert dk.base_url == PROVIDER_BY_NAME["deepseek"].base_url
    assert dk.recommended_models == PROVIDER_BY_NAME["deepseek"].recommended_models


def test_presets_skip_broken_entries():
    """畸形条目跳过, 不抛异常。"""
    out = presets_from_catalog({"providers": [
        {"name": "ok", "base_url": "http://x/v1"},
        {"name": 123},
        "not-a-dict",
        {},
    ]})
    assert len(out) == 1
    assert out[0].name == "ok"


def test_background_refresh_completes(tmp_path):
    """后台刷新线程完成写盘 (join 后文件存在)。"""
    holder = {}

    def on_done(n_p, n_m, error=None):
        holder["done"] = (n_p, n_m, error)

    t = local_catalog.refresh_in_background(tmp_path, on_done=on_done)
    t.join(timeout=30)
    assert not t.is_alive()
    assert local_catalog.catalog_file(tmp_path).exists()
    assert "done" in holder
    n_p, n_m, err = holder["done"]
    assert err is None
    assert n_p == len(ALL_PROVIDERS)
