#!/usr/bin/env python3
"""Format staged project Python files without staging unrelated local edits."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

RUFF_VERSION = "0.17.4"


def git(*args):
    return subprocess.check_output(["git", *args])


def main():
    os.chdir(os.fsdecode(git("rev-parse", "--show-toplevel").rstrip(b"\n")))
    files = [
        os.fsdecode(path)
        for path in git(
            "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR", "--", "*.py"
        ).split(b"\0")
        if path and not path.startswith((b"submodules/", b"ThorlabsPM/"))
    ]
    if not files:
        return 0

    configured = subprocess.run(
        ["git", "config", "--get", "artiq.ruffPath"],
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    if configured:
        ruff = [configured]
    elif shutil.which("uvx"):
        ruff = ["uvx", "--from", f"ruff=={RUFF_VERSION}", "ruff"]
    elif shutil.which("ruff"):
        ruff = ["ruff"]
    else:
        print("Install Ruff or configure git config artiq.ruffPath.", file=sys.stderr)
        return 1
    if subprocess.check_output([*ruff, "--version"], text=True).strip() != (
        f"ruff {RUFF_VERSION}"
    ):
        print(f"Expected Ruff {RUFF_VERSION}.", file=sys.stderr)
        return 1

    changes = []
    for path in files:
        info = git("ls-files", "--stage", "-z", "--", f":(literal){path}")
        mode, oid, stage = info.split(b"\t", 1)[0].split()
        if stage != b"0" or mode not in (b"100644", b"100755"):
            continue
        staged = git("cat-file", "blob", os.fsdecode(oid))
        formatted = subprocess.check_output(
            [*ruff, "format", "--isolated", "--stdin-filename", path, "-"],
            input=staged,
        )
        if staged == formatted:
            continue
        file = Path(path)
        if file.is_symlink() or not file.is_file() or file.read_bytes() != staged:
            print(
                f"Ruff would format {path}, but it has unstaged changes. "
                "Format and stage it deliberately, or commit the changes separately.",
                file=sys.stderr,
            )
            return 1
        changes.append((file, mode, staged, formatted))

    # Do not change anything until all candidates have been checked.
    for file, _, staged, _ in changes:
        if file.read_bytes() != staged:
            print(
                f"{file} changed during formatting; retry the commit.", file=sys.stderr
            )
            return 1
    for file, mode, _, formatted in changes:
        oid = subprocess.check_output(
            ["git", "hash-object", "-w", "--stdin"], input=formatted
        ).strip()
        file.write_bytes(formatted)
        subprocess.run(
            [
                "git",
                "update-index",
                "--cacheinfo",
                f"{os.fsdecode(mode)},{os.fsdecode(oid)},{file}",
            ],
            check=True,
        )
        print(f"Ruff formatted {file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
