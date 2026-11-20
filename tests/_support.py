"""测试辅助：按文件路径加载带连字符的包，并读取合成资料。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "thermal-process-signals"
DATA = ROOT / "data"


def load_package():
    spec = importlib.util.spec_from_file_location(
        "tps",
        SRC / "__init__.py",
        submodule_search_locations=[str(SRC)],
    )
    if "tps" not in sys.modules:
        module = importlib.util.module_from_spec(spec)
        sys.modules["tps"] = module
        spec.loader.exec_module(module)
    import tps  # noqa: F401

    for name in (
        "timex", "baseline", "detect", "routing", "clock_sync",
        "genealogy", "ledger", "checks", "pipeline", "report", "__main__",
    ):
        if not hasattr(tps, name):
            sub_spec = importlib.util.spec_from_file_location(
                f"tps.{name}", SRC / f"{name}.py"
            )
            sub = importlib.util.module_from_spec(sub_spec)
            sys.modules[f"tps.{name}"] = sub
            sub_spec.loader.exec_module(sub)
            setattr(tps, name, sub)
    return tps


def load_data(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def build_result():
    tps = load_package()
    from tps.pipeline import run_shift

    return run_shift(load_data("shift_handoff.json"), load_data("rework_census.json"))
