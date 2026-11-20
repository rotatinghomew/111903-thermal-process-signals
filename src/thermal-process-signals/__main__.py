"""命令入口：版本查看与当班分析。

用法：
  python -m thermal-process-signals version
  python -m thermal-process-signals report [--json] [--data DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .pipeline import run_shift
from .report import render


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def _load(data_dir: Path) -> tuple[dict, dict | None]:
    ledger = json.loads((data_dir / "shift_handoff.json").read_text(encoding="utf-8"))
    audit_path = data_dir / "rework_census.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else None
    return ledger, audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thermal-process-signals")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("version")
    report_cmd = sub.add_parser("report", help="生成当班分析报告")
    report_cmd.add_argument("--json", action="store_true", help="输出结构化 JSON")
    report_cmd.add_argument("--data", type=Path, default=_default_data_dir())
    args = parser.parse_args(argv)

    if args.command in (None, "version"):
        print(f"本地分析工作区 {__version__}")
        return 0

    ledger, audit = _load(args.data)
    result = run_shift(ledger, audit)
    if args.json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
