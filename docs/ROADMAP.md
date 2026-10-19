# G15Forge delivery gates

| Stage | Product | Verification |
| --- | --- | --- |
| P0 | ISO remaster prototype + Dell profile | shell smoke, input hashes, ISO tooling, distinct output |
| P1 | UEFI/BIOS guest boots prototype | Real VM boot logs, no SSD passthrough; guest sees /G15FORGE payload |
| P2 | Disposable Gentoo systemd VM install | audited QEMU graph, checkpoint, GPT + ESP, Stage3, network, kernel, bootloader; boots without live ISO |
| P3 | Custom kernel + initramfs | signed provenance, config fragments, modules, reproducible build, rollback |
| P4 | Real G15Forge live root ISO | live squashfs/erofs and initramfs integrated; UEFI & BIOS boot, systemd and persistence tested |
| P5 | Dell device enablement | hybrid Intel/NVIDIA graphics, wireless, audio, firmware, ACPI, suspend, battery, thermals, storage |
| P6 | LLM optimization laboratory | baseline → proposal → sandbox build → isolated tests → A/B benchmarks → reviewed promotion |
| P7 | Physical live certification | read-only USB boot on Dell, hardware evidence, thermal and power safeguards |
| P8 | Release | signed ISO, SHA-256, SBOM, vulnerability scanning, rollback and upgrade plan |

P0 ISO is **not** a completed customized OS; it is an official Gentoo live ISO carrying verified project assets. P4 requires actual customized runtime and driver integration.

LLM constraints: restrict write access to a per-experiment workspace, make one meaningful change per experiment, use reproducible benchmarks and thermal limits, reject regressions, forbid direct modification of host or baseline images.

For security: previous Codex candidate reviews v1.4–v1.4.3 remained blocked for live destructive execution. Develop fixes in isolated CI/unit tests, not by bypassing hooks.
