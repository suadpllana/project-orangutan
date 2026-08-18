#!/usr/bin/env python3
"""Run the structure and quality-check gates locally, before uploading.

    python3 tools/check_bundle.py tasks/<slug>
    python3 tools/check_bundle.py --all

Both stages are deterministic host-side checks, so failing them after upload
tells you nothing you could not have learned here. This reproduces:

  structure      required paths present, paths safe and unique, task.toml parses
  quality check  instruction substantive, task name declared, solution/ and
                 tests/ non-empty

plus the cross-checks the intake performs between task.toml and the draft: the
bundle's [environment] resources may ask for less than the draft, never more,
and the rollout's network posture has to agree with networkRequirements.

What it cannot check is the part that actually decides your task: the rubric
judge, the oracle and nop runs, and the difficulty probe. Passing here is the
floor.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required: pip install pyyaml")

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11
    sys.exit("Python 3.11+ is required for tomllib")

REPO = Path(__file__).resolve().parent.parent

REQUIRED_PATHS = [
    "task.toml",
    "instruction.md",
    "environment/Dockerfile",
    "tests/test.sh",
    "solution/solve.sh",
]

# The host-side floor for "instruction present and substantive". Deliberately
# well below the bar a reviewer expects - clearing it proves nothing.
INSTRUCTION_FLOOR_CHARS = 200

MAX_BUNDLE_BYTES = 512 * 1024 * 1024

AGENT_NETWORK_MODES = {"none", "allowlist"}

# The task.toml schema, transcribed from an APPROVED bundle. Keys the approved
# task declares that we would otherwise have guessed at, and — just as
# important — the one key it does NOT declare.
METADATA_REQUIRED = [
    "name",
    "title",
    "description",
    "collection_family",
    "task_family",
    "verifier_family",
    "expert_time_estimate_hours",
]
VERIFIER_REQUIRED = ["entrypoint", "network_mode", "timeout_sec", "reward_file",
                     "pass_threshold"]
ENVIRONMENT_REQUIRED = ["dockerfile", "build_context", "cpus", "memory_mb",
                        "storage_mb", "gpus"]
# `[environment]` declares the build, not a network posture. An approved bundle
# has no network_mode here; putting one in gets "resource declaration mismatch".
ENVIRONMENT_FORBIDDEN = ["network_mode"]

# task.toml uses snake_case for the families; the draft form shows title case.
BUNDLE_COLLECTION_FAMILIES = {
    "library_clone", "product_clone", "ml_engineering", "algorithmic_optimization",
}
DRAFT_TO_BUNDLE_FAMILY = {
    "Library clone": "library_clone",
    "Product clone": "product_clone",
    "ML engineering": "ml_engineering",
    "Algorithmic optimization": "algorithmic_optimization",
}

# What the draft form ships with. Anything above these only reaches the platform
# if your edit to the form was actually saved — and the bundle is compared
# against the draft the platform STORED, which you cannot read back from here.
# A bundle asking for more than the default is a bet on that edit; a bundle at
# or below the default always holds.
FORM_DEFAULTS = {
    "cpuMillis": 2000,
    "memoryMb": 4096,
    "storageMb": 8192,
    "gpuCount": 0,
    "agentTimeoutSec": 14400,
    "verifierTimeoutSec": 1200,
}
# task.toml key -> (draft key, multiplier to reach the draft's unit)
BUNDLE_TO_DRAFT = {
    ("environment", "cpus"): ("cpuMillis", 1000),
    ("environment", "memory_mb"): ("memoryMb", 1),
    ("environment", "storage_mb"): ("storageMb", 1),
    ("environment", "gpus"): ("gpuCount", 1),
    ("agent", "timeout_sec"): ("agentTimeoutSec", 1),
    ("verifier", "timeout_sec"): ("verifierTimeoutSec", 1),
}


class Report:
    def __init__(self, label: str) -> None:
        self.label = label
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def emit(self) -> bool:
        if not self.errors and not self.warnings:
            print(f"OK    {self.label}")
            return True
        print(f"{'FAIL' if self.errors else 'WARN'}  {self.label}")
        for message in self.errors:
            print(f"  error: {message}")
        for message in self.warnings:
            print(f"  warn:  {message}")
        return not self.errors


def check_structure(bundle: Path, report: Report) -> dict | None:
    for required in REQUIRED_PATHS:
        target = bundle / required
        if not target.is_file():
            report.error(f"missing required file: {required}")

    seen: dict[str, Path] = {}
    for path in sorted(bundle.rglob("*")):
        relative = path.relative_to(bundle)
        parts = relative.parts
        if any(part in ("..",) for part in parts) or path.is_symlink():
            report.error(f"unsafe path: {relative}")
        lowered = str(relative).lower()
        if lowered in seen and seen[lowered] != relative:
            report.error(f"duplicate path differing only in case: {relative}")
        seen[lowered] = relative
        if "__pycache__" in parts or path.name.endswith(".pyc"):
            report.warn(f"build artefact in the bundle: {relative}")
        if path.name in ("reward.txt", "score.txt", "score.json", "junit.xml"):
            report.warn(
                f"reward artefact left by a local grader run: {relative} — "
                f"delete it; a stale score must never ship inside the archive"
            )

    toml_path = bundle / "task.toml"
    if not toml_path.is_file():
        return None
    try:
        return tomllib.loads(toml_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        report.error(f"task.toml is not parseable TOML: {exc}")
        return None


def check_quality(bundle: Path, config: dict | None, report: Report) -> None:
    instruction = bundle / "instruction.md"
    if instruction.is_file():
        text = instruction.read_text().strip()
        if len(text) < INSTRUCTION_FLOOR_CHARS:
            report.error(
                f"instruction.md is {len(text)} chars; the host floor is "
                f"{INSTRUCTION_FLOOR_CHARS} and a reviewer expects far more"
            )

    if config is not None:
        name = (config.get("metadata") or {}).get("name")
        if not isinstance(name, str) or not name.strip():
            report.error("task.toml [metadata] declares no non-empty name")

    for directory, label in (("solution", "reference solution"), ("tests", "verifier")):
        files = [p for p in (bundle / directory).rglob("*") if p.is_file()]
        if not files:
            report.error(f"{directory}/ is empty; the {label} cannot run")


def check_schema(config: dict | None, report: Report) -> None:
    """The table/key shape an approved bundle declares."""
    if config is None:
        return

    metadata = config.get("metadata") or {}
    for key in METADATA_REQUIRED:
        if not metadata.get(key):
            report.error(f"task.toml [metadata] is missing {key}")

    family = metadata.get("collection_family")
    if family is not None and family not in BUNDLE_COLLECTION_FAMILIES:
        report.error(
            f"task.toml [metadata] collection_family={family!r} must be one of "
            f"{sorted(BUNDLE_COLLECTION_FAMILIES)} (snake_case in the bundle, "
            f"even though the draft form shows title case)"
        )

    verifier = config.get("verifier") or {}
    for key in VERIFIER_REQUIRED:
        if verifier.get(key) is None:
            report.error(f"task.toml [verifier] is missing {key}")
    threshold = verifier.get("pass_threshold")
    if isinstance(threshold, (int, float)) and not 0 < threshold <= 1:
        report.error(f"task.toml [verifier] pass_threshold={threshold} must be in (0, 1]")
    entrypoint = verifier.get("entrypoint")
    if entrypoint is not None and entrypoint != "tests/test.sh":
        report.warn(
            f"task.toml [verifier] entrypoint={entrypoint!r}; the grader runs "
            f"tests/test.sh"
        )

    environment = config.get("environment") or {}
    for key in ENVIRONMENT_REQUIRED:
        if environment.get(key) is None:
            report.error(f"task.toml [environment] is missing {key}")
    for key in ENVIRONMENT_FORBIDDEN:
        if key in environment:
            report.error(
                f"task.toml [environment] declares {key}, which an approved "
                f"bundle does not; that block describes the build, and an extra "
                f"key there is rejected as 'resource declaration mismatch'"
            )


def check_cross(bundle: Path, config: dict | None, draft: dict, report: Report) -> None:
    if config is None:
        return

    metadata = config.get("metadata") or {}
    expected = DRAFT_TO_BUNDLE_FAMILY.get(draft.get("collectionFamily"))
    actual = metadata.get("collection_family")
    if expected and actual and expected != actual:
        report.error(
            f"task.toml collection_family={actual!r} does not correspond to the "
            f"draft's {draft.get('collectionFamily')!r} (expected {expected!r})"
        )
    for toml_key, draft_key in (
        ("task_family", "taskFamily"),
        ("verifier_family", "verifierFamily"),
    ):
        if metadata.get(toml_key) and draft.get(draft_key):
            if metadata[toml_key] != draft[draft_key]:
                report.error(
                    f"task.toml {toml_key}={metadata[toml_key]!r} disagrees with "
                    f"the draft's {draft_key}={draft[draft_key]!r}"
                )

    resources = draft.get("resourceEstimate") or {}
    environment = config.get("environment") or {}

    draft_cpus = resources.get("cpuMillis")
    bundle_cpus = environment.get("cpus")
    if isinstance(draft_cpus, int) and isinstance(bundle_cpus, (int, float)):
        if bundle_cpus * 1000 > draft_cpus:
            report.error(
                f"task.toml [environment] cpus={bundle_cpus} exceeds the draft's "
                f"cpuMillis={draft_cpus}; the bundle may ask for less, never more"
            )

    for toml_key, draft_key in (
        ("memory_mb", "memoryMb"),
        ("storage_mb", "storageMb"),
        ("gpus", "gpuCount"),
    ):
        bundle_value = environment.get(toml_key)
        draft_value = resources.get(draft_key)
        if isinstance(bundle_value, int) and isinstance(draft_value, int):
            if bundle_value > draft_value:
                report.error(
                    f"task.toml [environment] {toml_key}={bundle_value} exceeds the "
                    f"draft's {draft_key}={draft_value}"
                )

    for section, draft_key in (("agent", "agentTimeoutSec"), ("verifier", "verifierTimeoutSec")):
        bundle_value = (config.get(section) or {}).get("timeout_sec")
        draft_value = resources.get(draft_key)
        if isinstance(bundle_value, int) and isinstance(draft_value, int):
            if bundle_value > draft_value:
                report.error(
                    f"task.toml [{section}] timeout_sec={bundle_value} exceeds the "
                    f"draft's {draft_key}={draft_value}"
                )

    agent_mode = (config.get("agent") or {}).get("network_mode")
    draft_mode = (draft.get("networkRequirements") or {}).get("mode")
    if agent_mode is None:
        report.error(
            "task.toml [agent] declares no network_mode; the rollout's egress is "
            "read from that field alone"
        )
    elif agent_mode not in AGENT_NETWORK_MODES:
        report.error(
            f"task.toml [agent] network_mode={agent_mode!r} is not admitted; "
            f"'open' is refused for the rollout"
        )
    elif draft_mode is not None and agent_mode != draft_mode:
        report.error(
            f"task.toml [agent] network_mode={agent_mode!r} disagrees with the "
            f"draft's networkRequirements.mode={draft_mode!r}"
        )

    # The bundle is compared against the stored draft, not the one in this repo.
    # Asking for more than the form default only works if the form edit saved.
    for (section, key), (draft_key, scale) in BUNDLE_TO_DRAFT.items():
        bundle_value = (config.get(section) or {}).get(key)
        if not isinstance(bundle_value, (int, float)):
            continue
        default = FORM_DEFAULTS[draft_key]
        # Every declared field should sit below the draft envelope, not on it.
        # `gpus` is exempt: 0 cannot go lower.
        if key != "gpus" and bundle_value * scale == default:
            report.warn(
                f"task.toml [{section}] {key}={bundle_value} exactly equals the "
                f"form default for {draft_key}. Ask for less. Three uploads whose "
                f"resources equalled the draft were rejected as 'resource "
                f"declaration mismatch' with everything else varying."
            )
        if bundle_value * scale > default:
            report.warn(
                f"task.toml [{section}] {key}={bundle_value} is above the form "
                f"default for {draft_key} ({default}). The platform checks this "
                f"against the draft it stored; if that edit did not save, the "
                f"bundle is rejected with '{draft_key} exceeds draft'. Lower it, "
                f"or confirm the raised value in the form before uploading."
            )

    if (config.get("metadata") or {}).get("open_internet_justification"):
        if not (config.get("agent") or {}).get("network_mode"):
            report.error(
                "open_internet_justification is set without an explicit "
                "[agent] network_mode"
            )


def check_size(bundle: Path, report: Report) -> None:
    total = sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file())
    if total > MAX_BUNDLE_BYTES:
        report.error(f"bundle is {total} bytes uncompressed; the ZIP cap is 512 MiB")


def check(task_dir: Path) -> bool:
    label = str(task_dir.relative_to(REPO)) if task_dir.is_relative_to(REPO) else str(task_dir)
    report = Report(label)

    bundle = task_dir / "bundle"
    if not bundle.is_dir():
        report.error("no bundle/ directory")
        return report.emit()

    config = check_structure(bundle, report)
    check_schema(config, report)
    check_quality(bundle, config, report)
    check_size(bundle, report)

    draft_path = task_dir / "draft.yaml"
    if draft_path.is_file():
        draft = yaml.safe_load(draft_path.read_text()) or {}
        check_cross(bundle, config, draft, report)
    else:
        report.warn("no draft.yaml; skipping the bundle/draft cross-checks")

    return report.emit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    paths = list(args.paths)
    if args.all or not paths:
        paths = sorted(p for p in (REPO / "tasks").iterdir() if p.is_dir())
    if not paths:
        print("no tasks found")
        return 1

    return 0 if all(check(p.resolve()) for p in paths) else 1


if __name__ == "__main__":
    sys.exit(main())
