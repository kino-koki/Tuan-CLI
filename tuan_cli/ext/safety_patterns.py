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
    (r"\bsgdisk\b[^\n]*\s-(?:Z|z|o)\b",
     "sgdisk zap (清空分区表)"),
    (r"\bvssadmin\b[^\n]*\bdelete\b[^\n]*\bshadows\b",
     "vssadmin delete shadows (删除卷影副本, 破坏勒索恢复能力)"),
    (r"\bmv\b[^\n]*\s/(?:etc|usr|var|bin|sbin|lib|lib64|boot|root|dev|proc|sys|opt|home|srv|run)(?:/|\s|$)",
     "move system directory (移动系统目录, 可能导致系统不可用)"),
    # V-11: mv 移动**根目录本身** (mv / /tmp/x) —— 前面规则只枚举具名系统目录, 不含 `/`。
    (r"\bmv\b[^\n]*\s/\s+\S", "move root directory (移动根目录, 系统不可恢复)"),
    (r"\buserdel\b[^\n]*\s+root\b",
     "userdel root (删除 root 账户及其文件)"),
    # V-11: shell 级 truncate 截断系统关键文件 (SQL TRUNCATE 已有, 命令版缺失)。
    # 注意: 路径前不能加 `\b` —— `/` 与空白都是非词字符, `\b` 需一侧为词字符,
    # 放在 ` /etc/` 前会导致 `\b/etc/` 永远匹配不到 (空格后直接是 `/`)。
    (r"\btruncate\b[^\n]*(?:/etc/|/var/|/usr/|/boot/|/dev/|~?/\.(?:ssh|config|bashrc|profile|zshrc))",
     "truncate system file (截断系统关键文件/配置, 数据不可恢复)"),
    # V-11: 进程替换把远程/外部输出直接喂给 shell 解释器 (bash <(curl ...)) ——
    # 语义等价于 `curl ... | bash` (已被拦截), 但走了进程替换通道, 属于覆盖缺口。
    (r"\b(?:bash|sh|zsh|ksh|dash|source|\.)\s*<\s*\([^)]*(?:curl\b|wget\b|fetch\b|nc\b|base64\b)",
     "shell via process substitution (进程替换将远程/外部输出直接喂给 shell 解释器)"),
    # V-11: awk/gawk -i inplace 就地改写 + 内嵌命令执行 (system/print) ——
    # `-i inplace` 一个旗标即可绕过不带 -i 的 awk 检测。
    (r"\bg?awk\b[^\n]*\s-i\s+inplace[^\n]*(?:system\s*\(|\bprint\b|\bprintf\b)",
     "awk in-place code execution (awk -i inplace 中执行命令/打印, 就地改写文件)"),
    # 读取敏感文件 / 私钥 —— 风险低于写入/删除系统路径, 降为 high (见 _HIGH_PATTERNS 同规则)。
    (r"\bchmod\b(?=[^\n]*\-[Rr]\b)(?=[^\n]*\b7777?\b)(?=[^\n]*\s/(?:\s|$))",
     "chmod -R 777 / (递归开放系统目录全部权限)"),
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
    # 安全修复: 原用 `[\s\S]*` 跨全文本扫描, 复杂度随文本长度平方以上放大 —— 在
    # glob 展开后的长串上单条模式耗时 1.03s (见 safety_normalize._GLOB_MAX_TOTAL_CHARS
    # 注释里的 22 秒案例)。改为 `[^\n]*` 行内语义, 并由 _match_any 逐行扫描覆盖
    # 多行载荷, 语义不变但扫描范围受单行长度限制。
    (r"(?=[^\n]*\btar\b[^\n]*\|\s*ssh\b)"
     r"(?=[^\n]*(?:~?/\.ssh(?:/|\b)|~?/\.aws(?:/|\b)|id_rsa|\.env\b|credentials|/etc/shadow|/etc/passwd))",
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
    # 安全修复: 原模式 `\|\s*(?:ba)?sh\b` 要求 `|` 后紧跟 shell 名, 中间的
    # **路径前缀**会整个绕过 —— `curl http://x | /bin/sh` / `| /bin/bash` /
    # `| /usr/bin/zsh` 全放行 (跨平台可移植性测试发现)。改为允许任意路径前缀,
    # 并把常见 shell 名全部列出: sh/bash/zsh/ksh/dash/ash/fish, 以及
    # Windows 侧的 powershell/pwsh/cmd。
    (r"\b(?:curl|wget|fetch|lynx|links)\b[^\n]*\|\s*"
     r"(?:(?:\S*[/\\])?)"
     r"(?:sh|bash|zsh|ksh|dash|ash|fish|es|tcsh|csh|powershell|pwsh|cmd|python3?|perl|ruby|node|php)"
     r"\b", "remote fetch pipe to shell (下载即执行 RCE)"),
    # `curl x | /usr/bin/env bash` —— env 间接寻址绕过上面的路径前缀规则。
    (r"\b(?:curl|wget)\b[^\n]*\|\s*(?:\S*[/\\])?(?:env|xargs|nohup)\s+"
     r"(?:\S*[/\\])?(?:sh|bash|zsh|ksh|dash|ash|fish|powershell|pwsh|cmd)\b",
     "remote fetch pipe to shell via env (下载即执行 RCE)"),
    (r"\bwget\b[^\n]*\-O[\s-]*\|", "wget -O- pipe to shell (下载即执行 RCE)"),
    # ---- 磁盘分区工具: 对块设备执行非只读操作即破坏性 ----
    # `fdisk -l` (仅列分区表) / `sgdisk -p` / `sgdisk --print` / `parted ... print`
    # 都是只读查询, 不算危险; 只有带写动作 (新建/删除/清空分区) 才拦。
    (r"\bfdisk\b(?![^\n]*(?:\s-l\b|\s--list\b|\s--read-only\b))(?=[^\n]*(?:/dev/|/mnt/|/sys/|/run/))",
     "fdisk 分区 (改写磁盘分区表)"),
    (r"\bsgdisk\b(?![^\n]*(?:\s-p\b|\s--print\b|\s-i\b|\s--info\b|\s--print-tree\b|\s-v\b|\s--verify\b))"
     r"(?=[^\n]*(?:/dev/|/mnt/))",
     "sgdisk 分区 (改写磁盘分区表)"),
    (r"\bparted\b[^\n]*(?![^\n]*(?:\sprint\b|\sprint-free\b))(?:\bmklabel\b|\bmkpart\b|\brm\s+\d+\b|\bdelete\b)",
     "parted 分区 (新建/删除分区)"),
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
    # ---- 账户 / 权限提升 (随机种子真实场景基准暴露的盲区) ----
    # 以下命令在修复前全部 risk=none 直接放行, 属于真实的提权与账户销毁路径。
    (r"\buseradd\b[^\n]*(?:\s-u\s*0\b|--uid[=\s]+0\b)",
     "useradd uid=0 (新建 uid=0 账户, 等同 root 提权)"),
    (r"\bgroupadd\b[^\n]*(?:\s-g\s*0\b|--gid[=\s]+0\b)",
     "groupadd gid=0 (新建 gid=0 组, 等同 root 组)"),
    (r"\bgroupmod\b[^\n]*(?:\s-g\s*0\b|--gid[=\s]+0\b)",
     "groupmod gid=0 (组 id 改为 0, 提权)"),
    (r"\b(?:usermod|chfn|chsh)\b[^\n]*\s-L\b[^\n]*\broot\b",
     "usermod -L root (锁定 root 账户, 导致无法登录的拒绝服务)"),
    (r"\bpasswd\b[^\n]*\s-l\b[^\n]*\broot\b",
     "passwd -l root (锁定 root 密码, 拒绝服务)"),
    (r"\buserdel\b[^\n]*(?:\s-r\b|--remove\b)",
     "userdel -r (删除用户及其主目录, 不可逆)"),
    (r"\bgroupdel\b\s+\S+",
     "groupdel (删除用户组)"),
    # chown -R 到系统关键目录: 已有红线只覆盖目标恰好是 `/`, 于是
    # `chown -R root:root /home` / `chown -R nobody:nobody /*` 全放行。
    # 注意要求目录名后紧跟行尾或「/ + 空白」—— 只命中系统目录**本身**, 不误伤
    # `chown -R www-data:www-data /var/www/html` 这类常规 web 部署操作。
    # macOS 的 /System 与 /Library 一并覆盖: chown -R root:wheel /System 会破坏
    # SIP 保护的只读文件系统所有权, 与 Linux 侧同属系统目录所有权接管。
    (r"\bchown\b[^\n]*-[Rr]\b[^\n]*\s/(?:home|etc|var|usr|bin|sbin|boot|root|lib|lib64|opt|srv|run|proc|sys|System|Library)(?:/\s|$)",
     "chown -R 系统目录 (递归变更系统目录所有权)"),
    (r"\bchown\b[^\n]*-[Rr]\b[^\n]*\s/\*",
     "chown -R /* (递归变更全盘所有权)"),
    # 防火墙默认拒绝 = 入站全部锁死; 与上面的 ACCEPT 对称, 一并列 critical。
    (r"\biptables\b[^\n]*-P\s+(?:INPUT|FORWARD|OUTPUT)\s+DROP",
     "iptables default DROP (防火墙默认拒绝, 入站锁死)"),
    (r"\biptables\b[^\n]*-A\s+INPUT\b[^\n]*-j\s+DROP",
     "iptables INPUT DROP (入站拒绝规则)"),
    (r"\bufw\b[^\n]*(?:disable|delete\s+rule|default\s+deny\s+incoming)",
     "ufw disable/delete/default-deny (关闭或收紧防火墙)"),
    (r"SELINUX\s*=\s*(?:disabled|permissive)", "SELinux disabled (写入配置关闭 SELinux)"),
    # ---- 存储 / 卷 / 分区销毁 ----
    (r"\bumount\s+-a", "umount -a (卸载所有文件系统)"),
    (r"\bswapoff\s+-a", "swapoff -a (关闭全部交换空间)"),
    (r"\b(?:lvremove|vgremove|pvremove)\b", "LVM remove (删除逻辑卷/卷组/物理卷)"),
    (r"\bmdadm\b[^\n]*--zero-superblock", "mdadm zero-superblock (销毁 RAID 元数据)"),
    # sgdisk zap / parted mklabel 已由上方「磁盘分区工具」规则统一覆盖
    # (含只读查询排除), 此处不再重复。
    # ---- macOS / Windows 灭毁与反恢复 ----
    (r"\bdiskutil\b[^\n]*\b(?:eraseDisk|eraseVolume|zeroDisk|secureErase)\b",
     "diskutil erase (抹除磁盘/卷)"),
    (r"\bnvram\b[^\n]*\s-(?:c|d)\b", "nvram -c (清空固件变量)"),
    (r"\btmutil\b[^\n]*\bdelete\b", "tmutil delete (删除 Time Machine 备份)"),
    (r"\bvssadmin\b[^\n]*\bdelete\b[^\n]*\bshadows\b",
     "vssadmin delete shadows (删除卷影副本, 破坏勒索恢复能力)"),
    (r"\bwbadmin\b[^\n]*\bdelete\b[^\n]*\bcatalog\b",
     "wbadmin delete catalog (删除 Windows 备份目录)"),
    # macOS 完整性与内核扩展: SIP 关闭后系统可被任意改写; 从临时目录加载 kext
    # 是典型的持久化后门手法。跨平台可移植性测试发现这几类此前全放行。
    (r"\bcsrutil\b[^\n]*\b(?:disable|clear-auth-file)\b",
     "csrutil disable (关闭系统完整性保护 SIP)"),
    (r"\bkextload\b[^\n]*\s(?:/tmp/|/var/tmp/|/dev/shm/|/Users/[^\n]*/(?!Applications\b)|~/|\./)",
     "kextload from temp (从临时/用户目录加载内核扩展, 持久化)"),
    (r"\bsystemextensionsctl\b[^\n]*\bremove\b", "systemextensionsctl remove (移除系统扩展)"),
    # macOS 钥匙串 / 证书: 删除根证书会破坏 TLS 校验信任链; 导入证书则可能
    # 植入中间人根 CA。仅匹配删除/导入动作, `security find-*` / `show-*` /
    # `list-*` / `unlock-*` 是只读查询或钥匙串管理。
    (r"\bsecurity\b[^\n]*\b(?:delete|remove)-certificate\b",
     "security delete/remove certificate (删除证书, 破坏信任链)"),
    (r"\bsecurity\b[^\n]*\bimport\b",
     "security import certificate (导入证书, 可能植入中间人根 CA)"),
    # `defaults write` 面向系统级域 (/Library/Preferences 或 com.apple.* 全局)
    # 是 macOS 常见持久化手段; 但 `defaults write com.apple.Safari ...` 之类
    # 面向用户 App 域的操作极常见, 故只锁系统级域。
    (r"\bdefaults\b[^\n]*\bwrite\b[^\n]*\s/(?:Library/Preferences|System/Library)",
     "defaults write system domain (写入系统级偏好, 持久化)"),
    # macOS SIP 保护的只读卷被移动 / 抹除。要求路径以空白或行尾结束,
    # 允许 `/System` 本体或 `/System/子路径` (`mv /System/Library /tmp/`)。
    (r"\bmv\b[^\n]*\s/System(?:/\S+)?(?:\s|$)", "mv /System (移动 macOS 系统卷内容)"),
    (r"\bchmod\b[^\n]*-[Rr]\b[^\n]*\s/System(?:/\S+)?(?:\s|$)", "chmod -R /System (改 macOS 系统卷权限)"),
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

    # ======================================================== 第四轮: 外部安全围堵方案 (V-02~V-09)
    # 依据 Tuan-CLI-安全漏洞与围堵方案.md 的 P0/P1 漏洞清单补齐规则库覆盖面。

    # ---- V-02 Windows LOLBins 下载/执行 (此前 10/13 条放行, 现全部 critical) ----
    # certutil -urlcache: 从 URL 下载文件/执行。任意旗标组合都拦截, 不限于 -f。
    (r"\bcertutil(?:\.exe)?\b[^\n]*-urlcache\b", "certutil urlcache (下载/执行文件)"),
    # bitsadmin /transfer /create: Windows 后台传输服务, 下载恶意载荷。
    (r"\bbitsadmin(?:\.exe)?\b[^\n]*/(?:transfer|create|addfile|addfilewithranges)\b",
     "bitsadmin transfer (后台下载/上传文件)"),
    # mshta: 执行 HTA (HTML Application) —— 常被用于下载即执行。
    (r"\bmshta(?:\.exe)?\b[^\n]*(?:https?://|javascript:|vbscript:|ms-its:|mk:@|file://)",
     "mshta execute HTA (HTML 应用执行)"),
    # rundll32 javascript:... —— 经典 LOLBin 绕过 (MSHTML 应用执行)。
    (r"\brundll32(?:\.exe)?\b[^\n]*javascript:",
     "rundll32 javascript (MSHTML 应用执行)"),
    # rundll32 / regsvr32 加载 .sct (Scriptlet) —— 远程脚本执行。
    (r"(?:rundll32|regsvr32)(?:\.exe)?\b[^\n]*\.sct\b",
     "regsvr32/rundll32 sct (远程脚本组件执行)"),
    # regsvr32 /i:http 或 /i:https —— 远程脚本执行。
    (r"\bregsvr32(?:\.exe)?\b[^\n]*/i:https?://",
     "regsvr32 i:http (远程脚本执行)"),
    # installutil: .NET 安装器, 可执行任意程序集。
    (r"\binstallutil(?:\.exe)?\b", "installutil (执行 .NET 程序集)"),
    # wmic process call create: 创建进程。
    (r"\bwmic(?:\.exe)?\b[^\n]*process[^\n]*call[^\n]*create",
     "wmic process call create (创建进程)"),
    # forfiles /c "cmd ...": 对匹配文件执行命令 (批量执行/删除)。
    (r"\bforfiles(?:\.exe)?\b[^\n]*/c\b[^\n]*\bcmd\b",
     "forfiles /c cmd (批量执行命令)"),
    # PowerShell 下载即执行: Invoke-WebRequest|iwr|wget|curl + Start-Process / iex / .\script.
    # 关键: 中间的 [^\n]* 必须是非贪婪 [^\n]*? — 贪婪会吞掉 http:// 让正则后半段无法匹配。
    # .\script 正则 \.[\\/] 表示点号 + (反斜杠或正斜杠), 文件名 + .ps1 结尾。
    (r"(?:\bInvoke-WebRequest\b|\biwr\b|\bwget\b|\bcurl\b|\bDownloadFile\b|\bDownloadString\b)"
     r"[^\n]*?(?:https?://)[^\n]*"
     r"(?:\bStart-Process\b|\bInvoke-Expression\b|\biex\b|\bir\b|\bash\b|\bcmd\b"
     r"|\.[\\/][A-Za-z0-9_.-]+\.ps1\b)",
     "PS download then execute/dot-source (下载后执行脚本)"),
    # .NET WebClient / HttpWebRequest + DownloadFile/DownloadString (下载任意内容)。
    (r"\b(?:Net\.WebClient|HttpWebRequest|HttpClient)\b[^\n]*(?:DownloadString|DownloadFile|Send|GetAsync)\b",
     ".NET web client download (下载任意内容)"),
    # Set-ExecutionPolicy Bypass -Force: 绕过脚本执行策略 (常配合下载即执行)。
    (r"\bSet-ExecutionPolicy\b[^\n]*Bypass\b[^\n]*-\s*Force\b",
     "Set-ExecutionPolicy Bypass (绕过执行策略)"),

    # ---- V-03 权限篡改与持久化: 写入目标路径敏感集抽象 ----
    # 凡写入/覆盖系统关键路径 (不限于 /etc), 与命令名无关, 一律 critical。
    # 敏感路径集: /etc /usr /bin /sbin /lib /boot /root /dev /sys /proc /var (系统级)
    # 以及家目录下 .ssh / .aws / .config / .env / 启动脚本 (用户级持久化)。
    # **排除项**: /dev/null / /dev/zero / /dev/random / /dev/urandom —— 这些是合法的
    # 丢弃输出/设备文件目标 (`echo x > /dev/null`) 而非恶意写入, 列入敏感路径会误伤
    # (官方测试 test_safety_redline_fix::test_dd_block_device_blind_spot_closed)。
    # 覆盖写入方向: 重定向 >、tee、cp/mv/install/ln 的**末操作数**, 以及 dd of=。
    # ① 重定向 / tee: 本身即写入动作, 无"源/目标"歧义 → 出现敏感路径即命中。
    #    例外: /var/log/<app>/ 应用日志追加属常规运维, 不拦 (但系统级日志仍拦)。
    (r"(?:>+\s*|tee\s+)"
     r"(?!/var/log/(?!syslog|auth\.log|messages|secure|kern\.log|dpkg\.log|wtmp|btmp|lastlog\b))"
     r"(?:/etc/|/usr/|/bin/|/sbin/|/lib(?:64)?/|/boot/|/root/|/sys/|/proc/|/var/|"
     r"~?/\.ssh/|~?/\.aws/|~?/\.config/|~?/\.bashrc|~?/\.bash_profile|~?/\.profile|"
     r"~?/\.zshrc|~?/\.zprofile|~?/\.env\b)",
     "write sensitive path (写入/覆盖系统或用户敏感路径)"),
    # ② cp/mv/ln/install: 锚定**最后一个操作数** (\S*\s*$), 并排除 /usr/local/。
    #    修复前 ln/install 用 [^\n]* 会匹配到命令中段, 把"源"当成"目标" → 误报
    #    (如 `ln -s /usr/bin/python3 py`、`install -m 755 app /usr/local/bin/app`)。
    (r"\b(?:cp|mv|ln|install)\b[^\n]*\s"
     r"(?:/etc/|/usr/(?!local/)|/bin/|/sbin/|/lib(?:64)?/|/boot/|/root/|/sys/|/proc/|/var/|"
     r"~?/\.ssh/|~?/\.aws/|~?/\.config/|~?/\.bashrc|~?/\.bash_profile|~?/\.profile|"
     r"~?/\.zshrc|~?/\.zprofile|~?/\.env\b)\S*\s*$",
     "write sensitive path target (写入目标为系统/用户敏感路径)"),
    # ③ 兜底: 覆盖已知系统二进制 —— 即使落在 /usr/local/bin (被②排除) 仍须 critical。
    (r"\b(?:cp|mv|ln|install|tee)\b[^\n]*/(?:usr(?:/local)?/s?bin|s?bin|usr/sbin)/\s*"
     r"(?:sudo|su|doas|passwd|login|init|ssh|sshd|python3?|perl|ruby|node|curl|wget|git|"
     r"bash|sh|zsh|ls|cat|ps|kill|systemctl|crontab|at|chsh|usermod)\s*$",
     "overwrite system binary (覆盖系统二进制, 后门持久化)"),
    # setfacl 提权: 修改 ACL 指向系统目录或关键文件。
    (r"\bsetfacl\b[^\n]*(?:/etc\b|/usr\b|/bin\b|/sbin\b|/root\b|/var\b|~?/\.ssh/)",
     "setfacl on system path (ACL 篡改系统路径)"),
    # useradd/usermod 带 -o -u 0 / -g 0 (UID 0 后门账户) —— 补充已有规则未覆盖的
    # `-o -u 0 -g 0` 组合 (已有规则只覆盖 -u 0 / --uid 0, 但 `-o` 组合写法更隐蔽)。
    (r"\b(?:useradd|usermod|adduser)\b[^\n]*(?:-o\b|--non-unique\b)",
     "useradd -o (允许重复 UID, 可创建 UID 0 后门)"),
    # tee 写入系统配置目录 (heredoc 形态 `tee -a /etc/... <<<`), 已有 cat> 覆盖但 tee 漏。
    (r"\btee\b[^\n]*(?:/etc/|/usr/|/bin/|/sbin/|/boot/|/root/|/var/)",
     "tee write system path (tee 写入系统路径, 持久化)"),

    # ---- V-04 供应链与发布操作 (不可逆) ----
    # gh repo delete: 删除远程仓库 (不可逆)。
    (r"\bgh\s+repo\s+delete\b", "gh repo delete (删除远程仓库, 不可逆)"),
    # git filter-branch --force: 改写历史 (不可逆, 影响所有协作方)。
    (r"\bgit\s+filter-branch\b[^\n]*--force\b", "git filter-branch --force (改写历史, 不可逆)"),
    # git remote set-url: 劫持推送目标。
    (r"\bgit\s+remote\s+set-url\b", "git remote set-url (劫持推送目标)"),
    # git push --mirror: 镜像推送 (覆盖远端所有引用)。
    (r"\bgit\s+push\b[^\n]*--mirror\b", "git push --mirror (镜像推送, 覆盖远端)"),
    # git gc --prune=now: 强制 GC, 清除 reflog (不可逆)。
    (r"\bgit\s+gc\b[^\n]*--prune=now\b", "git gc --prune=now (强制 GC, 清除引用)"),
    # npm publish: 发布包 (若 access public 则公开泄露; 即使 restricted 也可能发布错误版本)。
    (r"\bnpm\s+publish\b", "npm publish (发布 npm 包)"),
    (r"\byarn\s+publish\b", "yarn publish (发布 yarn 包)"),
    (r"\bpnpm\s+publish\b", "pnpm publish (发布 pnpm 包)"),
    # 依赖混淆: pip install 使用非默认/不可信 index-url / extra-index-url。
    (r"\bpip[0-9.]*\s+install\b[^\n]*(?:--index-url|--extra-index-url|-i\b)",
     "pip install custom index (依赖混淆, 从自定义源拉取)"),
    # npm install 使用非默认 registry (依赖混淆)。
    (r"\bnpm\s+(?:install|i|ci)\b[^\n]*--registry\b",
     "npm install custom registry (依赖混淆)"),
    (r"\byarn\s+(?:install|add)\b[^\n]*--registry\b",
     "yarn install custom registry (依赖混淆)"),
    # pip uninstall -y 静默卸载 (不可逆, 破坏环境)。
    (r"\bpip[0-9.]*\s+uninstall\b[^\n]*-\s*y\b",
     "pip uninstall -y (静默卸载核心依赖)"),
    # NPM 供应链投毒: install 含 preinstall/postinstall/install 关键词的包名
    # (包名伪装成含恶意 lifecycle hook 的已知包变体, 如 `ua-parser-js-preinstall`)。
    # 真实攻击: npm 生态中多次出现这类伪装包, postinstall 脚本执行 C2 payload。
    (r"\bnpm\s+(?:install|i|add)\b[^\n]*\b([A-Za-z0-9._-]+[-_](?:preinstall|postinstall|install|prepare|prepublish))\b",
     "npm install suspicious lifecycle hook pkg (疑似含恶意 preinstall/postinstall 的包)"),
    # 两段式下载执行: curl/wget/iwr 下载文件后接 && 或 ; + 解释器/直接执行。
    # 文档 V-11 标记为架构上限, 但正则可在单行内识别 download+execute 组合。
    # 不匹配 `curl ... | sh` 管道式 (已有 pipe to shell 规则覆盖), 只覆盖 && / ; 两段式。
    (r"(?:\bcurl\b|\bwget\b|\bInvoke-WebRequest\b|\biwr\b)[^\n]*https?://"
     r"[^\n]*(?:&&|;)[^\n]*\b(?:bash|sh|zsh|ksh|fish|dash|ash|csh|tcsh|python\d*|perl|ruby|node|php|lua|powershell|pwsh|cmd)\b",
     "two-step download then interpreter exec (下载文件后接解释器执行, GuardFall V-11)"),
    # 两段式变体: 下载文件后 chmod +x && 直接执行二进制 (不经过解释器)。
    (r"(?:\bcurl\b|\bwget\b|\biwr\b)[^\n]*https?://[^\n]*(?:&&|;)[^\n]*"
     r"\bchmod\b[^\n]*(?:\+x|\b7\d{2}\b)[^\n]*(?:&&|;)[^\n]*/(?:tmp|var|home|etc)/[^\s]*",
     "download + chmod +x + exec (下载后 chmod +x 并直接执行)"),
    # 两段式变体: 下载并覆盖已知二进制路径 (后续执行时自动触发)。
    (r"(?:\bcurl\b|\bwget\b|\biwr\b)[^\n]*https?://[^\n]*(?:\s|\|\s*)[>/]+[^\n]*"
     r"/(?:usr|usr/local|bin|sbin|etc|root)/[A-Za-z0-9_.-]+\b",
     "download overwrites system bin (下载并覆盖系统二进制路径)"),
    # git clone 从明显可疑域名 (供应链投毒)。
    # 只拦截含恶意特征关键词的域名 (evil/malware/trojan/backdoor/exploit/payload/c2 等)
    # 或直接用 IP 地址的 git clone (典型的临时 C2/投毒服务器)。
    # 排除法 (仅白名单 github/gitlab/bitbucket 外全部拦截) 会误伤良性域名
    # (test_shell_safety_guard::test_benign_commands_recognized 明确要求
    # `git clone https://example.com/repo.git` 为良性)。
    (r"\bgit\s+clone\b[^\n]*https?://"
     r"(?:[\d]{1,3}\.[\d]{1,3}\.[\d]{1,3}\.[\d]{1,3}"
     r"|[^\s/]*(?:evil|malware|trojan|backdoor|exploit|payload|c2|botnet|ransom|worm)[^\s/]*)",
     "git clone suspicious host (从可疑域名/IP 克隆仓库, 供应链投毒)"),
    # git submodule update --init --recursive + 从不可信 URL: 供应链投毒。
    (r"\bgit\s+submodule\s+update\b[^\n]*--recursive\b",
     "git submodule update --recursive (子模块投毒风险)"),

    # ---- V-06 云 / 编排 / 分布式存储删除类 ----
    (r"\betcdctl\b[^\n]*\b(?:del|delete|purge)\b", "etcdctl del (删除 etcd 键)"),
    (r"\bconsul\s+kv\s+(?:delete|del)\b", "consul kv delete (删除 Consul 键)"),
    (r"\bvault\s+kv\s+(?:delete|destroy)\b", "vault kv delete (删除 Vault 密钥)"),
    # sysctl 关闭安全特性 (ASLR / Yama 等)。
    (r"\bsysctl\b[^\n]*-w\b[^\n]*kernel\.(?:randomize_va_space|yama|kptr_restrict|dmesg_restrict)",
     "sysctl disable security (关闭内核安全特性)"),
    # iptables 清空全部规则 (-F 已有 high; -X 清空自定义链一并拦截)。
    (r"\biptables\b[^\n]*\s-X\b", "iptables -X (清空自定义链)"),
    # ufw disable (已有 high 兜底, 但此处显式强化为 critical 语义? 保持 high 即可, 不重复)。
    # setenforce 0 已有 critical (见上), 不重复。

    # ---- V-09 破坏性删除与日志擦除 ----
    # unlink: rm 的同义命令。
    (r"\bunlink\b[^\n]*\s(?:/etc/|/usr/|/bin/|/sbin/|/boot/|/root/|/var/|/home/)",
     "unlink system path (unlink 删除系统路径)"),
    # set +o history / set -o history 关闭命令历史 (反取证)。
    (r"\bset\s+[+-]o\s+history\b", "set +o history (关闭命令历史, 反取证)"),
    # history -c / clear history (已有 history -c 在 high, 但 `history -c` 在 _HIGH 已列, 补 `fc -l` 无需)。
    # shred -u (已有 shred 在 critical), 但补 `shred -u` 明确 (已有覆盖)。

    # ---- V-05 解释器内联载荷: 网络外泄 + 敏感文件读取组合 ----
    # Python: import socket / urllib / requests + connect/urlopen/post 的组合 (外泄)。
    (r"(?=[^\n]*\b(?:import\s+(?:socket|urllib|requests|ftplib|smtplib|http\.client|aiohttp|httpx)\b)"
     r")(?=[^\n]*(?:\.connect\s*\(|urlopen\s*\(|\.post\s*\(|\.request\s*\(|\.send\s*\())(?=[^\n]*"
     r"(?:open\s*\([^\n]*(?:/etc/|/home/|/root/|~?/\.ssh|~?/\.aws|id_rsa|\.env\b|credentials|shadow|passwd)))",
     "interpreter network exfil (解释器内联网络外泄)"),
    # Node: require('net')/http + connect/request + fs.readFileSync 敏感文件。
    (r"(?=[^\n]*\b(?:require\s*\(\s*['\"](?:net|http|https|dgram|tls)['\"]|fetch\s*\())(?=[^\n]*"
     r"(?:connect\s*\(|request\s*\(|fetch\s*\())(?=[^\n]*"
     r"(?:readFileSync\s*\([^\n]*(?:/etc/|/home/|/root/|~?/\.ssh|~?/\.aws|id_rsa|\.env\b|credentials|shadow|passwd)))",
     "node network exfil (Node 内联网络外泄)"),
    # Node http.get / http.post + fs.readFileSync 敏感路径外泄。
    # 用连续匹配 (不嵌套 lookahead), 只要同个命令里同时出现: http 模块 + .get 调用
    # + 敏感路径 + fs.readFileSync 就判定为外泄。
    (r"(?:require\s*\(\s*['\"]http['\"]\)|require\s*\(\s*['\"]https['\"]\)|require\s*\(\s*['\"]fetch['\"]\))"
     r"[^\n]*\.(?:get|post)\s*\([^\n]*"
     r"(?:require\s*\(\s*['\"]fs['\"]\)|readFileSync)"
     r"[^\n]*(?:/etc/|/root/|/home/|~?/\.ssh|~?/\.aws|id_rsa|\.env\b|credentials|shadow|passwd)",
     "node http.get + fs.readFileSync (Node http.get 组合文件读取外泄)"),
    # 反弹 shell / 反向连接 (无敏感文件, 但 socket 外连本身就是外泄通道)。
    # 覆盖 python/perl/ruby/node 内联 socket.connect + subprocess/exec/system/dup2 的
    # 反向 shell 形态。doc V-05 实测: python socket.connect → none。
    (r"(?=[^\n]*\b(?:socket\.socket|socket\.create_connection|socket\.socketpair)\s*\()(?=[^\n]*"
      r"(?:\.connect\s*\(|\.send\s*\(|\.sendall\s*\())(?=[^\n]*"
      r"(?:subprocess|os\.system|os\.exec|exec\s*\(|Popen|dup2|pty\.spawn))",
      "reverse shell (解释器内联反弹 shell / 反向连接)"),

    # ==================== 独立评测补丁 (VULN-2026-10) ====================
    # 依据 Tuan-CLI-全量冒烟验证报告.md 的安全围堵方案补漏。
    # 本段落与既有第四轮 V-02~V-09 互补: 补入报告指出但第四轮写法未覆盖的条目,
    # 以及报告唯一新增真漏洞 (云元数据 IMDS 探测)。

    # ---- V-02 补: Set-ExecutionPolicy Bypass (绕执行策略, 常配合下载即执行) ----
    (r"\bpowershell(?:\.exe)?\b[^\n]*-ExecutionPolicy\s+Bypass\b",
     "PS ExecutionPolicy Bypass (绕过执行策略)"),
    # ---- V-03 补: chown -R 用户主目录 (递归变更用户目录所有权, 数据失权) ----
    (r"\bchown\b(?=[^\n]*\s-[Rr]\b)(?=[^\n]*\s/home(?:/[^/\s]+)?(?:\s|$))",
     "chown -R home dir (递归变更用户目录所有权)"),
    # ---- V-05 补: 解释器内联读取敏感文件 (命令名驱动的 secret read 缺口) ----
    (r"\b(?:python|python3|python\d|perl|ruby|node|php|lua|awk|gawk)\b[^\n]*\s-[ce]\b"
     r"[^\n]*(?:id_rsa|id_ed25519|authorized_keys|\.aws/credentials|/etc/(?:passwd|shadow)|"
     r"\.env\b|\.npmrc|\.git-credentials|\.docker/config\.json)",
     "interp secret read (内联脚本读取敏感文件)"),
    # ---- V-03 补: chmod 移除敏感文件权限 (原为 medium) ----
    (r"\bchmod\b[^\n]*\b0{3,4}\b[^\n]*\s/(?:etc|usr|var|home|root|boot)/",
     "chmod 000 system file (移除系统文件权限)"),
    # ---- V-09 补: history -c (原为 high/medium, 反取证) ----
    (r"\bhistory\s+-c\b", "history -c (清空命令历史, 反取证)"),
    # ---- 第二轮冒烟补漏: 清空凭据 hive / 抹除磁盘 (凭据窃取前奏) ----
    (r"\bClear-Content\b[^\n]*(?:SAM|SECURITY|SYSTEM\\config|ntds\.dit|shadow)",
     "Clear-Content credentials (清空凭据文件, 破坏性)"),
    (r"\bClear-Disk\b[^\n]*-(?:RemoveData|RemoveOEM|Sanitize)",
     "Clear-Disk (抹除磁盘全部数据)"),
    (r"\bClear-Disk\b", "Clear-Disk (清空磁盘, 数据毁灭)"),
    # Start-Process 启动被编码/混淆载荷的进程
    (r"\bStart-Process\b[^\n]*(?:-(?:EncodedCommand|enc|e|ec)\b|"
     r"(?:-ArgumentList|-Args?)\s+['\"][^'\"]*-e(?:nc|c)?\s+[A-Za-z0-9+/=]{16,})",
     "Start-Process encoded payload (启动编码载荷进程)"),
    # ---- 第二轮冒烟补漏: 数据外泄 (命令名驱动 -> 语义驱动) ----
    # curl/wget/httpie 带文件内容 POST/PUT 上传
    (r"\b(?:curl|wget|http|httpie|xh)\b[^\n]*(?:-(?:d|T|F|data|data-raw|data-binary|upload-file)\s|"
     r"--(?:data|data-raw|data-binary|upload-file)\b)[^\n]*@\s*\S+",
     "curl upload file (上传本地文件内容, 外泄)"),
    # PowerShell Invoke-RestMethod/irm 带 Body 且 Body 含本地文件读取
    (r"\b(?:Invoke-RestMethod|irm|iwr|Invoke-WebRequest)\b[^\n]*"
     r"(?:-(?:Method|m)\s+(?:POST|PUT)|-(?:Body|b)\b)[^\n]*"
     r"(?:Get-Content|cat|gc\b|type\b|Import-Csv|ConvertTo-Json|[A-Za-z]:\\\\|~?/|\./)",
     "PS irm POST body (带本地内容的外发请求, 外泄)"),
    # 邮件外带附件 (经典 exfil 通道)
    (r"\bSend-MailMessage\b[^\n]*-(?:Attachments?|Body)\b",
     "Send-MailMessage attach (邮件外带附件/正文, 外泄)"),

    # ---- 第二轮冒烟补漏: 云元数据服务 (IMDS) 凭据窃取 —— 报告唯一新增真漏洞 ----
    # 攻击者拿 shell 后第一件事就是打 IMDS 拿临时云凭证横向移动 (真实攻击链第一步)。
    # 覆盖 AWS / Azure / 阿里云 / GCP / AWS IPv6 全部探测形态。
    (r"(?:curl|wget)\b[^\n]*(?:169\.254\.169\.254\b|100\.100\.100\.200\b|"
     r"metadata\.google\.internal\b|\[fd00:ec2::254\])",
     "cloud IMDS probe (云元数据服务探测, 凭据窃取)"),
]

_HIGH_PATTERNS = [
    # 远程访问通道停用 = 服务器被锁在门外 (有控制台可恢复, 故列 high 而非 critical)。
    # 修复前 `systemctl stop sshd` 只落到 medium 的通用「停止服务」兜底, 实际判 allow,
    # 随机种子真实场景基准里反复漏放。`systemctl` 是「动作在前」, `service` 是
    # 「服务名在前」, 两种语序都要覆盖。
    (r"\b(?:systemctl)\s+(?:stop|disable|mask)\b[^\n]*\b(?:sshd?|ssh[-_]?server|openssh)\b",
     "stop ssh service (停用 SSH, 远程访问被锁死)"),
    (r"\bservice\s+(?:sshd?|ssh[-_]?server|openssh)\s+(?:stop|disable|halt)\b",
     "service ssh stop (停用 SSH, 远程访问被锁死)"),
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
    (r"git\s+reset\s+--hard", "git reset --hard (硬重置)"),
    (r"ALTER\s+TABLE\s+.*\s+DROP", "alter table drop column (修改表结构删除列)"),
    (r"UPDATE\s+.*\s+SET.*WHERE.*=", "bulk update (批量更新数据)"),
    # 管道到 shell 解释器执行 (仅当 | 后紧跟解释器时才算, 避免 `ps | grep bash` 误匹配)
    (r"\|\s*(?:sh|bash|zsh|ksh|fish|dash|ash|csh|tcsh|python\d*|perl|ruby|node|php|lua|powershell|pwsh|cmd)\b",
     "pipe to shell (管道到 shell 执行)"),
    # V-10: tar 归档通过管道送到远端 ssh (打包整个工作区外泄)。
    # 原 ssh remote exec 一刀切 high 规则被移除后, 此条补位数据外泄检测。
    # 不需要敏感路径关键词 —— 打包 `.` / `*` 本身就是外泄。
    (r"\btar\b[^\n]*\|\s*ssh\b", "tar pipe to ssh (归档通过 SSH 管道外泄)"),
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
    # 日志写入: 覆盖/清空系统日志, 影响范围限于单个日志文件。
    # 只提示写 /var/log 根下的系统日志; 应用日志子目录 (/var/log/<app>/) 不打扰。
    (r"(?<!>)>\s*/var/log(?!/(?:[\w.-]+/))", "overwrite system log (覆盖/清空系统日志)"),
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
