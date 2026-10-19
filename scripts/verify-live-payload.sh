#!/bin/sh
# Run inside the booted Gentoo live guest. No writes, networking or installation.
set -eu
payload=${1:-/mnt/cdrom/G15FORGE}
[ -d "$payload" ] || { echo 'G15FORGE_GUEST=FAIL payload directory absent' >&2; exit 1; }
cd -- "$payload"
test -s README.txt
test -s profiles/make.conf
test -s PROVENANCE.txt
test -s stage3-amd64-systemd.tar.xz
sha256sum -c SHA256SUMS
sha256sum -c STAGE3.SHA256
printf 'G15FORGE_GUEST_KERNEL=%s\n' "$(uname -r)"
printf 'G15FORGE_GUEST=PASS\n'
