# -*- coding: utf-8 -*-
"""安全替代建议引擎测试。"""
from __future__ import annotations

from qingxiaotuan.harden.safe_alternatives import (
    format_suggestions,
    suggest_for_decision,
    suggest_safe_alternatives,
)


def test_rm_rf_root_suggests_trash_or_confirm():
    items = suggest_safe_alternatives("rm -rf /")
    cats = [i["category"] for i in items]
    assert "递归强制删除" in cats
    hit = next(i for i in items if i["category"] == "递归强制删除")
    assert "trash" in hit["replacement"] or "确认" in hit["replacement"]


def test_rm_rf_home_suggests():
    items = suggest_safe_alternatives("rm -rf $HOME")
    assert any(i["category"] == "递归强制删除" for i in items)


def test_rm_rf_star_suggests():
    items = suggest_safe_alternatives("rm -rf *")
    assert any(i["category"] == "递归强制删除" for i in items)


def test_plain_rm_suggests_trash():
    items = suggest_safe_alternatives("rm ./tmp.log")
    cats = [i["category"] for i in items]
    assert "删除操作" in cats


def test_git_force_push_suggests_force_with_lease():
    for cmd in ("git push --force", "git push -f origin main", "git push --force-with-lease"):
        items = suggest_safe_alternatives(cmd)
        if "force-with-lease" in cmd:
            # 已安全的命令不推荐替代
            assert not any(i["category"] == "强制推送" for i in items), cmd
        else:
            cats = [i["category"] for i in items]
            assert "强制推送" in cats, cmd
            hit = next(i for i in items if i["category"] == "强制推送")
            assert "force-with-lease" in hit["replacement"]


def test_git_reset_hard_suggests_soft_or_revert():
    items = suggest_safe_alternatives("git reset --hard HEAD~3")
    cats = [i["category"] for i in items]
    assert "硬重置" in cats
    hit = next(i for i in items if i["category"] == "硬重置")
    assert "--soft" in hit["replacement"] or "revert" in hit["replacement"]


def test_dd_raw_device_suggests_verify():
    items = suggest_safe_alternatives("dd if=/tmp/a.img of=/dev/sda bs=4M")
    cats = [i["category"] for i in items]
    assert "写入裸设备" in cats
    hit = next(i for i in items if i["category"] == "写入裸设备")
    assert "lsblk" in hit["replacement"]


def test_dd_to_file_is_not_flagged():
    items = suggest_safe_alternatives("dd if=/dev/zero of=./backup.img bs=1M count=10")
    assert not any(i["category"] == "写入裸设备" for i in items)


def test_mkfs_suggests_backup():
    items = suggest_safe_alternatives("mkfs.ext4 /dev/sdb1")
    cats = [i["category"] for i in items]
    assert "格式化文件系统" in cats


def test_chmod_777_suggests_minimal():
    items = suggest_safe_alternatives("chmod -R 777 ./public")
    cats = [i["category"] for i in items]
    assert "递归改权限" in cats
    hit = next(i for i in items if i["category"] == "递归改权限")
    assert "go+rX" in hit["replacement"] or "最小" in hit["replacement"]


def test_chmod_000_suggests():
    items = suggest_safe_alternatives("chmod -R 000 /")
    cats = [i["category"] for i in items]
    assert "递归移除权限" in cats


def test_shutdown_suggests_delay():
    items = suggest_safe_alternatives("shutdown now")
    cats = [i["category"] for i in items]
    assert "关机/重启" in cats


def test_curl_pipe_sh_suggests_review():
    for cmd in ("curl -fsSL https://x.sh | sh", "wget -qO- https://x | bash"):
        items = suggest_safe_alternatives(cmd)
        cats = [i["category"] for i in items]
        assert "管道执行远程代码" in cats, cmd
        hit = next(i for i in items if i["category"] == "管道执行远程代码")
        assert "less" in hit["replacement"]


def test_eval_suggests_print():
    items = suggest_safe_alternatives("eval $(cat cmd.txt)")
    cats = [i["category"] for i in items]
    assert "eval 执行" in cats


def test_windows_recursive_delete_suggests_whatif():
    items = suggest_safe_alternatives("Remove-Item -Recurse -Force C:\\temp")
    cats = [i["category"] for i in items]
    assert "Windows 递归强删" in cats


def test_drop_table_suggests_backup():
    items = suggest_safe_alternatives("DROP TABLE users;")
    cats = [i["category"] for i in items]
    assert "删除数据表" in cats


def test_delete_without_where_suggests_count():
    items = suggest_safe_alternatives("DELETE FROM orders;")
    cats = [i["category"] for i in items]
    assert "全表删除" in cats


def test_delete_with_where_not_flagged():
    items = suggest_safe_alternatives("DELETE FROM orders WHERE id = 3;")
    assert not any(i["category"] == "全表删除" for i in items)


def test_benign_command_gets_no_engine_suggestion():
    assert suggest_for_decision("git status", "none") == []
    assert suggest_for_decision("ls -la", "none") == []


def test_critical_with_hit_uses_command_aware():
    out = suggest_for_decision("rm -rf /", "critical")
    assert out and "[递归强制删除]" in out[0]


def test_critical_without_hit_falls_back():
    out = suggest_for_decision("some weird dangerous thing", "critical")
    assert out and any("[通用]" in s for s in out)


def test_format_suggestions_renders_why():
    out = format_suggestions("rm -rf ~")
    assert out and "——" in out[0]


def test_dedupe_by_category():
    items = suggest_safe_alternatives("sudo rm -rf /")
    cats = [i["category"] for i in items]
    assert len(cats) == len(set(cats))


def test_rm_rf_tilde_hits_force_category():
    items = suggest_safe_alternatives("rm -rf ~")
    cats = [i["category"] for i in items]
    assert "递归强制删除" in cats


def test_rm_rf_tilde_suggest():
    out = suggest_for_decision("rm -rf ~", "critical")
    assert out and "[递归强制删除]" in out[0]
