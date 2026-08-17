#!/usr/bin/env python3
"""Check a task.yaml against the authoring form's rules before you paste it in.

    python3 tools/validate_task.py tasks/<slug>/task.yaml
    python3 tools/validate_task.py --all

Every limit here mirrors docs/form-schema.md, which is the transcription of the
authoring UI.  The form rejects an over-long field only after you have pasted
it, so it is much cheaper to find out here.

Character counts use the rendered text: block scalars are counted after YAML
folds them, with the trailing newline stripped, which is what ends up in the
textarea.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required: pip install pyyaml")

REPO = Path(__file__).resolve().parent.parent

# field -> (min chars, max chars)
TEXT_LIMITS = {
    "objective": (40, 20_000),
    "motivation": (20, 10_000),
    "environment_summary": (40, 20_000),
    "difficulty_explanation": (40, 20_000),
    "oracle_strategy": (20, 20_000),
    "verification_strategy": (40, 20_000),
    "binary_success_condition": (20, 10_000),
    "partial_score_strategy": (20, 10_000),
    "anticipated_exploits": (20, 20_000),
}

TASK_FAMILIES = {
    "feature development",
    "bug fixing",
    "refactoring",
    "testing",
    "performance optimization",
    "security",
    "data analysis",
}
VERIFIER_FAMILIES = {"programmatic", "llm judge", "hybrid", "human"}
NETWORK_MODES = {"none", "proxy", "allowlist", "full"}

RESOURCE_FIELDS = {
    "cpu_millis": (100, 64_000),
    "memory_mb": (256, 131_072),
    "storage_mb": (512, 1_048_576),
    "gpu_count": (0, 8),
    "agent_timeout_s": (60, 86_400),
    "verifier_timeout_s": (60, 86_400),
}


class Report:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def emit(self) -> bool:
        rel = self.path.relative_to(REPO) if self.path.is_relative_to(REPO) else self.path
        if not self.errors and not self.warnings:
            print(f"OK    {rel}")
            return True
        print(f"{'FAIL' if self.errors else 'WARN'}  {rel}")
        for message in self.errors:
            print(f"  error: {message}")
        for message in self.warnings:
            print(f"  warn:  {message}")
        return not self.errors


def check_slug(slug: object, report: Report) -> None:
    if not isinstance(slug, str) or not slug:
        report.error("working_slug is required")
        return
    if not 3 <= len(slug) <= 80:
        report.error(f"working_slug must be 3-80 chars, got {len(slug)}")
    if slug.strip("abcdefghijklmnopqrstuvwxyz0123456789-"):
        report.error(f"working_slug must be lowercase-kebab: {slug!r}")
    if slug.startswith("-") or slug.endswith("-") or "--" in slug:
        report.error(f"working_slug has a stray hyphen: {slug!r}")


def check_text_fields(doc: dict, report: Report) -> None:
    for field, (low, high) in TEXT_LIMITS.items():
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            report.error(f"{field} is required")
            continue
        length = len(value.rstrip("\n"))
        if length < low:
            report.error(f"{field} is {length} chars, minimum {low}")
        elif length > high:
            report.error(f"{field} is {length} chars, maximum {high}")
        elif length > high * 0.9:
            report.warn(f"{field} is {length}/{high} chars - close to the cap")


def check_families(doc: dict, report: Report) -> None:
    if not doc.get("title"):
        report.error("title is required")
    if not doc.get("collection_family"):
        report.warn(
            "collection_family is blank - it is a dropdown, pick it in the form"
        )
    task_family = doc.get("task_family")
    if task_family not in TASK_FAMILIES:
        report.warn(
            f"task_family {task_family!r} is not one of the known options "
            f"({', '.join(sorted(TASK_FAMILIES))}) - confirm against the form"
        )
    verifier_family = doc.get("verifier_family")
    if verifier_family not in VERIFIER_FAMILIES:
        report.warn(
            f"verifier_family {verifier_family!r} is not one of the known options "
            f"({', '.join(sorted(VERIFIER_FAMILIES))}) - confirm against the form"
        )

    hours = doc.get("expert_time_estimate_hours")
    if not isinstance(hours, (int, float)) or hours <= 0:
        report.error("expert_time_estimate_hours must be a positive number")


def check_resources(doc: dict, report: Report) -> None:
    resources = doc.get("resources")
    if not isinstance(resources, dict):
        report.error("resources block is required")
        return
    for field, (low, high) in RESOURCE_FIELDS.items():
        value = resources.get(field)
        if not isinstance(value, int):
            report.error(f"resources.{field} must be an integer")
            continue
        if not low <= value <= high:
            report.error(f"resources.{field}={value} outside [{low}, {high}]")

    agent = resources.get("agent_timeout_s")
    hours = doc.get("expert_time_estimate_hours")
    if isinstance(agent, int) and isinstance(hours, (int, float)):
        if agent < hours * 3600 * 0.5:
            report.warn(
                f"agent_timeout_s={agent} is less than half the {hours}h expert "
                f"estimate - agents are usually given at least the expert's time"
            )


def check_network(doc: dict, report: Report) -> None:
    network = doc.get("network")
    if not isinstance(network, dict):
        report.error("network block is required")
        return
    mode = network.get("mode")
    if mode not in NETWORK_MODES:
        report.warn(f"network.mode {mode!r} is not one of {sorted(NETWORK_MODES)}")
    justification = network.get("justification") or ""
    if len(justification) > 4000:
        report.error(f"network.justification is {len(justification)} chars, max 4000")
    if mode not in (None, "none") and not justification.strip():
        report.error(f"network.mode is {mode!r}; a justification is required")


def check_layout(path: Path, doc: dict, report: Report) -> None:
    """The directory name and the slug have to agree, and the parts must exist."""
    task_dir = path.parent
    slug = doc.get("working_slug")
    if isinstance(slug, str) and task_dir.name != slug:
        report.error(f"directory {task_dir.name!r} does not match slug {slug!r}")
    for required in (
        "environment/workspace",
        "solution",
        "verifier/grade.py",
        "verifier/tests",
    ):
        if not (task_dir / required).exists():
            report.error(f"missing {required}")


def validate(path: Path) -> bool:
    report = Report(path)
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        report.error(f"not valid YAML: {exc}")
        return report.emit()
    if not isinstance(doc, dict):
        report.error("top level must be a mapping")
        return report.emit()

    check_families(doc, report)
    check_slug(doc.get("working_slug"), report)
    check_text_fields(doc, report)
    check_resources(doc, report)
    check_network(doc, report)
    check_layout(path, doc, report)
    return report.emit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="validate every task")
    args = parser.parse_args()

    paths = list(args.paths)
    if args.all or not paths:
        paths = sorted((REPO / "tasks").glob("*/task.yaml"))
    if not paths:
        print("no task.yaml found")
        return 1

    return 0 if all(validate(p) for p in paths) else 1


if __name__ == "__main__":
    sys.exit(main())
