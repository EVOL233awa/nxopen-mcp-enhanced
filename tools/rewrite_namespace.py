"""Rewrite the vendored upstream namespace to nxopen-mcp-enhanced.

Run from anywhere; idempotent. Skips itself and leaves upstream URLs intact.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OLD_DIR = SRC / "nxopen_mcp"
NEW_DIR = SRC / "nxopen_mcp_enhanced"
TEXT_SUFFIXES = {".py", ".toml", ".md", ".yml", ".yaml", ".txt"}
SKIP_FILES = {Path(__file__).resolve(), ROOT / "LICENSE"}
URL_MARKERS = ("github.com/mingfeng6684/nxopen-mcp",
               "pypi.org/project/nxopen-mcp")

MODULE_RE = re.compile(r"\bnxopen_mcp(?!_enhanced)\b")
DIST_RE = re.compile(r"\bnxopen-mcp(?!-enhanced)\b")


def rewrite_line(line: str) -> str:
    if any(marker in line for marker in URL_MARKERS):
        return line
    line = MODULE_RE.sub("nxopen_mcp_enhanced", line)
    line = line.replace(".nxopen-mcp", ".nxopen-mcp-enhanced")
    line = DIST_RE.sub("nxopen-mcp-enhanced", line)
    return line


def main() -> int:
    if OLD_DIR.exists() and not NEW_DIR.exists():
        OLD_DIR.rename(NEW_DIR)
        print(f"renamed {OLD_DIR.name} -> {NEW_DIR.name}")
    elif OLD_DIR.exists() and NEW_DIR.exists():
        print(f"both {OLD_DIR.name} and {NEW_DIR.name} exist; aborting", file=sys.stderr)
        return 2

    changed = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or path in SKIP_FILES:
            continue
        if "__pycache__" in path.parts or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        new = "".join(rewrite_line(line) for line in text.splitlines(keepends=True))
        if new != text:
            path.write_text(new, encoding="utf-8", newline="")
            changed += 1
    print(f"rewrote {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
