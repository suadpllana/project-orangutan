#!/usr/bin/env python3
"""Check a draft.yaml against the Orangutan authoring bounds.

    python3 tools/validate_draft.py tasks/<slug>/draft.yaml
    python3 tools/validate_draft.py --all

Bounds are enforced on submit, so finding a violation here is much cheaper than
finding it after you have pasted 4,000 characters into a textarea. Everything in
this file comes from the authoring guideline; see docs/draft-fields.md.

Character counts use the rendered text: block scalars are counted after YAML
folds them, with the trailing newline stripped, which is what ends up in the
field.
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
    "title": (3, 200),
    "objective": (40, 20_000),
    "motivation": (20, 10_000),
    "difficultyExplanation": (40, 20_000),
    "environmentSummary": (40, 20_000),
    "oracleStrategy": (20, 20_000),
    "verificationStrategy": (40, 20_000),
    "binarySuccessCondition": (20, 10_000),
    "partialScoreStrategy": (20, 10_000),
    "anticipatedExploits": (20, 20_000),
}

COLLECTION_FAMILIES = {
    "Library clone",
    "Product clone",
    "ML engineering",
    "Algorithmic optimization",
}
TASK_FAMILIES = {
    "feature_development",
    "debugging",
    "refactoring",
    "performance",
    "systems_integration",
    "other",
}
VERIFIER_FAMILIES = {"programmatic", "optimization", "ml_artifact", "custom"}
NETWORK_MODES = {"none", "allowlist"}

# field -> (min, max) from the guideline's resourceEstimate bounds
RESOURCE_BOUNDS = {
    "cpuMillis": (100, 64_000),
    "memoryMb": (128, 262_144),
    "storageMb": (128, 1_048_576),
    "gpuCount": (0, 8),
    "agentTimeoutSec": (1, 86_400),
    "verifierTimeoutSec": (1, 86_400),
}

# What the trial sandbox actually provides. A request above this is rejected at
# intake rather than run starved.
SANDBOX_CPU_MILLIS = 8_000
SANDBOX_MEMORY_MB = 65_536
SANDBOX_STORAGE_MB = 40_960

LONG_HORIZON_FLOOR_SEC = 7_200      # effective agentTimeoutSec must reach this
# The guideline's 7,200s is the ABSOLUTE floor, not the bar this collection
# applies. A submission declaring agentTimeoutSec = 14400 -- the form default,
# four hours -- was rejected at the Difficulty evaluation stage with
# "Too short for the collection - not long-horizon", with every other stage
# passed. So 14,400 is known-rejected.
LONG_HORIZON_KNOWN_REJECTED_SEC = 14_400

# ...and 43,200 (12h) is known-REFUSED, at the other end. The draft form itself
# rejects it, before anything is uploaded:
#
#   Above 37000s (~10h) - leave room for build, verify, teardown, which share a
#   trial's 14h wall-clock limit. A larger build or verify budget lowers this;
#   the exact bound is the whole per-trial envelope, checked at intake.
#
# That is the number this file used to RECOMMEND. It was derived here by
# subtracting a guessed 1,800s build-and-teardown allowance from the 50,400s
# pool, and the guess was wrong by an order of magnitude: at the form's default
# 1,200s verifier the platform holds back 50,400 - 37,000 - 1,200 = 12,200s for
# build and teardown, not 1,800. Never infer one side of the envelope from the
# other -- the reserve is the platform's and it is much larger than a build
# takes.
#
# So the admissible band is (14,400, 37,000]. 36,000s (10h) is the largest round
# value inside it and is what to use: 2.5x the value the difficulty gate
# rejected, and 1,000s clear of the ceiling.
AGENT_TIMEOUT_CEILING_SEC = 37_000
LONG_HORIZON_RECOMMENDED_SEC = 36_000
TRIAL_POOL_CEILING_SEC = 50_400     # build + agent + verify + teardown
# What the platform actually reserves for build + teardown, implied by the
# ceiling above rather than guessed. Kept for the pool arithmetic below.
BUILD_TEARDOWN_ALLOWANCE_SEC = TRIAL_POOL_CEILING_SEC - AGENT_TIMEOUT_CEILING_SEC - 1_200

MAX_ALLOWLIST_HOSTS = 100

# What the form ships with. Raising one of these is fine, but the raise only
# reaches the platform if the form edit saved — and your bundle is checked
# against the STORED draft, which cannot be read back from this repository.
FORM_DEFAULTS = {
    "cpuMillis": 2000,
    "memoryMb": 4096,
    "storageMb": 8192,
    "gpuCount": 0,
    "agentTimeoutSec": 14400,
    "verifierTimeoutSec": 1200,
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


def check_identity(doc: dict, report: Report) -> None:
    slug = doc.get("workingSlug")
    if not isinstance(slug, str) or not slug:
        report.error("workingSlug is required")
    else:
        if not 3 <= len(slug) <= 80:
            report.error(f"workingSlug must be 3-80 chars, got {len(slug)}")
        if slug.strip("abcdefghijklmnopqrstuvwxyz0123456789-"):
            report.error(f"workingSlug must be lowercase-kebab: {slug!r}")
        if slug.startswith("-") or slug.endswith("-") or "--" in slug:
            report.error(f"workingSlug has a stray hyphen: {slug!r}")

    for field, options in (
        ("collectionFamily", COLLECTION_FAMILIES),
        ("taskFamily", TASK_FAMILIES),
        ("verifierFamily", VERIFIER_FAMILIES),
    ):
        value = doc.get(field)
        if value not in options:
            report.error(
                f"{field}={value!r} is not one of {sorted(options)}"
            )

    hours = doc.get("expertTimeEstimateHours")
    if not isinstance(hours, (int, float)) or hours <= 0:
        report.error("expertTimeEstimateHours must be a positive number")


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


def check_resources(doc: dict, report: Report) -> None:
    resources = doc.get("resourceEstimate")
    if not isinstance(resources, dict):
        report.error("resourceEstimate block is required")
        return

    for field, (low, high) in RESOURCE_BOUNDS.items():
        value = resources.get(field)
        if not isinstance(value, int):
            report.error(f"resourceEstimate.{field} must be an integer")
            continue
        if not low <= value <= high:
            report.error(f"resourceEstimate.{field}={value} outside [{low}, {high}]")

    for field, ceiling, label in (
        ("cpuMillis", SANDBOX_CPU_MILLIS, "8 CPUs"),
        ("memoryMb", SANDBOX_MEMORY_MB, "65536 MB"),
        ("storageMb", SANDBOX_STORAGE_MB, "40960 MB"),
    ):
        value = resources.get(field)
        if isinstance(value, int) and value > ceiling:
            report.error(
                f"resourceEstimate.{field}={value} exceeds what the trial sandbox "
                f"provides ({label}); a request above it is rejected at intake"
            )

    agent = resources.get("agentTimeoutSec")
    verifier = resources.get("verifierTimeoutSec")
    if isinstance(agent, int) and agent < LONG_HORIZON_FLOOR_SEC:
        report.error(
            f"agentTimeoutSec={agent} is below the {LONG_HORIZON_FLOOR_SEC}s "
            f"long-horizon floor"
        )
    elif isinstance(agent, int) and agent <= LONG_HORIZON_KNOWN_REJECTED_SEC:
        report.error(
            f"agentTimeoutSec={agent} ({agent / 3600:.1f}h). A submission with "
            f"exactly this value was rejected at Difficulty evaluation with "
            f"'Too short for the collection - not long-horizon', every other "
            f"stage passed. The form default is not a recommendation. Use "
            f"{LONG_HORIZON_RECOMMENDED_SEC} (12h) unless the task genuinely "
            f"needs less, and confirm the raise SAVED in the form - intake "
            f"compares the bundle against the stored draft. "
            f"See docs/difficulty-gate.md."
        )
    elif isinstance(agent, int) and agent > AGENT_TIMEOUT_CEILING_SEC:
        report.error(
            f"agentTimeoutSec={agent} ({agent / 3600:.1f}h) is above the "
            f"{AGENT_TIMEOUT_CEILING_SEC}s ceiling the draft form enforces: "
            f"'Above 37000s (~10h) - leave room for build, verify, teardown, "
            f"which share a trial's 14h wall-clock limit.' The form refuses to "
            f"store the value, so nothing downstream ever sees it. Use "
            f"{LONG_HORIZON_RECOMMENDED_SEC} (10h). See docs/difficulty-gate.md."
        )
    elif isinstance(agent, int) and agent < LONG_HORIZON_RECOMMENDED_SEC:
        report.warn(
            f"agentTimeoutSec={agent} ({agent / 3600:.1f}h) is below the "
            f"{LONG_HORIZON_RECOMMENDED_SEC}s (10h) that is the largest round "
            f"value the form accepts. 4h was rejected as not long-horizon and "
            f"the safe threshold above that is not known, so take the whole "
            f"band the platform allows rather than leaving horizon unclaimed."
        )
    if isinstance(agent, int) and isinstance(verifier, int):
        trial = agent + verifier + BUILD_TEARDOWN_ALLOWANCE_SEC
        if trial > TRIAL_POOL_CEILING_SEC:
            report.error(
                f"agent + verifier + ~{BUILD_TEARDOWN_ALLOWANCE_SEC}s for build and "
                f"teardown is {trial}s, over the {TRIAL_POOL_CEILING_SEC}s per-trial "
                f"ceiling. The agent budget and the verifier budget come out of one "
                f"pool: raising the verifier lowers what the agent may ask for."
            )

    for field, default in FORM_DEFAULTS.items():
        value = resources.get(field)
        if isinstance(value, int) and value > default:
            report.warn(
                f"resourceEstimate.{field}={value} is above the form default "
                f"({default}). Confirm the raised value is saved in the form "
                f"before uploading a bundle that relies on it — the intake "
                f"compares task.toml against the stored draft, not this file."
            )

    hours = doc.get("expertTimeEstimateHours")
    if isinstance(agent, int) and isinstance(hours, (int, float)):
        # Giving the agent LESS time than a human expert is declared to need is
        # incoherent on its face, and the old check only fired below half the
        # estimate -- so a 7h task with a 4h agent budget passed silently. It
        # should not have.
        #
        # But it cannot be an unconditional error either, because the agent
        # budget is capped at AGENT_TIMEOUT_CEILING_SEC and the expert estimate
        # is not: the guideline says the estimate "is NOT a gate ... so give an
        # honest figure however large". Past ~10.3h the two simply cannot be
        # reconciled, and demanding it would force the estimate to be shaved to
        # fit -- which is the one thing the guideline tells you not to do.
        # So: error while the estimate is still purchasable, warn once it is not.
        wanted = hours * 3600
        if wanted > AGENT_TIMEOUT_CEILING_SEC:
            if agent < LONG_HORIZON_RECOMMENDED_SEC:
                report.error(
                    f"expertTimeEstimateHours={hours} needs {wanted / 3600:.1f}h "
                    f"and the form caps agentTimeoutSec at "
                    f"{AGENT_TIMEOUT_CEILING_SEC / 3600:.1f}h, so claim the whole "
                    f"band: {LONG_HORIZON_RECOMMENDED_SEC}, not {agent}."
                )
            else:
                report.warn(
                    f"expertTimeEstimateHours={hours} exceeds the "
                    f"{AGENT_TIMEOUT_CEILING_SEC / 3600:.1f}h the form allows an "
                    f"agent, so the budget is capped at {agent}s "
                    f"({agent / 3600:.1f}h) by the trial envelope rather than by "
                    f"your judgement. That is admissible - the estimate is "
                    f"descriptive metadata, not a gate - but keep it honest and "
                    f"make sure difficultyExplanation says the same number."
                )
        elif agent < wanted:
            report.error(
                f"agentTimeoutSec={agent} ({agent / 3600:.1f}h) is less than the "
                f"{hours}h you declared a human expert needs. An agent is not "
                f"faster than the expert; raise the budget or lower the estimate."
            )
        else:
            # Capped at the RECOMMENDED value, not at the ceiling: telling an
            # author to sit on 37,000 exactly would leave no slack for the
            # build and verify budgets that share the envelope with it.
            comfortable = min(hours * 3600 * 1.5, LONG_HORIZON_RECOMMENDED_SEC)
            fits = (
                comfortable + (verifier if isinstance(verifier, int) else 0)
                + BUILD_TEARDOWN_ALLOWANCE_SEC <= TRIAL_POOL_CEILING_SEC
            )
            if agent < comfortable and fits:
                report.warn(
                    f"agentTimeoutSec={agent} ({agent / 3600:.1f}h) leaves an "
                    f"agent barely the {hours}h an expert needs, and the "
                    f"per-trial pool has room for {comfortable / 3600:.1f}h. "
                    f"Long-horizon trials are budgeted above the expert "
                    f"estimate, not level with it."
                )


def check_network(doc: dict, report: Report) -> None:
    network = doc.get("networkRequirements")
    if not isinstance(network, dict):
        report.error("networkRequirements block is required")
        return

    mode = network.get("mode")
    if mode not in NETWORK_MODES:
        report.error(
            f"networkRequirements.mode={mode!r} must be one of {sorted(NETWORK_MODES)}; "
            f"unrestricted egress is not admitted"
        )

    hosts = network.get("hosts") or []
    if not isinstance(hosts, list):
        report.error("networkRequirements.hosts must be a list")
        hosts = []
    if mode == "allowlist" and not hosts:
        report.error("networkRequirements.mode is 'allowlist' but no hosts are listed")
    if mode == "none" and hosts:
        report.error("hosts are only accepted in allowlist mode")
    if len(hosts) > MAX_ALLOWLIST_HOSTS:
        report.error(f"{len(hosts)} hosts listed, maximum {MAX_ALLOWLIST_HOSTS}")

    justification = (network.get("justification") or "").strip()
    if not justification:
        report.warn("networkRequirements.justification is empty; one is expected")


def check_layout(path: Path, doc: dict, report: Report) -> None:
    task_dir = path.parent
    slug = doc.get("workingSlug")
    if isinstance(slug, str) and task_dir.name != slug:
        report.error(f"directory {task_dir.name!r} does not match slug {slug!r}")
    if not (task_dir / "bundle").is_dir():
        report.error("missing bundle/ - run tools/check_bundle.py once it exists")


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

    check_identity(doc, report)
    check_text_fields(doc, report)
    check_resources(doc, report)
    check_network(doc, report)
    check_layout(path, doc, report)
    return report.emit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="validate every draft")
    args = parser.parse_args()

    paths = list(args.paths)
    if args.all or not paths:
        paths = sorted((REPO / "tasks").glob("*/draft.yaml"))
    if not paths:
        print("no draft.yaml found")
        return 1

    return 0 if all(validate(p) for p in paths) else 1


if __name__ == "__main__":
    sys.exit(main())
