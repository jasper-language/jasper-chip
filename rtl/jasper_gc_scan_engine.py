# rtl/jasper_gc_scan_engine.py
# ScanEngine with MemoryAccess integration — each step issues a mem read.
from amaranth import *


class ScanEngine(Elaboratable):
    """ScanEngine with optional MemoryAccess integration.
    When use_memory=True, each step issues a mem read and waits for response.
    When use_memory=False, steps auto-advance (counting mode, original behavior).
    """
    def __init__(self, step_size=64, live_ratio=0.7, use_memory=False):
        self.step_size = step_size
        self.live_ratio = live_ratio
        self.use_memory = use_memory

        # Control
        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_correlation_id = Signal(16)
        self.in_epoch = Signal(8); self.in_merge_domain = Signal(4)
        self.in_region_base = Signal(32); self.in_region_size = Signal(32)

        # Completion
        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_status = Signal(3)
        self.out_correlation_id = Signal(16)
        self.out_epoch = Signal(8); self.out_merge_domain = Signal(4)
        self.out_bytes_scanned = Signal(32)
        self.out_objects_scanned = Signal(32)
        self.out_live_objects = Signal(32)
        self.out_dead_objects = Signal(32)
        self.out_error_code = Signal(8)
        self.busy = Signal()

        # Memory access interface
        self.mem_req_valid = Signal(); self.mem_req_ready = Signal()
        self.mem_req_is_write = Signal()
        self.mem_req_addr = Signal(32)
        self.mem_req_tag = Signal(16)
        self.mem_rsp_valid = Signal(); self.mem_rsp_ready = Signal()
        self.mem_rsp_tag = Signal(16)

    def elaborate(self, platform):
        m = Module(); SS = self.step_size

        IDLE = 0; SCAN_ISSUE = 1; SCAN_WAIT = 2; DONE = 3
        state = Signal(2, init=IDLE)

        sc_base = Signal(32); sc_sz = Signal(32)
        sc_cur = Signal(32); sc_cid = Signal(16)
        sc_ep = Signal(8); sc_dm = Signal(4)
        sc_ob = Signal(32); sc_lv = Signal(32)
        sc_stp = Signal(32)  # current step size

        r_bs = Signal(32); r_ob = Signal(32); r_lv = Signal(32)
        tag_cnt = Signal(16, init=0)  # unique tag per step

        m.d.comb += [self.in_ready.eq(state == IDLE), self.busy.eq(state != IDLE)]

        # Memory request: read, not write
        m.d.comb += self.mem_req_is_write.eq(0)

        # IDLE → SCAN_ISSUE
        with m.If((state == IDLE) & self.in_valid & self.in_ready):
            m.d.sync += [
                state.eq(SCAN_ISSUE),
                sc_base.eq(self.in_region_base), sc_sz.eq(self.in_region_size),
                sc_cur.eq(0),
                sc_cid.eq(self.in_correlation_id),
                sc_ep.eq(self.in_epoch), sc_dm.eq(self.in_merge_domain),
                sc_ob.eq(0), sc_lv.eq(0), sc_stp.eq(0),
                tag_cnt.eq(tag_cnt + 1),
            ]

        # SCAN_ISSUE: send memory read request (or auto-advance in counting mode)
        with m.If(state == SCAN_ISSUE):
            rem = Signal(32); stp = Signal(32)
            m.d.comb += [rem.eq(sc_sz - sc_cur), stp.eq(Mux(rem > SS, SS, rem))]
            if self.use_memory:
                m.d.comb += [
                    self.mem_req_valid.eq(1),
                    self.mem_req_addr.eq(sc_base + sc_cur),
                    self.mem_req_tag.eq(sc_cid + tag_cnt),
                ]
                with m.If(self.mem_req_ready):
                    m.d.sync += [state.eq(SCAN_WAIT), sc_stp.eq(stp), tag_cnt.eq(tag_cnt + 1)]
            else:
                # Counting mode: auto-advance
                m.d.sync += [sc_cur.eq(sc_cur + stp), sc_stp.eq(stp)]
                with m.If(stp > 0):
                    m.d.sync += [sc_ob.eq(sc_ob + 1)]
                    if self.live_ratio > 0.5:
                        m.d.sync += sc_lv.eq(sc_lv + 1)
                with m.If(sc_cur + stp >= sc_sz):
                    m.d.sync += [
                        r_bs.eq(sc_cur + stp),
                        r_ob.eq(sc_ob + Mux(stp > 0, 1, 0)),
                        r_lv.eq(sc_lv + Mux(stp > 0, 1 if self.live_ratio > 0.5 else 0, 0)),
                        state.eq(DONE),
                    ]
                with m.Else():
                    m.d.sync += state.eq(SCAN_ISSUE)

        # SCAN_WAIT: wait for memory response (only in memory mode)
        if self.use_memory:
            with m.If(state == SCAN_WAIT):
                m.d.comb += self.mem_rsp_ready.eq(1)
                with m.If(self.mem_rsp_valid):
                    m.d.sync += sc_cur.eq(sc_cur + sc_stp)
                    with m.If(sc_stp > 0):
                        m.d.sync += [sc_ob.eq(sc_ob + 1)]
                        if self.live_ratio > 0.5:
                            m.d.sync += sc_lv.eq(sc_lv + 1)
                    with m.If(sc_cur + sc_stp >= sc_sz):
                        m.d.sync += [
                            r_bs.eq(sc_cur + sc_stp),
                            r_ob.eq(sc_ob + Mux(sc_stp > 0, 1, 0)),
                            r_lv.eq(sc_lv + Mux(sc_stp > 0, 1 if self.live_ratio > 0.5 else 0, 0)),
                            state.eq(DONE),
                        ]
                    with m.Else():
                        m.d.sync += state.eq(SCAN_ISSUE)

        # DONE
        m.d.comb += [
            self.out_valid.eq(state == DONE), self.out_status.eq(0),
            self.out_correlation_id.eq(sc_cid),
            self.out_epoch.eq(sc_ep), self.out_merge_domain.eq(sc_dm),
            self.out_bytes_scanned.eq(r_bs), self.out_objects_scanned.eq(r_ob),
            self.out_live_objects.eq(r_lv), self.out_dead_objects.eq(r_ob - r_lv),
            self.out_error_code.eq(0),
        ]
        with m.If((state == DONE) & self.out_ready):
            m.d.sync += state.eq(IDLE)

        return m
