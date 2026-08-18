FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Everything the task needs is baked in here; the rollout runs with no network.
# The implementation itself must be pure standard library -- pytest is only for
# the visible suite, and the sealed grader uses it only to re-run that suite.
RUN pip install --no-cache-dir "pytest==8.3.3"

WORKDIR /app

# The build context is this `environment/` directory, so this brings in the
# starter package, the visible tests, the samples and the spec -- and nothing
# else.
COPY . /app/

# Defensive: the sealed verifier and the reference solution must never be
# reachable from inside the container, whatever the build context turns out to
# be. The Dockerfile itself is not part of the working tree either.
RUN rm -rf /app/tests /app/solution /app/Dockerfile /app/task.toml && \
    find /app -name '__pycache__' -type d -prune -exec rm -rf {} + || true

# Fail the build loudly if the starting tree is not where it belongs.
RUN test -f /app/zipstream/codec.py && \
    test -f /app/public_tests/test_public.py && \
    test -f /app/SPEC.md && \
    test -f /app/samples/logfmt.bin && \
    python -c "import sys; sys.path.insert(0, '/app'); import zipstream; print(zipstream.__version__)"

# The visible suite must pass on the seed, and the seed must still be missing
# the thing the task asks for. Both halves are checked; then the checker goes.
RUN cd /app && python -m pytest public_tests -q && python /app/selfcheck.py && \
    rm -f /app/selfcheck.py && \
    find /app -name '__pycache__' -type d -prune -exec rm -rf {} + || true

# One clean commit, so the agent can diff its own work.
RUN if command -v git >/dev/null 2>&1; then \
        cd /app && git init -q && git add -A && \
        git -c user.email=task@orangutan -c user.name=orangutan \
            commit -q -m "zipstream v1: the shipping codec" ; \
    fi

CMD ["/bin/bash"]
