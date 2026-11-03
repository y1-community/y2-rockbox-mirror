#!/usr/bin/env python3
"""Compatibility and behavioral tests for the V87 save broker."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BROKER = ROOT / "00_tools" / "y2_v87_boot_save_broker.sh"
BASE_TEST = ROOT / "00_tools" / "test_y2_v86_boot_save_broker.py"


def load_base():
    spec = importlib.util.spec_from_file_location("v86_broker_test", BASE_TEST)
    if spec is None or spec.loader is None:
        raise RuntimeError(BASE_TEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    source = BROKER.read_text(encoding="utf-8")
    forbidden = (
        "printf",
        "mktemp",
        "awk",
        "sed ",
        "cut ",
        "head ",
        "tail ",
        "install ",
    )
    retained = [token for token in forbidden if token in source]
    if retained:
        raise SystemExit(
            f"Unsupported vendor-shell command retained: {retained}")
    test = load_base()
    test.BROKER = BROKER
    test.main()
    print("PASS: vendor-shell command allowlist")


if __name__ == "__main__":
    main()
