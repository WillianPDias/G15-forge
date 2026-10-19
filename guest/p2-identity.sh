#!/usr/bin/env bash
# Kernel identity is authoritative here; an offline udev DB can leave lsblk SERIAL empty.
p2_check_serial() {
  local expected=$1 file=${2:-/sys/class/block/vda/serial} observed
  [[ $expected =~ ^G15P2[a-f0-9]{12}$ && -f $file ]] || return 2
  observed=$(cat -- "$file") || return 2
  [[ $observed == "$expected" ]]
}
