#!/usr/bin/env python3
"""Read-only evidence summarizer for one P2 lab.

Prints the lab identity, disk/checkpoint integrity comparison, bound-script
drift, phase receipts and review binding. It never writes, never runs QEMU
and never touches a network; missing records are reported as absent instead
of raising, so a partially executed lab still produces a complete picture.
"""
import argparse
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PHASES = ("diagnose", "partition", "install", "verify")


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def summarize(lab):
    lab = Path(lab).resolve()
    if lab.parent != (REPO / "out").resolve():
        raise ValueError("lab must be a direct child of repository out/")
    state = load(lab / "state.json")
    lines = [f"lab={lab.name}", f"lab_id={state['lab_id']}", f"serial={state['serial']}"]
    disk = state["disk"]
    lines.append(f"disk path={disk['path']}")
    lines.append(f"disk inode={disk['inode']} bytes={disk['bytes']} mode={disk['mode']}")
    current = sha(lab / "disk.qcow2")
    lines.append(f"disk sha256={current}")
    lines.append(f"checkpoint match={'YES' if current == state['checkpoint']['sha256'] else 'NO'}")
    lines.append(f"nvram checkpoint sha256={state['checkpoint_nvram']['sha256']}")
    changed = [path for path, expected in sorted(state["scripts"].items()) if sha(REPO / path) != expected]
    lines.append(f"bound scripts unchanged={'YES' if not changed else 'NO ' + ','.join(changed)}")
    for phase in PHASES:
        record = lab / f"{phase}.json"
        if record.exists():
            data = load(record)
            lines.append(f"phase {phase}: {data.get('result')} block_graph={data.get('block_graph', '-')} run={data.get('run', '-')}")
        else:
            lines.append(f"phase {phase}: not executed")
    review = lab / "review.json"
    if review.exists():
        lines.append(f"review sha256={sha(review)}")
        lines.append(f"review status={load(review)['status']}")
    else:
        lines.append("review: absent")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Summarize one P2 lab without modifying it")
    parser.add_argument("--lab", required=True, help="lab directory under out/")
    args = parser.parse_args(argv)
    print(summarize(args.lab))


if __name__ == "__main__":
    main()
