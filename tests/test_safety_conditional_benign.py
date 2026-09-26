"""条件良性判定回归测试: chmod/chown/systemctl/service 不允许无条件判良。

背景 (P0 修复): chmod/chown/systemctl/service 曾是无条件良性前缀, 导致
`chmod -R 000 /` 被降级为 none、`systemctl stop nginx` 漏掉 medium,
与 is_redline/score 的口径严重不一致。现改为条件良性:
- chmod/chown: 不命中任何 critical/high/medium 模式才判良;
- systemctl: 仅只读子命令 (status/show/list-*/is-*/cat/help/daemon-reload/get-default/version) 判良;
- service: 仅 status / --status-all 判良。
本文件固化该语义, 防止未来回归。
"""

from __future__ import annotations

from qingxiaotuan.ext.safety_engine import (
    SafetyEngine,
    is_benign_dev_command,
    is_hard_redline,
    is_redline,
)


def _score(cmd: str) -> str:
    return SafetyEngine().score({"command": cmd})["risk"]


# ------------------------------------------------------------ chmod / chown 良性形态
def test_chmod_benign_forms():
    ok = [
        "chmod +x deploy.sh",
        "chmod 644 README.md",
        "chmod -R 755 /home/user/app",
        "chmod a+x scripts/*.sh",
        "chmod u+rwx,g+rx,o+r file.txt",
        "chmod --reference=other.txt target.txt",
    ]
    for cmd in ok:
        assert is_benign_dev_command(cmd), f"chmod 良性形态被误判: {cmd!r}"
        assert _score(cmd) == "none", f"chmod 良性形态被升级: {cmd!r} -> {_score(cmd)}"


def test_chown_benign_forms():
    ok = [
        "chown user:group file.txt",
        "chown kino src/",
        "chown -R user:group /home/user/proj",
    ]
    for cmd in ok:
        assert is_benign_dev_command(cmd), f"chown 良性形态被误判: {cmd!r}"
        assert _score(cmd) == "none"


# ------------------------------------------------------------ chmod / chown 危险形态
def test_chmod_destructive_never_benign():
    bad = [
        "chmod -R 000 /",
        "chmod -r 000 /",
        "chmod -R 0000 /",
        "chmod 777 /etc/passwd",
        "chmod u+s /bin/bash",
        "chmod -x /usr/bin/ssh",
    ]
    for cmd in bad:
        assert not is_benign_dev_command(cmd), f"chmod 危险形态被误判良性: {cmd!r}"


def test_chmod_destructive_scores_match_redline():
    assert _score("chmod -R 000 /") == "critical"
    assert is_redline("chmod -R 000 /")
    assert is_hard_redline("chmod -R 000 /")
    assert _score("chmod 000 /tmp/secret") == "medium"
    assert _score("chmod -R 777 /var/www") == "high"
    assert _score("chmod u+s /bin/bash") == "critical"


def test_chown_destructive_scores():
    assert not is_benign_dev_command("chown -R root /")
    assert _score("chown -R root /") == "critical"
    assert is_redline("chown -R root /")
    assert not is_benign_dev_command("chown root /var/data")
    assert _score("chown root /var/data") == "medium"


# ------------------------------------------------------------ systemctl
def test_systemctl_readonly_benign():
    ok = [
        "systemctl status nginx",
        "systemctl show nginx",
        "systemctl list-units",
        "systemctl list-timers",
        "systemctl is-active nginx",
        "systemctl is-enabled sshd",
        "systemctl cat nginx",
        "systemctl help",
        "systemctl daemon-reload",
        "systemctl get-default",
        "sudo systemctl status nginx",
    ]
    for cmd in ok:
        assert is_benign_dev_command(cmd), f"systemctl 只读形态被误判: {cmd!r}"
        assert _score(cmd) == "none"


def test_systemctl_mutating_never_benign():
    bad = [
        "systemctl stop nginx",
        "systemctl disable sshd",
        "systemctl restart nginx",
        "systemctl start nginx",
        "systemctl enable docker",
        "systemctl mask docker",
        "systemctl unmask docker",
        "systemctl poweroff",
        "systemctl reboot",
        "systemctl halt",
        "sudo systemctl restart nginx",
    ]
    for cmd in bad:
        assert not is_benign_dev_command(cmd), f"systemctl 变更形态被误判良性: {cmd!r}"


def test_systemctl_scores():
    assert _score("systemctl stop nginx") == "medium"
    assert _score("systemctl disable sshd") == "medium"
    assert _score("systemctl mask docker") == "high"
    assert _score("systemctl restart nginx") == "none"  # 无模式命中, 靠严格模式确认兜底


# ------------------------------------------------------------ 解释器内联载荷穿透 (node/JS 包裹)
def test_interpreter_wrapper_inner_command_caught():
    """P0 回归: node -e \"require('child_process').execSync('CMD')\" 等解释器包裹,
    内层 CMD 无论是否带 child_process. 字面前缀, 都必须被检出 —— 不得因良性前缀
    `node ` 在 _segment_is_benign 短路放行。

    此前 require('child_process').execSync(...) 因 `child_process.` 字面前缀消失,
    逃过 _INTERP_PAYLOAD_API_RE (需 child_process\\.execSync 锚定), 又被 `node ` 良性
    前缀放行, 形成绕过 (systemctl mask / crontab -r / iptables -F / chmod 777 等
    高危子命令经 node 包裹后漏放)。
    """
    caught = [
        "node -e \"require('child_process').execSync('systemctl mask sshd')\"",
        "node -e \"require('child_process').execSync('crontab -r')\"",
        "node -e \"require('child_process').execSync('iptables -F')\"",
        "node -e \"require('child_process').execSync('chmod -R 777 /etc')\"",
        "node -e \"child_process.exec('rm -rf /')\"",
        "node -e \"const cp=require('child_process');cp.execSync('fallocate -l 100G /bigfile')\"",
        "echo ok; node -e \"require('child_process').execSync('systemctl mask sshd')\"",
    ]
    for cmd in caught:
        assert not is_benign_dev_command(cmd), f"解释器包裹的内层危险命令被误放良: {cmd!r}"
        caught_by = is_hard_redline(cmd) or is_redline(cmd) or _score(cmd) != "none"
        assert caught_by, f"解释器包裹内层危险命令未被任何层检出: {cmd!r}"

    # 良性内层命令保持放行 (不得误杀 node 日常调用)
    benign = [
        "node -e \"console.log(1+1)\"",
        "node myscript.js",
        "node -e \"const x=require('fs').readFileSync('a.txt');console.log(x)\"",
        "python -c \"print(1)\"",
    ]
    for cmd in benign:
        assert is_benign_dev_command(cmd) or _score(cmd) == "none", \
            f"良性解释器命令被误拦截: {cmd!r}"



# ------------------------------------------------------------ service
def test_service_readonly_benign():
    ok = [
        "service nginx status",
        "service --status-all",
        "service ssh status",
    ]
    for cmd in ok:
        assert is_benign_dev_command(cmd), f"service 只读形态被误判: {cmd!r}"
        assert _score(cmd) == "none"


def test_service_mutating_never_benign():
    bad = [
        "service nginx stop",
        "service nginx start",
        "service nginx restart",
        "service nginx reload",
    ]
    for cmd in bad:
        assert not is_benign_dev_command(cmd), f"service 变更形态被误判良性: {cmd!r}"
    assert _score("service nginx stop") == "medium"


# ------------------------------------------------------------ 组合与分段
def test_chmod_benign_chain_with_destructive_segment_not_benign():
    assert not is_benign_dev_command("chmod +x a.sh && rm -rf /")
    assert not is_benign_dev_command("systemctl status nginx; systemctl stop nginx")


def test_redline_score_consistency_holds():
    """is_redline 与 score critical 口径一致 (本次回归的核心不变量)。"""
    eng = SafetyEngine()
    for cmd in ["chmod -R 000 /", "chown -R root /", "systemctl poweroff",
                "systemctl reboot", "systemctl halt"]:
        assert (eng.score({"command": cmd})["risk"] == "critical") == is_redline(cmd), cmd
