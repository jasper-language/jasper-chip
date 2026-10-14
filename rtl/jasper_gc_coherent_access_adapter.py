# rtl/jasper_gc_coherent_access_adapter.py
# CoherentAccessAdapter v0.1 — bridge between MemoryRequestArbiter-compatible
# interface and CoherentAccess. Combinational signal mapping only.
# NOT a top-level MemoryAccess replacement. NOT a coherence protocol.
from amaranth import *
from rtl.jasper_gc_coherent_access import CoherentAccess


class CoherentAccessAdapter(Elaboratable):
    """Adapter shim: MemoryRequestArbiter mem_* ↔ CoherentAccess.

    Exposes a MemoryAccess-compatible interface (16-bit tag) while
    instantiating CoherentAccess internally. Debug signals expose
    CoherentAccess-specific response metadata for future integration.
    """
    def __init__(self, **kwargs):
        self._ca_kwargs = kwargs

        # MemoryRequestArbiter-compatible interface
        self.mem_req_valid = Signal()
        self.mem_req_ready = Signal()
        self.mem_req_is_write = Signal()
        self.mem_req_addr = Signal(32)
        self.mem_req_tag = Signal(16)
        self.mem_rsp_valid = Signal()
        self.mem_rsp_ready = Signal()
        self.mem_rsp_tag = Signal(16)

        # Debug response metadata (CoherentAccess extras)
        self.dbg_rsp_error = Signal()
        self.dbg_rsp_status = Signal(3)
        self.dbg_rsp_hit = Signal()
        self.dbg_rsp_epoch = Signal(8)

    def elaborate(self, platform):
        m = Module()

        ca = CoherentAccess(
            tag_width=16,
            addr_width=32,
            data_width=32,
            epoch_width=8,
            **{k: v for k, v in self._ca_kwargs.items()
               if k != 'tag_width' and
               k != 'addr_width' and
               k != 'data_width' and
               k != 'epoch_width'}
        )
        m.submodules.ca = ca

        # Request path: arbiter → CoherentAccess
        m.d.comb += [
            ca.req_valid.eq(self.mem_req_valid),
            self.mem_req_ready.eq(ca.req_ready),
            ca.req_is_write.eq(self.mem_req_is_write),
            ca.req_addr.eq(self.mem_req_addr),
            ca.req_tag.eq(self.mem_req_tag),
            ca.req_write_data.eq(0),
            ca.req_epoch.eq(0),
            ca.req_size.eq(0),
            ca.req_region_id.eq(0),
            ca.req_flags.eq(0),
        ]

        # Response path: CoherentAccess → arbiter
        m.d.comb += [
            self.mem_rsp_valid.eq(ca.rsp_valid),
            ca.rsp_ready.eq(self.mem_rsp_ready),
            self.mem_rsp_tag.eq(ca.rsp_tag),
        ]

        # Debug signals (comb passthrough)
        m.d.comb += [
            self.dbg_rsp_error.eq(ca.rsp_error),
            self.dbg_rsp_status.eq(ca.rsp_status),
            self.dbg_rsp_hit.eq(ca.rsp_hit),
            self.dbg_rsp_epoch.eq(ca.rsp_epoch),
        ]

        return m
