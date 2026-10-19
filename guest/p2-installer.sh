#!/usr/bin/env bash
# This program is delivered on a read-only seed CD and runs INSIDE QEMU only.
set -euo pipefail
export LC_ALL=C
phase=${1:?diagnose, prepare, install or verify}
seed=${2:-/run/g15forge-seed}
fail() { echo "P2_ERROR=$*" >&2; exit 2; }
[[ $EUID == 0 ]] || fail 'guest root required'
[[ -f "$seed/config.json" && -f "$seed/SHA256SUMS" ]] || fail 'seed absent'
(cd "$seed" && sha256sum -c SHA256SUMS)
# shellcheck source=guest/p2-identity.sh
source "$seed/p2-identity.sh"
readarray -t config < <(python3 - "$seed/config.json" <<'PY'
import json,sys
c=json.load(open(sys.argv[1]))
for k in ('lab_id','serial','disk_bytes','stage3_sha256','hostname'):
 print(c[k])
PY
)
[[ ${#config[@]} == 5 ]] || fail 'invalid config'
lab_id=${config[0]}; serial=${config[1]}; disk_bytes=${config[2]}; stage_sha=${config[3]}; hostname=${config[4]}
[[ $lab_id =~ ^[a-f0-9]{32}$ && $serial =~ ^G15P2[a-f0-9]{12}$ ]] || fail 'invalid identity'
[[ $disk_bytes == 68719476736 && $stage_sha =~ ^[a-f0-9]{64}$ && $hostname == g15forge-p2 ]] || fail 'invalid configuration'
disk=/dev/vda
target=/mnt/g15forge-p2

check_disk() {
  [[ -d /sys/firmware/efi && -b $disk ]] || fail 'UEFI guest/virtio disk absent'
  grep -Fq 'root=live:' /proc/cmdline || fail 'installation requires the live guest'
  p2_check_serial "$serial" || fail 'kernel virtio serial mismatch'
  [[ $(blockdev --getsize64 "$disk") == "$disk_bytes" ]] || fail 'disk size mismatch'
  [[ $(lsblk -dn -o TYPE "$disk") == disk ]] || fail 'not a whole virtual disk'
  [[ $(lsblk -dn -o NAME,TYPE | awk '$2=="disk" {print $1}') == vda ]] || fail 'unexpected additional disk'
}

unmounted_disk() {
  [[ -z $(lsblk -nr -o MOUNTPOINT "$disk" | tr -d '[:space:]') ]] || fail 'target already mounted'
  ! swapon --show=NAME --noheadings | grep -Eq '^/dev/vda' || fail 'target swap active'
}

case "$phase" in
  diagnose)
    lsblk -b -o NAME,TYPE,SIZE,RO,SERIAL,FSTYPE,MOUNTPOINT
    if [[ -f /sys/class/block/vda/serial ]]; then printf 'P2_SYSFS_SERIAL='; cat /sys/class/block/vda/serial; printf '\n'; fi
    check_disk
    findmnt -t iso9660
    for tool in sgdisk mkfs.fat mkfs.ext4 blkid mount chroot tar python3 sha256sum; do
      command -v "$tool" || fail "guest tool missing: $tool"
    done
    echo "P2_DIAGNOSE_PASS=$lab_id"
    ;;
  prepare)
    check_disk; unmounted_disk
    [[ $(blockdev --getro "$disk") == 0 ]] || fail 'disk is read-only'
    [[ $(lsblk -nr -o TYPE "$disk") == disk ]] || fail 'target already partitioned'
    [[ -s "$seed/approval.json" ]] || fail 'specific operator approval absent'
    python3 - "$seed/config.json" "$seed/approval.json" <<'PY'
import json,sys
c,a=[json.load(open(p)) for p in sys.argv[1:]]
assert a['operation']=='partition-and-format' and a['lab_id']==c['lab_id']
assert a['serial']==c['serial'] and a['review_sha256']==c['review_sha256']
assert a['approved'] is True
PY
    # Exactly this disk/serial, approved after a host checkpoint and graph review.
    sgdisk --clear --new=1:2048:+1G --typecode=1:ef00 --change-name=1:G15P2_EFI \
      --new=2:0:0 --typecode=2:8300 --change-name=2:G15P2_ROOT "$disk"
    blockdev --rereadpt "$disk"
    udevadm settle
    [[ -b /dev/vda1 && -b /dev/vda2 ]] || fail 'partitions absent'
    mkfs.fat -F 32 -n G15P2EFI /dev/vda1
    mkfs.ext4 -L G15P2ROOT /dev/vda2
    sync
    sgdisk --verify "$disk"
    blkid /dev/vda1 /dev/vda2
    echo "P2_PREPARE_PASS=$lab_id"
    ;;
  install)
    check_disk; unmounted_disk
    [[ $(blkid -s LABEL -o value /dev/vda1) == G15P2EFI ]] || fail 'ESP label mismatch'
    [[ $(blkid -s LABEL -o value /dev/vda2) == G15P2ROOT ]] || fail 'root label mismatch'
    [[ $(blkid -s TYPE -o value /dev/vda1) == vfat && $(blkid -s TYPE -o value /dev/vda2) == ext4 ]] || fail 'filesystem mismatch'
    stage=/run/initramfs/live/G15FORGE/stage3-amd64-systemd.tar.xz
    printf '%s  %s\n' "$stage_sha" "$stage" | sha256sum -c
    if ! ip route show default | grep -q '^default'; then
      command -v dhcpcd >/dev/null || fail 'DHCP client missing in live guest'
      dhcpcd -4 -w -t 30
    fi
    mkdir -p "$target"
    mount /dev/vda2 "$target"
    [[ ! -e "$target/etc/gentoo-release" ]] || fail 'target already contains Gentoo; no automatic reinstall'
    tar xpf "$stage" --xattrs --acls --numeric-owner -C "$target"
    mkdir -p "$target/boot/efi" "$target/etc/g15forge-p2" "$target/usr/local/sbin"
    mount /dev/vda1 "$target/boot/efi"
    cp --remove-destination /etc/resolv.conf "$target/etc/resolv.conf"
    cp "$seed/config.json" "$target/etc/g15forge-p2/config.json"
    cp "$seed/p2-installed-verify.sh" "$target/usr/local/sbin/g15forge-p2-verify"
    chmod 0755 "$target/usr/local/sbin/g15forge-p2-verify"
    root_uuid=$(blkid -s UUID -o value /dev/vda2)
    efi_uuid=$(blkid -s UUID -o value /dev/vda1)
    printf 'UUID=%s / ext4 defaults 0 1\nUUID=%s /boot/efi vfat umask=0077 0 2\n' "$root_uuid" "$efi_uuid" > "$target/etc/fstab"
    printf '%s\n' "$root_uuid" > "$target/etc/g15forge-p2/root-uuid"
    printf '%s\n' "$efi_uuid" > "$target/etc/g15forge-p2/efi-uuid"
    printf '%s\n' "$hostname" > "$target/etc/hostname"
    printf 'LANG=en_US.UTF-8\n' > "$target/etc/locale.conf"
    printf 'en_US.UTF-8 UTF-8\n' > "$target/etc/locale.gen"
    mkdir -p "$target/etc/systemd/network" "$target/etc/portage/repos.conf" "$target/etc/portage/binrepos.conf"
    cat > "$target/etc/systemd/network/20-wired.network" <<'EOF'
[Match]
Name=en* eth*
[Network]
DHCP=yes
EOF
    cat > "$target/etc/portage/repos.conf/gentoo.conf" <<'EOF'
[gentoo]
location = /var/db/repos/gentoo
sync-type = webrsync
sync-webrsync-verify-signature = true
EOF
    cat > "$target/etc/portage/binrepos.conf/gentoo.conf" <<'EOF'
[gentoobinhost]
priority = 9999
sync-uri = https://distfiles.gentoo.org/releases/amd64/binpackages/23.0/x86-64
verify-signature = true
EOF
    cat >> "$target/etc/portage/make.conf" <<'EOF'

# G15Forge P2 conservative VM baseline: no unmeasured host-specific tuning.
MAKEOPTS="-j4"
FEATURES="${FEATURES} binpkg-request-signature"
GRUB_PLATFORMS="efi-64"
GENTOO_MIRRORS="https://distfiles.gentoo.org"
EOF
    mount -t proc proc "$target/proc"
    for path in sys dev run; do mount --rbind "/$path" "$target/$path"; mount --make-rslave "$target/$path"; done
    cp "$seed/p2-chroot.sh" "$target/etc/g15forge-p2/chroot.sh"
    chroot "$target" /bin/bash /etc/g15forge-p2/chroot.sh
    sync
    echo "P2_INSTALL_PASS=$lab_id"
    ;;
  *) fail 'unknown phase';;
esac
