"""Step54: Ensure chip top wrappers expose *distinct* boundary ports.

Why:
  In Step53 wrappers, we initially re-exported internal Signals by aliasing.
  For real 3-chip partitioning (separate synthesis / separate netlists), we
  must create explicit boundary Signals and wire them to the internal module.

This test is intentionally simple and fast: it checks object identity.
"""

from __future__ import annotations


def _assert_not_aliased(top, pairs):
    for outer_name, inner_name in pairs:
        outer = getattr(top, outer_name)
        inner = getattr(top.u, inner_name)
        assert outer is not inner, f"{type(top).__name__}.{outer_name} aliases u.{inner_name}"


def main():
    from rtl.gc_chip_scan import GCScanChipTop
    from rtl.gc_chip_clean import GCCleanChipTop
    from rtl.gc_chip_move import GCMoveChipTop

    scan = GCScanChipTop()
    clean = GCCleanChipTop()
    move = GCMoveChipTop()

    _assert_not_aliased(
        scan,
        [
            ("wb_valid", "wb_valid"),
            ("wb_ready", "wb_ready"),
            ("out_valid", "out_valid"),
            ("out_ready", "out_ready"),
            ("epoch_advance", "epoch_advance"),
        ],
    )

    _assert_not_aliased(
        clean,
        [
            ("cmd_enq_valid", "cmd_enq_valid"),
            ("cmd_enq_ready", "cmd_enq_ready"),
            ("cmd_op", "cmd_op"),
            ("rsp_valid", "rsp_valid"),
            ("rsp_take", "rsp_take"),
            ("card_in_valid", "card_in_valid"),
            ("card_in_ready", "card_in_ready"),
            ("mv_upd_valid", "mv_upd_valid"),
        ],
    )

    _assert_not_aliased(
        move,
        [
            ("cmd_enq_valid", "cmd_enq_valid"),
            ("cmd_enq_ready", "cmd_enq_ready"),
            ("cmd_op", "cmd_op"),
            ("rsp_valid", "rsp_valid"),
            ("rsp_take", "rsp_take"),
            ("epoch_advance", "epoch_advance"),
            ("upd_valid", "upd_valid"),
        ],
    )

    print("OK: chip wrapper boundary ports are explicit (no aliasing).")


if __name__ == "__main__":
    main()
