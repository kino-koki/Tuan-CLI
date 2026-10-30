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
    is_benign_dev_command,
    is_hard_redline,
    is_redline,
)
from tuan_cli.ext.safety_engine import SafetyEngine
from tuan_cli.core.whitelist import get_warning_level

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


def test_benign_prefix_cannot_suppress_shared_risk_patterns():
    """危险模式先于 cat/mv 等日常命令前缀生效，且运行时警告级别共用评分规则。

    注意: cat ~/.ssh/id_rsa 的 SafetyEngine.score() 返回 high (不是 critical) ——
    读取凭证的危害低于写入/毁灭系统路径, 但 is_hard_redline() 独立返回 True 让
    IntentFilter / shell 安全闸门直接 DENY 凭证外泄 (不经过沙箱确认)。
    详见 safety_score.py 与 safety_redline.py 的 V-10 注释。
    """
    dangerous = [
        "mv /etc /tmp/backup",
        "userdel -r root",
        "chmod -R 777 /",
        "lvremove -y /dev/vg/lv",
        "wipefs -a /dev/sda",
        "sgdisk -Z /dev/sda",
        "vssadmin delete shadows /all /quiet",
    ]
    for command in dangerous:
        assert not is_benign_dev_command(command), command
        assert is_hard_redline(command), command
        assert _ENGINE.score({"command": command})["risk"] == "critical", command
        assert get_warning_level(command) == 5, command

    # 凭证外泄: 硬红线 = True 但 SafetyEngine risk = high (见 docstring)
    cmd_cred = "cat ~/.ssh/id_rsa"
    assert not is_benign_dev_command(cmd_cred), cmd_cred
    assert is_hard_redline(cmd_cred), cmd_cred
    assert _ENGINE.score({"command": cmd_cred})["risk"] == "high", cmd_cred

    assert is_benign_dev_command("echo 'chmod 777 / is dangerous'")
    assert _ENGINE.score({"command": "echo 'chmod 777 / is dangerous'"})["risk"] == "none"


def test_command_substitution_echo_output_is_analyzed():
    commands = [
        "rm$(echo ' -rf /')",
        "rm`echo ' -rf /'`",
        "rm$(printf ' %s' '-rf /')",
        "rm`printf '%b' '\\040-rf\\040/'`",
        "rm$(printf '%c' ' ' )-rf /",
        "echo $(rm -rf /)",
    ]
    for command in commands:
        assert not is_benign_dev_command(command), command
        assert is_hard_redline(command), command
        assert is_redline(command), command

    assert not is_redline("echo $(date)")
    assert not is_redline("echo $(grep 'rm -rf /' file.txt)")
    assert not is_redline("cat $(ls *.txt)")


def test_warning_level_reuses_shared_high_risk_severity():
    """warning_level 必须与共享打分库的 high 严重度一致 (high -> 3 次确认)。

    口径依据 (CHANGELOG 0.3.3「修复: `kill -9 <pid>` 与广播式 `pkill -9` 未分级」):
    - 定向 `kill -9 <pid>` (只杀一个已知进程) 降为 medium —— 信号操作不销毁数据;
    - 广播式强制信号 (`pkill -9` / `killall -9` 按名称杀全部同名进程) 与
      `kill -9 0|1` (整个进程组 / init) 保留 high —— 扩散面与不可恢复性高一个量级。

    本用例此前断言三条命令 (含定向 `kill -9 1234` 与不带 -9 的 `pkill -f worker`)
    全为 high, 属 10-24 批量导入时从未绿过的陈旧期望, 与上述刻意决策相反。
    """
    # 真正判 high 的广播式强制信号 -> warning_level 3
    for command in ("pkill -9 nginx", "killall -9 node", "kill -9 0"):
        assert _ENGINE.score({"command": command})["risk"] == "high", command
        assert get_warning_level(command) == 3, command

    # 定向终止 / 非强制信号 -> medium, 不走 3 次确认阶梯
    for command in ("kill -9 1234", "pkill -f worker", "killall worker"):
        assert _ENGINE.score({"command": command})["risk"] == "medium", command
        assert get_warning_level(command) == 0, command
