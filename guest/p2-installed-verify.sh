#!/usr/bin/env bash
set -euo pipefail
[[ -f /etc/g15forge-p2/config.json ]] || exit 2
exec > /dev/ttyS0 2>&1
echo P2_SYSTEMD_VERIFY_BEGIN
[[ $(cat /proc/1/comm) == systemd ]]
[[ -d /sys/firmware/efi ]]
[[ $(findmnt -n -o UUID /) == "$(cat /etc/g15forge-p2/root-uuid)" ]]
[[ $(findmnt -n -o UUID /boot/efi) == "$(cat /etc/g15forge-p2/efi-uuid)" ]]
[[ $(findmnt -n -o FSTYPE /) == ext4 ]]
[[ $(findmnt -n -o FSTYPE /boot/efi) == vfat ]]
if findmnt -rn -t iso9660; then echo P2_ERROR=live-media-mounted; exit 2; fi
systemctl is-active systemd-journald.service systemd-udevd.service systemd-networkd.service
sha256sum -c /etc/g15forge-p2/boot.sha256
test -s "/boot/vmlinuz-$(uname -r)"
test -s "/boot/initramfs-$(uname -r).img"
[[ -z $(systemctl --failed --no-legend --plain) ]]
printf 'P2_PID1=%s\nP2_KERNEL=%s\n' "$(cat /proc/1/comm)" "$(uname -r)"
findmnt --target /
findmnt --mountpoint /boot/efi
lsblk -b -o NAME,TYPE,SIZE,SERIAL,FSTYPE,UUID,MOUNTPOINT
systemctl --failed --no-pager
journalctl -b -p warning --no-pager
echo P2_SYSTEMD_PASS
sync
systemctl poweroff --no-block
