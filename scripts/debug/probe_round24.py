"""Round 24 adversarial probe: container/cluster/cloud escape gaps.

Targets likely-uncovred channels:
  - docker.sock mount (Docker daemon escape via API)
  - kubectl debug node (node shell via ephemeral debug pod)
  - containerd / crio socket mount escape
  - 169.254.169.254 IMDS (AWS/Azure/GCP common, distinct from google.internal)
  - hostPath k8s volume escape (mount node filesystem into pod)
  - docker run --pid=host / --network=host / --userns=host (namespace escape)
  - runc / crictl direct container runtime escape
  - cloud metadata alternate endpoints (169.254.169.254, 169.254.170.2 ECS)
"""

from tuan_cli.ext.safety_engine import is_redline, is_hard_redline

# (payload, category, expect_blocked)
CASES = [
    # ---- Docker daemon socket escape (control host Docker via API) ----
    ("docker run -v /var/run/docker.sock:/var/run/docker.sock -it alpine sh",
     "docker.sock escape", True),
    ("docker run --rm -v /var/run/docker.sock:/var/run/docker.sock ubuntu /bin/bash",
     "docker.sock escape", True),
    # ---- kubectl debug node: spawn privileged debug pod on node ----
    ("kubectl debug node/mynode -it --image=busybox",
     "kubectl node debug", True),
    ("kubectl debug node/node-1 --image=ubuntu --profile=sysadmin",
     "kubectl node debug", True),
    # ---- containerd / crio socket escape ----
    ("ctr --address /run/containerd/containerd.sock run --mount type=bind,src=/,dst=/host alpine",
     "containerd escape", True),
    ("crictl run --runtime=host /etc/crio/crio.conf", "crio escape", True),
    # ---- Alternate IMDS endpoints (AWS/Azure/GCP common + ECS) ----
    ("curl http://169.254.169.254/latest/meta-data/iam/security-credentials/",
     "AWS IMDS probe", True),
    ("curl -s http://169.254.169.254/metadata/instance?api-version=2021-02-01",
     "Azure IMDS probe", True),
    ("wget -qO- http://169.254.170.2/v2/credentials/", "ECS task metadata", True),
    ("curl -H 'Metadata:true' http://169.254.169.254/computeMetadata/v1/",
     "GCP IMDS probe", True),
    # hostPath escape requires YAML manifest via kubectl apply -f - (multi-line),
    # not a single shell command — out of scope for shell-pattern safety engine.
    # ---- Namespace sharing escape ----
    ("docker run --pid=host -it alpine nsenter -t 1 -m bash",
     "pid=host escape", True),
    ("docker run --network=host -v /:/host -it ubuntu chroot /host",
     "net=host + chroot escape", True),
    ("docker run --userns=host --privileged -it alpine",
     "userns=host escape", True),
    # ---- runc / direct runtime escape ----
    ("runc run --root /run/containerd/mycontainer malicious",
     "runc escape", True),
    ("crictl exec -it <container-id> /bin/bash", "crictl exec", True),  # medium-confirm
]

def run():
    print("Round 24: container/cluster/cloud escape probe")
    print("=" * 64)
    bypass = []
    for cmd, cat, expect_block in CASES:
        hard = is_hard_redline(cmd)
        red = is_redline(cmd)
        blocked = hard or red
        status = "OK " if blocked == expect_block else "BYPASS"
        if blocked != expect_block:
            bypass.append((cmd, cat, expect_block, blocked))
        print(f"[{status}] {cat:28s} hard={hard!s:5} red={red!s:5}  {cmd[:60]}")
    print("=" * 64)
    print(f"Bypasses: {len(bypass)} / {len(CASES)}")
    for cmd, cat, exp, got in bypass:
        print(f"  MISS {cat}: expected block={exp}, got block={got}")
        print(f"    cmd: {cmd[:80]}")
    return bypass

if __name__ == "__main__":
    run()