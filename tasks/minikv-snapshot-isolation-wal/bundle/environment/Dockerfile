FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Everything the task needs is baked in here; the rollout runs with no network.
# The implementation itself must be pure standard library.
RUN pip install --no-cache-dir "pytest==8.3.3"

WORKDIR /app

# The build context is this `environment/` directory, so this brings in the
# starter package, the public tests and the spec -- and nothing else.
COPY . /app/

# Defensive: the sealed verifier and the reference solution must never be
# reachable from inside the container, whatever the build context turns out to
# be. The Dockerfile is not part of the working tree either.
RUN rm -rf /app/tests /app/solution /app/Dockerfile /app/task.toml && \
    find /app -name '__pycache__' -type d -prune -exec rm -rf {} + || true

# The starting state must be the starting state: basic put/get works, and the
# transactional API is still missing. Then the checker removes itself.
RUN python /app/selfcheck.py && rm -f /app/selfcheck.py

# Fail the build loudly if the starter tree is not where it belongs, or if the
# visible suite does not pass.
RUN test -f /app/minikv/store.py && \
    test -f /app/public_tests/test_basic.py && \
    test -f /app/SPEC.md && \
    python -m pytest public_tests -q

# One clean commit so the agent can diff its own work.
RUN git init -q \
    && git config user.email author@example.com \
    && git config user.name "minikv" \
    && git add -A \
    && git commit -qm "minikv: naive whole-file storage engine"

CMD ["/bin/bash"]
