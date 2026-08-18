#!/usr/bin/env python3
"""Audit — and if necessary repair — the ZIP you are about to upload.

    python3 tools/verify_zip.py <path-to.zip>
    python3 tools/verify_zip.py <path-to.zip> --fix

`build_bundle.py` already asserts the five required paths sit at the archive
root, but it can only vouch for the file it wrote. This tool vouches for the
file in your hand, which is the one the inspector actually opens.

The gap between those two is real and it has now cost two uploads with the same
rejection, by two different mechanisms:

1. `build_bundle.py` used to wrap the archive in a `<slug>/` directory.
2. macOS expands a downloaded `.zip` automatically (Safari's "Open safe files
   after downloading" is on by default), so what is left on disk is a *folder*.
   Right-clicking that folder and choosing Compress rebuilds the wrapper — and
   adds a `__MACOSX/` tree and `.DS_Store` on top. Every required path is then
   one directory too deep and the inspector reports "required file missing".

Both look identical from the outside. Run this on the exact file you are about
to upload and the question is settled in five seconds.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path

REQUIRED_PATHS = [
    "task.toml",
    "instruction.md",
    "environment/Dockerfile",
    "tests/test.sh",
    "solution/solve.sh",
]
EXECUTABLE = {"tests/test.sh", "solution/solve.sh"}

# Junk the macOS archiver adds. None of it belongs in an upload.
JUNK_PREFIXES = ("__MACOSX/",)
JUNK_NAMES = {".DS_Store"}


def is_junk(name: str) -> bool:
    if name.startswith(JUNK_PREFIXES):
        return True
    base = name.rsplit("/", 1)[-1]
    return base in JUNK_NAMES or base.startswith("._")


def find_wrapper(names) -> str | None:
    """The shortest directory prefix under which all five required paths sit.

    Not necessarily one level. Zipping `tasks/<slug>/` rather than
    `tasks/<slug>/bundle/` buries them two deep, under `<slug>/bundle/`, and
    sweeps `draft.yaml` and `submission.md` in as well -- which is the shape
    that was actually uploaded and rejected.
    """
    present = set(names)
    prefixes = set()
    for name in names:
        parts = name.split("/")
        for depth in range(1, len(parts)):
            prefixes.add("/".join(parts[:depth]))
    candidates = [
        prefix for prefix in prefixes
        if all(f"{prefix}/{required}" in present for required in REQUIRED_PATHS)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda prefix: (prefix.count("/"), len(prefix)))


def audit(path: Path):
    """Return (ok, wrapper, problems, notes)."""
    problems: list[str] = []
    notes: list[str] = []

    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        return False, None, [f"cannot open as a ZIP: {exc}"], notes

    with archive:
        broken = archive.testzip()
        if broken is not None:
            problems.append(f"corrupt entry: {broken}")
        names = archive.namelist()

    files = [name for name in names if not name.endswith("/")]
    junk = [name for name in files if is_junk(name)]
    real = [name for name in files if not is_junk(name)]

    notes.append(f"{len(files)} entries ({len(real)} real, {len(junk)} macOS junk)")

    missing = [required for required in REQUIRED_PATHS if required not in names]
    wrapper = None
    if missing:
        wrapper = find_wrapper(names)
        if wrapper is not None:
            depth = wrapper.count("/") + 1
            problems.append(
                f"every required path is {depth} director"
                f"{'y' if depth == 1 else 'ies'} too deep, under {wrapper!r}. "
                f"THIS IS THE 'required file missing' REJECTION. The inspector "
                f"looks for 'task.toml', not '{wrapper}/task.toml'. "
                f"Re-run with --fix."
            )
            strays = sorted(
                name for name in real
                if not name.startswith(wrapper + "/") and not name.endswith("/")
            )
            if strays:
                problems.append(
                    f"{len(strays)} file(s) outside the bundle were swept in: "
                    f"{', '.join(strays[:4])}. This archive is a zip of "
                    f"tasks/<slug>/, not of tasks/<slug>/bundle/."
                )
        else:
            problems.append(f"missing at the archive root: {', '.join(missing)}")

    if junk:
        problems.append(
            f"{len(junk)} macOS archiver artefacts present "
            f"({', '.join(sorted(junk)[:3])}...). This archive was produced by "
            f"Finder's Compress, not by build_bundle.py."
        )

    for name in names:
        if name.startswith("/") or ".." in name.split("/"):
            problems.append(f"unsafe path: {name}")
    lowered: dict[str, str] = {}
    for name in real:
        if name.lower() in lowered and lowered[name.lower()] != name:
            problems.append(f"duplicate path differing only in case: {name}")
        lowered[name.lower()] = name

    if not missing:
        with zipfile.ZipFile(path) as archive:
            for required in sorted(EXECUTABLE):
                info = archive.getinfo(required)
                mode = (info.external_attr >> 16) & 0o777
                if not mode & stat.S_IXUSR:
                    problems.append(f"{required} is not executable in the archive ({mode:o})")

    return not problems, wrapper, problems, notes


def repair(path: Path, wrapper: str | None) -> bool:
    """Rewrite the archive flat, dropping the wrapper and the macOS junk."""
    backup = path.with_suffix(path.suffix + ".orig")
    shutil.copy2(path, backup)

    with zipfile.ZipFile(backup) as source:
        entries = []
        for info in source.infolist():
            if info.filename.endswith("/") or is_junk(info.filename):
                continue
            name = info.filename
            if wrapper:
                if not name.startswith(wrapper + "/"):
                    continue      # draft.yaml, submission.md, README - not bundle content
                name = name[len(wrapper) + 1:]
            if not name:
                continue
            entries.append((name, source.read(info), info))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, payload, original in sorted(entries):
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
            was = (original.external_attr >> 16) & 0o777
            if name in EXECUTABLE or was & stat.S_IXUSR:
                mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            info.external_attr = (stat.S_IFREG | mode) << 16
            target.writestr(info, payload)

    print(f"      repaired in place; the original is at {backup.name}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="rewrite the archive flat, dropping any wrapper directory and macOS junk",
    )
    args = parser.parse_args()

    if not args.archive.is_file():
        print(f"error: {args.archive} is not a file", file=sys.stderr)
        return 2

    digest = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    size = args.archive.stat().st_size
    print(f"{args.archive}")
    print(f"      {size:,} bytes   sha256:{digest[:16]}")

    ok, wrapper, problems, notes = audit(args.archive)
    for note in notes:
        print(f"      {note}")

    if ok:
        print("      OK - the five required paths are at the archive root.")
        print("      Upload this file as it is. Do not expand it first.")
        return 0

    for problem in problems:
        print(f"  error: {problem}")

    if args.fix:
        repair(args.archive, wrapper)
        ok, _wrapper, problems, notes = audit(args.archive)
        print(f"      re-checked: {'OK' if ok else 'STILL BROKEN'}")
        for note in notes:
            print(f"      {note}")
        for problem in problems:
            print(f"  error: {problem}")
        if ok:
            digest = hashlib.sha256(args.archive.read_bytes()).hexdigest()
            print(f"      new sha256:{digest[:16]}")
        return 0 if ok else 1

    print("      re-run with --fix to rewrite it, or just upload the file you")
    print("      were sent without expanding it first.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
