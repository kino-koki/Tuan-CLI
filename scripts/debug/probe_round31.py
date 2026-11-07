"""round31: container escape specifics 探针 (cgroup release_agent / hostPath / mount namespace)。"""
import sys
sys.path.insert(0, ".")
from tuan_cli.ext.safety_engine import SafetyEngine, is_redline, is_hard_redline

_ENGINE = SafetyEngine()

def label(cmd):
    if is_hard_redline(cmd): return "HARD"
    if is_redline(cmd): return "RED"
    s = _ENGINE.score({"command": cmd})
    return s.get("risk","none").upper()

PROBES = [
    # ===== cgroup v1 release_agent escape =====
    ("echo '#!/bin/sh\\nid > /tmp/pwned' > /tmp/x.sh && chmod +x /tmp/x.sh && mkdir -p /tmp/cgrp/rdma && echo 1 > /tmp/cgrp/rdma/notify_on_release && echo /tmp/x.sh > /tmp/cgrp/rdma/release_agent && touch /tmp/cgrp/rdma/foo", "cgroup release_agent escape", True, "container escape"),
    ("mkdir /tmp/cgrp && mount -t cgroup -o rdma cgroup /tmp/cgrp && echo 1 > /tmp/cgrp/notify_on_release && echo /tmp/x.sh > /tmp/cgrp/release_agent", "cgroup v1 mount + release_agent", True, "container escape"),
    # ===== cgroup v2 release_agent-like (core_pattern / modprobe) =====
    ("echo '|/tmp/x.sh %e %P' > /proc/sys/kernel/core_pattern", "core_pattern escape", True, "container escape via core_pattern"),
    ("echo '/tmp/x.sh' > /proc/sys/kernel/modprobe", "modprobe escape", True, "container escape via modprobe"),
    # ===== hostPath / sensitive mounts =====
    ("docker run -v /:/host -v /var/run/docker.sock:/var/run/docker.sock --privileged alpine", "host root + docker.sock + privileged", True, "full escape chain"),
    ("docker run -v /proc/sys/kernel/core_pattern:/core_pattern alpine sh -c 'echo evil > /core_pattern'", "mount core_pattern escape", True, "container escape via mount"),
    ("docker run --mount type=bind,source=/,target=/host alpine", "bind mount host root", True, "container escape via bind"),
    ("docker run --mount type=bind,source=/proc/sys,target=/proc-sys alpine", "bind mount proc/sys", True, "container escape via proc/sys"),
    ("kubectl apply -f evil-pod.yaml", "kubectl apply (may escape via hostPath)", False, "kubectl apply (medium?)"),
    # ===== namespace / PID escape =====
    ("nsenter -t 1 -n --net bash", "nsenter host net ns", True, "escape to host net"),
    ("nsenter -t 1 -m --mount bash", "nsenter host mount ns", True, "escape to host mount"),
    ("unshare --net --map-root-user ip addr", "unshare net ns", False, "unshare (isolates, not escape)"),  # ✓ unshare 隔离自身, 非逃逸
    # ===== capability / seccomp bypass =====
    ("capsh --print", "capsh print", False, "read-only"),
    ("capsh --caps='cap_sys_admin+ep' -- -c 'mount -t tmpfs none /tmp/mnt'", "capsh mount escape", True, "container escape via cap"),
    # ===== kernel modules from container =====
    ("insmod /tmp/evil.ko", "insmod from container", True, "kernel module load"),
    ("modprobe evil_module", "modprobe unknown module", True, "modprobe (pre-existing HIGH, conservative)"),  # ✓ 既有保守判定
    # ===== mount / pivot_root escape =====
    ("mount -t overlay overlay -o lowerdir=/host,upperdir=/tmp/u,workdir=/tmp/w /tmp/mnt", "overlay mount host", True, "container escape via overlay"),
    ("pivot_root /host /host/old_root && exec /bin/bash", "pivot_root escape", True, "container escape via pivot_root"),
    ("chroot /host /bin/bash", "chroot host", True, "container escape via chroot"),
    # ===== overlayfs CVE / dirty pipe style =====
    ("cp /tmp/evil /proc/self/root/usr/bin/sudo && /usr/bin/sudo id", "copy to host via proc/self/root", True, "container escape via /proc/self/root"),
    # ===== sensitive host file access from container =====
    ("cat /host/etc/shadow", "read host shadow", True, "read host credentials"),
    ("cat /host/proc/1/environ", "read host PID 1 env", True, "read host process env (creds)"),
    ("ls -la /host/var/run/docker.sock", "list host docker.sock", True, "identify docker.sock"),
    # ===== docker socket manipulation =====
    ("docker -H unix:///var/run/docker.sock run -v /:/host --privileged alpine", "docker via socket escape", True, "container escape via docker.sock"),
    ("curl --unix-socket /var/run/docker.sock http://localhost/containers/create", "docker API via socket", True, "container escape via API"),
    # ===== kubernetes hostPath escape (manifest injection) =====
    ("cat > pod.yaml <<EOF\napiVersion: v1\nkind: Pod\nspec:\n  containers:\n  - volumeMounts:\n    - mountPath: /host\n  volumes:\n  - hostPath:\n      path: /\nEOF", "hostPath manifest", False, "yaml file (medium)"),
    # ===== 容器内普通操作 (良性) =====
    ("docker run --rm alpine echo hello", "normal run", False, "benign"),
    ("docker exec container ls /", "normal exec", False, "benign"),
    ("kubectl exec pod -- ls /", "normal kubectl exec", False, "benign"),
    ("kubectl get pods", "kubectl get", False, "benign"),
    ("docker ps -a", "docker ps", False, "benign"),
    ("cat /etc/hostname", "read container hostname", False, "benign"),
    ("cat /etc/hosts", "read container hosts", False, "benign"),
    ("cat /proc/self/status", "read self status", False, "benign"),
    ("ls /proc/", "list proc", False, "benign"),
    ("cat /proc/cpuinfo", "read cpuinfo", False, "benign"),
    ("cat /proc/meminfo", "read meminfo", False, "benign"),
    ("ls /tmp/cgrp/", "list cgroup dir", False, "benign"),
    ("capsh --print", "capsh print (dup)", False, "benign"),
    ("mount", "mount read-only", False, "benign"),
    ("cat /etc/os-release", "read os-release", False, "benign"),
]

MIS = 0
for cmd, name, should_block, why in PROBES:
    got = label(cmd)
    blocked = got in ("RED", "HARD", "HIGH", "CRITICAL")
    ok = (should_block and blocked) or (not should_block and not blocked)
    mark = "✓" if ok else "✗"
    if not ok:
        MIS += 1
        print(f"{mark} [{name}] got={got} want={'block' if should_block else 'allow'} why={why}\n   {cmd}")
    else:
        print(f"{mark} [{got}] {name}")

print(f"\nmisjudged: {MIS}/{len(PROBES)}")
