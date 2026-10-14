# rtl/gc_tile_dispatch.py
# N-way tile dispatcher: routes events to 2L tiles by event_id hash.
from amaranth import *


class TileDispatch(Elaboratable):
    """Dispatch events to N 2L tiles using event_id hash."""
    def __init__(self, tile_count=2):
        self.tile_count = tile_count
        # Single input
        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_event_type = Signal(2); self.in_addr = Signal(32)
        self.in_data = Signal(32); self.in_tag = Signal(8)
        self.in_epoch = Signal(8); self.in_seq = Signal(2)
        # N tile outputs (each tile has 2 lane inputs)
        self.out_valid = [Signal() for _ in range(tile_count)]
        self.out_ready = [Signal() for _ in range(tile_count)]
        self.out_type = [Signal(2) for _ in range(tile_count)]
        self.out_addr = [Signal(32) for _ in range(tile_count)]
        self.out_data = [Signal(32) for _ in range(tile_count)]
        self.out_tag = [Signal(8) for _ in range(tile_count)]
        self.out_epoch = [Signal(8) for _ in range(tile_count)]
        self.out_seq = [Signal(2) for _ in range(tile_count)]
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module(); P = self; TC = P.tile_count
        tc_bits = (TC - 1).bit_length() if TC > 1 else 1
        tile_id = Signal(tc_bits)
        m.d.comb += tile_id.eq(P.in_addr[:tc_bits])

        # Route to selected tile
        for i in range(TC):
            sel = Signal(); m.d.comb += sel.eq(tile_id == i)
            m.d.comb += [
                P.out_valid[i].eq(P.in_valid & sel),
                P.out_type[i].eq(P.in_event_type),
                P.out_addr[i].eq(P.in_addr),
                P.out_data[i].eq(P.in_data),
                P.out_tag[i].eq(P.in_tag),
                P.out_epoch[i].eq(P.in_epoch),
                P.out_seq[i].eq(P.in_seq),
            ]

        # Ready when selected tile is ready
        ready = Const(0)
        for i in range(TC):
            ready = Mux(tile_id == i, P.out_ready[i], ready)
        m.d.comb += P.in_ready.eq(ready)
        m.d.comb += P.busy.eq(0)
        return m
