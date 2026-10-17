"""safety 引擎红队自查回归测试 (第四轮, 2026-10-06)。

本文件固化一轮「自己红队自己」发现的真实缺口, 防止回退:
1. P0 口径不一致: score() 此前未复用 is_hard_redline(), 导致
   `python -c "os.system('rm -rf /')"` / `ln -sf /dev/null /etc/passwd` 等
   在 is_redline 下为危险、在 score() (IPC 引擎入口) 下却是 none。
2. 新型绕过载荷 (不在既有 2310 条矩阵内):
   - Ruby/PHP/Node-require 的文件删除 API
   - blkdiscard 丢弃块设备
   - dd 写 LVM/device-mapper/disk-by-id 裸设备 (非 sd/nvme)
   - dd 经反斜杠续行 (backslash-newline) 跨行书写
   - PowerShell Remove-Item 旗标顺序无关 / Get-ChildItem -Recurse | Remove-Item
   - GNU sed e 标志 (s///e) 与 e 命令
   - 写入 ~/.ssh/authorized_keys 持久化后门
   - 编辑器 shell 逃逸 (vim -c '!cmd')

同时保证新增模式不误伤常见良性开发命令。
"""
from tuan_cli.ext.safety_engine import (
    is_hard_redline,
    is_redline,
)
from tuan_cli.ext.safety_engine import SafetyEngine

_ENGINE = SafetyEngine()


# ------------------------------------------------ 1. score() / is_redline() 口径统一
def test_score_agrees_with_is_redline_on_hard_redlines():
    """凡是 is_redline 判危险者, score() 不得给出 none (IPC 入口不得弱于护栏)。"""
    commands = [
        "python -c \"import os;os.system('rm -rf /')\"",
        "perl -e 'unlink \"/etc/passwd\"'",
        "ln -sf /dev/null /etc/passwd",
        "shutdown -h now",
        "powershell -enc cgBtACAALQByAGYAIAAvAA==",
        "node -e \"require('fs').rmSync('/',{recursive:true,force:true})\"",
        "printf '%s' 'cm0gLXJmIC8=' | base64 -d | sh",
    ]
    for cmd in commands:
        assert is_redline(cmd), f"is_redline 应命中: {cmd!r}"
        risk = _ENGINE.score({"command": cmd})["risk"]
        assert risk != "none", f"score() 不得为 none (口径不一致): {cmd!r} -> {risk}"


def test_score_block_flag_true_for_hard_redline():
    for cmd in ("rm -rf /", "ln -sf /dev/null /etc/passwd"):
        res = _ENGINE.score({"command": cmd})
        assert res["block"] is True, f"{cmd!r} 应 block=True"
        assert res["risk"] == "critical"


# ------------------------------------------------ 2. 新型绕过载荷 (red-team round 4)
# critical 级: 应同时命中 is_redline 与 is_hard_redline
_HARD_BYPASS_PAYLOADS = [
    ("ruby File.delete", "ruby -e 'File.delete(\"/etc/passwd\")'"),
    ("ruby Dir.rmdir", "ruby -e 'Dir.rmdir(\"/tmp/x\")'"),
    ("php unlink", "php -r 'unlink(\"/etc/passwd\");'"),
    ("perl unlink glob", "perl -e 'unlink glob(\"/etc/*\")'"),
    ("node require fs.rmSync", "node -e \"require('fs').rmSync('/',{recursive:true,force:true})\""),
    ("blkdiscard", "blkdiscard /dev/sda"),
    ("dd to lvm mapper", "dd if=/dev/zero of=/dev/mapper/vg0-root"),
    ("dd to disk/by-id", "dd if=/dev/zero of=/dev/disk/by-id/nvme-eui.0001"),
    ("dd backslash continuation", "dd if=/dev/zero \\\nof=/dev/sda"),
    ("Remove-Item flags swapped", "Remove-Item C:\\ -Force -Recurse"),
    ("Get-ChildItem pipe Remove-Item", "Get-ChildItem C:\\ -Recurse | Remove-Item -Force"),
    ("authorized_keys append", "echo 'ssh-rsa AAAA' >> ~/.ssh/authorized_keys"),
    ("authorized_keys tee", "echo 'ssh-rsa AAAA' | tee ~/.ssh/authorized_keys"),
    ("vim shell escape", "vim -c '!rm -rf /' file.txt"),
]

# high 级: 与既有 `| sh` 同类 (执行汇), 应被 score 判 >= high, 但不升级为硬红线
_HIGH_BYPASS_PAYLOADS = [
    ("sed s///e", "sed 's/x/rm -rf \\//e' file.txt"),
    ("sed e command", "sed 'e rm -rf /' file.txt"),
]


def test_hard_bypass_payloads_are_hard_redline():
    for name, payload in _HARD_BYPASS_PAYLOADS:
        assert is_redline(payload), f"[{name}] is_redline 应命中: {payload!r}"
        assert is_hard_redline(payload), f"[{name}] is_hard_redline 应命中: {payload!r}"


def test_all_bypass_payloads_score_at_least_high():
    for name, payload in _HARD_BYPASS_PAYLOADS + _HIGH_BYPASS_PAYLOADS:
        risk = _ENGINE.score({"command": payload})["risk"]
        assert risk in ("high", "critical"), f"[{name}] score 风险应 >= high, 实得 {risk}"


# ------------------------------------------------ 3. 不误伤良性命令
_BENIGN_COMMANDS = [
    "sed -n '1,10p' file.txt",
    "sed -e 's/foo/bar/' file.txt",
    "sed 's/x/y/g' file.txt",
    "grep -rn 'rm -rf' src/",
    "echo 'rm -rf / is dangerous'",
    "ls -la",
    "git status",
    "python -m pytest tests/",
    "node -e \"console.log(require('fs').readFileSync('a.txt'))\"",
    "vim -c ':wq' file.txt",
    "docker ps",
    "kubectl get pods",
]


def test_new_patterns_do_not_break_benign():
    for cmd in _BENIGN_COMMANDS:
        assert not is_redline(cmd), f"良性命令不应命中红线: {cmd!r}"
        assert not is_hard_redline(cmd), f"良性命令不应命中硬红线: {cmd!r}"
        assert _ENGINE.score({"command": cmd})["risk"] == "none", \
            f"良性命令 score 应为 none: {cmd!r}"
