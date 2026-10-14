# -*- coding: utf-8 -*-
"""Step53: 3-chip partition elaboration test.

Goal: prove Scan/Clean/Move chip-top wrappers wire and convert to RTLIL.

Run:
  python -m tests.test_step53_3chip_elaborate
"""

from __future__ import annotations

from amaranth.back import rtlil

from rtl.gc_3chip_system import GC3ChipSystem


def main() -> None:
    top = GC3ChipSystem(
        ncores=2,
        scan_kwargs=dict(fifo_depth=4, consume_every=1, batch_size=1, dedup_enable=True, cardset_size=4, out_depth=4),
        clean_kwargs=dict(entries=32, fifo_depth=2, engine_latency=0, card_dedup_enable=True, card_table_size=4, card_table_ways=1, card_index_mode=0),
        move_kwargs=dict(fifo_depth=2, map_depth=4, chase_depth=1),
    )
    il = rtlil.convert(top, name="GC3ChipSystem", ports=[top.epoch_advance])

    # Check top module present
    assert ("module \GC3ChipSystem" in il) or ("module GC3ChipSystem" in il)

    def has_mod(name: str) -> bool:
        return (f"module \{name}" in il) or (f"module {name}" in il)

    # Hierarchical module names from Amaranth RTLIL
    assert has_mod("GC3ChipSystem.scan.scan"), "missing scan submodule"
    assert has_mod("GC3ChipSystem.clean.clean"), "missing clean submodule"
    assert has_mod("GC3ChipSystem.move.move"), "missing move submodule"

    print("OK: GC3ChipSystem elaboration + rtlil.convert succeeded (3 chip tops wired).")


if __name__ == "__main__":
    main()
