#!/usr/bin/env python3
"""Backward-compatible scorer wrapper.

Prefer `mcmurphy score ...` for new usage.
"""

from __future__ import annotations

from mcmurphy.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["score", *(__import__("sys").argv[1:])]))
