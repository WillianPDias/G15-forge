#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
[[ -f /etc/g15forge-p2/config.json ]] || exit 2
mkdir -p /var/log/g15forge-p2
exec > >(tee /var/log/g15forge-p2/chroot.log) 2>&1
locale-gen
ln -snf /usr/share/zoneinfo/America/Sao_Paulo /etc/localtime
printf 'America/Sao_Paulo\n' > /etc/timezone
systemd-machine-id-setup
mkdir -p /etc/portage/package.license
printf 'sys-firmware/intel-microcode intel-ucode\n' > /etc/portage/package.license/g15forge-p2
emerge-webrsync
[[ $(readlink -f /etc/portage/make.profile) == */systemd ]] || { echo 'P2_ERROR=non-systemd profile'; exit 2; }
# The upstream binhost supplies signatures; never accept unsigned packages.
# The official binhost publishes no gentoo-kernel-bin binary, so the reviewed
# Gentoo distribution kernel (gentoo-kernel) is built from the signed sources
# that the same binhost provides. intel-microcode carries the intel-ucode
# license restriction that blocks binary redistribution through the binhost,
# so it is also built from its signed distfile; every other package stays
# binary-only.
emerge --getbinpkgonly --ask=n sys-fs/dosfstools sys-fs/e2fsprogs sys-kernel/dracut sys-boot/grub
emerge --getbinpkg --ask=n sys-kernel/gentoo-kernel sys-firmware/intel-microcode
kver=$(find /lib/modules -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -V | tail -n 1)
[[ -n $kver ]] || { echo 'P2_ERROR=no installed kernel modules'; exit 2; }
machine=$(cat /etc/machine-id)
for image in "/lib/modules/$kver/vmlinuz" "/boot/vmlinuz-$kver" "/boot/$machine/$kver/linux"; do
  if [[ -s $image ]]; then
    if [[ ! $image -ef /boot/vmlinuz-$kver ]]; then cp "$image" "/boot/vmlinuz-$kver"; fi
    break
  fi
done
[[ -s /boot/vmlinuz-$kver ]] || { echo 'P2_ERROR=kernel image absent'; exit 2; }
mkdir -p /etc/dracut.conf.d
printf 'hostonly="no"\nearly_microcode="yes"\nadd_drivers+=" virtio_pci virtio_blk virtio_net "\n' > /etc/dracut.conf.d/g15forge-p2.conf
dracut --force "/boot/initramfs-$kver.img" "$kver"
cat > /etc/default/grub <<'EOF'
GRUB_TIMEOUT=3
GRUB_DISTRIBUTOR="G15Forge P2"
GRUB_CMDLINE_LINUX="console=tty0 console=ttyS0,115200n8"
GRUB_DISABLE_OS_PROBER=true
EOF
grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=G15Forge --removable --no-nvram
grub-mkconfig -o /boot/grub/grub.cfg
test -s /boot/efi/EFI/BOOT/BOOTX64.EFI
test -s "/boot/initramfs-$kver.img"
cat > /etc/systemd/system/g15forge-p2-verify.service <<'EOF'
[Unit]
Description=G15Forge P2 installed guest evidence
After=local-fs.target systemd-journald.service systemd-udevd.service systemd-networkd.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/g15forge-p2-verify
StandardOutput=journal+console
StandardError=journal+console
[Install]
WantedBy=multi-user.target
EOF
systemctl enable systemd-networkd.service systemd-resolved.service g15forge-p2-verify.service
ln -snf /run/systemd/resolve/resolv.conf /etc/resolv.conf
emerge --info > /var/log/g15forge-p2/emerge-info.txt
find /var/db/pkg -mindepth 2 -maxdepth 2 -type d | sort > /var/log/g15forge-p2/packages.txt
sha256sum "/boot/vmlinuz-$kver" "/boot/initramfs-$kver.img" /boot/efi/EFI/BOOT/BOOTX64.EFI > /etc/g15forge-p2/boot.sha256
echo "P2_KERNEL=$kver"
