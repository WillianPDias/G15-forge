#!/usr/bin/env python3
"""Diskless KVM boot observation. Screenshots/logs require human assessment."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time


def command(iso, output, firmware, code, display):
    args = [
        "qemu-system-x86_64", "-no-user-config", "-nodefaults",
        "-machine", "q35,accel=kvm", "-cpu", "host", "-m", "4096", "-smp", "4",
        "-device", "VGA", "-device", "qemu-xhci", "-device", "usb-kbd",
        "-device", "ich9-ahci,id=cdcontroller",
        "-drive", f"file={iso},if=none,id=livecd,format=raw,readonly=on",
        "-device", "ide-cd,drive=livecd,bus=cdcontroller.0",
        "-boot", "order=d,menu=on", "-nic", "none", "-display", display,
        "-monitor", "none", "-serial", f"file:{output / 'serial.log'}",
        "-qmp", f"unix:{output / 'qmp.sock'},server=on,wait=off",
    ]
    if firmware == "uefi":
        args += ["-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={code}",
                 "-drive", f"if=pflash,format=raw,unit=1,file={output / 'nvram.fd'}"]
    return args


def qmp(stream, request):
    stream.write((json.dumps(request) + "\n").encode())
    stream.flush()
    while True:
        line = stream.readline()
        if not line:
            raise RuntimeError("QMP disconnected")
        reply = json.loads(line)
        if "error" in reply:
            raise RuntimeError(str(reply["error"]))
        if "return" in reply:
            return reply["return"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True, help="new directory; retained as evidence")
    parser.add_argument("--firmware", choices=("uefi", "bios"), default="uefi")
    parser.add_argument("--duration", type=int, default=180)
    parser.add_argument("--display", choices=("none", "gtk"), default="none")
    parser.add_argument("--ovmf-code", type=Path, default=Path("/usr/share/OVMF/OVMF_CODE_4M.fd"))
    parser.add_argument("--ovmf-vars", type=Path, default=Path("/usr/share/OVMF/OVMF_VARS_4M.fd"))
    args = parser.parse_args()
    if not 10 <= args.duration <= 1800:
        parser.error("duration must be between 10 and 1800 seconds")
    if not args.iso.is_file() or args.iso.is_symlink():
        parser.error("ISO must be a regular non-symlink file")
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        parser.error("BLOCKED: /dev/kvm absent or inaccessible; no acceleration fallback")
    if not shutil.which("qemu-system-x86_64"):
        parser.error("qemu-system-x86_64 missing")
    if args.firmware == "uefi" and not (args.ovmf_code.is_file() and args.ovmf_vars.is_file()):
        parser.error("OVMF code/vars missing")
    iso = args.iso.resolve()
    output = args.out_dir.resolve()
    # Commas delimit QEMU drive options; never interpret a filename as extra options.
    for path in (iso, output, args.ovmf_code.resolve()):
        if "," in str(path) or "\n" in str(path):
            parser.error("paths containing commas or newlines are unsupported")
    if len(os.fsencode(output / "qmp.sock")) >= 104:
        parser.error("output path too long for a QMP Unix socket")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    if args.firmware == "uefi":
        with args.ovmf_vars.open("rb") as source, (output / "nvram.fd").open("xb") as target:
            shutil.copyfileobj(source, target)
    cmd = command(iso, output, args.firmware, args.ovmf_code.resolve(), args.display)
    report = {"command": cmd, "firmware": args.firmware, "boot": "NOT_CONFIRMED",
              "guest_payload": "NOT_TESTED", "start_utc": time.strftime("%FT%TZ", time.gmtime())}
    (output / "command.json").write_text(json.dumps(report, indent=2) + "\n")
    process = None
    try:
        with (output / "qemu.log").open("xb") as log:
            process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            report["pid"] = process.pid
            start = time.monotonic()
            while not (output / "qmp.sock").exists():
                if process.poll() is not None or time.monotonic() - start > 15:
                    raise RuntimeError("QEMU failed to open QMP; inspect qemu.log")
                time.sleep(0.1)
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(10)
                sock.connect(str(output / "qmp.sock"))
                with sock.makefile("rwb") as stream:
                    greeting = json.loads(stream.readline())
                    if "QMP" not in greeting:
                        raise RuntimeError("invalid QMP greeting")
                    qmp(stream, {"execute": "qmp_capabilities"})
                    next_capture = 0
                    while process.poll() is None and time.monotonic() - start < args.duration:
                        elapsed = int(time.monotonic() - start)
                        if elapsed >= next_capture:
                            qmp(stream, {"execute": "screendump", "arguments": {
                                "filename": str(output / f"screen-{elapsed:04d}.ppm")}})
                            next_capture = elapsed + 30
                        time.sleep(1)
                    report["qemu_status"] = qmp(stream, {"execute": "query-status"}) if process.poll() is None else "exited"
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            report["exit_code"] = process.returncode
            report["process_reaped"] = True
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"VM_OBSERVATION=RECORDED\nBOOT=NOT_CONFIRMED\nEVIDENCE={output}")


if __name__ == "__main__":
    main()
