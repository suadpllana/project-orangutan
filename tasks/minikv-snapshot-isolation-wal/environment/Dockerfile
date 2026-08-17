# Image for both the agent run and the verifier run.
#
# The sandbox has no network at runtime, so everything the agent could need has
# to be baked in here. pytest is pinned because the graded suite is parsed from
# its JUnit XML output.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "pytest==9.1.1"

WORKDIR /workspace
COPY workspace/ /workspace/

# One clean commit, so the agent can diff its own work and the harness can
# collect a patch.
RUN git init -q \
    && git config user.email author@example.com \
    && git config user.name "minikv" \
    && git add -A \
    && git commit -qm "minikv: naive whole-file storage engine"

# Sanity check at build time: the starting point must pass its own tests, and
# the transactional API must still be missing.
RUN python -m pytest tests -q \
    && python - <<'PY'
from minikv import MiniKV
import tempfile
with tempfile.TemporaryDirectory() as d:
    db = MiniKV(d)
    try:
        db.begin()
    except NotImplementedError:
        pass
    else:
        raise SystemExit("begin() must start out unimplemented")
PY

CMD ["/bin/bash"]
