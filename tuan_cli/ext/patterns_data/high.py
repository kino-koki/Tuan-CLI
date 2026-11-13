"""High-severity safety patterns (data only)."""

_HIGH_PATTERNS = [
    # 远程访问通道停用 = 服务器被锁在门外 (有控制台可恢复, 故列 high 而非 critical)。
    # 修复前 `systemctl stop sshd` 只落到 medium 的通用「停止服务」兜底, 实际判 allow,
    # 随机种子真实场景基准里反复漏放。`systemctl` 是「动作在前」, `service` 是
    # 「服务名在前」, 两种语序都要覆盖。
    (r"\b(?:systemctl)\s+(?:stop|disable|mask)\b[^\n]*\b(?:sshd?|ssh[-_]?server|openssh)\b",
     "stop ssh service (停用 SSH, 远程访问被锁死)"),
    (r"\bservice\s+(?:sshd?|ssh[-_]?server|openssh)\s+(?:stop|disable|halt)\b",
     "service ssh stop (停用 SSH, 远程访问被锁死)"),
    # round 18: service 停防火墙/安全模块 (语序: 服务名在前)。
    (r"\bservice\s+(?:iptables|firewalld|ufw|nftables|auditd|apparmor|selinux|clamav|fail2ban)\s+(?:stop|disable)\b",
     "service stop firewall/security (停用防火墙/安全模块, 削弱防护)"),
    # round 18: kill -STOP 1 (冻结 init/PID 1, 整机失控)。
    # SIGSTOP(-STOP) 冻结 1 号进程与 SIGKILL 同级破坏, 但 -STOP 形态不被 killall -9 -1 抓到。
    (r"\bkill\b[^\n]*-(?:STOP|SIGSTOP)\b[^\n]*\b1\b",
     "kill -STOP 1 (冻结 init/PID1, 整机失控)"),
    (r"\bkill\b[^\n]*-1\b[^\n]*-(?:STOP|SIGSTOP)\b",
     "kill -STOP 1 (冻结 init/PID1, 整机失控)"),
    # round 18: sed -i 就地篡改审计日志 (反取证, 覆盖攻击痕迹)。
    (r"\bsed\b[^\n]*-i\b[^\n]*/var/log/(?:auth|secure|syslog|messages|audit)",
     "sed -i audit log (就地篡改审计日志, 反取证)"),
    (r"\bsed\b[^\n]*-i\b[^\n]*/var/adm/(?:wtmp|btmp|lastlog|utmp)",
     "sed -i login records (就地篡改登录记录, 反取证)"),
    (r"\b(?:usermod|chsh)\b[^\n]*\s-(?:s|shell)\b[^\n]*\s/(?:usr/)?(?:s?bin/(?:nologin|false))\b",
     "nologin shell (把账户切成不可登录)"),
    # 注: rm 递归强删已升级为 critical (见 has_recursive_rm), 不再列在 high。
    # 注: kill -9 / pkill / killall 已从本表下移至 _MEDIUM_PATTERNS (见其处注释) ——
    # 信号操作不会销毁数据, 不具 chmod 777 同级的扩散破坏性。
    # 例外: **按名称广播 + 强制信号**的组合仍留在 high。`pkill -9 nginx` 会一次性
    # SIGKILL 掉所有同名进程 (可能含关键服务), 风险比定向 `kill -9 <pid>` 高一档。
    (r"chmod\b[^\n]*\b777\b", "chmod 777 (全权限修改)"),
    (r"\b(?:pkill|killall)\b[^\n]*(?:\s-\s*(?:9|KILL|SIGKILL)\b|\s--signal\s+(?:9|KILL|SIGKILL)\b)",
     "pkill -9 (按名称强制终止全部同名进程)"),
    # `kill -9 0` 打到调用者的整个进程组, `kill -9 1` 打 init/systemd —— 都是广播形态,
    # 与定向 `kill -9 1234` 不同档。
    (r"\bkill\b[^\n]*(?:-\s*(?:9|KILL|SIGKILL)|--signal\s+(?:9|KILL|SIGKILL))[^\n]*\s(?:0|1)\b",
     "kill -9 0/1 (强杀整个进程组或 init)"),
    # ---- Gap-2026-11h (round 11): 提权/服务/网络配置类 (确认旗标, 可恢复运维不硬拦) ----
    # usermod -aG sudo/wheel/admin/root: 把账户加入特权组 = 权限提升。属运维常规, 列 high 确认。
    (r"\busermod\b[^\n]*\s-[a-zA-Z]*G[a-zA-Z]*\b[^\n]*(?:sudo|wheel|admin|root|docker|shadow|operator)",
     "usermod -aG privilege group (把账户加入特权组, 权限提升)"),
    # ---- round 19: SSH 隧道持久化 / 反向隧道 (绕过防火墙暴露内网服务) ----
    (r"\bssh\b[^\n]*\s-[A-Za-z]*[RD][A-Za-z]*\s", "ssh -R/-D tunnel (SSH 反向/动态隧道, 绕过防火墙暴露内网)"),
    (r"\bautossh\b", "autossh (自动重连 SSH 隧道, 持久化暴露内网)"),
    # ---- round 19: 网络嗅探 / MITM 工具 (拦截/篡改网络流量) ----
    (r"\b(?:ettercap|arpspoof|dsniff|webspy|urlsnarf|filesnarf)\b",
     "MITM tool (ARP 欺骗/中间人攻击工具)"),
    (r"\bmitmproxy\b|\bmitmdump\b", "mitmproxy (中间人代理, 拦截/篡改 HTTPS)"),
    (r"\btcpdump\b", "tcpdump (网络流量嗅探)"),
    # systemctl enable --now <unit>: 注册并立即启动服务 (持久化)。仅 enable 不启动, 列 high 确认。
    (r"\bsystemctl\b[^\n]*\benable\b[^\n]*--now\b", "systemctl enable --now (注册并启动自启动服务, 持久化)"),
    # ip link set <if> down / ifconfig <if> down: 切断网络接口 = 远程管理被锁死 (可恢复)。
    (r"\b(?:ip\s+link\s+set|ifconfig)\b[^\n]*\bdown\b", "network interface down (停用网络接口, 远程管理被锁死)"),
    # route add default / ip route add default: 替换默认网关 = 流量重定向 (中间人劫持)。
    (r"\b(?:route\s+add|ip\s+route\s+add)\b[^\n]*(?:default|0\.0\.0\.0/0)", "route add default (修改默认路由, 流量劫持)"),
    # update-rc.d disable/remove 关键服务 (SSH/网络): 关闭开机自启 = 远程管理被锁死 (可恢复)。
    # `update-rc.d ssh disable` 与 `update-rc.d disable ssh` 两种语序都要覆盖 → 顺序无关双 lookahead。
    (r"\bupdate-rc\.d\b(?=[^\n]*\b(?:disable|remove)\b)(?=[^\n]*\b(?:ssh|sshd|network|networking|openssh)\b)",
     "update-rc.d disable (关闭服务开机自启, 远程管理被锁死)"),
    # ---- Gap-2026-11i (round 12): 启动链/安全组件/模块加载类 (确认旗标, 可恢复或运维常规) ----
    # 启动引导篡改 (grub/efibootmgr): 改默认引导项/引导顺序 = 启动接管 (可恢复, 列 high)。
    (r"\b(?:grub-set-default|grub-mkconfig|grub-reboot)\b", "grub boot config (修改引导配置, 启动接管)"),
    # kexec -l/--load 仅加载新内核 (未执行): 列 high 确认; -e/--exec 执行已列 critical。
    (r"\bkexec\b[^\n]*(?:-l\b|--load\b)", "kexec load (加载新内核, 未立即执行)"),
    (r"\befibootmgr\b[^\n]*(?:-o\b|-n\b|-O\b|-N\b)", "efibootmgr boot order (修改 EFI 引导顺序)"),
    # 安全组件禁用 (AppArmor/fail2ban/防火墙规则移除): 削弱主机防护 (可恢复, 列 high)。
    (r"\baa-(?:disable|teardown)\b", "aa-disable (禁用 AppArmor 配置文件, 削弱防护)"),
    (r"\bfail2ban-client\b[^\n]*\bstop\b", "fail2ban-client stop (停止暴力破解防护)"),
    (r"\bfirewall-cmd\b[^\n]*--permanent\b[^\n]*(?:--remove-service|--remove-port|--remove-rich-rule)",
     "firewall-cmd remove rule (移除防火墙规则, 削弱防护)"),
    # modprobe 加载内核模块 (正常驱动加载, 列 high 确认; insmod 指定文件已列 critical)。
    # 注: --showconfig / -c 是只读配置转储, 不加载模块, 豁免确认。
    (r"\bmodprobe\b(?!\s+(?:--showconfig\b|-c\b))", "modprobe (加载内核模块)"),
    # psexec 远程命令执行 (横向移动/远程 RCE, 运维/红队双用, 列 high 确认)。
    (r"\bpsexec(?:\.exe)?\b", "psexec (远程命令执行, 横向移动)"),
    # 分离终端运行 shell (后台持久化, 一般形态列 high; -i 交互式已列 critical)。
    (r"\b(?:screen|tmux)\b[^\n]*-[A-Za-z]*d[A-Za-z]*\b[^\n]*\b(?:bash|sh|zsh|python\d*|perl|/bin/)",
     "detached shell (分离终端运行 shell, 后台持久化)"),
    # ---- Gap-2026-11j (round 13): 容器内执行/部署/隧道类 (确认旗标) ----
    # 进入容器执行 shell (运维调试也常用, 列 high 确认): docker/podman exec / kubectl exec。
    (r"\b(?:docker|podman)\s+exec\b[^\n]*\b(?:bash|sh|/bin/)", "container exec shell (进入容器执行 shell)"),
    (r"\bkubectl\s+exec\b[^\n]*(?:bash|sh|/bin/)", "kubectl exec shell (进入 Pod 执行 shell)"),
    # kubectl run 部署工作负载 / docker pull 拉取镜像 / docker commit 提交 (创建/获取运行载荷, 列 high 确认)。
    (r"\bkubectl\s+run\b[^\n]*--image\b", "kubectl run image (部署容器工作负载)"),
    (r"\b(?:docker|podman)\s+pull\b", "docker pull (拉取镜像, 供应链风险)"),
    (r"\b(?:docker|podman)\s+commit\b", "docker commit (提交容器为镜像, 可能嵌入后门)"),
    # ssh -W 连接转发 (隧道原语, 用于内网穿透/枢轴, 列 high 确认)。
    (r"\bssh\b[^\n]*-W\b", "ssh -W tunnel (ssh 连接转发隧道, 内网穿透)"),
    # ---- Gap-2026-11k (round 14): awk 命令执行原语 (确认旗标; 危险载荷由 critical 独立命中) ----
    (r"\bawk\b[^\n]*\bsystem\s*\(", "awk system (awk 执行命令, 命令执行原语)"),
    # ---- Gap-2026-11l (round 15): PATH 劫持 (把可疑目录前置到 PATH, 可恢复/运维常规, 列 high) ----
    (r"\bPATH\s*=\s*[^\n]*(?:/(?:tmp|var/tmp|dev/shm|home)\b|~/)[^\n]*", "PATH hijack (PATH 含可疑目录, 命令劫持)"),
    # ---- Gap-2026-11m (round 16): rclone/aws 同步目录到远端 (备份/同步双用, 列 high 确认) ----
    (r"\brclone\b[^\n]*(?:copy\b|sync\b|move\b)", "rclone sync remote (rclone 同步到远端, 数据外泄风险)"),
    (r"\baws\s+s3\s+(?:cp|sync)\b[^\n]*s3://", "aws s3 upload (上传到 S3, 数据外泄风险)"),
    (r"git\s+reset\s+--hard", "git reset --hard (硬重置)"),
    (r"ALTER\s+TABLE\s+.*\s+DROP", "alter table drop column (修改表结构删除列)"),
    (r"UPDATE\s+.*\s+SET.*WHERE.*=", "bulk update (批量更新数据)"),
    # 管道到 shell 解释器执行 (仅当 | 后紧跟解释器时才算, 避免 `ps | grep bash` 误匹配)
    (r"\|\s*(?:sh|bash|zsh|ksh|fish|dash|ash|csh|tcsh|python\d*|perl|ruby|node|php|lua|powershell|pwsh|cmd)\b",
     "pipe to shell (管道到 shell 执行)"),
    # V-10: tar 归档通过管道送到远端 ssh (打包整个工作区外泄)。
    # 原 ssh remote exec 一刀切 high 规则被移除后, 此条补位数据外泄检测。
    # 不需要敏感路径关键词 —— 打包 `.` / `*` 本身就是外泄。
    # 修复良性备份误杀: 只在目标端含**敏感路径** (/etc|shadow|passwd|etc) 或打包当前/整个系统 (.
    # / *) 时判 high; `tar czf - ./docs | ssh backup 'cat > b.tar.gz'`(显式路径的备份) 放行。
    (r"\btar\b[^\n]*\|\s*ssh\b(?=[^\n]*(?:/etc\b|/etc/|/root/|shadow|passwd|id_rsa|\.aws|\$\(cat|/var/log|~))",
     "tar pipe to ssh secret (敏感归档通过 SSH 管道外泄)"),
    # 通配/无路径打包: tar c . | ssh / tar czf - * | ssh (打包整个目录树, 含隐含敏感)
    (r"\btar\s+(?:[a-z]+)?\s*[-]?[a-zA-Z]*f?\s*-?\s*[.]\s*\|", "tar pipe dot (打包当前目录全部经 ssh 外泄)"),
    # 管道 split 后, `ssh host tar xf -` 独立出现 —— 在远端接收管道数据并写入文件系统。
    # 也覆盖 `ssh host 'tar xf -'` / `ssh host tar xzf -` / `dd | ssh host dd of=...` 等。
    (r"\bssh\b(?:\s+-[A-Za-z0-9]+(?:\s+\S+)?)*\s+[A-Za-z0-9_.@:-]+\s+(?:tar\s+[xzf]+|dd\s+of=)",
     "ssh remote untar/dd (SSH 远端接收管道数据并写入文件)"),
    # GNU sed 的 e 标志 / e 命令会把替换结果或其后文本当 shell 命令执行
    # (sed 's/x/rm -rf \//e' / sed 'e rm -rf /'), 与 | sh 同级的执行汇。
    # 替换串/模式里允许转义分隔符 (\\. 覆盖 `\/`), 否则 `s/x/rm -rf \//e` 会漏判。
    (r"\bsed\b[^\n]*\bs/(?:\\.|[^/\\\n])*/(?:\\.|[^/\\\n])*/[0-9gpI]*e",
     "sed s///e (GNU sed 执行替换结果)"),
    (r"\bsed\b[^\n]*['\"][^'\"]*\be\s+(?:rm|sh|bash|curl|wget|mkfs|dd)\b",
     "sed e command (GNU sed 执行 shell 命令)"),
    # Git 丢弃未暂存/未跟踪的变更 (不可逆)
    (r"git\s+clean\s+-[a-zA-Z]*f", "git clean -f (删除未跟踪文件)"),
    (r"git\s+checkout\s+--\s+\.", "git checkout -- . (丢弃所有工作区变更)"),
    # 容器/K8s 资源强删
    (r"docker\s+rm\s+-f", "docker rm -f (强制删除容器)"),
    (r"docker\s+rmi\s+-f", "docker rmi -f (强制删除镜像)"),
    (r"kubectl\s+delete", "kubectl delete (删除 K8s 资源)"),
    # tar 解包到系统目录 (覆盖/投毒系统文件): 仅 `-C` 目标是绝对系统路径时命中,
    # 相对路径 (-C ./build) 不命中, 避免开发场景误报。
    (r"\btar\b[^\n]*\s-[a-zA-Z]*C\s*(?:/(?:etc|usr|bin|sbin|lib|boot|sys|proc|dev|var)\b|/)",
     "tar 解包到系统目录 (覆盖系统文件)"),
    # 网络/防火墙
    (r"iptables\s+-F", "iptables -F (清空防火墙规则)"),
    (r"(?:ufw|firewalld)\s+(?:disable|delete|stop)\b",
     "ufw/firewalld disable (关闭防火墙)"),
    # 计划任务 / 文件清空 / 服务屏蔽 (不可逆或影响面大)
    (r"crontab\s+-r", "crontab -r (删除全部定时任务)"),
    (r"truncate\s+-s\s+0", "truncate to zero (清空文件)"),
    (r"systemctl\s+(mask|unmask)", "systemctl mask/unmask (屏蔽/恢复服务)"),
    # 写入计划任务目录 (cp/mv/install/ln 的末操作数 / >或tee 重定向目标 → /etc/cron*)。
    # 安全修复: 要求 cron 路径位于"目标位置"(行尾)或经重定向/tee —— 否则会把
    # `cp /etc/crontab /tmp/backup`(读取备份) 也误判为持久化写入。
    (r"\b(?:cp|mv|install|ln)\b[^\n]*\s/etc/cron\S*\s*$",
     "write cron drop-in (写入计划任务目录, 持久化)"),
    (r"(?:>+\s*|tee\s+)\s*/etc/cron\S*",
     "write cron drop-in (写入计划任务目录, 持久化)"),
    # 注: `> /var/log` 日志写入不在 high 档 —— 它只作用于单个日志文件, 不具
    # chmod 777 / git reset --hard 同级的扩散性破坏, 已移至 _MEDIUM_PATTERNS。
    # 旧规则把 `echo started >> /var/log/myapp/app.log` 这类应用日志追加判成 high,
    # 是过度升级 (实测误杀 10k 基准)。
    # Git 不可逆变体
    (r"git\s+push\b[^\n]*--delete", "git push --delete (删除远程分支)"),
    (r"git\s+branch\b[^\n]*\s-[Dd]\b", "git branch -D (强制删除分支)"),
    (r"git\s+stash\b[^\n]*\bdrop\b", "git stash drop (丢弃暂存)"),
    (r"git\s+rebase\b[^\n]*--onto", "git rebase --onto (改写历史)"),
    # 资源耗尽 / 死循环
    (r"while\s+true\b", "infinite loop (资源耗尽)"),
    (r"\byes\b[^\n]*>\s*/dev/null", "yes to /dev/null (资源耗尽)"),
    # 磁盘填满 / 炸弹
    (r"\bdd\b[^\n]*\bof=(?!/dev/(?:sd|nvme|vd|hd))", "dd write to file (可能填满磁盘)"),
    (r"\bfallocate\b[^\n]*-[lL]\s+\d+[GM]", "fallocate large (填满磁盘)"),
    (r"/dev/urandom\s*>", "urandom redirect (填满磁盘)"),
    # 痕迹清除
    (r"\bhistory\s+-c\b", "history -c (清除命令历史)"),
    (r"\bunset\b[^\n]*HISTFILE", "unset HISTFILE (禁用历史)"),
    # 读取敏感凭证 / 密钥文件
    # 文本处理动词一并覆盖: awk/sed/grep/tee/sort/uniq/xargs/cut/tr 都能把密钥
    # 内容读出或重定向到别处 (`awk {print} ~/.ssh/id_rsa > /tmp/x` 是真实外泄)。
    # `tee` 尤其危险 —— 它一边显示一边写文件。
    (r"\b(?:cat|tac|less|more|head|tail|nl|bat|type|awk|sed|grep|egrep|fgrep|zgrep"
     r"|tee|sort|uniq|cut|tr|paste|join|xargs|wc|xsl|csvlook)\b"
     r"[^\n]*(?:/etc/shadow|/etc/passwd|~?/\.ssh/|~?/\.aws/|id_rsa|\.env\b|/\.aws/credentials)",
     "read sensitive file (读取敏感凭证/密钥)"),
    # Git 不可逆变体 (扩展): 删除标签 / 清空全部 reflog
    (r"\bgit\s+tag\b[^\n]*\s-[dD]\b", "git tag -d (删除标签)"),
    (r"\bgit\s+reflog\s+expire\b[^\n]*--all\b", "git reflog expire --all (清空引用日志)"),
    # 移除不可变标志 (破坏防篡改保护)
    (r"\bchattr\s+-i\b", "chattr -i (移除不可变标志)"),
    # Windows 管理类 (破坏性但运维常见, 提升至 flag 确认而非硬拦截)
    (r"\bschtasks\b[^\n]*/delete\b", "schtasks delete (删除计划任务)"),
    (r"\bsc\b[^\n]*(?:stop|delete)\b", "sc stop/delete (停止或删除服务)"),
    (r"\bicacls\b[^\n]*/grant\b", "icacls /grant (篡改 ACL 权限)"),
    # K8s 缩容到零 / 暂停工作负载 (等于业务全停, 需人工确认)
    (r"\bkubectl\s+scale\b[^\n]*--replicas[=\s]+0\b",
     "kubectl scale --replicas=0 (缩容至零, 业务中断)"),
    (r"\bkubectl\s+(?:cordon|taint)\b", "kubectl cordon/taint (封锁节点)"),
    # ---- PowerShell / Windows 高危操作 (需确认) ----
    # 下载可执行文件落地
    (r"(?:Invoke-WebRequest|\biwr\b)[^\n]*-OutFile[^\n]*\.(?:exe|ps1|bat|cmd|dll|msi|vbs|js|scr)",
     "Invoke-WebRequest -OutFile exe (下载可执行落地)"),
    # WebClient 下载 (DownloadFile/DownloadString)
    (r"(?:\bDownloadFile\b|\bDownloadString\b)", "WebClient DownloadFile/DownloadString (下载)"),
    # 关闭 Windows 防火墙
    (r"Set-NetFirewallProfile[^\n]*-Enabled\s+False",
     "Set-NetFirewallProfile -Enabled False (关闭防火墙)"),
    (r"netsh[^\n]*(?:advfirewall|firewall)[^\n]*(?:state\s+off|opmode\s+disable|\bset\b[^\n]*(?:off|disable))",
     "netsh firewall off (关闭防火墙)"),
    # 关闭 Windows 更新 / 停用关键服务
    (r"Set-Service[^\n]*-StartupType\s+Disabled", "Set-Service -StartupType Disabled (停用服务)"),
    (r"Stop-Service[^\n]*-Force", "Stop-Service -Force (强制停用服务)"),
    # 新建本地用户 / 服务
    (r"\bNew-LocalUser\b", "New-LocalUser (新建本地用户)"),
    (r"\bNew-Service\b", "New-Service (新建服务)"),
    (r"\bsc(?:\.exe)?\s+create\b", "sc create (创建服务)"),
    # 强制结束进程
    (r"\bStop-Process\b[^\n]*(?:-Force|-Id\b)", "Stop-Process -Force/-Id (结束进程)"),
    (r"\btaskkill\b[^\n]*/[fF]", "taskkill /F (强制结束进程)"),
    # 隐藏窗口 / 启动可执行 (可疑进程)
    (r"Start-Process[^\n]*(?:-WindowStyle\s+Hidden|-FilePath[^\n]*\.(?:exe|ps1|bat|cmd|vbs|js|msi))",
     "Start-Process hidden/exe (可疑进程启动)"),
    # 二进制落地 (WriteAllBytes)
    (r"\[IO\.File\]::WriteAllBytes", "[IO.File]::WriteAllBytes (二进制落地)"),
    # 启用 RDP (远程桌面)
    (r"fDenyTSConnections[^\n]*/d\s*0", "enable RDP (开启远程桌面)"),
    # 注册表禁用 Windows 更新 / 杀软 (常见滥用)
    (r"reg(?:\.exe)?\s+add[^\n]*(?:Wuau|WindowsUpdate|DisableAntiSpyware)",
     "reg add WindowsUpdate/Defender disable (关闭更新/杀软)"),
    # ---- 第三轮补遗: 补齐既有 HIGH 块未覆盖的 PowerShell/Windows 危险面 ----
    (r"\bnet\s+user\b[^\n]*/add\b", "net user /add (新建本地账户, 可能留后门)"),
    (r"\bStop-Process\b", "Stop-Process (结束进程, 可能中断服务)"),
    (r"\[System\.Convert\]::FromBase64String|\bFromBase64String\b",
     "FromBase64String (解码载荷, 可能落地恶意文件)"),
    (r"\bAdd-LocalGroupMember\b[^\n]*(?:administrators|admin)", "add to administrators (加入管理员组, 提权)"),
    (r"\bnet\s+stop\b[^\n]*MpsSvc", "net stop MpsSvc (停用 Windows 防火墙服务)"),
    (r"\bStop-Service\b[^\n]*(?:-Force|wuauserv|WinUpdate|Windows\s*Update|winlogon|lsass|csrss|spoolsv|DefWatch|MpsSvc|bits|wisvc|DHCP|DNS)",
     "Stop-Service critical/security (停用关键/安全服务)"),
    # ---- SSH 远程执行内容的危险度由远程命令本身决定, 不在此一刀切 ----
    # V-10 修复: 原规则把所有 `ssh host 'cmd'` 都判 high, 导致
    # `ssh user@host 'ls -la'` 这种良性远程操作误报。移除一刀切规则,
    # 让远程执行的危险命令 (rm -rf / / chmod -R 777 / / cat ~/.ssh/id_rsa 等)
    # 被其本身的 critical/high 规则自然触发。SSH 本身作为合法远程运维工具保持良性。
]
