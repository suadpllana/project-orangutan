"""Build-time assertion that the starting state is the starting state.

Run from /app during the image build and then deleted, so the agent never sees
it. A seed that accidentally ships a working implementation is a task with no
gap, and this is the cheapest place to find that out.
"""

import tempfile

from minikv import MiniKV


def main() -> None:
    with tempfile.TemporaryDirectory() as path:
        db = MiniKV(path)

        # The parts that already work.
        db.put(b"k", b"v")
        assert db.get(b"k") == b"v", "the starting store must handle basic put/get"

        # The parts the task is about, which must still be missing.
        for name in ("begin", "checkpoint", "stats"):
            try:
                getattr(db, name)()
            except NotImplementedError:
                continue
            raise SystemExit(f"{name}() must start out unimplemented")

    print("selfcheck: starting state is intact")


if __name__ == "__main__":
    main()
