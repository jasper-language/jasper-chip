# rtl/jasper_gc_compact_engine.py
# CompactEngine with optional MemoryAccess integration and relocation write-back.
from amaranth import *


class CompactEngine(Elaboratable):
    def __init__(self, step_size=64, object_granule=32, move_ratio=0.3, use_memory=False, reloc_table_depth=256):
        self.step_size = step_size; self.object_granule = object_granule
        self.move_ratio = move_ratio; self.use_memory = use_memory
        self.reloc_table_depth = reloc_table_depth

        self.in_valid = Signal(); self.in_ready = Signal()
        self.in_correlation_id = Signal(16)
        self.in_epoch = Signal(8); self.in_merge_domain = Signal(4)
        self.in_region_base = Signal(32); self.in_region_size = Signal(32)
        self.out_valid = Signal(); self.out_ready = Signal()
        self.out_status = Signal(3)
        self.out_correlation_id = Signal(16)
        self.out_epoch = Signal(8); self.out_merge_domain = Signal(4)
        self.out_bytes_scanned = Signal(32)
        self.out_objects_scanned = Signal(32)
        self.out_live_objects = Signal(32); self.out_dead_objects = Signal(32)
        self.out_bytes_moved = Signal(32); self.out_objects_moved = Signal(32)
        self.out_metadata_updates = Signal(32)
        self.out_error_code = Signal(8)
        self.busy = Signal()

        self.mem_req_valid = Signal(); self.mem_req_ready = Signal()
        self.mem_req_is_write = Signal(); self.mem_req_addr = Signal(32)
        self.mem_req_tag = Signal(16)
        self.mem_req_write_data = Signal(32)
        self.mem_rsp_valid = Signal(); self.mem_rsp_ready = Signal()
        self.mem_rsp_tag = Signal(16)
        self.mem_rsp_read_data = Signal(32)

        self.relocation_active = Signal()
        self.relocation_count = Signal(32)
        self.reloc_base_addr = Signal(32)
        self.object_size = Signal(8, init=64)
        self.dbg_forwarding_count = Signal(range(self.reloc_table_depth + 1))

    def elaborate(self, platform):
        m = Module(); SS = self.step_size; GR = self.object_granule
        add_mv = 1 if self.move_ratio > 0.5 else 0
        RD = self.reloc_table_depth

        IDLE = 0; ISSUE = 1; WAIT = 2; DONE = 3; RELOC = 4
        state = Signal(3, init=IDLE)

        cp_base = Signal(32); cp_sz = Signal(32); cp_cur = Signal(32)
        cp_cid = Signal(16); cp_ep = Signal(8); cp_dm = Signal(4)
        cp_ob = Signal(32); cp_mv = Signal(32); cp_mu = Signal(32); cp_stp = Signal(32)
        r_bs = Signal(32); r_ob = Signal(32); r_mv = Signal(32); r_mu = Signal(32)

        # Forwarding table: register files storing old_addr and new_addr for objects to move
        fw_old_addr = Array([Signal(32) for _ in range(RD)])
        fw_new_addr = Array([Signal(32) for _ in range(RD)])
        fw_head = Signal(range(RD), init=0)
        fw_tail = Signal(range(RD), init=0)
        fw_cnt = Signal(range(RD + 1), init=0)
        wr_pending = Signal()  # write response pending (memory mode)

        m.d.comb += [
            self.in_ready.eq(state == IDLE),
            self.busy.eq(state != IDLE),
            self.relocation_active.eq(state == RELOC),
            self.relocation_count.eq(r_mv),
            self.dbg_forwarding_count.eq(fw_cnt),
        ]

        with m.If((state == IDLE) & self.in_valid & self.in_ready):
            m.d.sync += [
                state.eq(ISSUE),
                cp_base.eq(self.in_region_base), cp_sz.eq(self.in_region_size),
                cp_cur.eq(0), cp_cid.eq(self.in_correlation_id),
                cp_ep.eq(self.in_epoch), cp_dm.eq(self.in_merge_domain),
                cp_ob.eq(0), cp_mv.eq(0), cp_mu.eq(0), cp_stp.eq(0),
                fw_head.eq(0), fw_tail.eq(0), fw_cnt.eq(0),
                wr_pending.eq(0),
            ]

        # --- SCAN: ISSUE ---
        with m.If(state == ISSUE):
            rem = Signal(32); stp = Signal(32)
            m.d.comb += [rem.eq(cp_sz - cp_cur), stp.eq(Mux(rem > SS, SS, rem))]
            if self.use_memory:
                m.d.comb += [self.mem_req_valid.eq(1), self.mem_req_addr.eq(cp_base + cp_cur), self.mem_req_is_write.eq(0)]
                with m.If(self.mem_req_ready):
                    m.d.sync += [state.eq(WAIT), cp_stp.eq(stp)]
            else:
                m.d.sync += cp_cur.eq(cp_cur + stp)
                with m.If(stp > 0):
                    m.d.sync += [cp_ob.eq(cp_ob + 1), cp_mv.eq(cp_mv + add_mv), cp_mu.eq(cp_mu + 1)]
                    if add_mv:
                        with m.If(fw_cnt < RD):
                            m.d.sync += [
                                fw_old_addr[fw_tail].eq(cp_base + cp_cur),
                                fw_new_addr[fw_tail].eq(self.reloc_base_addr + fw_tail * self.object_size),
                                fw_tail.eq(Mux(fw_tail == RD - 1, 0, fw_tail + 1)),
                                fw_cnt.eq(fw_cnt + 1),
                            ]
                with m.If(cp_cur + stp >= cp_sz):
                    m.d.sync += [
                        r_bs.eq(cp_cur + stp), r_ob.eq(cp_ob + Mux(stp > 0, 1, 0)),
                        r_mv.eq(cp_mv + Mux(stp > 0, add_mv, 0)),
                        r_mu.eq(cp_mu + Mux(stp > 0, 1, 0)),
                    ]
                    with m.If(add_mv == 0):
                        m.d.sync += state.eq(DONE)
                    with m.Else():
                        m.d.sync += state.eq(RELOC)
                with m.Else():
                    m.d.sync += state.eq(ISSUE)

        # --- SCAN: WAIT (memory mode) ---
        if self.use_memory:
            with m.If(state == WAIT):
                m.d.comb += self.mem_rsp_ready.eq(1)
                with m.If(self.mem_rsp_valid):
                    m.d.sync += cp_cur.eq(cp_cur + cp_stp)
                    with m.If(cp_stp > 0):
                        m.d.sync += [cp_ob.eq(cp_ob + 1), cp_mv.eq(cp_mv + add_mv), cp_mu.eq(cp_mu + 1)]
                        if add_mv:
                            with m.If(fw_cnt < RD):
                                m.d.sync += [
                                    fw_old_addr[fw_tail].eq(cp_base + cp_cur),
                                    fw_new_addr[fw_tail].eq(self.reloc_base_addr + fw_tail * self.object_size),
                                    fw_tail.eq(Mux(fw_tail == RD - 1, 0, fw_tail + 1)),
                                    fw_cnt.eq(fw_cnt + 1),
                                ]
                    with m.If(cp_cur + cp_stp >= cp_sz):
                        m.d.sync += [
                            r_bs.eq(cp_cur + cp_stp), r_ob.eq(cp_ob + Mux(cp_stp > 0, 1, 0)),
                            r_mv.eq(cp_mv + Mux(cp_stp > 0, add_mv, 0)),
                            r_mu.eq(cp_mu + Mux(cp_stp > 0, 1, 0)),
                        ]
                        with m.If(add_mv == 0):
                            m.d.sync += state.eq(DONE)
                        with m.Else():
                            m.d.sync += state.eq(RELOC)
                    with m.Else():
                        m.d.sync += state.eq(ISSUE)

        # --- RELOCATE phase ---
        old_addr = Signal(32); new_addr = Signal(32)
        with m.If(state == RELOC):
            m.d.comb += [
                old_addr.eq(fw_old_addr[fw_head]),
                new_addr.eq(fw_new_addr[fw_head]),
                self.mem_req_addr.eq(new_addr),
                self.mem_req_is_write.eq(1),
                self.mem_req_write_data.eq(old_addr ^ new_addr),
                self.mem_req_tag.eq(cp_cid),
            ]
            if self.use_memory:
                m.d.comb += [
                    self.mem_req_valid.eq((fw_cnt > 0) & ~wr_pending),
                    self.mem_rsp_ready.eq(wr_pending),
                ]
                with m.If((fw_cnt > 0) & ~wr_pending & self.mem_req_ready):
                    m.d.sync += wr_pending.eq(1)
                with m.If(wr_pending & self.mem_rsp_valid):
                    m.d.sync += [
                        wr_pending.eq(0),
                        fw_head.eq(Mux(fw_head == RD - 1, 0, fw_head + 1)),
                        fw_cnt.eq(fw_cnt - 1),
                    ]
                with m.If((fw_cnt == 0) & ~wr_pending):
                    m.d.sync += state.eq(DONE)
            else:
                m.d.comb += self.mem_req_valid.eq(fw_cnt > 0)
                with m.If(fw_cnt > 0):
                    m.d.sync += [
                        fw_head.eq(Mux(fw_head == RD - 1, 0, fw_head + 1)),
                        fw_cnt.eq(fw_cnt - 1),
                    ]
                with m.Else():
                    m.d.sync += state.eq(DONE)

        # DONE
        m.d.comb += [
            self.out_valid.eq(state == DONE), self.out_status.eq(0),
            self.out_correlation_id.eq(cp_cid), self.out_epoch.eq(cp_ep),
            self.out_merge_domain.eq(cp_dm),
            self.out_bytes_scanned.eq(r_bs), self.out_objects_scanned.eq(r_ob),
            self.out_live_objects.eq(r_ob - r_mv), self.out_dead_objects.eq(r_mv),
            self.out_bytes_moved.eq(r_mv * GR), self.out_objects_moved.eq(r_mv),
            self.out_metadata_updates.eq(r_mu), self.out_error_code.eq(0),
        ]
        with m.If((state == DONE) & self.out_ready): m.d.sync += state.eq(IDLE)
        return m
