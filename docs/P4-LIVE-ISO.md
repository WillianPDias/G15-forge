# P4 — Original Gentoo systemd Live ISO candidate

This is the first **original Live root filesystem** pipeline, distinct from
P1 (official Gentoo Live with embedded assets) and P2 (installed-system VM).
It does not access the P2 QCOW2, attempt recovery, or modify the six P2-bound
scripts. The output is a **candidate**, not a boot-validated G15Forge release.

## Architecture

1. Provide a separate, prepared Gentoo systemd root directory, populated
   from authenticated Gentoo sources. It must not be a bind-mounted tree,
   active guest mount, host root, or an unsanitized workstation copy.
2. Include the correct kernel image in rootfs/boot/vmlinuz-VERSION and its
   modules in rootfs/lib/modules/VERSION.
3. Inside that prepared Gentoo environment only, create a dedicated Live
   initramfs with Dracut's dmsquash-live module. The guest helper under
   guest/p4-create-live-initramfs.sh writes only to its own /boot directory.
4. The host-side script scripts/p4_live_iso.py packs rootfs into a direct
   SquashFS, generates GRUB BIOS/UEFI rescue ISO with the dedicated kernel,
   initramfs, and own /boot/grub/grub.cfg, then checks xorriso's reported
   boot entries and volume ID.
5. The ISO's GRUB config selects the new image by CD label
   G15FORGE_LIVE, uses Dracut's live SquashFS driver and a temporary
   OverlayFS writable layer.

Upstream references:
- https://dracut-ng.github.io/dracut/man/dracut.cmdline.7.html
- https://www.gnu.org/software/grub/manual/grub/html_node/Invoking-grub_002dmkrescue.html

The Live kernel command line includes:
    root=live:CDLABEL=G15FORGE_LIVE
    rd.live.dir=/LiveOS rd.live.squashimg=squashfs.img
    rd.live.overlay.overlayfs=1

## Preparation and build

Prepare a **new, separate Gentoo systemd Live root**. Before building:

- Install its verified kernel, matching modules, Dracut (with dmsquash-live),
  systemd, and Live users/services as appropriate.
- Remove private SSH credentials, machine-specific identifiers and secrets.
  The preflight checks common cases; it is NOT an exhaustive secret scanner.
- Clear /etc/machine-id. No fixed / or /boot/efi mounts in /etc/fstab.
- Disable any P2 installed-disk verification unit and prepare Live services.
- Generate a separate Live initramfs inside that Gentoo environment using:
  
      bash p4-create-live-initramfs.sh VERSION

  Copy the reviewed helper there first. Do not run that helper on Pop!_OS.
- Export the result to a separate ordinary rootfs directory without
  /dev, /proc, /sys, /run, or other active bind mounts.

Host prerequisites (not automatically installed): Python 3,
squashfs-tools, grub-mkrescue with BIOS i386-pc and UEFI x86_64-efi
GRUB modules, xorriso and lsinitrd.

Example, substituting actual paths, release and a NONEXISTENT output:

    python3 scripts/p4_live_iso.py \
      --rootfs /ABS/gentoo-live-root \
      --kernel /ABS/gentoo-live-root/boot/vmlinuz-VERSION \
      --initramfs /ABS/gentoo-live-root/boot/initramfs-VERSION-live.img \
      --kernel-release VERSION \
      --out /ABS/new/g15forge-live-v0.2-candidate.iso

Writes a new .iso, a .sha256 checksum and a .provenance.json sidecar.
Existing output files are never replaced. Failed build workspace is kept
under .g15forge-live-* for diagnosis. No physical disks or existing P1/P2
artifacts are inputs unless the operator explicitly prepares a separate root.

## Test and release boundary

Current CI runs only offline guard/unit tests and ShellCheck/syntax checks.
Mocked ISO tools in the unit suite are **not** BIOS/UEFI boot tests.

Before accepting P4, boot the resulting ISO as diskless QEMU/KVM BIOS
and UEFI guests with isolated OVMF NVRAM. Capture real evidence for:
Gentoo identity, systemd as PID 1, matching kernel and modules, own
SquashFS root with writable overlay, system services, storage inventory,
and clean guest poweroff. Never attach a physical /dev/nvme device.

P5 still requires Dell G15 5511 validation of hybrid Intel/NVIDIA
graphics, Wi-Fi, audio, suspend, power, thermals and battery. Those
characteristics cannot be certified by CI or a generic QEMU guest.
