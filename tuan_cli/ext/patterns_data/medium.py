"""Medium-severity safety patterns (data only)."""

_MEDIUM_PATTERNS = [
    (r"sudo\s+", "超级用户权限"),
    (r">\s*/etc/", "写入系统配置"),
    (r"mv\s+.*/etc/", "移动系统文件"),
    # 服务管理
    (r"systemctl\s+(stop|disable)\s+\S+", "systemctl stop/disable (停止/禁用服务)"),
    (r"service\s+\S+\s+stop", "service stop (停止服务)"),
    # 进程管理
    # 注: kill -9 / pkill / killall 从 _HIGH_PATTERNS 下移至 medium —— 信号操作
    # 不会销毁数据, 破坏性远低于 chmod 777 / git reset --hard。仍需人工确认
    # (is_benign_dev_command 返回 False → 严格模式确认), 但不再触发多级确认。
    (r"\bkill\s+-9\b", "kill -9 (强制终止进程)"),
    (r"\bpkill\s+", "pkill (按名称终止进程)"),
    (r"\bkillall\s+", "killall (终止全部同名进程)"),
    # ---- Gap-2026-11h (round 11): 网络参数篡改 (转发/路由枢轴)。docker/k8s 常见, 列 medium 仅提示不拦截。
    (r"\bsysctl\b[^\n]*\s-w\b[^\n]*(?:ip_forward|net\.ipv4\.ip_forward|route|ip_forward)", 
     "sysctl network forwarding (启用 IP 转发/路由篡改, 渗透枢轴)"),
    # 日志写入: 覆盖/清空系统日志, 影响范围限于单个日志文件。
    # 只提示写 /var/log 根下的系统日志; 应用日志子目录 (/var/log/<app>/) 不打扰。
    (r"(?<!>)>\s*/var/log(?!/(?:[\w.-]+/))", "overwrite system log (覆盖/清空系统日志)"),
    # 权限变更
    (r"chmod\s+000\s+", "chmod 000 (移除所有权限)"),
    (r"chown\s+root\s+", "chown root (变更 root 所有权)"),
    # ---- round 11.1: 信号类毁灭补漏 ----
    # killall -9 -1 / pkill -9 -1 已提升到 _CRITICAL_PATTERNS (整机崩溃级)。
    # 下方通用 killall (无 -1 目标) 保持 medium: 终止同名进程需确认但非毁灭。
    # rsync --delete 规则已按危险目标 (根/系统目录) 提升到 _CRITICAL_PATTERNS,
    # 良性备份同步 (--delete /home/ /backup/) 不误杀。
]
