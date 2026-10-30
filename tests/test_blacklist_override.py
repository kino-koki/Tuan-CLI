"""专项测试: core.blacklist_override —— 用户本地黑名单减负。

覆盖:
  - _override_path / _load_raw / _load_suppressed
  - suppressed_labels / is_suppressed (label 关键字匹配)
  - suppress / release / list_suppressed
  - reset_cache (内存缓存失效)
"""

from __future__ import annotations

import json
import pytest

import tuan_cli.core.blacklist_override as bo


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """每个测试隔离: 覆盖 home_dir 指向临时目录 + 重置缓存。"""
    monkeypatch.setattr(bo, "home_dir", lambda: tmp_path)
    bo.reset_cache()
    yield
    bo.reset_cache()


class TestPathAndLoad:
    def test_override_path_points_to_home(self, tmp_path):
        assert bo._override_path() == tmp_path / "blacklist-override.json"

    def test_load_raw_empty_when_missing(self, tmp_path):
        assert bo._load_raw() == {}

    def test_load_raw_parses_json(self, tmp_path):
        (tmp_path / "blacklist-override.json").write_text(
            json.dumps({"suppressed": ["dd"]}), encoding="utf-8"
        )
        assert bo._load_raw() == {"suppressed": ["dd"]}

    def test_load_raw_corrupt_returns_empty(self, tmp_path):
        (tmp_path / "blacklist-override.json").write_text("not json", encoding="utf-8")
        assert bo._load_raw() == {}


class TestSuppressed:
    def test_suppressed_labels_cached(self, tmp_path):
        (tmp_path / "blacklist-override.json").write_text(
            json.dumps({"suppressed": ["dd", "  rm  "]}) or "{}", encoding="utf-8"
        )
        assert bo.suppressed_labels() == {"dd", "rm"}

    def test_is_suppressed_exact_match(self, tmp_path):
        (tmp_path / "blacklist-override.json").write_text(
            json.dumps({"suppressed": ["dd"]}), encoding="utf-8"
        )
        assert bo.is_suppressed("dd") is True

    def test_is_suppressed_substring_match(self, tmp_path):
        (tmp_path / "blacklist-override.json").write_text(
            json.dumps({"suppressed": ["write raw device"]}), encoding="utf-8"
        )
        # 关键字出现在 label 中 → 命中
        assert bo.is_suppressed("write raw device /dev/sda") is True

    def test_is_suppressed_empty_label(self, tmp_path):
        assert bo.is_suppressed("") is False

    def test_is_suppressed_no_match(self, tmp_path):
        (tmp_path / "blacklist-override.json").write_text(
            json.dumps({"suppressed": ["dd"]}), encoding="utf-8"
        )
        assert bo.is_suppressed("git push --force") is False


class TestMutate:
    def test_suppress_adds_and_saves(self, tmp_path):
        assert bo.suppress("dd") is True
        assert bo.suppressed_labels() == {"dd"}
        raw = json.loads((tmp_path / "blacklist-override.json").read_text(encoding="utf-8"))
        assert raw["suppressed"] == ["dd"]
        assert raw["version"] == 1

    def test_suppress_duplicate_returns_false(self, tmp_path):
        bo.suppress("dd")
        assert bo.suppress("dd") is False

    def test_suppress_empty_returns_false(self, tmp_path):
        assert bo.suppress("   ") is False

    def test_release_removes(self, tmp_path):
        bo.suppress("dd")
        bo.suppress("rm")
        assert bo.release("dd") is True
        assert bo.suppressed_labels() == {"rm"}

    def test_release_missing_returns_false(self, tmp_path):
        assert bo.release("nope") is False

    def test_list_suppressed_sorted(self, tmp_path):
        bo.suppress("z")
        bo.suppress("a")
        assert bo.list_suppressed() == ["a", "z"]

    def test_reset_cache_forces_reload(self, tmp_path):
        # 通过 _load_raw 直接触发首次加载 (缓存填充)
        bo.suppressed_labels()  # 空 → 缓存已加载 (cache_loaded=True)
        # 手工塞入缓存后, 直接改盘不会刷新 (缓存命中)
        bo._suppressed_cache.add("dd")
        bo._cache_loaded = True
        raw = json.loads((tmp_path / "blacklist-override.json").read_text(encoding="utf-8")) if (tmp_path / "blacklist-override.json").exists() else {}
        raw["suppressed"] = ["rm"]
        (tmp_path / "blacklist-override.json").write_text(json.dumps(raw), encoding="utf-8")
        assert bo.suppressed_labels() == {"dd"}  # 缓存命中, 未重读
        bo.reset_cache()
        assert bo.suppressed_labels() == {"rm"}  # 重读


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-p", "no:cacheprovider"]))
