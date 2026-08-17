#!/usr/bin/env python3
"""Zip a task bundle for upload.

    python3 tools/build_bundle.py tasks/<slug>
    python3 tools/build_bundle.py --all

Writes dist/<slug>.zip with the bundle rooted at a single <slug>/ directory,
matching the layout in the guideline. Runs check_bundle first and refuses to
package a bundle that fails it, because a rejected upload still burns an
artifact.

Executable bits matter: tests/test.sh and solution/solve.sh are the entrypoints
the harness invokes, so their mode is preserved explicitly rather than left to
whatever the zip writer defaults to.
"""

from __future__ import annotations

import argparse
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
EXECUTABLE = {"tests/test.sh", "solution/solve.sh"}


def should_skip(relative: Path) -> bool:
    if any(part in SKIP_DIRS for part in relative.parts):
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
            info = zipfile.ZipInfo(str(Path(slug) / relative))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
            if str(relative) in EXECUTABLE or path.stat().st_mode & stat.S_IXUSR:
                mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, path.read_bytes())
            written += 1

    size = target.stat().st_size
    print(f"wrote {target.relative_to(REPO)} ({written} files, {size:,} bytes)")
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
