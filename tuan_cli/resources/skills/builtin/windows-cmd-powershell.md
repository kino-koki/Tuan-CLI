---
name: Windows 命令参考 (CMD/PowerShell)
description: Windows 环境下 CMD 和 PowerShell 的常用命令速查表。当模型在 Windows 上遇到命令报错、不确定命令语法或需要跨平台命令转换时，查阅本表。
updated_at: 0
use_count: 0
activation: always
platform: win32
---

# Windows 命令参考 (CMD / PowerShell)

> **使用场景**: 当你在 Windows 用户电脑上执行 shell 命令时，如果遇到报错、不确定命令语法、或需要将 Linux/macOS 命令转换为 Windows 等价命令，请查阅本表。大部分模型的训练数据以 Linux/macOS 为主，对 Windows 命令支持有限，本表作为"外骨骼"增强你的 Windows 能力。

## 一、文件与目录操作

| 操作 | Linux/macOS | CMD | PowerShell |
|------|------------|-----|------------|
| 列出文件 | `ls -la` | `dir /a` | `Get-ChildItem -Force` |
| 切换目录 | `cd /path` | `cd C:\path` | `Set-Location C:\path` |
| 创建目录 | `mkdir -p dir` | `mkdir dir` | `New-Item -ItemType Directory -Path dir -Force` |
| 删除文件 | `rm file` | `del file` | `Remove-Item file` |
| 删除目录 | `rm -rf dir` | `rmdir /s /q dir` | `Remove-Item dir -Recurse -Force` |
| 复制文件 | `cp src dst` | `copy src dst` | `Copy-Item src dst` |
| 移动/重命名 | `mv old new` | `move old new` | `Move-Item old new` |
| 查看文件内容 | `cat file` | `type file` | `Get-Content file` |
| 追加内容 | `echo text >> file` | `echo text >> file` | `Add-Content -Path file -Value "text"` |
| 查找文件 | `find . -name "*.py"` | `dir /s /b *.py` | `Get-ChildItem -Recurse -Filter *.py` |
| 查找内容 | `grep -r "pattern" .` | `findstr /s /i "pattern" *.txt` | `Select-String -Path *.txt -Pattern "pattern"` |
| 文件大小 | `wc -c file` | `for %i in (file) do @echo %~zi` | `(Get-Item file).Length` |
| 修改权限 | `chmod 755 file` | `icacls file /grant Everyone:F` | `Set-Acl file (Get-Acl file)` |
| 符号链接 | `ln -s target link` | `mklink link target` | `New-Item -ItemType SymbolicLink -Path link -Target target` |

## 二、进程与系统

| 操作 | Linux/macOS | CMD | PowerShell |
|------|------------|-----|------------|
| 查看进程 | `ps aux` | `tasklist` | `Get-Process` |
| 杀进程 | `kill -9 PID` | `taskkill /f /pid PID` | `Stop-Process -Id PID -Force` |
| 查看端口 | `ss -tlnp` | `netstat -ano` | `Get-NetTCPConnection` |
| 环境变量 | `env` / `printenv` | `set` | `Get-ChildItem Env:` |
| 设置环境变量 | `export KEY=val` | `set KEY=val` | `$env:KEY = "val"` |
| 系统信息 | `uname -a` | `systeminfo` | `Get-ComputerInfo` |
| 主机名 | `hostname` | `hostname` | `$env:COMPUTERNAME` |
| 当前用户 | `whoami` | `whoami` | `$env:USERNAME` |
| 运行时间 | `uptime` | `systeminfo \| find "Boot"` | `(Get-CimInstance Win32_OS).LastBootUpTime` |
| 磁盘空间 | `df -h` | `wmic logicaldisk get size,freespace,caption` | `Get-PSDrive` |
| 环境变量(永久) | `~/.bashrc` | `setx KEY val` | `[Environment]::SetEnvironmentVariable("KEY","val","User")` |

## 三、网络

| 操作 | Linux/macOS | CMD | PowerShell |
|------|------------|-----|------------|
| 下载文件 | `curl -O url` | `curl -O url` 或 `bitsadmin /transfer job url file` | `Invoke-WebRequest -Uri url -OutFile file` |
| HTTP 请求 | `curl url` | `curl url` | `Invoke-WebRequest -Uri url` |
| DNS 查询 | `dig domain` | `nslookup domain` | `Resolve-DnsName domain` |
| Ping | `ping -c 4 host` | `ping -n 4 host` | `Test-Connection -Count 4 host` |
| 网络配置 | `ip addr` | `ipconfig` | `Get-NetIPAddress` |
| 路由表 | `route -n` | `route print` | `Get-NetRoute` |
| 连接测试 | `nc -zv host port` | `telnet host port` 或 `Test-NetConnection host -Port port` | `Test-NetConnection host -Port port` |

## 四、压缩与归档

| 操作 | Linux/macOS | CMD (需安装) | PowerShell |
|------|------------|-------------|------------|
| 压缩 ZIP | `zip -r out.zip dir` | `tar -cf out.zip dir` (Win10+) | `Compress-Archive -Path dir -DestinationPath out.zip` |
| 解压 ZIP | `unzip file.zip` | `tar -xf file.zip` (Win10+) | `Expand-Archive -Path file.zip -DestinationPath .` |
| 压缩 TAR.GZ | `tar czf out.tar.gz dir` | `tar czf out.tar.gz dir` (Win10+) | 需第三方工具 |
| Git 操作 | 原生支持 | 原生支持 | 原生支持 |

## 五、包管理

| 操作 | Linux/macOS | Windows |
|------|------------|---------|
| 安装包 | `apt install pkg` / `brew install pkg` | `winget install pkg` 或 `choco install pkg` |
| 卸载包 | `apt remove pkg` / `brew uninstall pkg` | `winget uninstall pkg` |
| 搜索包 | `apt search pkg` / `brew search pkg` | `winget search pkg` |
| 更新 | `apt update && apt upgrade` / `brew update` | `winget upgrade --all` |
| Python 包 | `pip install pkg` | `pip install pkg` (相同) |
| Node 包 | `npm install pkg` | `npm install pkg` (相同) |

## 六、常见陷阱与解决方案

### 1. 路径分隔符
- **Linux**: `/path/to/file`
- **Windows**: `C:\path\to\file` 或 `C:/path/to/file` (Python/PowerShell 中正斜杠也可用)
- **Python 中**: 始终用 `pathlib.Path` 或正斜杠 `/`, 不要用反斜杠 `\` (会被当转义符)

### 2. 编码问题
- CMD 默认 GBK (CP936), PowerShell 默认 UTF-16LE
- **解决**: 读写文件时显式指定 `encoding="utf-8"`
- Git Bash / MSYS2 环境下默认 UTF-8

### 3. 路径长度限制
- Windows 传统路径上限 260 字符 (`MAX_PATH`)
- **解决**: 启用长路径支持, 或用 `\\?\` 前缀, 或用 Python `pathlib`

### 4. 文件锁定
- Windows 文件被进程锁定时无法删除/移动
- **解决**: 先关闭占用进程, 或用 `MoveFileEx` 标记重启后操作

### 5. 换行符
- Windows: `\r\n` (CRLF)
- Linux/macOS: `\n` (LF)
- **Python 中**: `open()` 默认用系统换行符; 跨平台代码用 `newline=""` 或统一 `\n`

### 6. 环境变量大小写
- Windows 环境变量**不区分大小写** (`PATH` = `path` = `Path`)
- Linux/macOS **区分大小写**

### 7. 可执行文件
- Windows: `.exe`, `.bat`, `.cmd`, `.ps1`
- 不需要 `chmod +x`
- `.ps1` 需要 `ExecutionPolicy` 允许: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 8. 管道和重定向
- CMD 和 PowerShell 都支持 `|`, `>`, `>>`, `<`
- PowerShell 管道传递**对象**而非文本 (可用 `Where-Object`, `Select-Object`)
- CMD 管道传递**文本** (可用 `findstr`, `find`, `sort`)

### 9. 多行命令
- CMD: 用 `^` 换行, 或写在一行用 `&&` 连接
- PowerShell: 用反引号 `` ` `` 换行, 或用 `;` 分隔, 或用 `@()` 括起多行

### 10. Python 在 Windows 上
- 用 `python -m` 而非直接 `python` (避免 PATH 问题)
- `python -m pip install` 比 `pip install` 更可靠
- 虚拟环境: `.venv\Scripts\activate` (CMD) 或 `.venv\Scripts\Activate.ps1` (PowerShell)

## 七、快速参考: 常用 PowerShell 别名

PowerShell 的许多命令是 Unix 命令的别名, 可以直接使用:

| 别名 | 全称 | 说明 |
|------|------|------|
| `ls` / `dir` | `Get-ChildItem` | 列出文件 |
| `cat` / `type` | `Get-Content` | 读文件 |
| `echo` / `Write-Output` | `Write-Output` | 输出 |
| `cd` / `chdir` | `Set-Location` | 切换目录 |
| `cp` | `Copy-Item` | 复制 |
| `mv` | `Move-Item` | 移动 |
| `rm` | `Remove-Item` | 删除 |
| `pwd` | `Get-Location` | 当前目录 |
| `ps` | `Get-Process` | 进程列表 |
| `kill` | `Stop-Process` | 杀进程 |
| `sort` | `Sort-Object` | 排序 |
| `measure` | `Measure-Object` | 度量(统计) |

## 八、Agent 执行 Windows 命令的最佳实践

1. **优先用 Python**: 在 Windows 上, `subprocess.run(["python", "-m", ...])` 比直接调 shell 命令更跨平台可靠
2. **用参数列表, 不拼接字符串**: `subprocess.run(["dir", "/a"])` 比 `subprocess.run("dir /a", shell=True)` 安全
3. **指定编码**: `subprocess.run(..., encoding="utf-8", errors="replace")`
4. **超时保护**: `subprocess.run(..., timeout=30)` 防止命令挂起
5. **PowerShell 优先**: 如果 CMD 命令不工作, 试试 PowerShell (功能更全, 语法更一致)
6. **用 `Get-Command` 检查命令是否存在**: `Get-Command winget -ErrorAction SilentlyContinue`
7. **错误处理**: 检查 `returncode`, 不要假设命令成功
8. **路径用引号**: 路径含空格时必须引号: `dir "C:\Program Files"`

## 九、PowerShell 管道实战

PowerShell 管道传递**对象**而非文本, 这是与 CMD/Linux shell 的本质区别。

### 常用管道模式

```powershell
# 过滤进程 (等价于 Linux: ps aux | grep python)
Get-Process | Where-Object { $_.Name -like "*python*" }

# 排序 + 取前 10 (等价于 Linux: ls -lt | head -10)
Get-ChildItem | Sort-Object LastWriteTime -Descending | Select-Object -First 10

# 统计行数 (等价于 Linux: wc -l)
Get-Content file.txt | Measure-Object -Line

# 查找文件中的内容 (等价于 Linux: grep -r "pattern" .)
Get-ChildItem -Recurse -File | Select-String -Pattern "pattern" | Select-Object Path, LineNumber, Line

# 格式化输出 (等价于 Linux: awk '{print $1, $3}')
Get-Process | Format-Table Name, CPU -AutoSize

# 导出 CSV (等价于 Linux: ... > output.csv)
Get-Process | Export-Csv -Path "processes.csv" -NoTypeInformation

# 批量重命名 (等价于 Linux: for f in *.txt; do mv "$f" "${f%.txt}.md"; })
Get-ChildItem *.txt | Rename-Item -NewName { $_.Name -replace '\.txt$', '.md' }

# 批量删除 (等价于 Linux: find . -name "*.tmp" -delete)
Get-ChildItem -Recurse -Filter *.tmp | Remove-Item -Force

# 递归查找大文件 (等价于 Linux: find . -size +100M)
Get-ChildItem -Recurse -File | Where-Object { $_.Length -gt 100MB } | Sort-Object Length -Descending | Select-Object FullName, @{N='SizeMB';E={[math]::Round($_.Length/1MB,1)}}
```

### 对象操作 Cmdlet

| 操作 | PowerShell | Linux 等价 |
|------|-----------|-----------|
| 过滤 | `Where-Object { $_.Prop -eq "val" }` | `grep "val"` / `awk '$1=="val"'` |
| 映射 | `ForEach-Object { $_.Name }` | `awk '{print $1}'` / `cut -d',' -f1` |
| 排序 | `Sort-Object Property` | `sort` / `sort -k1` |
| 去重 | `Select-Object -Unique` | `sort -u` / `uniq` |
| 分组 | `Group-Object Property` | `sort \| uniq -c` |
| 聚合 | `Measure-Object -Sum -Average` | `awk '{s+=$1} END{print s}'` |
| 索引 | `Select-Object -Index 0,2,5` | `awk 'NR==1 \|\| NR==3 \|\| NR==6'` |
| 转置 | `$array \| ForEach-Object { [PSCustomObject]@{...} }` | `transpose` |

### 条件判断

```powershell
# 等价于 Linux: if [ -f "file" ]; then ...
if (Test-Path "file.txt") { "exists" } else { "not found" }

# 等价于 Linux: if [ "$VAR" = "value" ]; then ...
if ($env:MY_VAR -eq "value") { "match" }

# 等价于 Linux: test -d "dir" && echo "is dir"
if (Test-Path "dir" -PathType Container) { "is directory" }
```

## 十、常见 Linux→Windows 命令转换速查

| 你需要做什么 | Linux 命令 | Windows PowerShell 等价 |
|-------------|-----------|----------------------|
| 查看磁盘使用 | `du -sh *` | `Get-ChildItem \| Select-Object Name, @{N='SizeMB';E={[math]::Round($_.Length/1MB,2)}}` |
| 实时查看日志 | `tail -f log.txt` | `Get-Content log.txt -Wait` |
| 查看端口占用 | `lsof -i :8080` | `Get-NetTCPConnection -LocalPort 8080 \| Select-Object OwningProcess` |
| 设置文件权限 | `chmod 600 key.pem` | `icacls key.pem /inheritance:r /grant:r "$env:USERNAME:F"` |
| 查看系统负载 | `uptime` | `(Get-CimInstance Win32_Processor).LoadPercentage` |
| 搜索文件内容 | `grep -rn "TODO" --include="*.py" .` | `Get-ChildItem -Recurse -Filter *.py \| Select-String "TODO"` |
| 压缩目录 | `tar czf archive.tar.gz dir/` | `Compress-Archive -Path dir -DestinationPath archive.zip` |
| 解压文件 | `tar xzf archive.tar.gz` | `Expand-Archive -Path archive.zip -DestinationPath .` |
| SSH 连接 | `ssh user@host` | `ssh user@host` (Win10+ 内置 OpenSSH) |
| SCP 传输 | `scp file user@host:/path` | `scp file user@host:/path` (Win10+ 内置) |
