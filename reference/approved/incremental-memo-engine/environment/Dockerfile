FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Everything the task needs is baked in here; the rollout runs with no network.
# The implementation itself must be pure standard library.
RUN pip install --no-cache-dir "pytest==8.3.3"

WORKDIR /app

# The build context is this `environment/` directory, so this brings in the
# starter package, the public tests and the spec -- and nothing else.
COPY . /app/

# Defensive: the sealed verifier and the reference solution must never be
# reachable from inside the container, whatever the build context turns out to
# be.  The Dockerfile itself is not part of the working tree either.
RUN rm -rf /app/tests /app/solution /app/Dockerfile /app/task.toml && \
    find /app -name '__pycache__' -type d -prune -exec rm -rf {} + || true

# Fail the build loudly if the starter tree is not where it belongs.
RUN test -f /app/incremental/engine.py && \
    test -f /app/public_tests/test_public.py && \
    test -f /app/SPEC.md && \
    python -c "import sys; sys.path.insert(0, '/app'); import incremental; print(incremental.Engine)"

CMD ["/bin/bash"]
