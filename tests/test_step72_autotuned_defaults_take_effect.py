# -*- coding: utf-8 -*-
"""Step72: Verify GC3ChipSystem can surface and apply autotuned link depths.

Run:
  python -m tests.test_step72_autotuned_defaults_take_effect
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path


def test_step72_autotuned_defaults_take_effect():
    # Backup/restore the repo's default module so this test is hermetic.
    repo_py = Path("rtl/autotuned_link_depths.py")
    backup = repo_py.read_text(encoding="utf-8")
    try:
        # Write a synthetic Step70 recommendation payload.
        in_json = Path("reports/step70_recommended_depths.json")
        in_json.parent.mkdir(parents=True, exist_ok=True)
        in_json.write_text(
            json.dumps({
                "ok": 1,
                "card_link_depth": 7,
                "reloc_link_depth": 9,
            }, indent=2) + "\n",
            encoding="utf-8",
        )

        # Apply it into the in-repo importable module.
        from tools.step71_apply_autotune import apply_autotune

        apply_autotune(in_json=in_json, out_py=repo_py, out_json=None)

        # Reload the module so GC3ChipSystem sees the updated constants.
        import rtl.autotuned_link_depths as ald
        importlib.reload(ald)
        assert int(ald.VALID) == 1
        assert int(ald.CARD_LINK_DEPTH) == 7
        assert int(ald.RELOC_LINK_DEPTH) == 9

        from rtl.gc_3chip_system import GC3ChipSystem

        dut = GC3ChipSystem(
            ncores=2,
            card_link_depth=2,
            reloc_link_depth=2,
            use_autotuned_defaults=True,
        )

        # The effective depths must reflect the autotuned values.
        assert int(dut.effective_card_link_depth) == 7
        assert int(dut.effective_reloc_link_depth) == 9
        assert int(dut.card_link_depth) == 7
        assert int(dut.reloc_link_depth) == 9

        # And they must be exported for observability.
        # Amaranth 0.5 uses Signal.init as the stable name for the reset value.
        assert int(dut.dbg_card_link_depth.init) == 7
        assert int(dut.dbg_reloc_link_depth.init) == 9
    finally:
        repo_py.write_text(backup, encoding="utf-8")
        # Best effort: restore to VALID=0 for other tests.
        try:
            import rtl.autotuned_link_depths as ald
            importlib.reload(ald)
        except Exception:
            pass


if __name__ == "__main__":
    test_step72_autotuned_defaults_take_effect()
    print("OK: step72 autotuned defaults are applied and exported.")
