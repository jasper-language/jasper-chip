# rtl/jasper_gc_accelerator_ip.py
# SCAN→ScanEngine, SWEEP→SweepEngine, REBUILD→MRE, COMPACT→CompactEngine
from amaranth import *
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig
from rtl.jasper_gc_accelerator_if import JasperGCAcceleratorIF
from rtl.jasper_gc_accelerator_queue import CommandQueue, CompletionQueue
from rtl.jasper_gc_accelerator_scheduler import RegionScheduler
from rtl.jasper_gc_scan_engine import ScanEngine
from rtl.jasper_gc_sweep_engine import SweepEngine
from rtl.jasper_gc_metadata_rebuild_engine import MetadataRebuildEngine
from rtl.jasper_gc_compact_engine import CompactEngine
from rtl.jasper_gc_memory_access import MemoryAccess
from rtl.jasper_gc_chiplet_link import ChipletLink
from rtl.jasper_gc_coherent_access_adapter import CoherentAccessAdapter
from rtl.jasper_gc_memory_arbiter import MemoryRequestArbiter
from rtl.jasper_gc_accelerator_perf_counters import JasperGCAcceleratorPerfCounters


class JasperGCAcceleratorIP(Elaboratable):
    """enable_memory: SCAN+Sweep through MemoryAccess via arbiter.
    per_engine_memory: each engine gets its own MemoryAccess (parallel access).
    """
    def __init__(self, config: JasperGCAcceleratorConfig, enable_memory=False,
                 mem_read_latency=4, mem_queue_depth=8, per_engine_memory=False,
                 memory_model="memory_access",
                 link_latency=5, link_width=1, chiplet_queue_depth=4,
                 chiplet_mode="simple", burst_enable=False):
        self.config = config
        self.enable_memory = enable_memory
        self.mem_read_latency = mem_read_latency
        self.mem_queue_depth = mem_queue_depth
        self.per_engine_memory = per_engine_memory
        if memory_model not in ("memory_access", "chiplet_link", "coherent"):
            raise ValueError(
                f"memory_model must be 'memory_access', 'chiplet_link', or 'coherent', got {memory_model!r}")
        self.memory_model = memory_model
        self.link_latency = link_latency
        self.link_width = link_width
        self.chiplet_queue_depth = chiplet_queue_depth
        self.chiplet_mode = chiplet_mode
        self.burst_enable = burst_enable
        self._mem_backend = memory_model
        errors = config.validate()
        if errors: raise ValueError(f"Accelerator config validation: {'; '.join(errors)}")
        self.iface = JasperGCAcceleratorIF(config=config)
        self.adapter_type = Signal(2, init=config.adapter_type.value)
        # Debug signal references (set in elaborate)
        self._dbg = {}

    def elaborate(self, platform):
        m = Module(); cfg = self.config; I = self.iface
        mem_en = self.enable_memory

        cmdq = CommandQueue(depth=cfg.command_queue_depth,
                            burst_enable=self.burst_enable)
        sched = RegionScheduler(region_count=4,
            support_scan=cfg.support_scan, support_sweep=cfg.support_sweep,
            support_rebuild=cfg.support_rebuild, support_compact=cfg.support_compact,
            support_relocate=False, support_large_move=False, support_bg_phase=False)
        scan = ScanEngine(step_size=64, use_memory=mem_en)
        sweep = SweepEngine(step_size=64, use_memory=mem_en)
        mre = MetadataRebuildEngine(step_size=64, use_memory=mem_en)
        ce = CompactEngine(step_size=64, use_memory=mem_en)

        # MemoryAccess + Arbiter (only when memory enabled)
        if mem_en:
            arb = MemoryRequestArbiter()
            self._arb = arb
            m.submodules.arb = arb
            if self.per_engine_memory:
                mem_map = {}
                for ename in ['scan', 'sweep', 'mre', 'ce']:
                    if self.memory_model == "chiplet_link":
                        ma = ChipletLink(
                            link_latency=self.link_latency,
                            link_width=self.link_width,
                            queue_depth=self.chiplet_queue_depth,
                            mode=self.chiplet_mode)
                    elif self.memory_model == "coherent":
                        ma = CoherentAccessAdapter()
                    else:
                        ma = MemoryAccess(
                            read_latency=self.mem_read_latency,
                            write_latency=self.mem_read_latency,
                            queue_depth=self.mem_queue_depth)
                    mem_map[ename] = ma
                    m.submodules[f'{ename}_mem'] = ma
                    setattr(self, f'_{ename}_mem', ma)
            else:
                if self.memory_model == "chiplet_link":
                    mem = ChipletLink(
                        link_latency=self.link_latency,
                        link_width=self.link_width,
                        queue_depth=self.chiplet_queue_depth,
                        mode=self.chiplet_mode)
                elif self.memory_model == "coherent":
                    mem = CoherentAccessAdapter()
                else:
                    mem = MemoryAccess(
                        read_latency=self.mem_read_latency,
                        write_latency=self.mem_read_latency,
                        queue_depth=self.mem_queue_depth)
                self._mem = mem
                m.submodules.mem = mem
        compq = CompletionQueue(depth=cfg.completion_queue_depth)

        m.submodules.cmdq = cmdq; m.submodules.sched = sched
        m.submodules.scan = scan; m.submodules.sweep = sweep
        m.submodules.mre = mre; m.submodules.ce = ce
        m.submodules.compq = compq

        # Top → cmdq
        m.d.comb += [
            cmdq.cmd_valid.eq(I.cmd_valid), I.cmd_ready.eq(cmdq.cmd_ready),
            cmdq.cmd_type.eq(I.cmd_type),
            cmdq.cmd_correlation_id.eq(I.cmd_correlation_id),
            cmdq.cmd_epoch.eq(I.cmd_epoch),
            cmdq.cmd_merge_domain.eq(I.cmd_merge_domain),
            cmdq.cmd_region_base.eq(I.cmd_region_base),
            cmdq.cmd_region_size.eq(I.cmd_region_size),
            cmdq.cmd_priority.eq(I.cmd_priority),
            cmdq.cmd_flags.eq(I.cmd_flags),
        ]

        # cmdq → sched
        sched_hold = Signal()
        m.d.comb += sched_hold.eq(sched.out_valid & ~sched.out_ready)

        m.d.comb += [
            sched.in_valid.eq(cmdq.out_valid),
            cmdq.out_ready.eq(sched.in_ready & ~sched_hold),
            sched.in_type.eq(cmdq.out_type),
            sched.in_correlation_id.eq(cmdq.out_correlation_id),
            sched.in_epoch.eq(cmdq.out_epoch),
            sched.in_merge_domain.eq(cmdq.out_merge_domain),
            sched.in_priority.eq(cmdq.out_priority),
            sched.in_flags.eq(cmdq.out_flags),
            sched.in_region_base.eq(cmdq.out_region_base),
            sched.in_region_size.eq(cmdq.out_region_size),
            sched.current_epoch.eq(I.current_epoch),
        ]

        # Engine routing: SCAN=0, SWEEP=1, COMPACT=2, REBUILD=3
        engs = {'scan': 0, 'sweep': 1, 'ce': 2, 'mre': 3}
        eng_objs = [scan, sweep, ce, mre]
        for name, typ in engs.items():
            obj = eng_objs[typ]
            to_eng = Signal()
            m.d.comb += to_eng.eq(sched.out_valid & (sched.out_type == typ))
            setattr(self, f'_to_{name}', to_eng)
            m.d.comb += obj.in_valid.eq(to_eng)
        # out_ready: first matching engine (single driver via ready_chain)
        ready_chain = Const(1)
        for name, typ in sorted(engs.items()):
            obj = eng_objs[typ]
            to_eng = getattr(self, f'_to_{name}')
            ready_chain = Mux(to_eng, obj.in_ready, ready_chain)
        m.d.comb += sched.out_ready.eq(ready_chain)

        # All engines get the same command fields
        for obj in eng_objs:
            m.d.comb += [
                obj.in_correlation_id.eq(sched.out_correlation_id),
                obj.in_epoch.eq(sched.out_epoch),
                obj.in_merge_domain.eq(sched.out_merge_domain),
                obj.in_region_base.eq(sched.out_region_base),
                obj.in_region_size.eq(sched.out_region_size),
            ]

        # MemoryAccess wiring (only in memory mode)
        if mem_en:
            if self.per_engine_memory:
                # Each engine drives its own MemoryAccess directly
                eng_pairs = [
                    ('scan', scan), ('sweep', sweep), ('mre', mre), ('compact', ce),
                ]
                eng_to_mem = {'scan': 'scan', 'sweep': 'sweep', 'mre': 'mre',
                              'compact': 'ce'}
                for ename, eng in eng_pairs:
                    ma = mem_map[eng_to_mem[ename]]
                    if self.memory_model == "coherent":
                        m.d.comb += [
                            ma.mem_req_valid.eq(eng.mem_req_valid),
                            eng.mem_req_ready.eq(ma.mem_req_ready),
                            ma.mem_req_is_write.eq(eng.mem_req_is_write),
                            ma.mem_req_addr.eq(eng.mem_req_addr),
                            ma.mem_req_tag.eq(eng.mem_req_tag),
                            eng.mem_rsp_valid.eq(ma.mem_rsp_valid),
                            ma.mem_rsp_ready.eq(eng.mem_rsp_ready),
                        ]
                    else:
                        m.d.comb += [
                            ma.req_valid.eq(eng.mem_req_valid),
                            eng.mem_req_ready.eq(ma.req_ready),
                            ma.req_is_write.eq(eng.mem_req_is_write),
                            ma.req_addr.eq(eng.mem_req_addr),
                            ma.req_tag.eq(eng.mem_req_tag),
                            eng.mem_rsp_valid.eq(ma.rsp_valid),
                            ma.rsp_ready.eq(eng.mem_rsp_ready),
                        ]
                # Wire arbiter inputs for perf counters (arbiter outputs unused)
                for ename, eng in eng_pairs:
                    m.d.comb += [
                        getattr(arb, f'{ename}_req_valid').eq(eng.mem_req_valid),
                        getattr(arb, f'{ename}_req_is_write').eq(eng.mem_req_is_write),
                        getattr(arb, f'{ename}_req_addr').eq(eng.mem_req_addr),
                        getattr(arb, f'{ename}_req_tag').eq(eng.mem_req_tag),
                    ]
            else:
                # v0.1: shared MemoryAccess through arbiter
                eng_arb = [
                    ('scan', scan), ('sweep', sweep), ('mre', mre), ('compact', ce),
                ]
                for name, eng in eng_arb:
                    m.d.comb += [
                        getattr(arb, f'{name}_req_valid').eq(eng.mem_req_valid),
                        eng.mem_req_ready.eq(getattr(arb, f'{name}_req_ready')),
                        getattr(arb, f'{name}_req_is_write').eq(eng.mem_req_is_write),
                        getattr(arb, f'{name}_req_addr').eq(eng.mem_req_addr),
                        getattr(arb, f'{name}_req_tag').eq(eng.mem_req_tag),
                        eng.mem_rsp_valid.eq(getattr(arb, f'{name}_rsp_valid')),
                        getattr(arb, f'{name}_rsp_ready').eq(eng.mem_rsp_ready),
                    ]
                if self.memory_model == "coherent":
                    m.d.comb += [
                        arb.mem_req_ready.eq(mem.mem_req_ready),
                        mem.mem_req_valid.eq(arb.mem_req_valid),
                        mem.mem_req_is_write.eq(arb.mem_req_is_write),
                        mem.mem_req_addr.eq(arb.mem_req_addr),
                        mem.mem_req_tag.eq(arb.mem_req_tag),
                        arb.mem_rsp_valid.eq(mem.mem_rsp_valid),
                        mem.mem_rsp_ready.eq(arb.mem_rsp_ready),
                        arb.mem_rsp_tag.eq(mem.mem_rsp_tag),
                    ]
                else:
                    m.d.comb += [
                        arb.mem_req_ready.eq(mem.req_ready),
                        mem.req_valid.eq(arb.mem_req_valid),
                        mem.req_is_write.eq(arb.mem_req_is_write),
                        mem.req_addr.eq(arb.mem_req_addr),
                        mem.req_tag.eq(arb.mem_req_tag),
                        arb.mem_rsp_valid.eq(mem.rsp_valid),
                        mem.rsp_ready.eq(arb.mem_rsp_ready),
                        arb.mem_rsp_tag.eq(mem.rsp_tag),
                    ]

        # Per-engine region capture (for correct unlock on completion)
        scan_region = Signal(max(4, 1))
        sweep_region = Signal(max(4, 1))
        mre_region = Signal(max(4, 1))
        ce_region = Signal(max(4, 1))
        m.d.sync += [
            scan_region.eq(Mux(self._to_scan & scan.in_ready,
                               sched.out_region_base[28:30], scan_region)),
            sweep_region.eq(Mux(self._to_sweep & sweep.in_ready,
                                sched.out_region_base[28:30], sweep_region)),
            mre_region.eq(Mux(self._to_mre & mre.in_ready,
                              sched.out_region_base[28:30], mre_region)),
            ce_region.eq(Mux(self._to_ce & ce.in_ready,
                             sched.out_region_base[28:30], ce_region)),
        ]
        # Completion arbitration: explicit priority (ce > mre > sweep > scan)
        sel_ce = Signal()
        sel_mre = Signal()
        sel_sweep = Signal()
        sel_scan = Signal()
        m.d.comb += [
            sel_ce.eq(ce.out_valid),
            sel_mre.eq(mre.out_valid & ~ce.out_valid),
            sel_sweep.eq(sweep.out_valid & ~ce.out_valid & ~mre.out_valid),
            sel_scan.eq(scan.out_valid & ~ce.out_valid & ~mre.out_valid & ~sweep.out_valid),
        ]

        # Region unlock: must come after sel_* signals
        any_done_expr = Const(0)
        for obj in eng_objs:
            any_done_expr = any_done_expr | (obj.out_valid & obj.out_ready)
        m.d.comb += [
            sched.unlock.eq(any_done_expr),
            sched.unlock_region.eq(
                Mux(sel_ce, ce_region,
                Mux(sel_mre, mre_region,
                Mux(sel_sweep, sweep_region,
                    scan_region)))),
        ]

        # out_ready: only selected engine
        m.d.comb += [
            ce.out_ready.eq(sel_ce & compq.in_ready),
            mre.out_ready.eq(sel_mre & compq.in_ready),
            sweep.out_ready.eq(sel_sweep & compq.in_ready),
            scan.out_ready.eq(sel_scan & compq.in_ready),
        ]

        eng_valid = Signal()
        m.d.comb += eng_valid.eq(sel_ce | sel_mre | sel_sweep | sel_scan)

        # Completion mux: select based on priority
        def pick_ce(mv, mrev, swv, scv):
            return Mux(sel_ce, mv, Mux(sel_mre, mrev, Mux(sel_sweep, swv, scv)))

        sig_names = [
            ('out_status', 3), ('out_correlation_id', 16), ('out_epoch', 8),
            ('out_merge_domain', 4), ('out_bytes_scanned', 32),
            ('out_objects_scanned', 32), ('out_error_code', 8),
        ]
        extra_sigs = [
            ('out_live_objects', 32), ('out_dead_objects', 32),
            ('out_bytes_moved', 32), ('out_objects_moved', 32),
            ('out_metadata_updates', 32),
        ]

        for name, sig in sig_names:
            setattr(self, f'_eng_{name}',
                pick_ce(getattr(ce, name), getattr(mre, name), getattr(sweep, name), getattr(scan, name)))

        self._eng_out_live_objects = pick_ce(0, 0, sweep.out_live_objects, scan.out_live_objects)
        self._eng_out_dead_objects = pick_ce(0, 0, sweep.out_dead_objects, scan.out_dead_objects)
        self._eng_out_bytes_moved = pick_ce(ce.out_bytes_moved, 0, sweep.out_bytes_moved, 0)
        self._eng_out_objects_moved = pick_ce(ce.out_objects_moved, 0, sweep.out_objects_moved, 0)
        self._eng_out_metadata_updates = pick_ce(ce.out_metadata_updates, mre.out_metadata_updates, sweep.out_metadata_updates, 0)

        # Merge with scheduler reject
        m.d.comb += [
            compq.in_valid.eq(sched.comp_valid | eng_valid),
            compq.in_status.eq(Mux(sched.comp_valid, sched.comp_status, self._eng_out_status)),
            compq.in_correlation_id.eq(Mux(sched.comp_valid, sched.comp_correlation_id, self._eng_out_correlation_id)),
            compq.in_epoch.eq(Mux(sched.comp_valid, sched.comp_epoch, self._eng_out_epoch)),
            compq.in_merge_domain.eq(Mux(sched.comp_valid, sched.comp_merge_domain, self._eng_out_merge_domain)),
            compq.in_bytes_scanned.eq(self._eng_out_bytes_scanned),
            compq.in_objects_scanned.eq(self._eng_out_objects_scanned),
            compq.in_live_objects.eq(self._eng_out_live_objects),
            compq.in_dead_objects.eq(self._eng_out_dead_objects),
            compq.in_bytes_moved.eq(self._eng_out_bytes_moved),
            compq.in_objects_moved.eq(self._eng_out_objects_moved),
            compq.in_metadata_updates.eq(self._eng_out_metadata_updates),
            compq.in_error_code.eq(self._eng_out_error_code),
        ]

        # compq → top
        m.d.comb += [
            I.comp_valid.eq(compq.out_valid), compq.out_ready.eq(I.comp_ready),
            I.comp_status.eq(compq.out_status),
            I.comp_correlation_id.eq(compq.out_correlation_id),
            I.comp_epoch.eq(compq.out_epoch), I.comp_merge_domain.eq(compq.out_merge_domain),
            I.comp_bytes_scanned.eq(compq.out_bytes_scanned),
            I.comp_objects_scanned.eq(compq.out_objects_scanned),
            I.comp_live_objects.eq(compq.out_live_objects),
            I.comp_dead_objects.eq(compq.out_dead_objects),
            I.comp_objects_moved.eq(compq.out_objects_moved),
            I.comp_bytes_moved.eq(compq.out_bytes_moved),
            I.comp_metadata_updates.eq(compq.out_metadata_updates),
            I.comp_error_code.eq(compq.out_error_code),
        ]
        # Performance counters v0.1
        pc = JasperGCAcceleratorPerfCounters()
        m.submodules.pc = pc
        self._pc = pc
        m.d.comb += [
            pc.cmd_valid.eq(I.cmd_valid), pc.cmd_ready.eq(I.cmd_ready),
            pc.comp_valid.eq(I.comp_valid), pc.comp_ready.eq(I.comp_ready),
        ]
        if mem_en:
            m.d.comb += [
                pc.mem_req_valid.eq(arb.mem_req_valid),
                pc.mem_req_ready.eq(arb.mem_req_ready),
                pc.mem_rsp_valid.eq(arb.mem_rsp_valid),
                pc.mem_rsp_ready.eq(arb.mem_rsp_ready),
                pc.arb_outstanding.eq(arb.dbg_outstanding),
                pc.arb_any_engine_req.eq(arb.dbg_any_engine_req_valid),
            ]
        # Per-engine wiring
        eng_wiring = [
            ('scan', scan, self._to_scan),
            ('sweep', sweep, self._to_sweep),
            ('ce', ce, self._to_ce),
            ('mre', mre, self._to_mre),
        ]
        for e_name, e_obj, e_to in eng_wiring:
            m.d.comb += [
                getattr(pc, f'{e_name}_busy_sig').eq(e_obj.busy),
                getattr(pc, f'{e_name}_out_v').eq(e_obj.out_valid),
                getattr(pc, f'{e_name}_out_r').eq(e_obj.out_ready),
            ]
            # to_* signals
            if e_name == 'scan':
                m.d.comb += pc.to_scan.eq(e_to)
            elif e_name == 'sweep':
                m.d.comb += pc.to_sweep.eq(e_to)
            elif e_name == 'ce':
                m.d.comb += pc.to_ce.eq(e_to)
            elif e_name == 'mre':
                m.d.comb += pc.to_mre.eq(e_to)
        if mem_en:
            # Engine mem_req signals from arbiter
            m.d.comb += [
                pc.scan_mem_req_v.eq(arb.scan_req_valid),
                pc.scan_mem_req_r.eq(arb.scan_req_ready),
                pc.sweep_mem_req_v.eq(arb.sweep_req_valid),
                pc.sweep_mem_req_r.eq(arb.sweep_req_ready),
                pc.mre_mem_req_v.eq(arb.mre_req_valid),
                pc.mre_mem_req_r.eq(arb.mre_req_ready),
                pc.ce_mem_req_v.eq(arb.compact_req_valid),
                pc.ce_mem_req_r.eq(arb.compact_req_ready),
            ]
        # Scheduler reject signals
        m.d.comb += [
            pc.reject_stale.eq(sched._reject_stale),
            pc.reject_unsupp.eq(sched._reject_unsupp),
            pc.reject_busy.eq(sched._reject_busy),
        ]

        m.d.comb += I.adapter_type.eq(self.adapter_type)
        cap = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 5)
        m.d.comb += I.cap_supported_types.eq(cap)
        return m
