# First experimental ISO — 2026-10-19

## Artifact

| Field | Observed value |
| --- | --- |
| Version | `0.1-experimental` |
| Path | `/home/williandias/G15Forge-VM/iso/g15forge-prototype-v0.1.iso` |
| Size | `1328953344` bytes |
| SHA-256 | `db84a091a3e1615fadcc87bd25ce48b879466e17d0256e28de853b1d38ef8845` |
| Build source commit | `4d421ec` on `feat/iso-prototype-dell-g15-5511` |
| Live runtime | Upstream Gentoo Minimal, kernel `6.18.57` |
| Embedded Stage3 | systemd, SHA-256 `01ed7040d5768b5a056d3c0f7d38b0db23e8c1c4e28a57736d92ea9e30342217` |

The ISO was built from the independently authenticated sources described in [VALIDATION.md](VALIDATION.md). Both detached signatures returned GOODSIG/VALIDSIG; the full primary fingerprint and signing subkey match the official Gentoo Handbook. The ISO source hash is `a0422d9d74c99174417ba2538642e687c838667bbd1ca01293987405116c4c4c`.

The ISO contains build provenance and payload checksums under `/G15FORGE`. External `.sha256` and `.provenance.txt` sidecars accompany it. Later validation-tool and HFS+ metadata-detection improvements do not change the already published artifact or its recorded build commit. Apple firmware/HFS+ blessings are outside this milestone.

## Actual checks

- Local shell syntax, ShellCheck 0.9.0 and 18 Python tests passed, including a real xorriso 1.5.6 hybrid-layout regression with dummy boot files. Those dummy files were never used for the delivered ISO.
- Full ISO checksum, payload manifest and embedded Stage3 checksum passed after extraction.
- BIOS and UEFI El Torito entries, boot paths, load sizes and GRUB BIOS patch options were retained. MBR protective label, GRUB MBR, GPT and APM are present; address/geometry changes account for the larger image.
- Both GPT copies and entry arrays passed CRC checks; all partitions lie within usable bounds without overlap. EFI partition SHA-256 is `c0a7eff5a3dd30eb8b551cb94320c4b7fac0742964dbe6e701d13f1ed2ff8641`, identical to the source.
- BIOS and UEFI KVM guests reached the live shell, reported their firmware mode, read the ISO mounted at `/run/initramfs/live`, verified all payload checksums and checked Stage3 against the independent expected digest.
- The final OVMF + virtio-vga run passed the same guest checks with a readable live console. All four QEMU observations ended with their child process reaped; the initial no-probe run is not counted as boot proof.
- Guest block inventory showed only `sr0` (read-only ISO) and `loop0` (read-only live filesystem). No installation disk or historical QCOW2 was attached. Network was disabled. Each UEFI run had its own NVRAM.
- Reviewed BIOS and UEFI serial kernel logs contained no panic, Oops or failed initramfs/root transition. The live session ran the original Gentoo runtime; the bundled systemd Stage3 is not an installed systemd OS.

## Local evidence

Evidence remains under the repository's ignored `out/` directory. These paths are operator-local; the ISO and large logs are not committed to GitHub.

| Evidence | Location |
| --- | --- |
| Source signatures and input hashes | `out/first-build-20261019/` |
| Full passing local test log | `out/first-build-20261019/tests-real-xorriso.log` |
| Tool versions and aggregate provenance | `out/first-build-20261019/delivery-final.json` |
| Initial ISO inspection | `out/inspection-v0.1/` |
| GPT/EFI validation and extracted payload | `out/inspection-v0.1-gpt/` |
| BIOS guest command, result, serial/dmesg and screenshots | `out/vm-bios-v01/` |
| UEFI guest command, result, serial/dmesg (VGA) | `out/vm-uefi-probe-v01/` |
| UEFI virtio video validation | `out/vm-uefi-virtio-v01/` |
| Successful build work/log | `/home/williandias/G15Forge-VM/iso/.g15forge-build-FrOsrKDS/` |
| Preserved failed build | `/home/williandias/G15Forge-VM/iso/.g15forge-build-IhX8wesD/` |

The first UEFI observation without a guest probe remained NOT_CONFIRMED. A later probe confirmed functional boot and payload checks via serial, despite a corrupted standard-VGA framebuffer. `virtio-vga` provides readable UEFI output and is the runner's new default. No physical GPU, NVIDIA driver, thermal or power behavior is certified by these VM tests.

The subsequent installed systemd target, custom kernel/initramfs/bootloader, drivers, reproducible Live pipeline and measured LLM optimization lab are tracked in [issue #2](https://github.com/WillianPDias/G15-forge/issues/2).
