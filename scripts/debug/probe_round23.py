"""round23: 容器逃逸 + WSL/Hyper-V + Linux capabilities + Windows UAC 绕过。"""
import sys
sys.path.insert(0, "g:/Tuan-CLI")
from tuan_cli.ext.safety_redline import is_hard_redline, is_redline
from tuan_cli.ext.safety_score import SafetyEngine

_engine = SafetyEngine()

def tier(cmd):
    if is_hard_redline(cmd):
        return "HARD"
    if is_redline(cmd):
        return "RED"
    r = _engine.score({"command": cmd})
    if str(r.get("risk", "")) in ("high", "critical", "extreme"):
        return "CONFIRM"
    return "ALLOW"

cases = [
    # ---- Linux capabilities 提权 (容器逃逸常见) ----
    ("capsh --print", "capsh print (枚举 caps, 良性)"),
    ("capsh --drop=cap_setuid -- -c id", "capsh drop (caps 操作)"),
    ("setcap cap_setuid+ep /bin/bash", "setcap (设置 cap_setuid 提权)"),
    ("getcap -r / 2>/dev/null | grep -i cap_setuid", "getcap (枚举 setuid 文件)"),
    # ---- Docker 逃逸手法 ----
    ("docker cp /etc/shadow container:/tmp/", "docker cp (复制敏感文件到容器)"),
    ("docker exec -it --privileged container sh", "docker exec privileged"),
    ("docker run --cap-add=SYS_ADMIN -v /:/mnt alpine", "docker cap-add SYS_ADMIN"),
    # ---- WSL / Hyper-V (Windows 虚拟化逃逸) ----
    ("wsl --exec bash -c 'cat /etc/shadow'", "wsl exec (WSL 内执行命令)"),
    ("wsl --import evil C:\\evil C:\\payload.tar --version 2", "wsl import (导入恶意 distro)"),
    ("powershell -c Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All", "enable hyper-v (提权启用虚拟化)"),
    ("vmconnect localhost 'Default Switch'", "vmconnect (连接 Hyper-V VM)"),
    # ---- Windows UAC 绕过 ----
    ("powershell -c Start-Process cmd -Verb runAs", "powershell runAs (UAC bypass)"),
    ("reg add HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System /v EnableLUA /t REG_DWORD /d 0 /f", "disable UAC via reg"),
    ("powershell -c [System.Diagnostics.Process]::Start('powershell.exe','-Verb runAs')", "dotnet process UAC"),
    # ---- 良性对照 (期望 ALLOW) ----
    ("capsh --print", "capsh info (benign)"),
    ("getcap /bin/su", "getcap single (benign)"),
    ("docker ps -a", "docker list (benign)"),
    ("wsl --list --verbose", "wsl list (benign)"),
    ("reg query HKCU\\Software\\Microsoft\\Windows\\CurrentVersion", "reg query (benign)"),
    ("powershell -c Get-Command wsl", "powershell getcmd (benign)"),
]

fails = 0
for cmd, intent in cases:
    t = tier(cmd)
    expect_allow = intent.endswith("(benign)")
    ok = (t == "ALLOW") if expect_allow else (t in ("HARD", "RED", "CONFIRM"))
    if not ok:
        fails += 1
    tag = "OK " if ok else ("FP " if expect_allow else "MISS")
    print(f"  {tag} [{t:7}] ({intent[:44]}) {cmd[:62]}")

print(f"\n  失败 {fails}/{len(cases)} (期望 0)")
