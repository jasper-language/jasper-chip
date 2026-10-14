# -*- coding: utf-8 -*-
"""Step71: Verify Step70 JSON can be applied into a stable importable module.

Run:
  python -m tests.test_step71_apply_autotune_tool
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

from tools.step71_apply_autotune import apply_autotune


def _import_from_path(py_path: Path):
    spec = importlib.util.spec_from_file_location("autotuned_link_depths_tmp", str(py_path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def test_step71_apply_autotune_tool():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        in_json = td / "in.json"
        out_py = td / "autotuned_link_depths.py"

        in_json.write_text(json.dumps({
            "ok": 1,
            "card_link_depth": 3,
            "reloc_link_depth": 5,
        }, indent=2) + "\n", encoding="utf-8")

        payload = apply_autotune(in_json=in_json, out_py=out_py, out_json=None)
        assert payload["ok"] == 1
        assert payload["card_link_depth"] == 3
        assert payload["reloc_link_depth"] == 5
        assert out_py.exists()

        mod = _import_from_path(out_py)
        assert int(getattr(mod, "VALID", 0)) == 1
        assert int(getattr(mod, "CARD_LINK_DEPTH", 0)) == 3
        assert int(getattr(mod, "RELOC_LINK_DEPTH", 0)) == 5


if __name__ == "__main__":
    test_step71_apply_autotune_tool()
    print("OK: step71 apply-autotune tool produces expected importable module.")
