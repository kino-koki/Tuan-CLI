"""危险红线模式库与判定 (safety_engine 拆分模块)。

承载 CRITICAL / HIGH / MEDIUM 模式库、token 化判定 (rm/force push/win 删除/关机/鉴权覆盖)、
良性开发命令降误杀、Base64 管道 / 解释器内联载荷 / 编码字面量 / 提及-执行区分等绕过防御,
以及 EXTREME 极高风险判定。依赖 safety_normalize 的归一化能力。
"""
import base64
import re
import unicodedata

from .safety_normalize import (
    _CMD_SUB_ANY_RE,
    _DASH_MAP,
    _INTERP_RE,
    _cmd_name,
    _decode_ansi_c_escapes,
    _eval_is_unverifiable,
    _normalize,
    _scan_variants,
    _segments,
    _strip_sudo,
    _unicode_clean,
)


def _check_rm_flags(parts: list[str]) -> bool:
    """检查以 rm 为首的 token 序列是否含递归+强制旗标。

    覆盖: rm -rf / rm -r -f / rm --recursive --force / rm dir -rf (旗标后置) 等。
    `--` 之后停止旗标收集。
    """
    long_flags, short_letters = set(), ""
    dash_seen = False          # 是否已见过 - 旗标 (用于合并分离式字母 token)
    for tok in parts[1:]:
        tok = tok.strip("'\"")          # '-rf' / \"-rf\" 引号包裹的旗标
        if tok == "--":
            break
        if tok.startswith("--"):
            long_flags.add(tok.lower())
            dash_seen = True
        elif tok.startswith("-") and len(tok) > 1:
            short_letters += tok[1:]
            dash_seen = True
        # 变量展开把 "-rf" 拆成 "-r" + "f" 的分离式字母 ($F=-rf, $A=R → "$B -$A f /"):
        # 紧跟在 - 旗标之后的单个 r/R/f/F 字母 token 也算作旗标继续, 否则 force 会被
        # 当成普通操作数而漏判 (见 test_nested_variable)。
        elif dash_seen and len(tok) == 1 and tok.lower() in "rf":
            short_letters += tok.lower()
    # rm 无 -F 旗标, 故短旗标统一按小写判定 (覆盖 Windows 上 RM -RF / 写法)
    short_letters = short_letters.lower()
    recursive = "--recursive" in long_flags or "r" in short_letters
    force = "--force" in long_flags or "f" in short_letters
    return recursive and force


def _rm_targets(parts: list[str]) -> list[str]:
    """从 rm 的 token 序列中提取「目标路径操作数」(去掉旗标与 `--` 分隔符)。

    用于区分 `rm -rf /`(删除根) 与 `rm -rf ./build`(清构建产物) —— 二者危险度
    天差地别, 不应同判。识别失败时返回空列表 (调用方按保守/危险处理)。
    """
    targets: list[str] = []
    dash_seen = False
    for tok in parts[1:]:
        tok = tok.strip("'\"")
        if tok == "--":
            dash_seen = True
            continue
        if not dash_seen:
            if tok.startswith("--") or (tok.startswith("-") and len(tok) > 1):
                continue
            # 分离式旗标残留 (`-r` + `f` 拆开时的单字母)
            if len(tok) == 1 and tok.lower() in "rf":
                continue
        targets.append(tok)
    return targets


# 系统级 / 根级 危险删除目标: 删了就是灾难, 必须硬红线。
_DANGEROUS_RM_TARGET_RE = re.compile(
    r"""^(?:
        /                         # 根目录
      | ~/?$                     # 家目录本身
      | \$\{?HOME\}?/?$          # $HOME / ${HOME}
      | /(?:etc|usr|var|bin|sbin|lib|lib64|boot|root|dev|proc|sys|opt|home|srv|run)(?:/|$)
      | [A-Za-z]:[\\/]           # Windows 盘根 (C:\)
      | \\\\                     # UNC 路径
    )""",
    re.VERBOSE,
)


def _is_dangerous_rm_target(target: str) -> bool:
    """判断单个 rm 目标是否属「删除即灾难」的危险目标。

    危险 (True):
      - 根 / 家目录 / $HOME / 占位符 `.` `..` `*` `/*`
      - 绝对系统路径 (`/etc`、`/usr`、`/tmp/x` 等以 `/` 开头)
      - `~` 展开路径、Windows 盘根 (`C:\\`)
      - 非相对前缀的通配 (`*`、`/var/*`)

    安全 (False):
      - 明确的相对路径: `./build`、`build/`、`node_modules`、`dist`、`./*`
      - 变量/占位符形式的相对目标 (`$_build_dir`) —— 无法静态证明危险, 从宽
        (硬红线仍由 `rm -rf /` 这类明确形态兜住)

    空目标 (无操作数) 视为危险 —— `rm -rf` 缺参数不是可安全放行的形态。
    """
    t = target.strip()
    if not t:
        return True
    if t in (".", "..", "*", "/*", "~", "~/"):
        return True
    if t.startswith("~"):              # ~/anything 展开到家目录
        return True
    if _DANGEROUS_RM_TARGET_RE.match(t):
        return True
    if t.startswith("/"):              # 任何绝对路径 (含 /tmp)
        return True
    if t.startswith("\\"):             # Windows 根/UNC
        return True
    # 通配符: 仅当存在「具体的相对目录前缀」时视为安全。
    #   build/*  -> 前缀 build   -> 安全 (清构建目录内容)
    #   ./dist/* -> 前缀 ./dist  -> 安全
    #   ./*      -> 前缀 .       -> 危险 (删除当前目录全部内容)
    #   *        -> 无前缀        -> 危险
    if "*" in t or "?" in t:
        prefix = re.split(r"[*?]", t, maxsplit=1)[0].rstrip("/")
        return prefix in ("", ".", "./")
    return False


def has_dangerous_recursive_rm(text: str) -> bool:
    """递归+强制删除**危险目标** (硬红线判定)。

    与 ``has_recursive_rm`` 的区别: 后者只要 `rm -r -f` 即命中 (不论目标),
    用于「需确认」级别; 本函数额外判定**目标路径危险度** —— 仅当目标是根 / 家目录 /
    绝对系统路径 / 通配等灾难级目标时返回 True。

    `rm -rf ./build`、`rm -rf node_modules`、`rm -rf dist/` 这类清理构建产物的常规
    良性操作**不再**构成硬红线 (降为可确认), 避免把安全做成骚扰。
    `rm -rf /`、`rm -rf ~`、`rm -rf /etc`、`rm -rf *`、`rm -rf ..` 仍为硬红线。
    """
    exec_sink = bool(
        _EXEC_SINK_RE.search(re.sub(r"'[^']*'|\"[^\"]*\"", " ", text))
        or _CMD_SUB_ANY_RE.search(text)
    )
    for seg in _scan_variants(text):
        parts = _strip_sudo(seg.split())
        if not parts:
            continue
        cmd = _cmd_name(parts[0])
        if cmd == "rm":
            if _check_rm_flags(parts) and any(
                _is_dangerous_rm_target(t) for t in _rm_targets(parts)
            ):
                return True
            continue
        if cmd in _TEXT_MENTION_VERBS and not exec_sink:
            continue
        for i, tok in enumerate(parts):
            if _cmd_name(tok) == "rm" and i + 1 < len(parts):
                remaining = [''] + parts[i + 1:]
                if _check_rm_flags(remaining) and any(
                    _is_dangerous_rm_target(t) for t in _rm_targets(remaining)
                ):
                    return True
    return False


# 文本/文档类动词: 其后参数里的 `rm -rf` 只是提及 (搜索词/提交说明/回显),
# 不是要执行的命令, 不应触发递归删除红线 (避免 echo/grep/git commit -m 误杀)。
_TEXT_MENTION_VERBS = frozenset({
    "echo", "cat", "printf", "print", "sed", "awk", "grep", "rg", "ag",
    "head", "tail", "less", "more", "sort", "uniq", "cut", "tr", "journalctl",
    "strings", "xxd", "od", "git", "type", "file",
})


def has_recursive_rm(text: str) -> bool:
    """递归+强制删除: rm -rf / -fr / -r -f / --recursive --force / sudo rm 均命中。

    旗标后置写法 (GNU getopt 重排, 如 `rm dir -rf`) 同样命中 ——
    因此扫描全部 token 收集旗标, 不在首个操作数处截断; `--` 之后的才是真参数。
    判定前先经 _normalize 穿透子壳/变量/引号/解释器间接写法。

    安全修复 v1.5: 文本/文档类动词 (echo/cat/grep/sed/git ...) 后出现的 `rm -rf`
    一律视为"提及"跳过 —— 它们只把字符串当作数据, 不会执行 rm; 真正会执行参数的
    动词 (diff/xargs/find -exec/sh/bash/eval/env/sudo/...) 才做全文 rm 扫描,
    覆盖 `diff rm -rf / /dev/null` / `xargs rm -rf` 等; `$(echo rm) -rf /` 这类
    构造已由 _normalize 命令替换内联成独立 `rm` 段, 走首分支命中。

    安全修复 v1.6: 上述豁免仅在整条命令"没有执行汇"时成立。若文本动词的输出被
    真正送去执行 (printf 'rm -rf /' | sh / echo X | base64 -d | sh / eval ...),
    引号内容就是待执行的命令而非提及 —— 此时必须恢复全文扫描并命中红线。
    """
    # 去掉引号内容后检测执行汇 (管道到 shell / base64 解码 / 命令替换 / eval /
    # xargs / 解释器跑脚本 / 落地为脚本文件), 有汇则取消文本动词豁免。
    # 命令替换 `$(` / 反引号即使被引号包裹也会被真实 shell 先求值再解释 (`'$(echo rm)' -rf /`),
    # 故只要出现在原始命令里就取消豁免, 避免 echo 把 rm 的输出"淡化"成提及而放行。
    exec_sink = bool(
        _EXEC_SINK_RE.search(re.sub(r"'[^']*'|\"[^\"]*\"", " ", text))
        or _CMD_SUB_ANY_RE.search(text)
    )
    for seg in _scan_variants(text):
        parts = _strip_sudo(seg.split())
        if not parts:
            continue
        cmd = _cmd_name(parts[0])
        # 直接 rm 命令
        if cmd == "rm":
            if _check_rm_flags(parts):
                return True
            continue
        # 文本/文档类动词: rm 只是提及, 不是执行 → 跳过 (防误杀)
        if cmd in _TEXT_MENTION_VERBS and not exec_sink:
            continue
        # 其余动词 (diff/xargs/find/sh/bash/eval/env/sudo/未知...): 全文扫描 rm 执行
        for i, tok in enumerate(parts):
            if _cmd_name(tok) == "rm" and i + 1 < len(parts):
                remaining = [''] + parts[i + 1:]  # 空字符串代替 rm 占位
                if _check_rm_flags(remaining):
                    return True
    return False


def has_auth_overwrite(text: str) -> bool:
    """ln 符号链接覆盖系统认证文件: ln -sf X /etc/passwd 等。

    与 has_recursive_rm 相同: 文本/文档类动词后的「提及」跳过, 存在执行汇
    (管道到 shell / base64 解码 / 命令替换 / eval / xargs) 时取消豁免。
    归一化后的 PowerShell -EncodedCommand 解码文本同样进入本判定。
    """
    exec_sink = bool(
        _EXEC_SINK_RE.search(re.sub(r"'[^']*'|\"[^\"]*\"", " ", text))
        or _CMD_SUB_ANY_RE.search(text)
    )
    auth_file = re.compile(r"/etc/(?:passwd|shadow|sudoers|gshadow)\b")
    for seg in _scan_variants(text):
        parts = _strip_sudo(seg.split())
        if not parts:
            continue
        cmd = _cmd_name(parts[0])
        if cmd in _TEXT_MENTION_VERBS and not exec_sink:
            continue
        if any(_cmd_name(t) == "ln" and any(auth_file.search(u) for u in parts[i + 1:])
               for i, t in enumerate(parts)):
            return True
    return False


def has_force_push(text: str) -> bool:
    """强推: git push -f / --force / --force-with-lease[=x], 不受旗标顺序影响;
    `+refspec` (git 强推语法, 如 push origin +main) 同样视为强推。

    全量扫描 push 之后的所有 token (不在首个 remote/refspec 操作数处截断),
    覆盖 `git push origin main --force` 这类旗标后置写法。"""
    for seg in _scan_variants(text):
        parts = seg.split()
        names = [_cmd_name(p) for p in parts]
        if "push" not in names:
            continue
        rest = parts[names.index("push") + 1:]
        short_letters = ""
        for tok in rest:
            if tok == "--":
                break  # -- 之后是纯位置参数, 不再收集旗标
            if tok.startswith("+"):
                return True  # +refspec: git 的强制推送语法
            if tok.startswith("--force"):
                return True  # --force / --force-with-lease[=...]
            if tok.startswith("-") and len(tok) > 1:
                short_letters += tok[1:]
            # 操作数 (remote/refspec) 不截断扫描, 覆盖旗标后置变体
        if "f" in short_letters:
            return True
    return False


def has_win_recursive_delete(text: str) -> bool:
    """Windows 递归删除: del /s /q、rd /s、rmdir /s (同样先归一化)。"""
    for seg in _scan_variants(text):
        parts = seg.split()
        if not parts or _cmd_name(parts[0]) not in ("del", "rd", "rmdir", "erase"):
            continue
        if "/s" in {t.lower() for t in parts[1:] if t.startswith("/")}:
            return True
    return False


def has_system_shutdown(text: str) -> bool:
    """系统关机/重启: shutdown / halt / poweroff / reboot / init 0|6 / systemctl poweroff|reboot|halt。

    同样先归一化, 穿透子壳/变量/引号/解释器间接写法。"""
    SHUTDOWN_TOKENS = {"shutdown", "halt", "poweroff", "reboot"}
    SHUTDOWN_CMDS = {"systemctl"}
    SHUTDOWN_SUB = {"poweroff", "reboot", "halt"}
    for seg in _scan_variants(text):
        parts = _strip_sudo(seg.split())
        if not parts:
            continue
        cmd = _cmd_name(parts[0])
        # shutdown / halt / poweroff / reboot (无参数或带参数均命中)
        if cmd in SHUTDOWN_TOKENS:
            return True
        # init 0 / init 6
        if cmd == "init" and len(parts) >= 2 and parts[1] in ("0", "6"):
            return True
        # systemctl poweroff / systemctl reboot / systemctl halt
        if cmd in SHUTDOWN_CMDS and len(parts) >= 2 and parts[1] in SHUTDOWN_SUB:
            return True
    return False


# ------------------------------------------------------------ 致命红线模式库 (label 双语)
# 注: rm 递归强删与 force push 由上方 token 化函数覆盖 (正则易被写法变体绕过), 不再重复列出。
# 这些模式仅作正则补充, 供 score() 与 is_redline 共用, 保证「单一来源」口径一致。
_RAW_DISK = r"/dev/(?:sd[a-z]|nvme\d+n\d+(?:p\d+)?|vd[a-z]|hd[a-z])"

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
    (r"Remove-Item\s+[^\n]*-Recurse\s+[^\n]*-Force", "Remove-Item -Recurse -Force (PowerShell 递归强删)"),
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


def _label_suppressed(label: str) -> bool:
    """判断某个黑名单模式 label 是否被用户本地抑制 (黑名单减负)。

    见 core/blacklist_override.py: 用户可在本地声明抑制某些模式 label 关键字。
    任何异常 (导入失败/读取失败) 一律视为「未抑制」, 保持默认拦截口径。
    """
    try:
        from ..core.blacklist_override import is_suppressed
        return is_suppressed(label)
    except Exception:  # noqa: BLE001
        return False


def _match_any(text: str, patterns) -> bool:
    """任一正则命中即返回 True (忽略大小写)。

    命中前先检查该模式 label 是否被用户本地抑制 (黑名单减负): 被抑制的模式跳过,
    不计入命中。注意这**只**影响正则模式库; rm -rf / force push / shutdown 等
    token 化硬红线走独立判定, 不受此影响。
    """
    for pattern, label in patterns:
        if _label_suppressed(label):
            continue
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


# 文本处理命令: 其参数里出现 drop table / delete from 等只是搜索词, 不算 SQL 红线
_TEXT_UTIL_RE = re.compile(
    r'^\s*(?:grep|egrep|fgrep|rg|ag|echo|sed|awk|print\w*|printf|cat|tac|head|tail|'
    r'less|more|tee|sort|uniq|cut|tr|journalctl|'
    r'git\s+(?:log|diff|show|blame|shortlog)|find\b.*-name|strings|xxd|od)\b',
    re.IGNORECASE,
)


def _sql_redline(command: str) -> bool:
    """SQL 破坏性操作 (DROP/DELETE/TRUNCATE/ALTER...DROP) 的段感知检测。

    _CRITICAL_PATTERNS 里的 SQL 正则若直接对整条命令匹配, 会把
    `grep -i 'drop table'` 这类"搜索词碰巧含 SQL 关键字"的命令误判为红线。
    故逐段判断: 段首是文本处理命令 (grep/echo/sed/...) 时跳过该段,
    仅对真正执行 SQL 的段 (psql -c / mysql -e / 裸 DROP TABLE ...) 判定。
    """
    sql_patterns = [
        p for p in _CRITICAL_PATTERNS
        if p[0].lstrip().upper().startswith(("DROP", "DELETE", "TRUNCATE", "ALTER"))
    ]
    # 先归一化 (展开 IFS / 变量 / 引号 / 解释器间接写法), 再逐段判定,
    # 否则 `DROP$IFS$9 TABLE` 这类变量分隔混淆会漏判。
    # 用 _scan_variants 同时扫描「原始 + 归一化」: 归一化会剥掉 dropDatabase() 的括号
    # (cleaned 阶段 strip("()")), 导致 `dropDatabase\s*\(` 正则失配, 故必须保留原始文本段。
    #
    # 安全修复: 文本工具豁免仅在"没有执行汇"时成立。若文本工具的输出被真正送去
    # 执行 (echo 'DROP TABLE users;' | sh -c 'cat' / | mysql / | base64 -d | sh),
    # 引号内 SQL 就是待执行的语句而非搜索词 —— 必须恢复判定, 否则形成绕过。
    exec_sink = bool(
        _EXEC_SINK_RE.search(re.sub(r"'[^']*'|\"[^\"]*\"", " ", command))
        or _CMD_SUB_ANY_RE.search(command)
    )
    for seg in _scan_variants(command):
        if _TEXT_UTIL_RE.match(seg) and not exec_sink:
            continue
        if _match_any(seg, sql_patterns):
            return True
    return False


# ------------------------------------------------------------ 良性开发命令 (降误杀)
# 这些命令本身是日常开发操作, 不应被升级为 high/critical 而误杀/打断。
# 与「硬红线」(is_hard_redline) 是两层: 硬红线在护栏 step1 先判, 仍会拦截
# rm -rf /、dd、mkfs、force push 等不可逆破坏; 本表只防止把常见开发命令误判。

_SAFE_GIT_SUBCMDS = frozenset({
    "status", "diff", "log", "show", "branch", "remote", "fetch", "tag", "stash",
    "blame", "rev-parse", "ls-files", "shortlog", "describe", "config", "help",
    "add", "commit", "clone", "pull", "merge", "rebase", "switch", "restore", "mv",
    "submodule", "worktree", "init",
})

# 普通 (非 git) 良性命令前缀 / 精确名
_BENIGN_PREFIXES = (
    # 文件读取 / 查看
    "cat ", "head ", "tail ", "less ", "more ", "ls ", "ll ", "tree ", "grep ",
    "egrep ", "fgrep ", "rg ", "ag ", "wc ", "file ", "find ", "which ", "where ",
    "type ", "pwd ", "echo ", "printf ", "awk ", "sed -n", "sort ", "uniq ", "cut ",
    "diff ", "cmp ", "stat ", "readlink ", "realpath ", "dirname ", "basename ",
    "nl ", "column ",
    # 进程 / 任务查询 (只读)。权限与服务管理 (chmod/chown/systemctl/service) 是双刃剑,
    # 不能按前缀无条件放行 —— 改由 _conditional_benign 按参数形态判定 (见其注释)。
    "ps ", "top ", "jobs ", "crontab -l ",
    # 文件写入 / 构建 (非破坏性)
    "touch ", "mkdir ", "cp ", "mv ", "tee ", "ln ",
    # 目录切换 / 环境变量 / 无副作用外壳原语 (命令链前缀段, 单段无害)
    "cd ", "export ",
    # 包管理 / 构建
    "pip ", "pip3 ", "poetry ", "conda ", "uv ", "npm ", "pnpm ", "yarn ", "cargo ",
    "go ", "make ", "cmake ", "apt ", "apt-get ", "brew ", "dpkg ", "pip install",
    "pip uninstall", "npm i", "npm ci", "npm run", "npx ",
    # 测试 / lint / 类型 (本地, 非破坏性)
    "pytest", "python -m pytest", "python -m unittest", "python -m tox", "tox ",
    "python ", "python3 ", "node ", "nodejs ",
    "jest ", "mocha ", "vitest ", "coverage ", "ruff ", "black ", "isort ",
    "flake8 ", "mypy ", "pylint ", "pre-commit ", "eslint ", "tsc ",
)
_BENIGN_EXACT = frozenset({"pytest", "tox", "ls", "pwd", "true", ":"})

# IFS 混淆展开 (良性识别专用): 与红线 _normalize 同一口径, 仅用于良性匹配前的归一。
# 覆盖 `t_ifs` 的全部形态: ${IFS} / $IFS$9 / ${IFS}$9 (尾随 $N 数字一并吞掉,
# 否则 `aws${IFS}$9s3` 展开后残留 $9 干扰 token 化)。
_IFS_BENIGN_RE = re.compile(r"\$\{ifs\}\$?[0-9]*|\$ifs\$?[0-9]*", re.IGNORECASE)

# ------------------------------------------------------------ 条件化良性判定
# 有些命令是"双刃剑": 同一命令名既能只读查询也能搞破坏 (nc 可探测端口也可弹 shell、
# tar 可打包也可解到系统目录、云 CLI 可 list 也可 delete)。这类不能按前缀无脑放行,
# 必须按参数形态区分 —— 只在**能证明只读/局部**时才降级, 凡有一丝"外传/执行/系统写入"
# 可能就交回红线判定 (fail-closed)。硬红线 (is_hard_redline) 始终独立判定, 不受影响。
_CONTAINER_READONLY_RE = re.compile(
    r'\b(?:docker|podman)\s+(?:ps|images|logs|inspect|stats|version|info|top|history)\b'
    r'|\bkubectl\s+(?:get|describe|logs|version|cluster-info|api-resources|config\s+view)\b'
    r'|\bhelm\s+(?:list|ls|status|get|history|show|version)\b',
    re.IGNORECASE,
)
# 云 CLI: 只放行 list/describe/get/show/whoami 等只读语义子命令。
# delete/rm/cp/mv/put/exec 等一律不在此列 —— 即使写作 `aws s3 rm --recursive` 也照常升级。
_CLI_READONLY_RE = re.compile(
    r'\b(?:aws|az|gcloud|oci|doctl|terraform\s+output|tofu\s+output)\s+',
    re.IGNORECASE,
)
_CLI_READONLY_VERB_RE = re.compile(
    r'\b(?:list|ls|describe|get|show|whoami|version|help|account\s+show)\b',
    re.IGNORECASE,
)
# tar: 打包/解包/查看。必须**段首**就是 tar —— `ssh host tar xf -` 里 tar 只是远端载荷,
# 按段首匹配可避免把远程解压误判为本地打包。含管道视为潜在外传, 不降级。
_TAR_RE = re.compile(r'^tar\d*\s', re.IGNORECASE)
_TAR_HAS_FILE_OP_RE = re.compile(r'\b[ctxjzJZv]*[f]\b')
_TAR_SYS_TARGET_RE = re.compile(
    r'(?:^|\s)-[a-zA-Z]*C\s*(?:/(?:etc|usr|sys|boot|dev|bin|sbin|lib|proc)\b|/)'
    r'|(?:^|\s)-C\s*$',
    re.IGNORECASE,
)
# nc: 仅 -z (握手探测, 不传数据) 降级; -e/-c/--exec/--sh-exec (绑定 shell) 绝不降级。
_NC_RE = re.compile(r'\b(?:nc|ncat|netcat|nc\.exe)\s+', re.IGNORECASE)
_NC_SCAN_RE = re.compile(r'\s-z\b|\s-zv\b|\s-zvw\b')
_NC_EXEC_RE = re.compile(r'\s-[a-z]*[ec]\b|--(?:exec|sh-exec|lua-exec|cmd)\b', re.IGNORECASE)
# rsync: 同步/备份是日常开发操作; 仅含 --delete / --remove-source-files / --delete-* (远端
# 或源端删除) 才交回红线判定。普通 `rsync -a ./src host:/back/` 判良性。
_RSYNC_RE = re.compile(r'\brsync\b', re.IGNORECASE)
_RSYNC_DESTRUCTIVE_RE = re.compile(
    r'--delete(?:-after|-before|-during|-excluded)?|--remove-source-files', re.IGNORECASE)
# scp: 文件复制是日常开发操作, 判良性 (危险方向 `scp evil host:/x && ssh host ...` 因 ssh
# 段非良性, 整体仍交回红线; 此处只放行单纯复制)。
_SCP_RE = re.compile(r'\bscp\b', re.IGNORECASE)

# chmod/chown: 双刃剑, 由危险模式库反向判定 —— 不命中任何 critical/high/medium 模式才判
# 良性 (chmod +x / chown user:group 等日常操作); 命中 (chmod 000/777、chmod -R 000 /、
# chown root、chown -R / 等) 一律交回模式评分。此前它们是无条件良性前缀,
# 导致 `chmod -R 000 /` 被判 none、`systemctl stop nginx` 漏掉 medium, 与红线口径不一致。
_CHMOD_CHOWN_RE = re.compile(r'\b(?:chmod|chown)\b', re.IGNORECASE)
# systemctl: 仅只读子命令判良性 (status/show/list-*/is-*/cat/help/daemon-reload/get-default/version);
# stop/start/restart/enable/disable/mask/kill/isolate/poweroff 等有状态变更/破坏语义, 一律不判良性。
_SYSTEMCTL_READONLY_RE = re.compile(
    r'\bsystemctl\s+(?:status|show|list-\w+|is-\w+|cat|help|daemon-reload|get-default|version)\b',
    re.IGNORECASE,
)
# service: 仅 status / --status-all 判良性; stop/start/restart 等交回模式评分或严格确认。
_SERVICE_READONLY_RE = re.compile(
    r'\bservice\s+(?:--status-all|status)\b|\bservice\s+\S+\s+status\b',
    re.IGNORECASE,
)


def _conditional_benign(s: str) -> bool:
    """双刃剑命令的条件化良性判定 (见上方注释): 证明只读/局部才降级, 否则交回红线。"""
    if _CONTAINER_READONLY_RE.search(s):
        return True
    if _CLI_READONLY_RE.search(s) and _CLI_READONLY_VERB_RE.search(s):
        return True
    if _TAR_RE.search(s):
        # -C 指向系统目录 / 绝对路径根: 不降级; 含管道: 疑外传, 不降级
        if _TAR_SYS_TARGET_RE.search(s) or "|" in s:
            return False
        return bool(_TAR_HAS_FILE_OP_RE.search(s))
    if _NC_RE.search(s):
        return bool(_NC_SCAN_RE.search(s)) and not _NC_EXEC_RE.search(s)
    if _RSYNC_RE.search(s):
        return not _RSYNC_DESTRUCTIVE_RE.search(s)
    if _SCP_RE.search(s):
        return True
    if _CHMOD_CHOWN_RE.search(s):
        # chmod/chown 无危险模式命中才判良性 (反向判定, 与 score() 口径一致)
        return not _match_any(s, _CRITICAL_PATTERNS + _HIGH_PATTERNS + _MEDIUM_PATTERNS)
    if _SYSTEMCTL_READONLY_RE.search(s):
        return True
    if _SERVICE_READONLY_RE.search(s):
        return True
    return False

# 系统关键路径: 命中则即使前缀良性也保留原风险 (不降级), 避免静默放过系统写入
_SYSTEM_PATH_RE = re.compile(
    r"[>\s](?:/etc/|/dev/|/sys/|/boot/|/usr/lib/|~?/\.ssh/|~?/\.aws/|id_rsa|\.env\b|c:\\\\windows|%systemroot%)",
    re.IGNORECASE,
)

# 良性前缀命令内的"壳子跳板"暗示: 命中即按非良性处理。
# 目的是堵住「看似良性的命令(awk/cat/echo/find/python -m ...)借壳执行危险动作」的绕过:
#   awk '{system("rm -rf /")}'、find . -exec rm、echo "$(...)" | sh、cmd /c ...、powershell ... 等。
# 这类命令一旦被误判为良性, 在可信区会绕过严格确认直接执行; 故命中这里统一降级为非良性,
# 由上层 (strict 确认 / 高危多级确认) 接管。覆盖词(如 system()/powershell)出现在普通
# 文本/grep 里造成的少量误报, 只是把命令从"自动放行"降级为"需人工确认", 不会误杀越权。
_EMBEDDED_EXEC_RE = re.compile(
    r"\$\(|`|system\s*\(|popen\s*\(|eval\s*\(|exec\s*\(|"
    r"(?:cmd|sh|bash|zsh|ksh|dash|fish|pwsh)\s*-c\b|"
    r"[- ]-exec\b|[- ]-delete\b|--force\b|"
    r"powershell(?:\.exe)?\b|pwsh\b|certutil\b|bitsadmin\b|wscript\b|cscript\b|"
    r"\breg\s+(?:add|delete)\b|schtasks\b|sc\s+start\b|net\s*(?:user|localgroup)\b|"
    r"\bbcdedit\b|\bdiskpart\b",
    re.IGNORECASE,
)


def _git_is_benign(seg: str) -> bool:
    """单段 git 命令是否非破坏性 (用于降误杀)。

    - 子命令在白名单内;
    - 若是 push, 不得含 --force / --force-with-lease / -f / +refspec;
    - 若是 checkout, 不得含 '-- .' / -f / --force / --orphan。
    """
    parts = seg.split()
    if len(parts) < 2 or parts[0] != "git":
        return False
    sub = parts[1]
    if sub not in _SAFE_GIT_SUBCMDS:
        return False
    sp = " " + seg
    rest = " ".join(parts[2:])
    if sub == "push" and ("--force" in rest or "--force-with-lease" in rest
                          or " -f" in sp or "+" in rest or "--delete" in rest):
        return False
    if sub == "checkout" and ("-- ." in rest or " -f" in sp or "--force" in rest
                              or "--orphan" in rest):
        return False
    # 破坏性变体: 删除分支 / 丢弃暂存 / 删除标签 / 改写历史 —— 不得判为良性
    if sub == "branch" and (" -D" in sp or " -d" in sp or "--delete" in rest):
        return False
    if sub == "stash" and ("drop" in rest or "clear" in rest):
        return False
    if sub == "tag" and (" -d" in sp or "--delete" in rest):
        return False
    if sub == "rebase" and "--onto" in rest:
        return False
    return True


def _segment_is_benign(seg: str) -> bool:
    # 先做 Unicode 折叠, 与 _normalize 保持同一清洗口径: NFD 解构 → 剥零宽/变体/组合符
    # → NFKC 折叠 → dash 同形字归位。两个原因:
    #   1) 段内 `git branch －D` 的 U+FF0D 不折叠就无法命中下方 ASCII 旗标检查 (" -d" in sp),
    #      会被误判为良性开发命令而放行 (漏放 git 破坏性操作 / 变形后的危险命令)。
    #   2) 零宽字符 (U+200B/200C/200D/2060/FEFF) 会把 `git status` 变成 `git\u200bstatus`,
    #      既匹配不到良性前缀 (良性命令被误报为 flag), 也让命令名比较失真 —— 与危险判定
    #      (_normalize 已清洗) 不对称。剥离只影响含不可见字符的命令, 且只会让判定更准:
    #      `r\u200bm -rf /` 清洗后命中 rm -rf, 良性判定反而正确地给出 False。
    s = unicodedata.normalize('NFD', seg.strip().lower())
    s = _unicode_clean(s)
    s = unicodedata.normalize('NFKC', s).translate(_DASH_MAP)
    # IFS 混淆展开: 与红线判定 (_normalize) 保持同一清洗口径, 让 `git${IFS} status` /
    # `git$ifs$9 status` 归一为 `git status` 后再做良性匹配 (否则会被误判为 flag)。
    s = _IFS_BENIGN_RE.sub(" ", s)
    if not s:
        return True
    if _SYSTEM_PATH_RE.search(s):
        return False
    if _EMBEDDED_EXEC_RE.search(s):
        return False
    if s.startswith("git "):
        return _git_is_benign(s)
    if s in _BENIGN_EXACT:
        return True
    if any(s.startswith(p) for p in _BENIGN_PREFIXES):
        return True
    return _conditional_benign(s)


# ------------------------------------------------------------ Base64 管道检测 (GuardFall D类绕过防御)
# GuardFall 研究发现: echo payload | base64 -d | sh 是一种经典的编码绕过手法。
# 攻击者把恶意命令 base64 编码后通过管道喂给 shell, 绕过基于字符串匹配的护栏。
# 青小团对此做三层防御:
#   1) 检测 base64 -d/-D/--decode 管道到 shell 解释器
#   2) 尝试解码 Base64 内容, 对解码后内容做红线检测
#   3) 对编码+管道组合做 fail-closed 拦截

# Base64 解码命令模式: base64 -d / base64 -D / base64 --decode / base64 -di 等
_BASE64_DECODE_RE = re.compile(
    r'\bbase64\b\s+(?:-[dDiI]|--decode|--ignore-garbage)\b',
    re.IGNORECASE,
)

# 管道到 shell 解释器: | sh / | bash / | zsh / | python / | perl 等。
# 支持绝对路径形态 (| /bin/sh / | /usr/bin/bash) —— 攻击者常借此绕开裸名匹配。
_PIPE_TO_SHELL_RE = re.compile(
    r'\|\s*(?:/[\w./+-]*/)?(?:sh|bash|zsh|ksh|fish|dash|ash|csh|tcsh|python\d*|perl|ruby|node|php|lua)\b',
    re.IGNORECASE,
)

# echo/printf/cat + base64 管道链: echo '...' | base64 -d | sh
_ECHO_B64_PIPE_RE = re.compile(
    r'(?:echo|printf|cat)\b.*?\|\s*base64\b',
    re.IGNORECASE,
)


def _try_decode_base64_segments(text: str) -> list[str]:
    """尝试从命令中提取并解码 Base64 编码的段。

    查找形如 echo 'xxx' | base64 -d 或管道链中的 Base64 内容, 尝试解码。
    返回解码后的文本列表 (可能为空)。

    修复 (跨管道段漏解): 编码串常位于 '|' 之前、而 base64 -d 在 '|' 之后;
    旧实现按 _segments 切分后要求『每个段都含 base64 -d』, 导致承载密文的
    左段被整段跳过、解密永远拿不到 payload。改为: 只要整条命令含 base64 解码,
    就扫描全部段的所有部分提取候选 base64 串。
    """
    decoded: list[str] = []

    def _try_append(candidate: str) -> None:
        try:
            decoded_bytes = base64.b64decode(candidate, validate=True)
            decoded_text = decoded_bytes.decode("utf-8", errors="replace")
            if (all(c.isprintable() or c in '\n\r\t' for c in decoded_text)
                    and len(decoded_text) > 3):
                decoded.append(decoded_text)
        except Exception:  # noqa: BLE001
            pass

    # 仅在命令整体含 base64 解码时才尝试, 避免对普通文本误解码
    if not _BASE64_DECODE_RE.search(text):
        return decoded
    # 匹配引号包裹的 base64 字符串
    b64_string_re = re.compile(r"([A-Za-z0-9+/]{4,}={0,2})")
    # 扫描全部段 (跨管道): base64 命令自身所在的部分跳过, 其余部分提取密文
    for seg in _segments(text):
        for part in seg.split("|"):
            if _BASE64_DECODE_RE.search(part):
                continue  # 跳过 base64 命令本身
            # 引号包裹的 base64 (echo 'xxx' / printf '%s' 'xxx')
            for quote_char in ("'", '"'):
                for m in re.finditer(
                    rf"{quote_char}([^'{quote_char}]+){quote_char}", part
                ):
                    candidate = m.group(1).strip()
                    if b64_string_re.fullmatch(candidate):
                        _try_append(candidate)
            # 裸 base64 token ($(echo xxx | base64 -d) 中 xxx 无引号)
            for m in b64_string_re.finditer(part):
                candidate = m.group(1)
                if len(candidate) < 8:
                    continue  # 太短的不太可能是有效 base64
                _try_append(candidate)
    return decoded


def _is_base64_pipeline_dangerous(command: str) -> bool:
    """检测 Base64 管道到 shell 解释器的危险组合 (GuardFall D类绕过防御)。

    检测逻辑:
    1. 命令是否包含 base64 解码 + 管道到 shell 的组合
    2. 如果是, 尝试解码 base64 内容并对其做红线检测
    3. 任一层命中即返回 True (fail-closed)
    """
    normalized = _normalize(command).lower()
    # 检查是否同时包含 base64 解码和管道到 shell
    has_b64_decode = bool(_BASE64_DECODE_RE.search(normalized))
    has_pipe_shell = bool(_PIPE_TO_SHELL_RE.search(normalized))
    has_echo_b64 = bool(_ECHO_B64_PIPE_RE.search(normalized))
    # 场景1: echo '...' | base64 -d | sh (完整管道链)
    if has_b64_decode and has_pipe_shell:
        # 尝试解码 base64 内容并检测
        decoded_segments = _try_decode_base64_segments(command)
        for seg in decoded_segments:
            if is_redline(seg):
                return True
        # 即使解码失败或内容未命中红线, base64→shell 管道组合本身就是高风险
        # 因为静态分析无法可靠解码所有编码方式, 保守拦截
        return True
    # 场景2: echo payload | base64 -d (无管道到 shell, 但可能通过重定向执行)
    if has_echo_b64 and has_b64_decode:
        decoded_segments = _try_decode_base64_segments(command)
        for seg in decoded_segments:
            if is_redline(seg):
                return True
    return False


# ------------------------------------------------------------ 解释器内联载荷检测
# token 化红线函数按 shell 语法解析「段首命令名」。
# 但 `python -c "shutil.rmtree('/')"` / `perl -e 'system("rm -rf /")'` 这类写法里,
# 段首是 *解释器* 而不是 rm —— 语法完全合法、命令名无害, token 化判定必然失效。
# 这是「合法解释器调用 + 破坏性内联代码」的组合, 必须单独一路检测。

# 内联载荷里的破坏性 shell 片段
_INTERP_PAYLOAD_SHELL_RE = re.compile(
    r"""(
        rm\s+-[rRfF]{1,2}\b                 # rm -rf / rm -fr / rm -r -f
      | rm\s+--(?:recursive|force)\b
      | \bmkfs\b | \bdd\s+if= | \bwipefs\b | \bshred\b
      | \b(?:shutdown|halt|poweroff|reboot)\b
      | DROP\s+(?:TABLE|DATABASE|SCHEMA)
      | DELETE\s+FROM | TRUNCATE\s+TABLE
      | >\s*/dev/(?:sd[a-z]|nvme|vd[a-z]|hd[a-z])
      | :\s*\(\s*\)\s*\{                     # fork bomb
      | \bchown\b(?=[^\n]*\-[Rr]\b)(?=[^\n]*\s/(?:\s|$))   # chown -R ... / (递归变更根所有权)
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# 内联载荷里的破坏性 API 调用 (跨语言)
_INTERP_PAYLOAD_API_RE = re.compile(
    r"""(
        shutil\.rmtree
      | FileUtils\.rm_rf | FileUtils\.remove_entry
      | os\.system | os\.popen | os\.remove | os\.unlink | os\.rmdir | os\.execute
      | subprocess\.(?:run|call|Popen|check_output|check_call)
      | child_process\.execSync | child_process\.exec\s*\(
      | fs\.rmSync | fs\.unlinkSync | fs\.rmdirSync | shelljs\.rm
      | \bsystem\s*\( | \bpopen\s*\( | \bunlink\b | \brmdir\s*\(
      | dropDatabase | \bFLUSHALL\b | \bFLUSHDB\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# awk 无 -c 旗标, 需单独匹配其程序体: awk 'BEGIN{system("...")}'
_AWK_PROGRAM_RE = re.compile(
    r"""\bawk\b(?:[ \t]+-[A-Za-z]+)*[ \t]+('[^']*'|"[^"]*")""",
    re.IGNORECASE,
)

# 程序化调用中的破坏性二进制: 破坏性子命令作为首个字符串参数传给
# system/cmd/exec/run/popen/spawn/Runtime.exec/shutil.rmtree 等跨语言 API。
# 针对性强化: 覆盖 elixir `System.cmd("rm", ["-rf","/"])`、java
# `Runtime.getRuntime().exec("rm -rf /")`、`subprocess.run(["rm","-rf","/"])`
# 这类「旗标被拆成数组元素」的写法 —— 旧的正则要求 rm 紧跟 -rf, 必漏。
_INTERP_PAYLOAD_PROG_RE = re.compile(
    r"""(
        \b(?:system|cmd|exec|run|popen|spawn|runProgram|run_program|shell_exec
          |os\.system|os\.popen
          |subprocess\.(?:run|call|Popen|check_output|check_call)
          |child_process\.exec\w*|Runtime\.getRuntime\(\)\.exec|shutil\.rmtree)
        \s*\([^()]*?
        ["'](?:rm|sh|bash|zsh|mkfs|dd|wipefs|shred|format|del|rd|rmdir|erase)\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# here-string (<<< '...'): kotlin -script - <<< 'Runtime.getRuntime().exec("rm -rf /")'
# 等把代码放在 here-string 而非 -c/-e 参数的写法, 旧实现只抓到 `<<<` 而漏掉真代码。
_HERESTRING_RE = re.compile(r"<<<\s*('[^']*'|\"[^\"]*\")")

# 执行 API 调用后紧跟的字符串参数即"将被执行的命令", 须对其做同样的危险判定。
# 覆盖 node require('child_process').execSync('systemctl mask sshd') 这类用 require
# 引入模块、导致 `child_process.` 字面前缀消失、旧正则 (child_process\.execSync) 失配的写法;
# 同时覆盖 `spawn('rm', ['-rf','/'])` 旗标拆成数组的写法。内层命令经 _normalize 后跑
# 全模式库 (与 score() 口径一致), 故 `systemctl mask` / `chmod 777` / `iptables -F` 等
# 高危子命令也能被穿透检出。
_INTERP_EXEC_ARG_RE = re.compile(
    r"""(?:execSync|execFileSync|execFile|exec|spawnSync|spawn
         |system|popen|run|call|Popen|check_output|check_call
         |os\.system|os\.popen|subprocess\.(?:run|call|Popen|check_output|check_call)
         |Runtime\.getRuntime\(\)\.exec|shutil\.rmtree
         |child_process\.\w+|shelljs\.\w+)
       \s*\([^()]*?['"]([^'"]{1,2000})['"]""",
    re.IGNORECASE | re.VERBOSE,
)


# ------------------------------------------------------------ 编码字面量检测
# 除 Base64 管道外, 经典的静态绕过还有: 
#   printf '\162\155\040-\162\146\040/'           (八进制转义拼出 rm -rf /)
#   printf '\x72\x6d\x2d\x72\x66\x20/'            (十六进制转义)
#   echo 726d202d7266202f | xxd -r -p | sh        (hex 经 xxd 反解码投喂 shell)
# 这些写法把破坏性 shell 片段藏进转义/hex, 静态字符串匹配必漏, 需先解码再判定。

# 解码后是危险 shell 片段 (复用解释器内联负载的 shell 片段正则)
def _decoded_shell_fragment_dangerous(payload: str) -> bool:
    if _INTERP_PAYLOAD_SHELL_RE.search(payload):
        return True
    if re.search(r"\brm\s+-[rRfF]{1,2}\b", payload):
        return True
    # 解码荷可把 -rf 的连字符也一并编码 (\x72\x6d\x2d... = "rm-rf /"), 词间无空格,
    # 上方空白感知正则失配 —— 再补「rm 紧跟连字符旗标」的无空格形式。
    if re.search(r"\brm[-](?:[rRfF]){1,2}\b", payload):
        return True
    return False


# echo/printf/cat 引号字面量 (用于提取转义编码内容)
_ENC_LIT_RE = re.compile(
    r"\b(?:echo|printf|cat)\b[^|\n;]*?(['\"])(.*?)\1", re.IGNORECASE | re.DOTALL)
# xxd -r (hex 到二进制解码)
_XXD_RE = re.compile(r"\bxxd\b[^\n]*-\s*r\b", re.IGNORECASE)
# echo 后的纯 hex 字节串 (允许字节间空格/分隔): 726d202d7266202f
_ECHO_HEX_RE = re.compile(r"\becho\s+([0-9a-fA-F][0-9a-fA-F\s]*[0-9a-fA-F])\b")


def _hex_to_text(candidate: str) -> str | None:
    compact = re.sub(r"\s+", "", candidate)
    if len(compact) < 6 or len(compact) % 2 != 0:
        return None
    if not re.fullmatch(r"[0-9a-fA-F]+", compact):
        return None
    try:
        return bytes.fromhex(compact).decode("utf-8", "replace")
    except ValueError:
        return None


def _is_encoded_literal_dangerous(text: str) -> bool:
    """检测转义/hex 编码字面量是否承载破坏性 shell 片段 (fail-closed)。"""
    # 1) printf/echo/cat 引号字面量内嵌 \xHH / \0OOO / \NNN 转义: 解码后判定.
    #    跳过 `$'...'`/`$"..."` ANSI-C quoting (显式字面量, echo/printf 只打印不执行,
    #    应保持 benign —— 见 test_redline_ansi_c_escape_safe); 仅判定普通引号字面量。
    for m in _ENC_LIT_RE.finditer(text):
        q = m.start(1)                     # 引号字符的起始位置 (非整条匹配起点)
        if q > 0 and text[q - 1] == "$":
            continue  # $'...' ANSI-C quoting: 字面量, 非待执行命令名
        lit = m.group(2)
        if "\\" in lit:
            # 安全修复: 仅在字面量真正用 \xHH / \NNN(八进制) 编码命令名时才 fail-closed;
            # 普通 \n \t \r 等控制转义只是打印格式 (如告警串 "rm -rf is dangerous\n"),
            # 不构成命令混淆, 否则会误杀良性 echo/printf。
            if not re.search(r"\\x[0-9a-fA-F]{2}|\\[0-7]{3}", lit):
                continue
            dec = _decode_ansi_c_escapes(lit)
            if dec and _decoded_shell_fragment_dangerous(dec):
                return True
    # 2) xxd -r 解码 hex 并 (典型地) 管道到 shell: echo <hex> | xxd -r -p | sh
    if _XXD_RE.search(text):
        pipe_to_shell = bool(_PIPE_TO_SHELL_RE.search(text))
        for m in _ECHO_HEX_RE.finditer(text):
            hex_dec: str | None = _hex_to_text(m.group(1))
            if hex_dec is None:
                continue
            if hex_dec and _decoded_shell_fragment_dangerous(hex_dec):
                # 解码内容本身就是危险片段: 即使未显式管道到 sh, 也判危险
                # (xxd 输出可经重定向/命令替换落地), 保持 fail-closed。
                return True
            if pipe_to_shell:
                return True
    return False


# ============================================================ 提及 vs 执行区分
# 安全修复: 引号内的破坏性内容如果只是"提及"(写在文档/搜索/提交信息里),
# 并不构成执行 —— 例如 echo 'sh -c "rm -rf /"' / grep -r 'rm -rf /' src/。
# 但若整条命令存在"执行汇"(管道喂给 shell / base64 解码 / 命令替换 / eval /
# 解释器跑脚本), 引号内容就会被真正执行, 此时绝不能当作提及放行。
_MENTION_VERB_RE = re.compile(
    r'\b(?:echo|printf|grep|egrep|fgrep|rg|ag|cat|head|tail|less|more|'
    r'git\s+commit\s+-m|git\s+log|man|tee|touch)\b',
    re.IGNORECASE,
)

_EXEC_SINK_RE = re.compile(
    r'\|\s*(?:ba|z|k|fi|da|a|c|tc)?sh\b'                    # | sh / | bash
    r'|\|\s*(?:python\d*|perl|ruby|node|php|lua)\b'          # | python
    r'|\bbase64\b\s+(?:-[dDiI]|--decode)'                    # base64 -d
    r'|`|\$\('                                               # 命令替换
    r'|\b(?:eval|xargs|exec)\b'                              # eval / xargs
    r'|\b(?:ba|z|k|fi|da|a|c|tc)?sh\b\s+-[A-Za-z]'           # sh -c
    r'|\b(?:ba|z|k|fi|da|a|c|tc)?sh\b\s+\S'                  # sh script.sh
    r'|>>?\s*\S+\.(?:sh|bash|py|pl|rb)\b',                   # > x.sh (落地后执行)
    re.IGNORECASE,
)


def _mention_spans(text: str) -> list[tuple[int, int]]:
    """返回"仅提及、不执行"的引号区间 [(start, end), ...]。

    判定: 引号前是文本类动词 (echo/grep/printf/...) **且** 去掉引号内容后
    整条命令不存在执行汇。返回空列表表示引号内容会被真正执行 (须照常检测)。
    """
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"", " ", text)
    if _EXEC_SINK_RE.search(stripped):
        return []
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"('[^']*'|\"[^\"]*\")", text):
        head = text[:m.start()]
        # 只在当前段内查找提及动词 (避免跨 &&/; 把前段动词算进来)
        cut = max(head.rfind(c) for c in ";&|\n")
        seg_head = head[cut + 1:]
        if _MENTION_VERB_RE.search(seg_head):
            spans.append((m.start(), m.end()))
    return spans


def _iter_interpreter_payloads(text: str):
    """迭代命令中所有解释器内联载荷 (已去包裹引号)。

    覆盖 sh/bash/zsh/ksh/python/perl/ruby/node/php/lua/tclsh 的 -c/-e/-r 调用,
    以及 awk 的程序体。返回载荷字符串序列。
    """
    for m in _INTERP_RE.finditer(text):
        payload = (m.group(1) or "").strip()
        if len(payload) >= 2 and payload[0] in "'\"" and payload[-1] == payload[0]:
            payload = payload[1:-1]
        # groovy/ruby 三引号执行形式: """code""".execute()
        tq = re.match(r'"""([\s\S]*?)"""', payload)
        if tq and "execute" in payload:
            payload = tq.group(1)
        if payload:
            yield payload
    for m in _AWK_PROGRAM_RE.finditer(text):
        payload = (m.group(1) or "").strip()
        if len(payload) >= 2:
            payload = payload[1:-1]
        if payload:
            yield payload
    # here-string: cmd - <<< 'CODE' / cmd <<< "CODE"
    for m in _HERESTRING_RE.finditer(text):
        payload = (m.group(1) or "").strip()
        if len(payload) >= 2 and payload[0] in "'\"" and payload[-1] == payload[0]:
            payload = payload[1:-1]
        if payload:
            yield payload


def _interpreter_payload_dangerous(text: str) -> bool:
    """解释器内联载荷 (-c/-e/-r / awk 程序体 / here-string) 是否含破坏性内容。

    四路检测:
      1) 载荷内直接出现破坏性 shell 片段 (rm -rf / dd / mkfs / DROP TABLE ...);
      2) 载荷内出现跨语言破坏性 API (shutil.rmtree / os.system / execSync ...);
      3) 破坏性二进制 (rm/sh/mkfs/dd ...) 作为首个字符串参数传给程序化执行 API
         (system/cmd/exec/run/subprocess/...), 覆盖旗标被拆成数组的写法;
      4) 执行 API 的内层字符串参数 (execSync('CMD') / spawn('rm',['-rf','/']) 等)
         即待执行命令, 穿透检测内层 CMD —— 含 require('child_process').execSync(
         'systemctl mask') 这类前缀消失的写法; 内层 CMD 经 _normalize 后跑全模式库,
         与 score() 口径一致 (systemctl mask / chmod 777 / iptables -F 等均能检出)。
    """
    # 引号内的破坏性内容若只是"提及"(echo/grep/提交信息), 不构成执行 —— 跳过
    mention = _mention_spans(text)
    for payload in _iter_interpreter_payloads(text):
        if mention and any(payload in text[a:b] for a, b in mention):
            continue
        if _INTERP_PAYLOAD_SHELL_RE.search(payload):
            return True
        if _INTERP_PAYLOAD_API_RE.search(payload):
            return True
        if _INTERP_PAYLOAD_PROG_RE.search(payload):
            return True
        # 执行 API 的内层字符串参数即是待执行命令, 穿透检测
        for m in _INTERP_EXEC_ARG_RE.finditer(payload):
            inner = m.group(1)
            if not inner:
                continue
            if _INTERP_PAYLOAD_SHELL_RE.search(inner):
                return True
            # 内层命令经归一化后跑全模式库 (与 score() 口径一致)
            if _match_any(_normalize(inner),
                          _CRITICAL_PATTERNS + _HIGH_PATTERNS + _MEDIUM_PATTERNS):
                return True
            # 内层再套一层执行 (execSync('sh -c "rm -rf /"'))
            if _interpreter_payload_dangerous(inner):
                return True
    return False


def is_benign_dev_command(text: str) -> bool:
    """整条命令是否为良性开发命令 (所有分段都是)。

    用于降低安全引擎误杀率: 命中则 score() / get_warning_level() 不会将其升级为
    high/critical。注意「硬红线」(is_hard_redline) 在护栏 step1 独立判定,
    本函数不影响对 rm -rf /、dd、mkfs、force push 等不可逆破坏的拦截。
    """
    # Base64 管道不是良性命令 (GuardFall D类绕过)
    if _is_base64_pipeline_dangerous(text):
        return False
    # 转义/hex 编码字面量并非良性命令 (printf '\162\155...' / xxd 解码)
    if _is_encoded_literal_dangerous(text):
        return False
    # 解释器内联载荷含破坏性内容 → 不是良性命令
    if _interpreter_payload_dangerous(text):
        return False
    segs = _segments(text) or [text]
    return all(_segment_is_benign(s) for s in segs)


# 硬红线模式 (排除 SQL 破坏性操作): 用于 shell 护栏 step1 的「永不自动执行」判定。
# SQL 破坏性操作 (DROP/DELETE/TRUNCATE) 不在此列 —— 它们属于『可确认关键级』,
# 由 shell 护栏的 step3/step4 经极端 5 次确认放行 (见 tools/shell._pre_exec_guard)。
# 注意 is_redline() 仍是综合危险检测器 (含 SQL), 供 MCP 守卫 / 脚本内容检查等场景使用。
_REDLINE_PATTERNS = [
    p for p in _CRITICAL_PATTERNS
    if not p[0].lstrip().upper().startswith(("DROP", "DELETE", "TRUNCATE"))
]


def is_hard_redline(command: str) -> bool:
    """硬红线: 文件系统 / OS 级毁灭操作, 即使在 YOLO 模式 / 确认通道存在时也永不自动执行。

    与 is_redline() 的区别: 排除 SQL 破坏性操作 (DROP/DELETE/TRUNCATE), 后者走
    「可确认关键级」流程。本函数仅供 shell 护栏 step1 使用, 以保持「硬红线」语义纯净。
    """
    if _eval_is_unverifiable(command):
        return True
    if _is_base64_pipeline_dangerous(command):
        return True
    if _is_encoded_literal_dangerous(command):
        return True
    if _interpreter_payload_dangerous(command):
        return True
    # 硬红线用「危险目标」版本: rm -rf / ~ /etc * 等灾难级目标才永不自动执行;
    # rm -rf ./build 这类清理构建产物的相对路径操作降为可确认 (见 has_dangerous_recursive_rm)。
    if (has_dangerous_recursive_rm(command) or has_force_push(command)
            or has_win_recursive_delete(command) or has_system_shutdown(command)
            or has_auth_overwrite(command)):
        return True
    if _match_any(command, _REDLINE_PATTERNS):
        return True
    # 归一化后 (PowerShell -EncodedCommand / 命令替换解码等) 的红线模式也要命中
    if _match_any(_normalize(command), _REDLINE_PATTERNS):
        return True
    return False


def is_redline(command: str) -> bool:
    """综合危险操作检测器 (单一来源): 供 shell 护栏 / MCP 守卫 / 脚本内容检查共用。

    覆盖两类判定:
      1) token 化函数 (has_recursive_rm / has_force_push / has_win_recursive_delete /
         has_system_shutdown) —— 穿透子壳/变量/引号/解释器间接写法 (见 _normalize);
      2) _CRITICAL_PATTERNS 正则库 (dd / mkfs / format / chmod -R 000 / chown -R root /
         DROP TABLE / DELETE / 系统关机等) —— 含 SQL 破坏性操作 (归为 confirmable-critical)。
      3) eval + 命令替换: 替换结果会被 eval 当作代码执行, 静态不可验证, fail-closed 拒绝。
      4) Base64 管道 (GuardFall D类绕过): echo payload | base64 -d | sh 等编码管道。

    返回 True 即代表「命中致命/危险操作」; 其中文件系统/OS 级毁灭操作同时构成硬红线
    (见 is_hard_redline), SQL 破坏性操作则由调用方按可确认关键级处理。
    """
    if _eval_is_unverifiable(command):
        return True
    if _is_base64_pipeline_dangerous(command):
        return True
    if _is_encoded_literal_dangerous(command):
        return True
    if _interpreter_payload_dangerous(command):
        return True
    if (has_recursive_rm(command) or has_force_push(command)
            or has_win_recursive_delete(command) or has_system_shutdown(command)
            or has_auth_overwrite(command)):
        return True
    if _match_any(command, _REDLINE_PATTERNS) or _sql_redline(command):
        return True
    # 归一化后 (PowerShell -EncodedCommand / 命令替换解码等) 的红线模式也要命中
    if _match_any(_normalize(command), _REDLINE_PATTERNS):
        return True
    return False


# =====================================================================
# 极高风险判定 (EXTREME 级别) - 2026-08-28 新增
# 即使 YOLO 模式也绝不自动执行, 必须弹 5 次警告且每次按键位置不同
# 白名单优先: 即使已加入白名单, 命中 EXTREME 判定照样拦截
# =====================================================================

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


def is_extreme(command: str) -> bool:
    """极高风险操作 (EXTREME 级别) - YOLO 模式也不放行。

    与 is_redline 的区别:
    - is_redline: 黑名单 (CRITICAL + HIGH), 弹 3 次警告
    - is_extreme: 极高风险 (EXTREME), 必须弹 5 次警告, 每次按键位置不同

    判定逻辑:
    1. 先通过 _normalize + _unwrap_indirection 处理命令 (剥壳/解码/替换变量)
    2. 与 _EXTREME_PATTERNS 逐一匹配
    3. 命中任意一条即返回 True

    返回 True 意味着: 即使 YOLO 模式也绝不自动执行, 必须 5 次手动确认。
    """
    normalized = _normalize(command)
    # 额外做一次 normalize 后的 token 化检测 (覆盖 rm -rf / 变体)
    for seg in _segments(normalized.lower()):
        parts = seg.split()
        if parts and parts[0] in ("rm",) :
            # 检查 -rf/-fr/-r -f/-f -r 组合 + 目标为 / ~ $HOME /*
            flags = set()
            target = None
            for p in parts[1:]:
                if p.startswith("-") and len(p) > 1:
                    for c in p[1:]:
                        flags.add(c)
                else:
                    target = p
            if "r" in flags and "f" in flags:
                if target in ("/", "/*", "~", "$HOME", "\\", "C:\\", "D:\\"):
                    return True
                if target and (target == "/" or target.startswith("/") or target.endswith("\\")):
                    return True

    # 正则匹配
    if _match_any(command, _EXTREME_PATTERNS):
        return True
    return False
