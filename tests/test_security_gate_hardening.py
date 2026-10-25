"""SecurityGate 加固回归测试 (v0.3.2 五模式改造配套)。

覆盖 decide_file_write 的三类加固:

1. **内容硬红线** —— 写入内容命中 is_hard_redline 直接拒绝, 与 decide_shell
   step1 口径一致; 拒绝原因明确标注「硬红线」便于审计定位。
2. **扩展敏感路径** —— _SYSTEM_PATH_RE 补充 /root /opt /system 等 Linux 目录,
   Windows Program Files / Program Files (x86) / ProgramData / WinSxS / System32
   目录, 以及家庭目录常见凭据文件 (id_rsa / .npmrc / .gitconfig 等)。
3. **路径注入防御** —— null byte 剔除, Windows 保留设备名 (NUL / CON / COM1-9 /
   LPT1-9) 拒绝, realpath 穿透 symlink 使 ./link -> .ssh/ 也命中敏感路径。

所有测试都验证 fail-closed 语义: **加严不改宽**, 原有判定保持不变, 普通
工作区路径仍放行。
"""
import os
import tempfile

import pytest

from tuan_cli.core.workspace_trust import TrustLevel
from tuan_cli.ext.security_gate import SecurityGate


# ============================================================
# 1. 内容硬红线 (is_hard_redline 前置判定)
# ============================================================


def test_gate_file_write_content_hard_redline_rm_rf_root():
    """内容含 rm -rf / 命中硬红线, 直接拒绝 (不允许 confirm 放行)。"""
    v = SecurityGate().decide_file_write("a.sh", "rm -rf /")
    assert v.blocks()
    assert v.severity == "critical"
    assert any("硬红线" in r for r in v.reasons)


def test_gate_file_write_content_hard_redline_dd():
    """内容含 dd if=/dev/zero of=/dev/sda 命中硬红线。"""
    v = SecurityGate().decide_file_write("a.sh", "dd if=/dev/zero of=/dev/sda")
    assert v.blocks()
    assert any("硬红线" in r for r in v.reasons)


def test_gate_file_write_content_hard_redline_mkfs():
    """内容含 mkfs.ext4 命中硬红线。"""
    v = SecurityGate().decide_file_write("a.sh", "mkfs.ext4 /dev/sda1")
    assert v.blocks()
    assert any("硬红线" in r for r in v.reasons)


def test_gate_file_write_content_hard_redline_force_push():
    """内容含 git push --force 命中硬红线。"""
    v = SecurityGate().decide_file_write("a.sh", "git push --force")
    assert v.blocks()
    assert any("硬红线" in r for r in v.reasons)


def test_gate_file_write_content_soft_redline_sql():
    """内容含 SQL DROP 命中软红线 (is_redline), 但非硬红线, 原因文案不重复。"""
    v = SecurityGate().decide_file_write("backup.sql", "DROP TABLE users")
    assert v.blocks()
    assert v.severity == "critical"
    # 走 is_redline 分支, 原因不含「硬红线」文案
    assert not any("硬红线" in r for r in v.reasons)


def test_gate_file_write_benign_content_allowed():
    """良性内容不受影响, 原判定保留。"""
    v = SecurityGate().decide_file_write("a.txt", "hello world")
    assert v.allows()


# ============================================================
# 2. 扩展敏感路径 (_SYSTEM_PATH_RE 口径扩展)
# ============================================================


def test_gate_file_write_linux_root_path():
    """/root 命中敏感路径。"""
    v = SecurityGate().decide_file_write("/root/.bashrc", "x")
    assert v.needs_confirm()


def test_gate_file_write_linux_opt_path():
    """/opt 命中敏感路径。"""
    v = SecurityGate().decide_file_write("/opt/app/config", "x")
    assert v.needs_confirm()


def test_gate_file_write_linux_system_path():
    """/system 命中敏感路径。"""
    v = SecurityGate().decide_file_write("/system/etc/init.d/foo", "x")
    assert v.needs_confirm()


def test_gate_file_write_win_program_files():
    """Windows Program Files 命中敏感路径。"""
    v = SecurityGate().decide_file_write("C:\\Program Files\\app\\bin", "x")
    assert v.needs_confirm()


def test_gate_file_write_win_program_files_x86():
    """Windows Program Files (x86) 命中敏感路径。"""
    v = SecurityGate().decide_file_write("C:\\Program Files (x86)\\app", "x")
    assert v.needs_confirm()


def test_gate_file_write_win_programdata():
    """Windows ProgramData 命中敏感路径。"""
    v = SecurityGate().decide_file_write("C:\\ProgramData\\app", "x")
    assert v.needs_confirm()


def test_gate_file_write_win_system32():
    """Windows System32 命中敏感路径。"""
    v = SecurityGate().decide_file_write("C:\\Windows\\System32\\drivers\\etc\\hosts", "x")
    assert v.needs_confirm()


def test_gate_file_write_win_winxs():
    """Windows WinSxS 命中敏感路径。"""
    v = SecurityGate().decide_file_write("C:\\Windows\\WinSxS\\foo", "x")
    assert v.needs_confirm()


def test_gate_file_write_win_no_drive_letter_still_matches():
    """不带盘符的 Windows 敏感目录 (相对形态) 仍命中。"""
    # 模拟 shell 内拼接的相对路径, 段级匹配应能捕获
    v = SecurityGate().decide_file_write("./Program Files/app", "x")
    assert v.needs_confirm()


def test_gate_file_write_credential_id_rsa():
    """家庭目录 id_rsa 命中敏感路径。"""
    v = SecurityGate().decide_file_write("~/id_rsa", "x")
    assert v.needs_confirm()


def test_gate_file_write_credential_id_ed25519():
    """家庭目录 id_ed25519 命中敏感路径。"""
    v = SecurityGate().decide_file_write("id_ed25519.pub", "x")
    assert v.needs_confirm()


def test_gate_file_write_credential_npmrc():
    """.npmrc 命中敏感路径。"""
    v = SecurityGate().decide_file_write("./.npmrc", "x")
    assert v.needs_confirm()


def test_gate_file_write_credential_pypirc():
    """.pypirc 命中敏感路径。"""
    v = SecurityGate().decide_file_write("./.pypirc", "x")
    assert v.needs_confirm()


def test_gate_file_write_credential_netrc():
    """.netrc 命中敏感路径。"""
    v = SecurityGate().decide_file_write("./.netrc", "x")
    assert v.needs_confirm()


def test_gate_file_write_credential_gitconfig():
    """.gitconfig 命中敏感路径。"""
    v = SecurityGate().decide_file_write("./.gitconfig", "x")
    assert v.needs_confirm()


# ============================================================
# 3. 路径注入防御
# ============================================================


def test_gate_file_write_null_byte_blocked():
    """路径含 null byte 直接拒绝 (注入攻击特征)。"""
    v = SecurityGate().decide_file_write("evil.txt\x00.bak", "x")
    assert v.blocks()
    assert v.severity == "critical"
    assert any("null byte" in r for r in v.reasons)


def test_gate_file_write_null_byte_mid_path_blocked():
    """路径中间的 null byte 也拒绝。"""
    v = SecurityGate().decide_file_write("/tmp\x00/evil.txt", "x")
    assert v.blocks()


def test_gate_file_write_win_device_nul_blocked():
    """Windows 保留设备名 NUL 拒绝。"""
    v = SecurityGate().decide_file_write("NUL", "x")
    assert v.blocks()
    assert v.severity == "high"


def test_gate_file_write_win_device_con_blocked():
    """Windows 保留设备名 CON (带扩展名) 拒绝。"""
    v = SecurityGate().decide_file_write("CON.txt", "x")
    assert v.blocks()


def test_gate_file_write_win_device_com1_blocked():
    """Windows 保留设备名 COM1 拒绝。"""
    v = SecurityGate().decide_file_write("COM1", "x")
    assert v.blocks()


def test_gate_file_write_win_device_lpt1_blocked():
    """Windows 保留设备名 LPT1 拒绝。"""
    v = SecurityGate().decide_file_write("LPT1.log", "x")
    assert v.blocks()


def test_gate_file_write_win_device_case_insensitive():
    """Windows 保留设备名大小写不敏感。"""
    assert SecurityGate().decide_file_write("nul", "x").blocks()
    assert SecurityGate().decide_file_write("Prn", "x").blocks()
    assert SecurityGate().decide_file_write("aux.log", "x").blocks()


def test_gate_file_write_win_device_non_reserved_allowed():
    """非保留设备名不拦截 (COM10 及以上不是 Windows 保留设备名)。"""
    v = SecurityGate().decide_file_write("COM10", "x")
    assert v.allows()


def test_gate_file_write_symlink_resolved_to_sensitive(tmp_path):
    """realpath 穿透 symlink, 使 ./link -> .ssh/ 也命中敏感路径。"""
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    link = tmp_path / "link"
    try:
        os.symlink(str(ssh_dir), str(link))
    except OSError:
        pytest.skip("symlink not supported on this platform")
    # 通过 symlink 写入, realpath 会解析到 .ssh/ 命中敏感路径
    v = SecurityGate().decide_file_write(str(link), "x")
    assert v.needs_confirm()


# ============================================================
# 4. 回归: 原有判定不变 (加严不改宽)
# ============================================================


def test_gate_file_write_original_system_paths_still_confirmed():
    """原有 /etc /var/log 等系统路径判定不变。"""
    g = SecurityGate()
    assert g.decide_file_write("/etc/hosts", "x").needs_confirm()
    assert g.decide_file_write("/var/log/app.log", "x").needs_confirm()
    assert g.decide_file_write("./.ssh/config", "x").needs_confirm()
    assert g.decide_file_write(".ssh/authorized_keys", "x").needs_confirm()
    assert g.decide_file_write("sub/.aws/credentials", "x").needs_confirm()
    assert g.decide_file_write("./sub/../.gnupg/gpg.conf", "x").needs_confirm()


def test_gate_file_write_original_normal_workspace_still_allowed():
    """原有普通工作区路径仍放行。"""
    v = SecurityGate().decide_file_write("src/main.py", "x")
    assert v.allows()


def test_gate_file_write_original_redline_content_still_denied():
    """原有内容红线判定不变。"""
    assert SecurityGate().decide_file_write("a.sh", "rm -rf /").blocks()


def test_gate_file_write_yolo_still_upgrades_sensitive():
    """YOLO 模式下敏感路径仍需确认 (加严不改宽)。"""
    g = SecurityGate(yolo=True)
    assert g.decide_file_write("/etc/hosts", "x").needs_confirm()
    assert g.decide_file_write("C:\\Program Files\\app", "x").needs_confirm()
    # 硬红线内容即使在 YOLO 下也拒绝
    assert g.decide_file_write("a.sh", "rm -rf /").blocks()
    # null byte / 设备名与 YOLO 无关, 一律拒绝
    assert g.decide_file_write("NUL", "x").blocks()
    assert g.decide_file_write("evil\x00.txt", "x").blocks()


def test_gate_file_write_untrusted_still_denied():
    """UNTRUSTED 工作区仍拒绝所有文件写入 (原判定不变)。"""
    g = SecurityGate(trust_level=TrustLevel.UNTRUSTED)
    assert g.decide_file_write("a.txt", "x").blocks()
