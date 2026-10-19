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
for bin in xorriso sha256sum mktemp cp realpath ln tee; do command -v "$bin" >/dev/null || fail "missing executable: $bin"; done
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
for suffix in .sha256 .provenance.txt; do
  [[ ! -e "$out$suffix" && ! -L "$out$suffix" ]] || fail "output sidecar already exists: $out$suffix"
done
[[ "$out" == *.iso ]] || fail "output must end in .iso"
printf '%s  %s\n' "${iso_sha,,}" "$iso" | sha256sum -c --status || fail "ISO checksum mismatch"
if [[ -n "$stage" ]]; then
  printf '%s  %s\n' "${stage_sha,,}" "$stage" | sha256sum -c --status || fail "Stage3 checksum mismatch"
fi
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ -f "$root/overlays/iso/README.txt" && -f "$root/profiles/dell-g15-5511/make.conf" ]] || fail "missing overlay/profile"
# Retain diagnostics on both success and failure. Never recursively delete paths.
work=$(mktemp -d -- "$outdir/.g15forge-build-XXXXXXXX")
tmpout="$work/image.iso"
trap 'printf "BUILD_WORKDIR=%s\n" "$work" >&2' EXIT
mkdir -p "$work/G15FORGE/profiles"
cp -- "$root/overlays/iso/README.txt" "$work/G15FORGE/README.txt"
cp -- "$root/profiles/dell-g15-5511/make.conf" "$work/G15FORGE/profiles/make.conf"
cp -- "$root/scripts/verify-live-payload.sh" "$work/G15FORGE/verify-live-payload.sh"
if [[ -n "$stage" ]]; then
  cp -- "$stage" "$work/G15FORGE/stage3-amd64-systemd.tar.xz"
  printf '%s  %s\n' "${stage_sha,,}" 'stage3-amd64-systemd.tar.xz' > "$work/G15FORGE/STAGE3.SHA256"
fi
{
  printf 'G15FORGE_VERSION=0.1-experimental\nBUILD_UTC=%s\n' "$(date -u +%FT%TZ)"
  printf 'SOURCE_ISO=%s\nSOURCE_ISO_SHA256=%s\n' "$iso" "${iso_sha,,}"
  printf 'SOURCE_STAGE3=%s\nSOURCE_STAGE3_SHA256=%s\n' "$stage" "${stage_sha,,}"
  printf 'AUTHENTICATION=caller_must_verify_Gentoo_signature_independently\n'
  printf 'BOOT_STATUS=NOT_TESTED\n'
  if command -v git >/dev/null && git -C "$root" rev-parse HEAD >/dev/null 2>&1; then
    printf 'GIT_COMMIT=%s\n' "$(git -C "$root" rev-parse HEAD)"
    printf 'GIT_STATUS_BEGIN\n'
    git -C "$root" status --porcelain --untracked-files=normal
    printf 'GIT_STATUS_END\n'
  fi
  sha256sum -- "$root/scripts/build-prototype-iso.sh" "$root/scripts/verify-live-payload.sh"
  bash --version | head -n 1
  xorriso -version 2>&1
  printf 'BUILD_COMMAND='
  printf '%q ' bash "$root/scripts/build-prototype-iso.sh" --iso "$iso" --iso-sha256 "$iso_sha" --out "$out"
  if [[ -n "$stage" ]]; then printf '%q ' --stage3 "$stage" --stage3-sha256 "$stage_sha"; fi
  printf '\n'
} > "$work/G15FORGE/PROVENANCE.txt"
(
  cd -- "$work/G15FORGE"
  files=(README.txt profiles/make.conf verify-live-payload.sh PROVENANCE.txt)
  if [[ -n "$stage" ]]; then files+=(stage3-amd64-systemd.tar.xz STAGE3.SHA256); fi
  sha256sum -- "${files[@]}" > SHA256SUMS
)
# Preserve existing boot records/configuration of the Gentoo hybrid ISO.
# xorriso must validate and re-emit the boot descriptors; do not claim
# UEFI or BIOS boots successfully until real VM tests pass.
xorriso -indev "$iso" -outdev "$tmpout" \
  -map "$work/G15FORGE" /G15FORGE \
  -boot_image any replay -commit 2>&1 | tee "$work/xorriso-build.log"
[[ -s "$tmpout" ]] || fail "xorriso produced an empty image"
# An atomic hard link cannot replace a competing destination or expose a partial ISO.
ln -T -- "$tmpout" "$out" || fail "could not publish ISO without overwrite"
( set -C; sha256sum -- "$out" > "$out.sha256" ) || fail "could not publish checksum without overwrite"
( set -C; cat -- "$work/G15FORGE/PROVENANCE.txt" > "$out.provenance.txt" ) || fail "could not publish provenance without overwrite"
printf 'ISO_PROTOTYPE=CREATED\nOUTPUT=%s\n' "$out"
printf 'NEXT=VERIFY_BOOT_BIOS_AND_UEFI_IN_DISPOSABLE_VM\n'
