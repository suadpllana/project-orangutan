# Builds /app. Everything the agent needs is baked in here: the rollout has no
# network, so nothing may be fetched at runtime.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pinned: the graded suite is parsed from this pytest's JUnit XML output.
RUN pip install --no-cache-dir "pytest==9.1.1"

WORKDIR /app
COPY minikv/ /app/minikv/
COPY tests/ /app/tests/
COPY README.md /app/README.md

# One clean commit so the agent can diff its own work.
RUN git init -q \
    && git config user.email author@example.com \
    && git config user.name "minikv" \
    && git add -A \
    && git commit -qm "minikv: naive whole-file storage engine"

# Build-time self-check: the starting point must pass its own tests, and the
# transactional API must still be missing. Kept in a script rather than a RUN
# heredoc, which the classic Dockerfile parser does not join across newlines.
COPY selfcheck.py /selfcheck.py
RUN python -m pytest tests -q \
    && python /selfcheck.py \
    && rm /selfcheck.py

CMD ["/bin/bash"]
