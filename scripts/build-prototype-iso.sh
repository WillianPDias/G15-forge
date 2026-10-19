#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

usage() {
  cat <<'HELP'
Usage: build-prototype-iso.sh --iso PATH --iso-sha256 HEX --out PATH [--stage3 PATH --stage3-sha256 HEX]
Safely remaster a verified Gentoo ISO, adding a G15Forge payload at /G15FORGE.
Never overwrites an existing output. This does NOT install Gentoo or customize
the running live kernel/rootfs. Requires xorriso and sha256sum.
HELP
}
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
iso='' ; out='' ; iso_sha='' ; stage='' ; stage_sha=''
while (($#)); do
  case "$1" in
    --iso|--iso-sha256|--stage3|--stage3-sha256|--out)
      (($# >= 2)) || fail "missing value: $1"
      case "$1" in
        --iso) iso=$2;; --iso-sha256) iso_sha=$2;;
        --stage3) stage=$2;; --stage3-sha256) stage_sha=$2;;
        --out) out=$2;;
      esac
      shift 2;;
    --help|-h) usage; exit 0;;
    *) fail "unknown argument: $1";;
  esac
done
[[ -n "$iso" && -n "$iso_sha" && -n "$out" ]] || fail "required argument missing"
[[ "$iso_sha" =~ ^[a-fA-F0-9]{64}$ ]] || fail "invalid ISO sha256"
[[ -z "$stage" && -z "$stage_sha" || -n "$stage" && -n "$stage_sha" ]] || fail "stage3 path and sha256 must be paired"
if [[ -n "$stage" ]]; then
  [[ "$stage_sha" =~ ^[a-fA-F0-9]{64}$ ]] || fail "invalid Stage3 sha256"
fi
for bin in xorriso sha256sum mktemp cp realpath; do command -v "$bin" >/dev/null || fail "missing executable: $bin"; done
[[ -f "$iso" && ! -L "$iso" ]] || fail "ISO must be a regular non-symlink file"
if [[ -n "$stage" ]]; then [[ -f "$stage" && ! -L "$stage" ]] || fail "Stage3 must be a regular non-symlink file"; fi
iso=$(realpath -e -- "$iso")
if [[ -n "$stage" ]]; then stage=$(realpath -e -- "$stage"); fi
outdir=$(dirname -- "$out")
[[ -d "$outdir" ]] || fail "output directory does not exist"
outdir=$(realpath -e -- "$outdir")
out="$outdir/$(basename -- "$out")"
[[ "$out" != "$iso" && "$out" != "$stage" ]] || fail "output aliases input"
[[ ! -e "$out" && ! -L "$out" ]] || fail "output already exists"
[[ "$out" == *.iso ]] || fail "output must end in .iso"
printf '%s  %s\n' "${iso_sha,,}" "$iso" | sha256sum -c --status || fail "ISO checksum mismatch"
if [[ -n "$stage" ]]; then
  printf '%s  %s\n' "${stage_sha,,}" "$stage" | sha256sum -c --status || fail "Stage3 checksum mismatch"
fi
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ -f "$root/overlays/iso/README.txt" && -f "$root/profiles/dell-g15-5511/make.conf" ]] || fail "missing overlay/profile"
work=$(mktemp -d)
tmpout=$(mktemp -- "$outdir/.g15forge-build-XXXXXXXX.iso")
cleanup() { rm -rf -- "$work"; if [[ -n "${tmpout:-}" ]]; then rm -f -- "$tmpout"; fi; }
trap cleanup EXIT
mkdir -p "$work/G15FORGE/profiles"
cp -- "$root/overlays/iso/README.txt" "$work/G15FORGE/README.txt"
cp -- "$root/profiles/dell-g15-5511/make.conf" "$work/G15FORGE/profiles/make.conf"
if [[ -n "$stage" ]]; then
  cp -- "$stage" "$work/G15FORGE/stage3-amd64-systemd.tar.xz"
  printf '%s  %s\n' "${stage_sha,,}" 'stage3-amd64-systemd.tar.xz' > "$work/G15FORGE/STAGE3.SHA256"
fi
# Preserve existing boot records/configuration of the Gentoo hybrid ISO.
# xorriso must validate and re-emit the boot descriptors; do not claim
# UEFI or BIOS boots successfully until real VM tests pass.
xorriso -indev "$iso" -outdev "$tmpout" \
  -map "$work/G15FORGE" /G15FORGE \
  -boot_image any replay -commit
[[ -s "$tmpout" ]] || fail "xorriso produced an empty image"
# Fail if some other process created the destination; do not overwrite.
( set -C; cat -- "$tmpout" > "$out" ) || fail "could not publish ISO without overwrite"
sha256sum -- "$out" > "$out.sha256"
printf 'ISO_PROTOTYPE=CREATED\nOUTPUT=%s\n' "$out"
printf 'NEXT=VERIFY_BOOT_BIOS_AND_UEFI_IN_DISPOSABLE_VM\n'
