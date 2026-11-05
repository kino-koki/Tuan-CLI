"""round28 sanity: verify IMDS/container pattern extensions don't false-positive on benign lookalikes."""
import sys
sys.path.insert(0, ".")
from tuan_cli.ext.safety_engine import SafetyEngine

_ENGINE = SafetyEngine()

CASES = [
    # lookalike IPs that must NOT trigger IMDS (pre-existing design confirms)
    ("curl http://169.254.1.1/api/health", False, "different IPv4"),
    ("curl http://10.0.0.1/latest/meta-data/", False, "private non-IMDS"),
    # normal Azure/GCP API endpoints
    ("Invoke-RestMethod -Uri https://management.azure.com/subscriptions", False, "ARM public"),
    ("Invoke-WebRequest https://storage.googleapis.com/bucket/obj", False, "GCS public"),
    # container benign
    ("docker run --rm -v /data:/data alpine echo hi", False, "user volume mount"),
    ("docker run --volume=/home:/home alpine ls /home", False, "bind mount user dir"),
    ("kubectl exec web -- ls /etc", False, "normal pod exec ls"),
    ("kubectl logs web", False, "read logs"),
    ("curl -sk https://127.0.0.1:10250/pods", False, "kubelet read-only"),
    # cloud CLI benign
    ("aws s3 ls", False, "list buckets"),
    ("kubectl get nodes", False, "read-only"),
    ("az group create --name rg --location eastus", False, "create rg"),
]

# Pre-existing design (fail-closed on privileged / exec / upload) — not regressions:
#   docker run --privileged ... -> critical
#   kubectl exec -it web -- /bin/bash -> high
#   aws s3 cp -> high

MIS = 0
for cmd, should_flag, why in CASES:
    res = _ENGINE.score({"command": cmd})
    flagged = res["risk"] in ("high", "critical") or res["block"]
    ok = flagged == should_flag
    tag = "✓" if ok else "✗"
    if not ok: MIS += 1
    print(f"{tag} [{res['risk']}/{res['block']}] want_flag={should_flag} why={why}\n   {cmd}")

print(f"\nfalse_positives: {MIS}/{len(CASES)}")
