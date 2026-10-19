#!/usr/bin/env python3
"""P2 disposable guest controller. Partitioning requires a specific human approval."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import time
import uuid

from test_prototype_vm import qmp, type_text

REPO = Path(__file__).resolve().parents[1]
SIZE = 64 * 1024**3
STAGE_SHA = "01ed7040d5768b5a056d3c0f7d38b0db23e8c1c4e28a57736d92ea9e30342217"
LIVE_SHA = "db84a091a3e1615fadcc87bd25ce48b879466e17d0256e28de853b1d38ef8845"
CODE = Path("/usr/share/OVMF/OVMF_CODE_4M.fd")
VARS = Path("/usr/share/OVMF/OVMF_VARS_4M.fd")
PHASES = {"diagnose": "P2_DIAGNOSE_PASS=", "partition": "P2_PREPARE_PASS=", "install": "P2_INSTALL_PASS=", "verify": "P2_SYSTEMD_PASS"}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(data):
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()


def write_new(path, data):
    with Path(path).open("xb") as stream:
        stream.write(canonical(data))
        stream.flush(); os.fsync(stream.fileno())
    directory = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def regular(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"expected independent regular file: {path}")
    if any(c in str(path) for c in (",", "\n", "\r")):
        raise ValueError("QEMU paths cannot contain commas/newlines")
    return {"path": str(path.resolve()), "device": info.st_dev, "inode": info.st_ino,
            "bytes": info.st_size, "mode": oct(stat.S_IMODE(info.st_mode)), "uid": info.st_uid,
            "gid": info.st_gid, "link_count": info.st_nlink, "sha256": sha(path)}


def source(path, expected):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or sha(path) != expected:
        raise ValueError(f"source identity mismatch: {path}")
    return {"path": str(path.resolve()), "sha256": expected}


def run_tool(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"tool failed ({result.returncode}): {command[0]}\n{result.stderr}")
    return result.stdout


def image_info(path):
    chain = json.loads(run_tool(["qemu-img", "info", "--output=json", "--backing-chain", str(path)]))
    if len(chain) != 1 or chain[0].get("format") != "qcow2" or chain[0].get("virtual-size") != SIZE:
        raise ValueError("expected standalone 64 GiB QCOW2")
    info = chain[0]
    if any(info.get(k) for k in ("backing-filename", "full-backing-filename", "encrypted")):
        raise ValueError("backing/encrypted image forbidden")
    if info.get("format-specific", {}).get("data", {}).get("data-file"):
        raise ValueError("external QCOW2 data file forbidden")
    return info


def guest_hashes():
    files = [REPO / "scripts/p2_vm.py", REPO / "scripts/test_prototype_vm.py", *sorted((REPO / "guest").glob("p2-*.sh"))]
    return {str(path.relative_to(REPO)): sha(path) for path in files}


def load(lab):
    lab = Path(lab)
    if lab.is_symlink() or lab.resolve().parent != (REPO / "out").resolve():
        raise ValueError("P2 lab must be a direct non-symlink child of repository out/")
    state = json.loads((lab / "state.json").read_text())
    if state["lab"] != str(lab.resolve()) or not re.fullmatch(r"[a-f0-9]{32}", state["lab_id"]):
        raise ValueError("lab identity mismatch")
    if state["serial"] != "G15P2" + state["lab_id"][:12]:
        raise ValueError("serial identity mismatch")
    return lab.resolve(), state


@contextmanager
def exclusive(lab):
    with (lab / "control.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def validate(state, pristine=False):
    lab = Path(state["lab"])
    current = regular(lab / "disk.qcow2")
    if current["path"] != state["disk"]["path"] or any(current[k] != state["disk"][k] for k in ("device", "inode")):
        raise ValueError("installation disk replaced")
    if regular(lab / "checkpoint-blank.qcow2") != state["checkpoint"]:
        raise ValueError("checkpoint identity changed")
    if regular(lab / "checkpoint-nvram.fd") != state["checkpoint_nvram"]:
        raise ValueError("NVRAM checkpoint identity changed")
    image_info(lab / "disk.qcow2")
    if pristine and current["sha256"] != state["checkpoint"]["sha256"]:
        raise ValueError("disk no longer matches blank checkpoint; no retry or restoration")
    if guest_hashes() != state["scripts"]:
        raise ValueError("installer changed after preparation; create a new review/lab")
    source(Path(state["stage3"]["path"]), STAGE_SHA)
    source(Path(state["live_iso"]["path"]), LIVE_SHA)
    return current


def qemu_command(state, phase, output, seed=None):
    if phase not in PHASES:
        raise ValueError("unknown phase")
    disk = Path(state["lab"]) / "disk.qcow2"
    ro = ",readonly=on" if phase == "diagnose" else ""
    args = ["qemu-system-x86_64", "-no-user-config", "-nodefaults", "-machine", "q35,accel=kvm",
            "-cpu", "host", "-m", "8192", "-smp", "4", "-device", "virtio-vga",
            "-device", "qemu-xhci", "-device", "usb-kbd",
            "-drive", f"if=none,id=p2disk,format=qcow2,file={disk}{ro}",
            "-device", f"virtio-blk-pci,drive=p2disk,serial={state['serial']}",
            "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={CODE}",
            "-drive", f"if=pflash,format=raw,unit=1,file={output / 'nvram.fd'}",
            "-display", "none", "-monitor", "none", "-serial", f"file:{output / 'serial.log'}",
            "-qmp", f"unix:{output / 'qmp.sock'},server=on,wait=off"]
    if phase == "install":
        args += ["-nic", "user,model=virtio-net-pci,ipv6=off"]
    else:
        args += ["-nic", "none"]
    if phase != "verify":
        if seed is None:
            raise ValueError("live phase requires read-only seed")
        args += ["-device", "ich9-ahci,id=livecontroller",
                 "-drive", f"if=none,id=livecd,format=raw,readonly=on,file={state['live_iso']['path']}",
                 "-device", "ide-cd,drive=livecd,bus=livecontroller.0",
                 "-drive", f"if=none,id=seedcd,format=raw,readonly=on,file={seed}",
                 "-device", "ide-cd,drive=seedcd,bus=livecontroller.1", "-boot", "order=d"]
    else:
        args += ["-boot", "order=c"]
    return args


def audit_blocks(blocks, expected):
    found = {}
    for entry in blocks:
        inserted = entry.get("inserted")
        if not inserted:
            raise ValueError("empty/unexpected block device")
        filename = inserted.get("image", {}).get("filename")
        if not filename or filename not in expected or filename in found:
            raise ValueError(f"unexpected/duplicate QEMU block source: {filename}")
        if inserted["ro"] != expected[filename]:
            raise ValueError(f"unexpected QEMU write access: {filename}")
        found[filename] = inserted["ro"]
    if found != expected:
        raise ValueError("QEMU block graph missing an expected source")


def prepare(args):
    lab = args.lab.resolve() if args.lab else REPO / "out" / ("p2-" + uuid.uuid4().hex[:12])
    if lab.parent != (REPO / "out").resolve():
        raise ValueError("lab must be directly under repository out/")
    live = source(args.live_iso, LIVE_SHA)
    stage = source(args.stage3, STAGE_SHA)
    lab.parent.mkdir(exist_ok=True)
    lab.mkdir(mode=0o700, exist_ok=False)
    state = {"schema": 1, "lab": str(lab), "lab_id": uuid.uuid4().hex, "disk_bytes": SIZE,
             "hostname": "g15forge-p2", "live_iso": live, "stage3": stage, "scripts": guest_hashes()}
    state["serial"] = "G15P2" + state["lab_id"][:12]
    created = run_tool(["qemu-img", "create", "-f", "qcow2", str(lab / "disk.qcow2"), str(SIZE)])
    (lab / "create.log").write_text(created)
    with (lab / "disk.qcow2").open("rb") as src, (lab / "checkpoint-blank.qcow2").open("xb") as dst:
        shutil.copyfileobj(src, dst)
        dst.flush(); os.fsync(dst.fileno())
    (lab / "disk.qcow2").chmod(0o600)
    (lab / "checkpoint-blank.qcow2").chmod(0o400)
    with VARS.open("rb") as src, (lab / "checkpoint-nvram.fd").open("xb") as dst:
        shutil.copyfileobj(src, dst)
        dst.flush(); os.fsync(dst.fileno())
    (lab / "checkpoint-nvram.fd").chmod(0o400)
    state["disk"] = regular(lab / "disk.qcow2")
    state["checkpoint"] = regular(lab / "checkpoint-blank.qcow2")
    state["checkpoint_nvram"] = regular(lab / "checkpoint-nvram.fd")
    if state["disk"]["sha256"] != state["checkpoint"]["sha256"]:
        raise ValueError("checkpoint copy mismatch")
    state["image_info"] = image_info(lab / "disk.qcow2")
    (lab / "image-check.log").write_text(run_tool(["qemu-img", "check", "-f", "qcow2", str(lab / "disk.qcow2")]))
    if regular(lab / "disk.qcow2") != state["disk"]:
        raise ValueError("image changed during checkpoint validation")
    write_new(lab / "state.json", state)
    print(canonical(state).decode())


def review(lab, state):
    validate(state, pristine=True)
    diagnosed = json.loads((lab / "diagnose.json").read_text())
    if diagnosed["result"] != "PASS" or not diagnosed["process_reaped"]:
        raise ValueError("successful read-only guest diagnosis required")
    report = {"operation": "partition-and-format", "lab_id": state["lab_id"], "serial": state["serial"],
              "disk": state["disk"], "checkpoint": state["checkpoint"], "checkpoint_nvram": state["checkpoint_nvram"], "scripts": state["scripts"],
              "diagnosis": diagnosed, "disk_bytes": SIZE,
              "guest_layout": {"table": "GPT", "esp": "1 GiB FAT32", "root": "remaining space ext4"},
              "qemu_command": qemu_command(state, "partition", lab / "r/partition", lab / "r/partition/seed.iso"),
              "status": "AWAITING_SPECIFIC_HUMAN_APPROVAL"}
    write_new(lab / "review.json", report)
    print(canonical(report).decode())
    print("REVIEW_SHA256=" + sha(lab / "review.json"))


def check_approval(lab, state, path):
    approval = json.loads(path.read_text())
    expected = {"approved": True, "operation": "partition-and-format", "lab_id": state["lab_id"],
                "serial": state["serial"], "review_sha256": sha(lab / "review.json")}
    if type(approval.get("approved")) is not bool or approval != expected:
        raise ValueError("approval does not bind this exact reviewed operation")
    review_data = json.loads((lab / "review.json").read_text())
    for key in ("scripts", "disk", "checkpoint", "checkpoint_nvram", "lab_id", "serial"):
        if review_data[key] != state[key]:
            raise ValueError(f"review identity mismatch: {key}")
    return approval


def seed_iso(state, phase, output, approval):
    payload = output / "seed"
    payload.mkdir(mode=0o700)
    for path in (REPO / "guest").glob("p2-*.sh"):
        shutil.copyfile(path, payload / path.name)
    config = {k: state[k] for k in ("lab_id", "serial", "disk_bytes", "hostname")}
    config["stage3_sha256"] = STAGE_SHA
    config["review_sha256"] = sha(Path(state["lab"]) / "review.json") if approval else "NOT_APPROVED"
    write_new(payload / "config.json", config)
    if approval:
        write_new(payload / "approval.json", approval)
    with (payload / "SHA256SUMS").open("x") as manifest:
        for path in sorted(payload.iterdir()):
            if path.name != "SHA256SUMS":
                manifest.write(f"{sha(path)}  {path.name}\n")
    log = run_tool(["xorriso", "-as", "mkisofs", "-quiet", "-R", "-V", "G15P2SEED", "-o", str(output / "seed.iso"), str(payload)])
    (output / "seed-build.log").write_text(log)
    return output / "seed.iso"


def execute(lab, state, phase, approval_path=None, timeout=240):
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        raise ValueError("KVM unavailable; requires approved host execution, no fallback")
    if (lab / f"{phase}.json").exists():
        raise ValueError("phase already completed; no automatic replay")
    validate(state, pristine=phase in ("diagnose", "partition"))
    approval = None
    if phase == "partition":
        if approval_path is None:
            raise ValueError("STOP: specific human approval required before partitioning")
        approval = check_approval(lab, state, approval_path)
    if phase in ("install", "verify"):
        prerequisite = "partition" if phase == "install" else "install"
        if json.loads((lab / f"{prerequisite}.json").read_text())["result"] != "PASS":
            raise ValueError("prerequisite phase did not pass")
    output = lab / "r" / ("partition" if phase == "partition" else phase[0] + "-" + uuid.uuid4().hex[:8])
    output.parent.mkdir(exist_ok=True)
    output.mkdir(mode=0o700)
    if len(os.fsencode(output / "qmp.sock")) >= 104:
        raise ValueError("QMP path too long")
    with (lab / "checkpoint-nvram.fd").open("rb") as src, (output / "nvram.fd").open("xb") as dst:
        shutil.copyfileobj(src, dst)
    seed = seed_iso(state, phase, output, approval) if phase != "verify" else None
    command = qemu_command(state, phase, output, seed)
    write_new(output / "command.json", {"command": command})
    expected = {str(CODE): True, str(output / "nvram.fd"): False,
                str(lab / "disk.qcow2"): phase == "diagnose"}
    if phase != "verify":
        expected.update({state["live_iso"]["path"]: True, str(seed): True})
    report = {"phase": phase, "lab_id": state["lab_id"], "result": "FAIL", "run": str(output), "process_reaped": False}
    process = None
    natural_exit = False
    try:
        with (output / "qemu.log").open("xb") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            report["pid"] = process.pid
            start = time.monotonic()
            while not (output / "qmp.sock").exists():
                if process.poll() is not None or time.monotonic() - start > 15:
                    raise RuntimeError("QEMU failed before QMP; inspect log")
                time.sleep(0.1)
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(10); sock.connect(str(output / "qmp.sock"))
                with sock.makefile("rwb") as stream:
                    if "QMP" not in json.loads(stream.readline()):
                        raise RuntimeError("invalid QMP greeting")
                    qmp(stream, {"execute": "qmp_capabilities"})
                    blocks = qmp(stream, {"execute": "query-block"})
                    write_new(output / "blocks.json", blocks)
                    audit_blocks(blocks, expected)
                    report["block_graph"] = "PASS"
                    typed = False; next_capture = 0
                    while process.poll() is None and time.monotonic() - start < timeout:
                        elapsed = int(time.monotonic() - start)
                        if elapsed >= next_capture:
                            qmp(stream, {"execute": "screendump", "arguments": {"filename": str(output / f"screen-{elapsed:04d}.ppm")}})
                            print(f"P2_PHASE={phase} ELAPSED={elapsed}", flush=True)
                            next_capture = elapsed + 30
                        if phase != "verify" and elapsed >= 90 and not typed:
                            guest_phase = "prepare" if phase == "partition" else phase
                            text = ("(mkdir -p /run/g15forge-seed && mount -o ro /dev/sr1 /run/g15forge-seed && "
                                    f"bash /run/g15forge-seed/p2-installer.sh {guest_phase} /run/g15forge-seed; "
                                    "echo P2_RUN_EXIT=$?; sync; poweroff) > /dev/ttyS0 2>&1\n")
                            (output / "guest-command.txt").write_text(text)
                            type_text(stream, "\n"); time.sleep(2); type_text(stream, text); typed = True
                        time.sleep(1)
                    natural_exit = process.poll() is not None
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=10)
            report["exit_code"] = process.returncode
            report["process_reaped"] = True
        serial = (output / "serial.log").read_text(errors="replace").replace("\r", "") if (output / "serial.log").exists() else ""
        marker = PHASES[phase] + (state["lab_id"] if phase != "verify" else "")
        if natural_exit and report.get("exit_code") == 0 and marker in serial.splitlines() and report.get("block_graph") == "PASS":
            report["result"] = "PASS"
        report["serial_sha256"] = sha(output / "serial.log") if (output / "serial.log").exists() else None
        report["disk_after"] = regular(lab / "disk.qcow2")
        write_new(output / "result.json", report)
    if report["result"] != "PASS":
        raise RuntimeError(f"phase failed; preserved evidence: {output}")
    write_new(lab / f"{phase}.json", report)
    print(canonical(report).decode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    diag = sub.add_parser("diagnose")
    diag.add_argument("--lab", type=Path)
    prep = sub.add_parser("prepare")
    prep.add_argument("--lab", type=Path)
    prep.add_argument("--live-iso", required=True, type=Path)
    prep.add_argument("--stage3", required=True, type=Path)
    for command in ("review", "partition", "install", "verify"):
        child = sub.add_parser(command)
        child.add_argument("--lab", type=Path, required=True)
        if command == "partition":
            child.add_argument("--approval", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "diagnose" and args.lab is None:
        print(canonical({"tools": {name: shutil.which(name) for name in ("qemu-img", "qemu-system-x86_64", "xorriso", "python3")},
                         "kvm_available": os.access("/dev/kvm", os.R_OK | os.W_OK), "ovmf": [str(CODE), str(VARS)]}).decode())
    else:
        lab, state = load(args.lab)
        with exclusive(lab):
            if args.command == "review":
                review(lab, state)
            else:
                execute(lab, state, args.command, getattr(args, "approval", None), 7200 if args.command == "install" else 240)


if __name__ == "__main__":
    main()
