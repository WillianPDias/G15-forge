# Dell G15 5511 baseline (user supplied)

| Component | Known inventory |
| --- | --- |
| Laptop | Dell G15 5511 |
| CPU | Intel Core i7-11800H, Tiger Lake, 8C/16T |
| RAM | 32 GiB |
| GPUs | Intel UHD + NVIDIA RTX 3060 Laptop 6 GiB (GA106M), hybrid graphics |
| Host | Pop!_OS 24.04 COSMIC/Wayland, separate from project |
| NVMe | /dev/nvme1n1 512 GB (host), /dev/nvme0n1 2 TB (data) |
| VM | QEMU/KVM 8.2.2; OVMF UEFI; virtio 80 GiB QCOW2 |
| Stage3 | stage3-amd64-systemd-20261018T124555Z.tar.xz |
| Stage3 SHA-256 | 01ed7040d5768b5a056d3c0f7d38b0db23e8c1c4e28a57736d92ea9e30342217 |

Known boot test: official Gentoo Minimal Live ISO booted UEFI in guest, detected blank 80 GiB virtio disk. This is not proof that G15Forge is installed or bootable yet.

Tuning candidates (do not apply blindly): tigerlake make.conf, intel_pstate/HWP, thermald, TLP or power-profiles-daemon (choose one coherent power-management stack), Intel microcode, NVIDIA proprietary driver compatible with actual kernel, PRIME/offload, Vulkan, firmware and secure-boot signing.

Critical unknowns: exact Wi-Fi chipset, Bluetooth, audio codec, ethernet, touchpad, display/refresh rate, cooling firmware behavior, Dell AC adapter reporting, suspend/resume, Secure Boot state. Inventory during read-only hardware certification before claims of 100% coverage. Battery health was previously degraded; avoid aggressive stress tests without power confirmation.

Safety: never pass either NVMe into QEMU; never run parted/mkfs on Pop host; preserve existing images and host services.
