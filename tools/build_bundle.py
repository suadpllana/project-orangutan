#!/usr/bin/env python3
"""Zip a task bundle for upload.

    python3 tools/build_bundle.py tasks/<slug>
    python3 tools/build_bundle.py --all

Writes dist/<slug>.zip with the bundle's contents at the ARCHIVE ROOT - no
<slug>/ wrapper, because the inspector looks for "task.toml", not
"<slug>/task.toml". Runs check_bundle first and refuses to package a bundle that
fails it, because a rejected upload still burns an artifact, then re-opens the
finished archive and asserts the five required paths are really in it.

Executable bits matter: tests/test.sh and solution/solve.sh are the entrypoints
the harness invokes, so their mode is preserved explicitly rather than left to
whatever the zip writer defaults to.
"""

from __future__ import annotations

import argparse
import hashlib
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
# Reward artefacts a local grader run leaves behind. Shipping one would put a
# stale score inside the archive.
SKIP_NAMES = {"reward.txt", "reward.json", "score.txt", "score.json", "junit.xml"}
EXECUTABLE = {"tests/test.sh", "solution/solve.sh"}

# The exact set the inspection stage looks for, at the archive root.
REQUIRED_PATHS = [
    "task.toml",
    "instruction.md",
    "environment/Dockerfile",
    "tests/test.sh",
    "solution/solve.sh",
]


def should_skip(relative: Path) -> bool:
    if any(part in SKIP_DIRS for part in relative.parts):
        return True
    if relative.name in SKIP_NAMES:
        return True
    return relative.suffix in SKIP_SUFFIXES


def build(task_dir: Path, run_checks: bool) -> bool:
    slug = task_dir.name
    bundle = task_dir / "bundle"
    if not bundle.is_dir():
        print(f"error: {slug} has no bundle/", file=sys.stderr)
        return False

    if run_checks:
        checked = subprocess.run(
            [sys.executable, str(REPO / "tools" / "check_bundle.py"), str(task_dir)]
        )
        if checked.returncode != 0:
            print(f"error: {slug} fails the structure/quality checks", file=sys.stderr)
            return False

    DIST.mkdir(exist_ok=True)
    target = DIST / f"{slug}.zip"

    files = sorted(p for p in bundle.rglob("*") if p.is_file())
    written = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(bundle)
            if should_skip(relative):
                continue
            # Paths go in at the ARCHIVE ROOT, with no <slug>/ wrapper: the
            # inspector looks for "task.toml", not "<slug>/task.toml".  The
            # guideline's `my-task/` diagram is the on-disk task directory whose
            # *contents* are zipped, not a level inside the archive - reading it
            # the other way got a bundle rejected for "required file missing"
            # with all five files present one directory too deep.
            # POSIX separators throughout: on Windows `str(relative)` is
            # `tests\test.sh`, which silently missed the EXECUTABLE set and
            # shipped both entrypoints without their executable bit.
            name = relative.as_posix()
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
            if name in EXECUTABLE or path.stat().st_mode & stat.S_IXUSR:
                mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, path.read_bytes())
            written += 1

    # Verify the archive we just wrote, not the directory we read.  Everything
    # else in this repository checks `bundle/` on disk, which is exactly what
    # let a packaging bug through.
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
    missing = [path for path in REQUIRED_PATHS if path not in names]
    if missing:
        print(
            f"error: {', '.join(missing)} not at the archive root - the "
            f"inspector will reject this as 'required file missing'",
            file=sys.stderr,
        )
        return False

    size = target.stat().st_size
    digest = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
    print(f"wrote {target.relative_to(REPO)} ({written} files, {size:,} bytes)")
    print("      required paths present at the archive root")
    # A fingerprint, so "which zip did you upload?" has an answer. Every send of
    # a bundle should quote it.
    print(f"      sha256:{digest}")
    # This verification ends at the filesystem. What the inspector opens is
    # whatever survives the download, and macOS auto-expands a .zip and puts the
    # <slug>/ wrapper back the moment the folder is re-compressed -- which is
    # the "required file missing" rejection, a second time. Say so here, and
    # check the uploaded file with tools/verify_zip.py.
    print("      upload this file AS IS - do not expand it first")
    print(f"      verify the file you upload: python3 tools/verify_zip.py "
          f"{target.relative_to(REPO)}")
    if size > 512 * 1024 * 1024:
        print("error: over the 512 MiB upload cap", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--no-checks", action="store_true", help="skip check_bundle.py (not advised)"
    )
    args = parser.parse_args()

    paths = list(args.paths)
    if args.all or not paths:
        paths = sorted(p for p in (REPO / "tasks").iterdir() if p.is_dir())
    if not paths:
        print("no tasks found")
        return 1

    return 0 if all(build(p.resolve(), not args.no_checks) for p in paths) else 1


if __name__ == "__main__":
    sys.exit(main())
