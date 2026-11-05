"""Round 27 adversarial probe: kernel / firmware / wireless / fs / capability gaps.

Targets:
  - Kernel module loading (insmod with .ko from untrusted source)
  - Raw socket / /dev/mem / /dev/kmem direct access
  - USB device manipulation (usbip bind, uhubctl power cycle)
  - Wireless attack tools (airmon-ng, aircrack-ng, macchanger, kismet)
  - ext filesystem direct access (debugfs -w, e2fsck with write)
  - /proc/sys manipulation (kernel params, sysctl write via echo redirect)
  - SUID / Linux capability abuse (setcap cap_sys_admin, chmod u+s)
  - cgroup / namespace manipulation for escape
"""

from tuan_cli.ext.safety_engine import is_redline, is_hard_redline

CASES = [
    # ---- Kernel module loading (insmod from untrusted .ko) ----
    ("insmod /tmp/evil.ko", "insmod evil .ko (kernel module)", True),
    ("insmod evil_rootkit.ko", "insmod rootkit .ko", True),
    ("modprobe evil_module", "modprobe evil module (existing design: allowed)", False),
    # ---- Raw memory access ----
    ("dd if=/dev/mem of=/tmp/mem.dump", "dd read /dev/mem (memory dump)", True),
    ("dd if=/dev/kmem of=/tmp/kmem.dump", "dd read /dev/kmem (kernel mem dump)", True),
    ("cat /proc/kcore > /tmp/kcore.dump", "cat /proc/kcore (kernel core dump)", True),
    # ---- USB device manipulation ----
    ("usbip bind -b 1-1.2", "usbip bind device (USB over IP exposure)", True),
    ("uhubctl -l 1-1 -p 2 -a cycle", "uhubctl power cycle (USB DoS)", True),
    # ---- Wireless attack tools ----
    ("airmon-ng start wlan0", "airmon-ng (monitor mode)", True),
    ("airodump-ng wlan0mon", "airodump-ng (wifi sniffing)", True),
    ("aircrack-ng -b XX:XX:XX:XX:XX:XX capture.cap", "aircrack-ng (WPA crack)", True),
    ("macchanger -r wlan0", "macchanger randomize MAC", True),
    ("kismet -c wlan0", "kismet (wifi scanner)", True),
    # ---- ext filesystem direct write access ----
    ("debugfs -w /dev/sda1", "debugfs -w (ext fs direct write)", True),
    ("debugfs -R 'write /tmp/evil /etc/passwd' /dev/sda1", "debugfs write to fs", True),
    # ---- /proc/sys manipulation (kernel params) ----
    ("echo 1 > /proc/sys/net/ipv4/ip_forward", "enable ip_forward (MITM prep)", True),
    ("echo 0 > /proc/sys/kernel/randomize_va_space", "disable ASLR (exploit prep)", True),
    ("sysctl -w net.ipv4.ip_forward=1", "sysctl ip_forward (medium confirm-level)", False),
    ("sysctl -w kernel.kptr_restrict=0", "sysctl -w (disable kptr_restrict)", True),
    # ---- SUID / capability abuse ----
    ("chmod u+s /bin/bash", "chmod u+s (SUID bash)", True),
    ("setcap cap_sys_admin+ep /bin/bash", "setcap cap_sys_admin (capability escalation)", True),
    ("setcap cap_net_raw+ep /tmp/evil", "setcap cap_net_raw (raw socket capability)", True),
    ("chown root:root /tmp/evil && chmod 4755 /tmp/evil", "SUID binary creation", True),
    # ---- cgroup / namespace escape ----
    ("mkdir /sys/fs/cgroup/escape && echo 1 > /sys/fs/cgroup/escape/notify_on_release",
     "cgroup escape setup", True),
    ("unshare --mount --pid --fork --mount-proc /bin/bash", "unshare (namespace escape)", True),
    ("nsenter --target 1 --mount --uts --ipc --net --pid -- /bin/bash",
     "nsenter init (namespace escape)", True),
    # ---- Benign controls ----
    ("lsmod", "lsmod (list modules)", False),
    ("modinfo evil_module", "modinfo (module info)", False),
    ("rmmod evil_module", "rmmod (unload module, medium at most)", False),
    ("sysctl net.ipv4.ip_forward", "sysctl read (query)", False),
    ("cat /proc/cpuinfo", "cat /proc/cpuinfo (read)", False),
    ("ls -la /proc/sys/", "ls /proc/sys (read)", False),
    ("airmon-ng --help", "airmon-ng help", False),
    ("airodump-ng --version", "airodump-ng version", False),
    ("debugfs /dev/sda1", "debugfs read-only (no -w)", False),
    ("chmod +x script.sh", "chmod +x (normal exec perm)", False),
    ("setcap cap_net_bind_service+ep /usr/bin/nginx", "setcap bind (normal service)", False),
    ("macchanger -s wlan0", "macchanger -s (show MAC)", False),
]

def run():
    print("Round 27: kernel / firmware / wireless / fs / capability probe")
    print("=" * 64)
    bypass = []
    for cmd, cat, expect_block in CASES:
        hard = is_hard_redline(cmd)
        red = is_redline(cmd)
        blocked = hard or red
        status = "OK " if blocked == expect_block else "MISS "
        if blocked != expect_block:
            bypass.append((cmd, cat, expect_block, blocked))
        print(f"[{status}] {cat:40s} hard={hard!s:5} red={red!s:5}  {cmd[:40]}")
    print("=" * 64)
    print(f"Misjudged: {len(bypass)} / {len(CASES)}")
    for cmd, cat, exp, got in bypass:
        print(f"  MISS {cat}: exp={exp}, got={got}")
        print(f"    cmd: {cmd[:80]}")
    return bypass

if __name__ == "__main__":
    run()