# G15Forge implementation contract

- Goal: fully custom and verified Dell G15 5511 Gentoo systemd OS, first QEMU/KVM, later read-only physical live boot, ultimately a bootable distributable ISO.
- Implement working software and real tests; distinguish synthetic PASS from boot/hardware validation.
- Work on branches, use PR review, never force-push main.
- No access to or modification of physical /dev/nvme* devices, host Pop!_OS, Docker, AI Engineering OS, or Codex hooks.
- Use no host-disk passthrough. Partition only disposable QCOW2 targets with explicit verified identities and human approval.
- Keep original Gentoo ISO, Stage3 and base QCOW2 immutable. Verify Stage3 before extraction; preserve provenance.
- On denied hooks STOP the denied action; continue independent permitted coding work.
- Never claim NVIDIA 3060, power limits, battery, thermals or Wi-Fi are tested in pure QEMU.
- Keep performance claims benchmark-based and reversible. Avoid blind -O3 or global compiler CFLAGS for unproven gains.
- LLM optimization loop can propose changes, but acceptance requires A/B measurements, reproducibility, safety gates and checkpoint.
- Build prototype first; kernel/initramfs, bootloader, installed Gentoo, signed packages and official hardware certification follow.
