#!/usr/bin/env bash
# Execute only within a separately prepared Gentoo Live root/chroot.
# Never modifies host disk partitions, firmware variables, or P2 QCOW2.
set -euo pipefail
[[ $# == 1 ]] || { echo 'usage: p4-create-live-initramfs.sh KERNEL_RELEASE' >&2; exit 2; }
kver=$1
[[ $kver =~ ^[A-Za-z0-9][A-Za-z0-9._+-]{1,100}$ ]] || { echo 'invalid kernel release' >&2; exit 2; }
[[ -f /etc/gentoo-release && -f /lib/modules/$kver/modules.dep ]] ||
    { echo 'not a prepared Gentoo system for this kernel' >&2; exit 2; }
[[ -s /boot/vmlinuz-$kver ]] || { echo 'matching kernel image missing' >&2; exit 2; }
command -v dracut >/dev/null
command -v lsinitrd >/dev/null
out="/boot/initramfs-$kver-live.img"
[[ ! -e $out && ! -L $out ]] || { echo 'refusing existing Live initramfs' >&2; exit 2; }
dracut --no-hostonly --add "dmsquash-live" "$out" "$kver"
lsinitrd -m "$out" | grep -Fq 'dmsquash-live' ||
    { echo 'dracut Live module missing' >&2; exit 2; }
printf 'P4_LIVE_INITRAMFS=%s\n' "$out"
