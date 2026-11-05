"""Round 24 sanity: benign dev commands must NOT be flagged by new round-24 patterns."""
from tuan_cli.ext.safety_engine import is_hard_redline, is_redline

# (payload, why-benign, expect_any_flag)
CASES = [
    ("ctr --version", "version query", False),
    ("crictl ps", "list containers", False),
    ("crictl images", "list images", False),
    ("crictl logs <id>", "view logs", False),
    ("runc --version", "version", False),
    ("crictl inspect <id>", "inspect", False),
    # these SHOULD flag (confirm-level escape / exec)
    ("ctr run --mount type=bind,src=/,dst=/host alpine", "ctr run mount host /", True),
    ("crictl run --runtime=host cfg.json", "crictl host runtime", True),
    ("runc run evil", "runc run arbitrary", True),
    # crictl exec = runtime debug command, treated like kubectl/docker exec (medium).
    # It is NOT a hard redline — confirm-level is the right posture. Expected unflagged here.
    ("crictl exec -it <id> bash", "crictl exec (medium, confirm-level)", False),
    ("kubectl debug node/n1 --image=busybox", "node debug", True),
]

def run():
    bad = 0
    for cmd, why, expect_flag in CASES:
        hard = is_hard_redline(cmd)
        red = is_redline(cmd)
        flagged = hard or red
        ok = flagged == expect_flag
        if not ok:
            bad += 1
        print(f"[{'OK ' if ok else 'BAD'}] flag={flagged!s:5} exp={expect_flag!s:5} {why:28s} {cmd[:50]}")
    print(f"\nmisjudged: {bad}/{len(CASES)}")
    return bad

if __name__ == "__main__":
    run()