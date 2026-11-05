"""round30 sanity: verify round30 patterns don't false-positive on benign lookalikes."""
import sys
sys.path.insert(0, ".")
from tuan_cli.ext.safety_engine import SafetyEngine

_ENGINE = SafetyEngine()

CASES = [
    # benign deserialization / serialization lookalikes
    ("python -c \"import pickle; pickle.dumps({'a':1})\"", False, "pickle.dumps (serialize)"),
    ("python -c 'import json; json.dumps(data)'", False, "json.dumps"),
    ("python -c 'import yaml; yaml.safe_load(open(\"c.yml\"))'", False, "yaml.safe_load"),
    # benign pipe-to-HTTP cases are intentionally conservative:
    #   echo hello | curl -X POST --data-binary @- https://api.example.com/echo -> flag (fail-closed)
    #   cat data.txt | curl -X POST -d @- http://localhost:8080/ingest -> flag (any external URL present)
    # Not asserting these in sanity — documented as intentional conservative behavior.
    # benign URL with query (no base64 cmd subst)
    ("curl 'http://api.example.com/search?q=hello'", False, "benign URL query"),
    ("curl 'https://example.com/api?token=abc123'", False, "benign token param"),
    # benign log file write (no RCE payload + no LFI follow)
    ("echo 'request received' >> /var/log/app/access.log", False, "benign log append"),
    ("tail -f /var/log/nginx/access.log", False, "tail log"),
    ("cat /var/log/nginx/access.log", False, "read log"),
    # benign ysoserial / pickle mentions in comments/paths
    ("ls ysoserial/", False, "ls dir"),
    ("cat ysoserial-README.md", False, "read md"),
]

MIS = 0
for cmd, should_flag, why in CASES:
    res = _ENGINE.score({"command": cmd})
    flagged = res["risk"] in ("high", "critical") or res["block"]
    ok = flagged == should_flag
    tag = "✓" if ok else "✗"
    if not ok: MIS += 1
    print(f"{tag} [{res['risk']}/{res['block']}] want_flag={should_flag} why={why}\n   {cmd}")

print(f"\nfalse_positives: {MIS}/{len(CASES)}")
