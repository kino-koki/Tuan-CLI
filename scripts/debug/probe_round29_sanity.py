"""round29 sanity: verify package-manager supply chain patterns don't false-positive on benign use."""
import sys
sys.path.insert(0, ".")
from tuan_cli.ext.safety_engine import SafetyEngine

_ENGINE = SafetyEngine()

CASES = [
    # normal installs
    ("pip install requests", False, "normal"),
    ("pip install -r requirements.txt", False, "normal"),
    ("pip install numpy pandas", False, "normal"),
    ("npm install", False, "normal"),
    ("npm install --save-dev jest", False, "normal"),
    ("npm install express socket.io", False, "normal"),
    ("yarn add react react-dom", False, "normal"),
    ("gem install rails", False, "normal"),
    ("cargo build --release", False, "normal"),
    ("go build ./...", False, "normal"),
    ("go install golang.org/x/tools/cmd/gopls@latest", False, "normal go install (may HARD, that's ok)"),
    # read-only
    ("pip list", False, "read"),
    ("pip show requests", False, "read"),
    ("npm list", False, "read"),
    ("cargo search serde", False, "read"),
    ("gem list", False, "read"),
    # config read
    ("cat ~/.npmrc", False, "read npmrc"),
    ("cat /etc/pip.conf", False, "read pip.conf"),
    ("pip config list", False, "read config"),
    ("npm config list", False, "read config"),
    ("npm config get registry", False, "read registry"),
    ("gem sources --list", False, "list sources"),
    # unrelated writes
    ("echo hello > /tmp/test.txt", False, "unrelated"),
    ("cp a.txt b.txt", False, "unrelated"),
]

MIS = 0
for cmd, should_flag, why in CASES:
    res = _ENGINE.score({"command": cmd})
    flagged = res["risk"] in ("high", "critical") or res["block"]
    ok = flagged == should_flag
    tag = "✓" if ok else "✗"
    if not ok:
        MIS += 1
        print(f"{tag} [{res['risk']}/{res['block']}] want_flag={should_flag} why={why}\n   {cmd}")
    else:
        print(f"{tag} [{res['risk']}] {why}")

print(f"\nfalse_positives: {MIS}/{len(CASES)}")
