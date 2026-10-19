#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
bash -n "$repo/scripts/build-prototype-iso.sh"
bash "$repo/scripts/build-prototype-iso.sh" --help >/dev/null
if bash "$repo/scripts/build-prototype-iso.sh" --iso /no/such.iso --iso-sha256 bad --out /tmp/no.iso >/dev/null 2>&1; then
  echo 'SMOKE=FAIL accepted invalid checksum' >&2; exit 1
fi
grep -Fq -- 'tigerlake' "$repo/profiles/dell-g15-5511/make.conf"
grep -Fq -- 'systemd' "$repo/docs/ROADMAP.md"
echo 'SMOKE=PASS'
