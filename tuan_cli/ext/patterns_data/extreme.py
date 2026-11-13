"""Extreme-severity safety patterns (data only)."""

_EXTREME_PATTERNS = [
    # 系统毁灭级: 删除根目录/主目录
    (r"rm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF]\s+(/|/~|\$HOME)", "rm -rf / (删除根目录)"),
    (r"rm\s+-[a-zA-Z]*[fF][a-zA-Z]*[rR]\s+(/|/~|\$HOME)", "rm -rf / (删除根目录)"),
    (r"rm\s+-rf\s+(/|/~|\$HOME)\b", "rm -rf / (删除根目录)"),
    (r"rm\s+-rf\s+/*", "rm -rf /* (递归删除全部文件)"),
    (r"rm\s+-rf\s+~", "rm -rf ~ (删除用户主目录)"),
    (r"rm\s+-rf\s+\$HOME", "rm -rf $HOME (删除用户主目录)"),
    # 磁盘/文件系统级破坏
    (r"dd\s+if=.*\s+of=/dev/(sd[a-z]|nvme\d+n\d+(p\d+)?|vd[a-z]|hd[a-z])\b",
     "dd write to raw disk (直接写磁盘设备, 含 NVMe/virtio/IDE)"),
    (r"mkfs\..*", "mkfs (格式化文件系统)"),
    (r"format\s+[a-zA-Z]:", "format disk (格式化磁盘)"),
    # 系统关机/重启
    (r"shutdown\s+(-h|-s|now|/s)", "shutdown (系统关机)"),
    (r"reboot\b", "reboot (系统重启)"),
    # 权限全灭 + 递归
    (r"chmod\s+-[Rr]\s+0{3,}\s+/", "chmod -R 000 / (递归移除所有权限)"),
    (r"chown\s+-[Rr]\s+root\s+/", "chown -R root / (递归变更 root 所有权)"),
    # Fork 炸弹
    (r":\(\s*\|\s*:\s*&", "fork bomb (Fork 炸弹)"),
    # Windows 递归强删
    (r"remove-item\s+.*-recurse.*-force.*[a-zA-Z]:\\\\", "Remove-Item -Recurse -Force C:\\ (Windows 递归强删)"),
    (r"rd\s+/s\s+/q\s+[a-zA-Z]:\\\\", "rd /s /q C:\\ (Windows 递归强删)"),
]
