"""Collection and the integrity scan.

Only implementation files are copied into a tree the grader owns, and the
graded runs happen there. That one decision closes a whole family of attacks at
once -- a `conftest.py` that rewrites assertions, a `sitecustomize.py` that runs
before anything else, a `pytest.ini` that deselects tests, an edited copy of the
visible suite -- because none of those files is ever collected.

What the copy cannot stop is a codec that looks around at runtime instead of
compressing, so the collected source is tokenised and checked for the names
that have no honest use here. Tokenising rather than grepping matters: a
docstring that says "unlike zlib, this codec models the data itself" is a
comment, not a call, and a scan that cannot tell the difference punishes people
for explaining themselves.
"""

import io
import os
import shutil
import tokenize

PACKAGE = "zipstream"

# Total size of the Python the submission ships. The reference is about 27 KiB;
# the cap is there so a static dictionary trained offline cannot grow without
# limit, not to make anyone count characters.
SOURCE_BUDGET = 96 * 1024

# Bare names that are never legitimate in this package.
FORBIDDEN_NAMES = frozenset(
    [
        "zlib", "gzip", "bz2", "lzma", "zipfile", "tarfile", "brotli",
        "zstandard", "zstd", "lz4", "snappy", "py7zr", "blosc",
        "ctypes", "subprocess", "multiprocessing", "socket", "tracemalloc",
        "pytest", "unittest", "_getframe", "settrace", "setprofile",
        "addaudithook",
    ]
)

# Names that are ordinary words on their own and only suspicious when they are
# reached through a particular module.
QUALIFIED = {
    ("sys", "modules"), ("sys", "argv"), ("sys", "meta_path"),
    ("sys", "path_hooks"), ("sys", "_getframe"), ("sys", "settrace"),
    ("os", "environ"), ("os", "getenv"), ("os", "system"), ("os", "popen"),
    ("inspect", "stack"), ("inspect", "currentframe"),
    ("traceback", "extract_stack"), ("importlib", "reload"),
}

# Strings that only appear in code that is trying to work out whether it is
# being tested.
FORBIDDEN_STRINGS = (
    "PYTEST_CURRENT_TEST", "sitecustomize", "usercustomize",
    # `codecs.encode(data, "zlib_codec")` names no forbidden module at all: the
    # codec registry does the import for you. The runtime blocker still stops
    # it -- encodings.zlib_codec imports zlib -- but a submission should be told
    # why it failed, not left with an ImportError from inside the stdlib.
    "zlib_codec", "bz2_codec", "hex_codec", "uu_codec",
)


class IntegrityError(Exception):
    """The submission broke one of the implementation constraints."""


def collect(submission_root, scratch):
    """Copy `<submission>/zipstream/**.py` into a tree the grader owns."""
    source = os.path.join(submission_root, PACKAGE)
    if not os.path.isdir(source):
        raise IntegrityError("no %s/ package found in %s" % (PACKAGE, submission_root))

    target = os.path.join(scratch, PACKAGE)
    os.makedirs(target, exist_ok=True)

    copied = []
    for root, directories, files in os.walk(source):
        directories[:] = sorted(d for d in directories if d != "__pycache__")
        relative = os.path.relpath(root, source)
        destination = target if relative == "." else os.path.join(target, relative)
        os.makedirs(destination, exist_ok=True)
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            if name in ("conftest.py", "sitecustomize.py", "usercustomize.py"):
                continue
            shutil.copyfile(os.path.join(root, name), os.path.join(destination, name))
            copied.append(os.path.join(destination, name))

    if not copied:
        raise IntegrityError("%s/ contains no Python files" % (PACKAGE,))
    if not os.path.isfile(os.path.join(target, "__init__.py")):
        raise IntegrityError("%s/__init__.py is missing" % (PACKAGE,))
    return copied


def scan(paths):
    """Return a list of integrity findings; empty means clean."""
    findings = []
    total = 0

    for path in paths:
        with open(path, "rb") as handle:
            raw = handle.read()
        total += len(raw)
        name = os.path.basename(path)

        try:
            tokens = list(tokenize.tokenize(io.BytesIO(raw).readline))
        except (tokenize.TokenError, SyntaxError, IndentationError) as exc:
            findings.append("%s does not tokenise: %s" % (name, exc))
            continue

        previous_name = None
        previous_was_dot = False
        for token in tokens:
            if token.type == tokenize.NAME:
                if token.string in FORBIDDEN_NAMES:
                    findings.append(
                        "%s line %d names %r" % (name, token.start[0], token.string)
                    )
                elif previous_was_dot and (previous_name, token.string) in QUALIFIED:
                    findings.append(
                        "%s line %d reaches %s.%s"
                        % (name, token.start[0], previous_name, token.string)
                    )
                previous_name = token.string
                previous_was_dot = False
            elif token.type == tokenize.OP and token.string == ".":
                previous_was_dot = True
            elif token.type == tokenize.STRING:
                for needle in FORBIDDEN_STRINGS:
                    if needle in token.string:
                        findings.append(
                            "%s line %d embeds %r" % (name, token.start[0], needle)
                        )
                previous_was_dot = False
            elif token.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                                    tokenize.INDENT, tokenize.DEDENT):
                previous_was_dot = False

    if total > SOURCE_BUDGET:
        findings.append(
            "the package is %d bytes of Python; the budget is %d"
            % (total, SOURCE_BUDGET)
        )
    return findings, total
