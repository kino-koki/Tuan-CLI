"""Round 27 sanity: benign controls must NOT trip new kernel/wireless/capability rules."""
from tuan_cli.ext.safety_engine import is_hard_redline, is_redline

CASES = [
    # dd on non-kernel devices (benign)
    ("dd if=/dev/zero of=/tmp/test bs=1M count=10", "dd /dev/zero (benign)", False),
    ("dd if=image.iso of=/dev/sdb", "dd write USB image (may be critical if raw disk)", None),
    # debugfs read-only (no -w / no -R write)
    ("debugfs /dev/sda1", "debugfs read-only (no -w)", False),
    ("debugfs -R 'ls -d /' /dev/sda1", "debugfs -R ls (read op)", False),
    # usbip non-bind subcommands
    ("usbip list -r 192.168.1.5", "usbip list (query)", False),
    ("usbip attach -r 192.168.1.5 -b 1-1.2", "usbip attach (client)", None),
    # wireless tool help/version
    ("airmon-ng --help", "airmon-ng help", False),
    ("airodump-ng --version", "airodump-ng version", False),
    ("aircrack-ng --help", "aircrack-ng help", False),
    ("kismet --version", "kismet version", False),
    ("macchanger -s wlan0", "macchanger show MAC (read)", False),
    ("macchanger --help", "macchanger help", False),
    # sysctl read (no -w)
    ("sysctl net.ipv4.ip_forward", "sysctl read", False),
    ("sysctl -a", "sysctl -a (list all)", False),
    ("sysctl -w net.ipv4.ip_forward=1", "sysctl ip_forward (medium, non-critical)", False),
    ("sysctl -w kernel.kptr_restrict=0", "sysctl kptr_restrict (critical)", True),
    # setcap low-risk capabilities (common service needs)
    ("setcap cap_net_bind_service+ep /usr/bin/nginx", "setcap bind_service (common)", False),
    ("setcap cap_dac_read_search+ep /usr/bin/foo", "setcap dac_read_search (read)", False),
    # modprobe/modinfo/rmmod (existing design: load known driver is allowed)
    ("modprobe virtio_net", "modprobe known driver", False),
    ("modinfo i915", "modinfo read", False),
    ("rmmod evil_module", "rmmod (unload)", False),
    # These SHOULD flag
    ("dd if=/dev/mem of=/tmp/mem.dump", "dd kernel mem", True),
    ("debugfs -w /dev/sda1", "debugfs -w", True),
    ("usbip bind -b 1-1.2", "usbip bind", True),
    ("airmon-ng start wlan0", "airmon-ng start", True),
    ("aircrack-ng -b XX capture.cap", "aircrack-ng crack", True),
    ("macchanger -r wlan0", "macchanger randomize", True),
    ("setcap cap_net_raw+ep /tmp/evil", "setcap net_raw", True),
    ("setcap cap_sys_module+ep /tmp/evil", "setcap sys_module", True),
]

def run():
    bad = []
    for cmd, why, expect in CASES:
        flagged = is_hard_redline(cmd) or is_redline(cmd)
        if expect is None:
            status = "?? "
            continue
        ok = flagged == expect
        if not ok:
            bad.append((cmd, why, expect, flagged))
        print(f"[{'OK ' if ok else 'BAD'}] flag={flagged!s:5} exp={expect!s:5} {why}")
        if not ok:
            print(f"      cmd: {cmd}")
    print(f"\nmisjudged: {len(bad)}/{len(CASES)}")
    for cmd, why, exp, got in bad:
        print(f"  BAD {why}: exp={exp}, got={got}")
        print(f"    cmd: {cmd}")
    return bad

if __name__ == "__main__":
    run()