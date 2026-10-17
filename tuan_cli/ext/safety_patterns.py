"""安全引擎模式库 (safety_engine 拆分模块)。

纯数据: 致命/高危/中危/极高危四档「(正则, label)」模式库。
本模块不做任何判定, 仅供 safety_redline.py 与 safety_score.py 复用。

维护约定:
- 每条为 ``(regex, label)``; label 双语 (英文便于测试/日志, 中文便于展示)。
- label 是用户本地黑名单减负 (`tuan safe reduce <label关键字>`) 的匹配键, 改动 label
  会影响既有用户的减负声明, 请谨慎。
- 新增模式请同步补 tests/ 下的回归用例 (见 test_safety_redteam_round4.py)。
"""

# 裸磁盘设备 (dd / 重定向目标判定用): 覆盖 sd/nvme/vd/hd/xvd/mmcblk/sr
# 以及 LVM 与持久化设备名 (mapper / dm- / disk-by-id|path|uuid / cciss)。
_RAW_DISK = (
    r"/dev/(?:sd[a-z]|nvme\d+n\d+(?:p\d+)?|vd[a-z]|hd[a-z]|xvd[a-z]"
    r"|mmcblk\d+|sr\d+|cciss/\S+|mapper/\S+|dm-\d+|disk/by-(?:id|path|uuid)/\S+)"
)

_CRITICAL_PATTERNS = [
    # ---- SQL / 数据销毁 (扩展: 库/模式/索引/视图/字段/缓存) ----
    (r"DROP\s+(?:TABLE|DATABASE|SCHEMA|INDEX|VIEW)\b", "drop object (删除数据库对象)"),
    (r"DELETE\s+FROM\b", "delete rows (删除数据行)"),
    (r"TRUNCATE\s+(?:TABLE)?\s*\w+", "truncate (清空数据)"),
    (r"ALTER\s+TABLE\b[^\n]*\bDROP\b", "alter table drop (删除字段/约束, 不可逆)"),
    (r"\bFLUSHALL\b|\bFLUSHDB\b", "flush database (清空数据库全部键)"),
    (r"dropDatabase\s*\(", "mongo drop database (Mongo 删库)"),
    # ---- 磁盘 / 文件系统级破坏 ----
    (r"format\s+[a-zA-Z]:", "format disk (格式化磁盘)"),
    # mkfs 三种写法全覆盖: mkfs.ext4 / mkfs -t ext4 / mkfs.xfs -f
    (r"\bmkfs(?:\.\w+)?\b", "mkfs (创建文件系统, 抹除磁盘数据)"),
    # dd 只要写入块设备即致命, 不要求 if=/of= 的先后顺序 (dd of=/dev/sda if=/dev/zero 同样致命)
    (r"\bdd\b(?=[^\n]*\bof\s*=\s*" + _RAW_DISK + r"\b)",
     "dd write raw device (dd 直写磁盘设备)"),
    (r"\bwipefs\b", "wipefs (擦除文件系统签名)"),
    (r"\bshred\b", "shred (安全擦除文件)"),
    (r"\bblkdiscard\b", "blkdiscard (丢弃块设备全部数据, 不可恢复)"),
    # ---- 编辑器 / 分页器 shell 逃逸 (vim -c '!cmd' / ex 命令执行) ----
    (r"\b(?:vim|vi|nvim|ex|less|more)\b[^\n]*-c\s*['\"][^'\"]*!",
     "editor shell escape (编辑器 -c 中执行 shell 命令)"),
    # ---- 写入 SSH 授权公钥 (持久化后门) ----
    (r">{1,2}\s*~?/\.ssh/authorized_keys\b|\btee\b[^\n]*~?/\.ssh/authorized_keys\b",
     "write authorized_keys (写入 SSH 授权公钥, 持久化后门)"),
    (r">\s*" + _RAW_DISK + r"\b",
     "redirect to raw disk (重定向写入磁盘设备, 含 NVMe/virtio/IDE)"),
    (r"\blvremove\b|\bzfs\s+destroy\b|\bparted\b[^\n]*\brm\b",
     "volume/partition destroy (销毁卷或分区)"),
    # ---- 系统关机 / 重启 ----
    (r"\b(shutdown|halt|poweroff|reboot)\b", "system shutdown/reboot (系统关机或重启)"),
    (r"\b(?:init|telinit)\s+[06]\b", "init/telinit 0/6 (系统关机或重启)"),
    (r"systemctl\s+(poweroff|reboot|halt)", "systemd shutdown/reboot (系统关机或重启)"),
    # ---- 权限全灭 (递归 + 全零 + 根路径, 三条件不要求顺序) ----
    (r"\bchmod\b(?=[^\n]*\-[Rr]\b)(?=[^\n]*\b0{3,4}\b)(?=[^\n]*\s/)",
     "chmod -R 000 / (递归移除所有权限, 系统不可用)"),
    (r"\bchown\b(?=[^\n]*\-[Rr]\b)(?=[^\n]*\s/(?:\s|$))",
     "chown -R / (递归变更根目录所有权)"),
    # ---- fork bomb: 泛化函数名 (`:` `.` `bomb` `fork` 均可作函数名) ----
    (r"[\w:.]+\s*\(\s*\)\s*\{\s*[^{}]*\|[^{}]*&[^{}]*\}", "fork bomb (分叉炸弹)"),
    # ---- 子 shell / 括号内的致命命令 ----
    # 对抗 process substitution <(rm -rf /) → (rm -rf /) 或显式子 shell (rm -rf /);
    # _normalize 已剥掉外层括号, 但当括号出现在非首 token (如 diff (rm -rf /) /dev/null)
    # 时, has_recursive_rm 的段首判定不会命中, 需要正则兜底。
    (r"\(\s*rm\s+\S*-[rRfF]+\S*\s*/\s*\)", "subshell rm -rf (子 shell 中递归强删)"),
    # ---- find 递归删除 ----
    (r"find\s+\S+[^\n]*-delete", "find -delete (递归删除文件)"),
    # ---- Windows 磁盘 / 权限级破坏 ----
    (r"diskpart\b", "diskpart (磁盘分区)"),
    (r"cipher\s+/w", "cipher /w (擦除空闲空间)"),
    # 放宽: 实际写法常为 takeown /f <路径> /r, 旧模式要求 /f 紧邻 /r 而漏判
    (r"takeown\s+/f\b[^\n]*\s+/r\b", "takeown recursive (递归夺取所有权)"),
    (r"bcdedit\b", "bcdedit (修改启动配置)"),
    (r"reg\s+delete", "reg delete (删除注册表项)"),
    # ---- PowerShell ----
    # 旗标顺序无关 (旧实现要求 -Recurse 紧跟 -Force, `Remove-Item C:\ -Force -Recurse` 漏判)
    (r"\bRemove-Item\b(?=[^\n]*-Recurse)(?=[^\n]*-Force)",
     "Remove-Item -Recurse -Force (PowerShell 递归强删)"),
    # 递归在上游 cmdlet、删除在管道下游: Get-ChildItem C:\ -Recurse | Remove-Item -Force
    (r"\b(?:Get-ChildItem|gci)\b[^\n]*-Recurse[^\n]*\|\s*(?:Remove-Item|ri|del|erase|rm)\b",
     "Get-ChildItem -Recurse | Remove-Item (PowerShell 管道递归删除)"),
    # PowerShell 别名强删: rm/del/erase/rd/rmdir/ri 带 -r/-Recurse
    (r"powershell[^\n]*\b(?:rm|del|erase|rd|rmdir|ri)\b[^\n]*\s-[rR]",
     "PowerShell alias recursive delete (PowerShell 别名递归删除)"),
    (r"Stop-Computer", "Stop-Computer (PowerShell 关机)"),
    (r"Restart-Computer", "Restart-Computer (PowerShell 重启)"),
    # ---- 第三轮: PowerShell / Windows 命令let 侧写 (补齐 76.5% 漏放面) ----
    # 远程代码执行 (iex / Invoke-Expression / 别名)
    (r"\bInvoke-Expression\b|\biex\b|\bie\b", "PowerShell RCE (Invoke-Expression / iex/ie 执行任意代码)"),
    # 杀软 / 安全防护禁用 (Set-MpPreference 关实时防护 / 移除定义; Add-MpPreference 加白)
    (r"\bSet-MpPreference\b[^\n]*(?:Disable|Remove|Exclusion)",
     "Set-MpPreference tamper (禁用/移除 Defender 防护或加白路径)"),
    (r"\bAdd-MpPreference\b[^\n]*Exclusion", "Add-MpPreference exclusion (Defender 加白, 绕过扫描)"),
    # 注册表 Run / RunOnce 持久化
    (r"\bSet-ItemProperty\b[^\n]*(?:\\Run\b|\\RunOnce\b)",
     "registry Run persistence (写入注册表启动项, 持久化)"),
    # 开启 RDP (注册表 Terminal Server / fDenyTSConnections)
    (r"\bSet-ItemProperty\b[^\n]*(?:Terminal\s*Server|fDenyTSConnections)",
     "enable RDP via registry (注册表开启远程桌面)"),
    (r"\breg(?:\.exe)?\s+add[^\n]*fDenyTSConnections", "reg enable RDP (注册表开启远程桌面)"),
    # 计划任务 / 服务持久化
    (r"\bschtasks\b[^\n]*/create\b", "schtasks create (创建计划任务, 持久化)"),
    (r"\bRegister-ScheduledTask\b", "Register-ScheduledTask (注册计划任务, 持久化)"),
    (r"\bNew-Service\b", "New-Service (创建服务, 持久化/执行)"),
    # 清空安全/系统日志 (反取证)
    (r"\bClear-EventLog\b", "Clear-EventLog (清空事件日志, 反取证)"),
    (r"\bwevtutil\b[^\n]*\b(?:cl|sl)\b", "wevtutil clear (清空/停用事件日志, 反取证)"),
    # 格式化卷
    (r"\bFormat-Volume\b", "Format-Volume (格式化卷, 数据销毁)"),
    # 关闭防火墙
    (r"\bSet-NetFirewallProfile\b[^\n]*Enabled\s+False", "disable firewall profile (关闭防火墙)"),
    (r"\bnetsh\b[^\n]*advfirewall[^\n]*state\s+off", "netsh disable firewall (关闭防火墙)"),
    # 抓取 SAM/SYSTEM/SECURITY 蜂巢 (凭据窃取)
    (r"\breg(?:\.exe)?\s+save\b[^\n]*(?:SAM|SYSTEM|SECURITY)", "reg save SAM/SYSTEM (导出系统蜂巢, 凭据窃取)"),
    # 写入 Startup 启动目录 (持久化)
    (r"\b(?:Set-Content|Copy-Item|Move-Item|New-Item|Out-File|Add-Content|Set-Item)\b[^\n]*"
     r"(?:Start\s*Menu[\\/]Programs[\\/]Startup|\\Startup[\\/])",
     "write Startup dir (写入启动目录, 持久化)"),
    # ---- 反弹 shell / 远程代码执行 ----
    (r"/dev/tcp/\d{1,3}(?:\.\d{1,3}){3}/\d+", "reverse shell (/dev/tcp 反弹 shell)"),
    (r"\b(?:nc|ncat|netcat)\b[^\n]*-[ce]\s", "netcat shell (nc -e/-c 反弹 shell)"),
    # ---- 反向 shell 载荷 (解释器内联代码, 归一化后特征) ----
    # python: os.dup2(s.fileno(), 0..2) 三通道重定向到 socket 是反向 shell 专属模式
    (r"\b(?:os\.)?dup2\s*\([^\n]*\.fileno\(\)",
     "reverse shell dup2 (dup2 重定向三通道到 socket, 反向 shell)"),
    # python: import socket + connect(IP...) + /bin/sh 三要素 (缺一不算, 防误杀正常 socket 客户端)
    (r"(?=[^\n]*\bimport\s+socket\b)(?=[^\n]*\bconnect\s*\()(?=[^\n]*/bin/sh\b)",
     "reverse shell python (socket+connect+/bin/sh 反向 shell)"),
    # perl: socket(S,PF_INET,...) + sockaddr_in(inet_aton) + open(STDIN,">&S") 三要素
    (r"(?=[^\n]*socket\(\s*S\s*,\s*PF_INET)(?=[^\n]*sockaddr_in\s*\([^\n]*inet_aton\b)"
     r"(?=[^\n]*open\(\s*STDIN)",
     "reverse shell perl (perl Socket 反向连接)"),
    # ---- fork bomb: 花括号内管道+后台 (无括号形态, 归一化剥壳后命中; 覆盖 :(){ |& } 变体) ----
    (r"\{[^{}]*\|[^{}]*&\s*\}", "fork bomb (花括号管道后台, 分叉炸弹)"),
    # ---- 系统关键认证文件覆盖 ----
    (r">\s*/etc/(?:passwd|shadow|sudoers)\b", "overwrite /etc/passwd|shadow|sudoers (覆盖系统认证文件)"),
    # ---- 容器 / K8s 批量毁灭 ----
    (r"\bdocker\s+(?:rm|rmi|volume\s+rm)\b[^\n]*\$\(", "docker mass delete (批量删除全部容器/镜像/卷)"),
    (r"\bdocker\s+system\s+prune\b", "docker system prune (清理全部镜像/容器/卷)"),
    (r"\bkubectl\s+delete\s+namespace\b", "kubectl delete namespace (删除命名空间及其全部资源)"),
    (r"\bkubectl\s+delete\b[^\n]*--all", "kubectl delete --all (批量删除 K8s 资源)"),
    # ---- 容器逃逸: docker run 挂载宿主根/系统目录 (含 docker.sock 挂载) ----
    # 仅当卷源是「绝对系统路径」时命中: `/`(宿主根) 或 /etc|/usr|/var 等; 相对路径
    # (./data)、命名卷 (mydata:)、/tmp 绑定挂载均不命中, 避免开发场景误报。
    (r"\bdocker\s+run\b[^\n]*(?:-v|--volume)\s*=?\s*(?:/(?:etc|usr|bin|sbin|lib|boot|sys|proc|dev|var)(?:/[^\s:]*)?|/)\s*:",
     "docker run 挂载宿主根/系统目录 (容器逃逸)"),
    # ---- 云 CLI 不可逆销毁 ----
    (r"\baws\s+s3\s+(?:rm|rb)\b[^\n]*--(?:recursive|force)", "aws s3 递归删除对象/强制删桶"),
    (r"\baws\s+ec2\s+terminate-instances\b", "aws terminate instances (终止 EC2 实例)"),
    (r"\baws\s+rds\s+delete-db-instance\b", "aws delete rds (删除数据库实例)"),
    (r"\bgcloud\s+projects\s+delete\b", "gcloud 删除项目"),
    (r"\bgcloud\s+sql\s+instances\s+delete\b", "gcloud 删除数据库实例"),
    (r"\baz\s+group\s+delete\b", "azure 删除资源组"),
    (r"\bterraform\s+destroy\b", "terraform destroy (销毁全部基础设施)"),
    # ---- 持久化后门 ----
    (r"\|\s*crontab\b", "crontab pipe (写入定时任务, 持久化)"),
    (r">{1,2}\s*~?/\.(?:bashrc|bash_profile|profile|zshrc|zprofile)",
     "shell rc injection (写入 shell 启动脚本, 持久化)"),
    (r">\s*/etc/cron", "写入系统 cron 目录 (持久化)"),
    # ---- 日志 / 审计痕迹清除 ----
    (r":\s*>\s*/var/log", "truncate syslog (清空系统日志)"),
    (r"cat\s+/dev/null\s*>", "wipe file (用 /dev/null 清空文件)"),
    # ---- 数据外泄 (敏感文件上传到外部) ----
    (r"curl\b[^\n]*\s-[dTF]\s+@?(?=[^\n]*(?:/etc/|/home/|/root/|/var/log|~?/\.ssh|~?/\.aws|~?/\.env|\.env\b|id_rsa|credentials|passwd|shadow|@-))",
     "curl exfiltrate sensitive file (数据外泄)"),
    (r"wget\b[^\n]*--post-file=", "wget exfiltrate file (数据外泄)"),
    (r"wget\b[^\n]*--post-data=", "wget exfiltrate data (数据外泄)"),
    # ---- 容器编排 / K8s 销毁 ----
    (r"\bhelm\s+uninstall\b", "helm uninstall (删除 K8s release)"),
    # ---- 网络侦察 / 可疑 C2 端点 ----
    (r"\bnmap\b", "nmap (端口扫描/网络侦察)"),
    (r"https?://[^\s'\"<>]*\b(?:pastebin\.com/raw|ngrok\.io|requestbin\.net|webhook\.site|interact\.sh|burpcollaborator\.net)",
     "suspicious C2/exfil endpoint (可疑 C2/外泄端点)"),
    # ---- 数据外泄: 敏感文件经 scp/rsync 复制到远端 ----
    (r"\bscp\b[^\n]*(?:~?/\.ssh/|~?/\.aws/|id_rsa|\.env\b|/etc/shadow|/etc/passwd|credentials)",
     "scp sensitive file (敏感文件复制到远端, 外泄)"),
    (r"\brsync\b[^\n]*(?:~?/\.ssh/|~?/\.aws/|id_rsa|\.env\b|/etc/shadow|/etc/passwd|credentials)",
     "rsync sensitive file (敏感文件同步到远端, 外泄)"),
    # ---- 数据外泄: tar 归档 (含密钥/凭证) 经管道传到远端 ssh ----
    # 两个顺序无关的前瞻: 命中 `tar ... | ssh` 管道 且 命令中含密钥/凭证类敏感路径。
    # 仅匹配密钥/凭证类 (不含 /home|/etc 目录), 避免把 `tar /home/me | ssh` 正常备份误判。
    (r"(?=[\s\S]*\btar\b[\s\S]*\|\s*ssh\b)"
     r"(?=[\s\S]*(?:~?/\.ssh(?:/|\b)|~?/\.aws(?:/|\b)|id_rsa|\.env\b|credentials|/etc/shadow|/etc/passwd))",
     "tar over ssh with secret path (敏感归档外泄到远端)"),
    # ---- 数据外泄: netcat 读敏感文件外发 ----
    (r"\bnc\b[^\n]*<\s*[^\n]*(?:ssh|aws|\.env\b|id_rsa|shadow|passwd|credentials)",
     "nc send sensitive file (netcat 外发敏感文件)"),
    # ---- 云 CLI 不可逆销毁 (扩展) ----
    (r"\baws\s+lambda\s+delete-function\b", "aws lambda delete (删除函数)"),
    (r"\baws\s+iam\s+delete-user\b", "aws iam delete-user (删除 IAM 用户)"),
    (r"\bgcloud\s+compute\s+instances\s+delete\b", "gcloud delete instance (删除计算实例)"),
    (r"\baz\s+vm\s+delete\b", "azure delete vm (删除虚拟机)"),
    (r"\bkubectl\s+drain\b", "kubectl drain (驱逐并封锁节点)"),
    # ---- Windows 账户 / 注册表破坏 ----
    (r"\bnet\s+user\b[^\n]*/delete\b", "net user delete (删除账户)"),
    (r"reg(?:\.exe)?\s+add[^\n]*\\Run", "reg add Run (写入启动项, 持久化)"),
    # ---- 移动至 /dev/null (彻底销毁数据) ----
    (r"\bmv\b[^\n]*\s/[^\n]*?/dev/null\b", "mv to /dev/null (把文件/目录移入黑洞, 数据销毁)"),
    # ---- 杀掉全部进程 (pid -1 = 所有进程) ----
    (r"\bkill\b[^\n]*\s-1\b", "kill -1 (向所有进程发送信号, 系统级中断)"),
    # ---- git push 删远程引用 (冒号语法: git push origin :ref) ----
    (r"git\s+push\b[^\n]*\s:\s*\S+", "git push :ref (删除远程分支/标签)"),
    # ---- 远程拉取即执行 (curl|wget ... | sh) —— 经典 RCE 投递链 ----
    (r"\b(?:curl|wget)\b[^\n]*\|\s*(?:ba)?sh\b", "remote fetch pipe to shell (下载即执行 RCE)"),
    (r"\bwget\b[^\n]*\-O[\s-]*\|", "wget -O- pipe to shell (下载即执行 RCE)"),
    # ---- NoSQL / 内存库 毁灭性操作 ----
    (r"\b(?:mongo|mongosh)\b[^\n]*--eval[^\n]*(?:dropDatabase|drop\s*\(|dropCollection)",
     "mongo dropDatabase (MongoDB 删库)"),
    (r"\bredis-cli\b[^\n]*\bflushall\b", "redis flushall (清空全部 Redis 数据)"),

    # ======================================================== 第二轮新增攻击面
    # ---- 痕迹抹除 / 反取证 (历史与审计日志) ----
    (r"\brm\b[^\n]*(?:\.bash_history|\.zsh_history|\.python_history|\.lesshst)\b",
     "remove shell history file (删除命令历史文件)"),
    (r"\bunset\b[^\n]*\bHISTFILE\b[^\n]*(?:;|&&|\|)[^\n]*\bunset\b[^\n]*\bHISTSIZE\b",
     "unset HISTFILE+HISTSIZE (关闭命令历史记录, 反取证)"),
    (r"\bfind\b[^\n]*-exec[^\n]*\brm\b", "find -exec rm (批量查找并删除)"),
    (r"\bjournalctl\b[^\n]*--vacuum", "journalctl --vacuum (清空 systemd 日志)"),
    (r"\btruncate\b[^\n]*-s\s*0\b[^\n]*(?:/var/log/|/var/adm/|/var/audit/|wtmp|btmp|lastlog)",
     "truncate log to zero (清空登录/审计日志)"),
    # ---- 持久化与提权后门 ----
    (r"\bchmod\b[^\n]*\bu\+s\b", "chmod u+s (设置 SUID 提权后门)"),
    (r"\bchmod\s+[0-7]*[2467][0-7]{3}\b", "chmod setuid/setgid (设置提权位)"),
    (r"\bat\b[^\n]*\s-f\b", "at -f (计划任务执行脚本, 持久化)"),
    (r"\bsystemctl\s+enable\b[^\n]*(?:/tmp/|/dev/shm/|/var/tmp/|\./)",
     "systemctl enable from temp (从临时目录注册自启动服务)"),
    # ---- 安全机制关闭 (防火墙 / 审计 / 杀软 / SELinux) ----
    (r"\bsetenforce\s+0\b", "setenforce 0 (关闭 SELinux 强制模式)"),
    # 注: 裸 ufw/firewalld disable|stop 归为 HIGH (可确认), 不在此列为 critical。
    # 系统化停用安全服务 (systemctl stop/disable ufw|firewalld|auditd|...) 仍为 critical。
    (r"\bsystemctl\s+(?:stop|disable)\b[^\n]*"
     r"(?:ufw|firewalld|auditd|apparmor|selinux|fail2ban|clamav)",
     "stop/disable security service (停用安全服务)"),
    (r"\biptables\b[^\n]*-P\s+(?:INPUT|FORWARD|OUTPUT)\s+ACCEPT",
     "iptables default ACCEPT (防火墙默认放行)"),
    (r"\bchmod\b[^\n]*-x\b[^\n]*/(?:usr|bin|sbin)/",
     "chmod -x on system binary (移除系统可执行文件执行位)"),
    (r"SELINUX\s*=\s*(?:disabled|permissive)", "SELinux disabled (写入配置关闭 SELinux)"),
    # ---- 存储 / 卷 / 分区销毁 ----
    (r"\bumount\s+-a", "umount -a (卸载所有文件系统)"),
    (r"\bswapoff\s+-a", "swapoff -a (关闭全部交换空间)"),
    (r"\b(?:lvremove|vgremove|pvremove)\b", "LVM remove (删除逻辑卷/卷组/物理卷)"),
    (r"\bmdadm\b[^\n]*--zero-superblock", "mdadm zero-superblock (销毁 RAID 元数据)"),
    (r"\bsgdisk\b[^\n]*\s-(?:Z|z|o)\b", "sgdisk zap (清空分区表)"),
    (r"\bparted\b[^\n]*\bmklabel\b", "parted mklabel (重建分区表)"),
    # ---- macOS / Windows 灭毁与反恢复 ----
    (r"\bdiskutil\b[^\n]*\b(?:eraseDisk|eraseVolume|zeroDisk|secureErase)\b",
     "diskutil erase (抹除磁盘/卷)"),
    (r"\bnvram\b[^\n]*\s-(?:c|d)\b", "nvram -c (清空固件变量)"),
    (r"\btmutil\b[^\n]*\bdelete\b", "tmutil delete (删除 Time Machine 备份)"),
    (r"\bvssadmin\b[^\n]*\bdelete\b[^\n]*\bshadows\b",
     "vssadmin delete shadows (删除卷影副本, 破坏勒索恢复能力)"),
    (r"\bwbadmin\b[^\n]*\bdelete\b[^\n]*\bcatalog\b",
     "wbadmin delete catalog (删除 Windows 备份目录)"),
    # ---- 写入系统持久化目录 (计划任务 / 自启动 / init) ----
    # 只匹配"写入方向": 重定向目标 / tee 目标 / cp|mv|install 的最后一个操作数,
    # 避免把 `cp /etc/crontab /tmp/backup` 这类读取备份误判为持久化。
    (r"(?:>+\s*|tee\s+|cp\s+\S+\s+|mv\s+\S+\s+|install\s+[^\n]*\s)"
     r"(?:/etc/cron\.d/|/etc/cron\.(?:daily|hourly|weekly|monthly)/|"
     r"/etc/systemd/system/|/etc/init\.d/|/etc/rc\.local)",
     "write persistence dir (写入计划任务/自启动目录, 持久化)"),
    # ---- 裸重定向截断系统日志 (除标准系统日志外不拦, 避免误伤 >> 应用日志) ----
    (r"(?<![>\w])>\s*(?:/var/(?:log|adm|audit)/)"
     r"(?:syslog|messages|auth\.log|secure|kern\.log|daemon\.log|"
     r"wtmp|btmp|utmp|lastlog|faillog|audit\.log)\b",
     "truncate system log (重定向清空系统日志)"),
    # ---- 环境变量代码注入 ----
    (r"\bLD_PRELOAD\s*=", "LD_PRELOAD (动态库劫持, 代码注入)"),
    (r"\bBASH_ENV\s*=", "BASH_ENV (非交互 shell 启动注入)"),
    (r"\bPROMPT_COMMAND\s*=\s*[^;\s]", "PROMPT_COMMAND (提示符命令注入)"),
    # ---- PowerShell / Windows 防御规避 · RCE · 持久化 · 凭据窃取 · 系统毁灭 ----
    # 任意代码执行 (iex / Invoke-Expression), 含下载即执行
    (r"(?:\bInvoke-Expression\b|\biex\b|\bie\b(?=\s*\())", "Invoke-Expression/iex/ie (任意代码执行, RCE)"),
    # 关闭 / 卸载 Windows Defender (实时防护 / 行为监控 / IOAV / 定义)
    (r"Set-MpPreference[^\n]*(?:-Disable\w*|-RemoveDefinitions)",
     "Set-MpPreference disable AV (关闭/卸载 Defender)"),
    # 添加杀软排除 (白名单免杀)
    (r"Add-MpPreference[^\n]*-Exclusion(?:Path|Process|Extension)",
     "Add-MpPreference exclusion (杀软排除, 免杀)"),
    # 清空安全/系统/应用事件日志 (反取证)
    (r"\bClear-EventLog\b", "Clear-EventLog (清空事件日志, 反取证)"),
    (r"\bwevtutil\b[^\n]*\scl\b", "wevtutil cl (清空事件日志, 反取证)"),
    # 注册表 Run / RunOnce / 启动项持久化 (Set-ItemProperty)
    (r"Set-ItemProperty[^\n]*-Path[^\n]*(?:Run|RunOnce|Userinit|Image\s*File\s*Execution|Shell\s*Folders)",
     "Set-ItemProperty registry persistence (注册表自启动持久化)"),
    # 计划任务持久化
    (r"\bschtasks\b[^\n]*/create", "schtasks /create (计划任务持久化)"),
    (r"\bRegister-ScheduledTask\b", "Register-ScheduledTask (计划任务持久化)"),
    # 凭据/哈希提取: 导出 SAM/SYSTEM/SECURITY hive
    (r"reg(?:\.exe)?\s+save[^\n]*(?:SAM|SYSTEM|SECURITY)", "reg save SAM/SYSTEM (导出系统凭据 hive)"),
    # 格式化卷 (数据毁灭)
    (r"\bFormat-Volume\b", "Format-Volume (格式化卷, 数据毁灭)"),
    (r"\bformat\s+[a-zA-Z]:[^\n]*\b", "format drive: (格式化磁盘)"),
    # 关键系统服务停用 (winlogon/lsass/csrss 等)
    (r"Stop-Service[^\n]*-Name\s+(?:winlogon|lsass|csrss|spoolsv|DefWatch|eventlog)",
     "Stop-Service critical (停用关键系统服务)"),
    # 新建管理员账户
    (r"\bnet\s+(?:user|localgroup)\b[^\n]*/add", "net user/localgroup /add (新建账户)"),
    (r"\bAdd-LocalGroupMember\b[^\n]*(?:administrators|-Group\s+administrators)",
     "Add-LocalGroupMember administrators (提权至管理员)"),
    # 写入启动目录持久化 (Set-Content 到 Startup)
    (r"Set-Content[^\n]*(?:\\Startup\\|Start\s*Menu\\Programs\\Startup)",
     "write Startup folder (写入启动目录持久化)"),
    # 注册表 Run 持久化 (reg add) —— 与既有 reg add Run 规则互补, 强化覆盖
    (r"reg(?:\.exe)?\s+add[^\n]*(?:\\Run|\\RunOnce)", "reg add Run key (注册表自启动持久化)"),
]

_HIGH_PATTERNS = [
    # 注: rm 递归强删已升级为 critical (见 has_recursive_rm), 不再列在 high。
    (r"chmod\b[^\n]*\b777\b", "chmod 777 (全权限修改)"),
    (r"git\s+reset\s+--hard", "git reset --hard (硬重置)"),
    (r"ALTER\s+TABLE\s+.*\s+DROP", "alter table drop column (修改表结构删除列)"),
    (r"UPDATE\s+.*\s+SET.*WHERE.*=", "bulk update (批量更新数据)"),
    # 管道到 shell 解释器执行 (仅当 | 后紧跟解释器时才算, 避免 `ps | grep bash` 误匹配)
    (r"\|\s*(?:sh|bash|zsh|ksh|fish|dash|ash|csh|tcsh|python\d*|perl|ruby|node|php|lua|powershell|pwsh|cmd)\b",
     "pipe to shell (管道到 shell 执行)"),
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
    (r">\s*/var/log", "overwrite system log (覆盖/清空系统日志)"),
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
    (r"\b(?:cat|tac|less|more|head|tail|nl|bat|type)\b[^\n]*(?:/etc/shadow|/etc/passwd|~?/\.ssh/|~?/\.aws/|id_rsa|\.env\b|/\.aws/credentials)",
     "read sensitive file (读取敏感凭证/密钥)"),
    # Git 不可逆变体 (扩展): 删除标签 / 清空全部 reflog
    (r"\bgit\s+tag\b[^\n]*\s-[dD]\b", "git tag -d (删除标签)"),
    (r"\bgit\s+reflog\s+expire\b[^\n]*--all\b", "git reflog expire --all (清空引用日志)"),
    # 移除不可变标志 (破坏防篡改保护)
    (r"\bchattr\s+-i\b", "chattr -i (移除不可变标志)"),
    # 信号升级: 强制终止全部同名进程 / 强制杀指定
    (r"\bpkill\s+-9\b", "pkill -9 (强制杀进程)"),
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
    # ---- 远程命令执行 (ssh 后跟命令; 纯登录 ssh host / ssh -T git@github.com 不算) ----
    (r"\bssh\b(?:\s+-[A-Za-z0-9]+(?:\s+\S+)?)*\s+[A-Za-z0-9_.@:-]+\s+[^-]\S*",
     "ssh remote exec (SSH 远程执行命令)"),
]

_MEDIUM_PATTERNS = [
    (r"sudo\s+", "超级用户权限"),
    (r">\s*/etc/", "写入系统配置"),
    (r"mv\s+.*/etc/", "移动系统文件"),
    (r"kill\s+-9", "强制终止进程"),
    # 服务管理
    (r"systemctl\s+(stop|disable)\s+\S+", "systemctl stop/disable (停止/禁用服务)"),
    (r"service\s+\S+\s+stop", "service stop (停止服务)"),
    # 进程管理
    (r"\bpkill\s+", "pkill (按名称杀进程)"),
    (r"\bkillall\s+", "killall (杀全部同名进程)"),
    # 权限变更
    (r"chmod\s+000\s+", "chmod 000 (移除所有权限)"),
    (r"chown\s+root\s+", "chown root (变更 root 所有权)"),
]


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
