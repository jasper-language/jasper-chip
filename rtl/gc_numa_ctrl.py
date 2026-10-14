# rtl/gc_numa_ctrl.py
# Server/NUMA GC Controller: 扩展 GCCycleController 支持每 NUMA 节点 GC 周期控制
from amaranth import *

class GCNumaCtrlDisabled(Elaboratable):
    """Disabled 实现: 单节点行为, 等价当前 GCCycleController.

    忽略 NUMA 拓扑, 所有节点同步执行同一 GC 周期.
    """
    def __init__(self, n_numa_nodes=1, local_node_id=0):
        self.n_numa_nodes = n_numa_nodes
        self.local_node_id = local_node_id

        self.start_cycle = Signal()
        self.cycle_active = Signal()
        self.phase = Signal(3)

        self.rs_start = Signal()
        self.rs_active = Signal()
        self.rs_done = Signal()
        self.rs_root_count = Signal(32)

        self.hw_start = Signal()
        self.hw_active = Signal()
        self.hw_done = Signal()
        self.hw_objects = Signal(32)

        self.scan_start = Signal()
        self.scan_active = Signal()
        self.scan_done = Signal()

        self.sweep_start = Signal()
        self.sweep_active = Signal()
        self.sweep_done = Signal()

        self.mv_start = Signal()
        self.mv_active = Signal()
        self.mv_done = Signal()
        self.mv_relocs = Signal(32)

        self.total_roots = Signal(32)
        self.total_objects = Signal(32)
        self.total_freed = Signal(32)
        self.total_relocs = Signal(32)
        self.cycle_count = Signal(32)
        self.cycle_ticks = Signal(32)

        self.epoch = Signal(8)
        self.epoch_advance = Signal()

        self.per_node_cycle_active = Signal(n_numa_nodes)
        self.per_node_cycle_done = Signal(n_numa_nodes)
        self.global_cycle_start = Signal()
        self.global_cycle_complete = Signal()

    def elaborate(self, platform):
        m = Module()

        PHASE_IDLE     = 0
        PHASE_ROOTS    = 1
        PHASE_HEAP     = 2
        PHASE_MARK     = 3
        PHASE_SWEEP    = 4
        PHASE_RELOCATE = 5
        PHASE_COMPLETE = 6

        tick_ctr = Signal(32)
        cyc_ctr  = Signal(32)

        m.d.comb += [
            self.rs_start.eq(self.cycle_active & (self.phase == PHASE_ROOTS)),
            self.hw_start.eq(self.cycle_active & (self.phase == PHASE_HEAP)),
            self.scan_start.eq(self.cycle_active & (self.phase == PHASE_MARK)),
            self.sweep_start.eq(self.cycle_active & (self.phase == PHASE_SWEEP)),
            self.mv_start.eq(self.cycle_active & (self.phase == PHASE_RELOCATE)),
        ]

        with m.If(self.start_cycle & ~self.cycle_active):
            m.d.sync += [
                self.cycle_active.eq(1),
                self.phase.eq(PHASE_ROOTS),
                tick_ctr.eq(0),
                cyc_ctr.eq(cyc_ctr + 1),
            ]

        with m.If(self.cycle_active):
            m.d.sync += tick_ctr.eq(tick_ctr + 1)

            with m.Switch(self.phase):
                with m.Case(PHASE_ROOTS):
                    with m.If(self.rs_done):
                        m.d.sync += [
                            self.phase.eq(PHASE_HEAP),
                            self.total_roots.eq(self.rs_root_count),
                        ]

                with m.Case(PHASE_HEAP):
                    with m.If(self.hw_done):
                        m.d.sync += [
                            self.phase.eq(PHASE_MARK),
                            self.total_objects.eq(self.hw_objects),
                        ]

                with m.Case(PHASE_MARK):
                    with m.If(self.scan_done):
                        m.d.sync += self.phase.eq(PHASE_SWEEP)

                with m.Case(PHASE_SWEEP):
                    with m.If(self.sweep_done):
                        m.d.sync += self.phase.eq(PHASE_RELOCATE)

                with m.Case(PHASE_RELOCATE):
                    with m.If(self.mv_done):
                        m.d.sync += [
                            self.phase.eq(PHASE_COMPLETE),
                            self.total_relocs.eq(self.mv_relocs),
                        ]

                with m.Case(PHASE_COMPLETE):
                    m.d.sync += [
                        self.cycle_active.eq(0),
                        self.cycle_ticks.eq(tick_ctr),
                        self.cycle_count.eq(cyc_ctr),
                        self.epoch.eq(self.epoch + 1),
                    ]

        m.d.comb += [
            self.global_cycle_start.eq(self.start_cycle),
            self.global_cycle_complete.eq(self.phase == PHASE_COMPLETE),
            self.epoch_advance.eq(self.phase == PHASE_COMPLETE),
        ]
        return m


class GCNumaCtrlEnabled(Elaboratable):
    """Enabled 实现: 多 NUMA 节点协调.

    广播 epoch, 每个节点独立执行 GC 周期的 root_scan → heap_walk → mark → sweep → relocate,
    通过 global_cycle_start 同步启动, global_cycle_complete 在所有节点完成后触发.
    per_node_cycle_active/done 反映各节点状态.
    """
    def __init__(self, n_numa_nodes=4, local_node_id=0):
        self.n_numa_nodes = n_numa_nodes
        self.local_node_id = local_node_id

        self.start_cycle = Signal()
        self.cycle_active = Signal()
        self.phase = Signal(3)

        self.rs_start = Signal()
        self.rs_active = Signal()
        self.rs_done = Signal()
        self.rs_root_count = Signal(32)

        self.hw_start = Signal()
        self.hw_active = Signal()
        self.hw_done = Signal()
        self.hw_objects = Signal(32)

        self.scan_start = Signal()
        self.scan_active = Signal()
        self.scan_done = Signal()

        self.sweep_start = Signal()
        self.sweep_active = Signal()
        self.sweep_done = Signal()

        self.mv_start = Signal()
        self.mv_active = Signal()
        self.mv_done = Signal()
        self.mv_relocs = Signal(32)

        self.total_roots = Signal(32)
        self.total_objects = Signal(32)
        self.total_freed = Signal(32)
        self.total_relocs = Signal(32)
        self.cycle_count = Signal(32)
        self.cycle_ticks = Signal(32)

        self.epoch = Signal(8)
        self.epoch_advance = Signal()

        self.per_node_cycle_active = Signal(n_numa_nodes)
        self.per_node_cycle_done = Signal(n_numa_nodes)
        self.global_cycle_start = Signal()
        self.global_cycle_complete = Signal()

    def elaborate(self, platform):
        m = Module()
        nn = self.n_numa_nodes
        lid = self.local_node_id

        PHASE_IDLE     = 0
        PHASE_ROOTS    = 1
        PHASE_HEAP     = 2
        PHASE_MARK     = 3
        PHASE_SWEEP    = 4
        PHASE_RELOCATE = 5
        PHASE_COMPLETE = 6

        tick_ctr = Signal(32)
        cyc_ctr  = Signal(32)

        node_done_bits = Cat(*[self.per_node_cycle_done[i] for i in range(nn)])
        all_done = Signal()
        m.d.comb += all_done.eq((self.phase == PHASE_COMPLETE) & node_done_bits.all())

        m.d.comb += [
            self.rs_start.eq(self.cycle_active & (self.phase == PHASE_ROOTS)),
            self.hw_start.eq(self.cycle_active & (self.phase == PHASE_HEAP)),
            self.scan_start.eq(self.cycle_active & (self.phase == PHASE_MARK)),
            self.sweep_start.eq(self.cycle_active & (self.phase == PHASE_SWEEP)),
            self.mv_start.eq(self.cycle_active & (self.phase == PHASE_RELOCATE)),
        ]

        with m.If(self.start_cycle & ~self.cycle_active):
            m.d.sync += [
                self.cycle_active.eq(1),
                self.phase.eq(PHASE_ROOTS),
                tick_ctr.eq(0),
                cyc_ctr.eq(cyc_ctr + 1),
            ]

        m.d.comb += self.global_cycle_start.eq(self.start_cycle & ~self.cycle_active)

        with m.If(self.cycle_active):
            m.d.sync += tick_ctr.eq(tick_ctr + 1)

            with m.Switch(self.phase):
                with m.Case(PHASE_ROOTS):
                    with m.If(self.rs_done):
                        m.d.sync += [
                            self.phase.eq(PHASE_HEAP),
                            self.total_roots.eq(self.rs_root_count),
                        ]

                with m.Case(PHASE_HEAP):
                    with m.If(self.hw_done):
                        m.d.sync += [
                            self.phase.eq(PHASE_MARK),
                            self.total_objects.eq(self.hw_objects),
                        ]

                with m.Case(PHASE_MARK):
                    with m.If(self.scan_done):
                        m.d.sync += self.phase.eq(PHASE_SWEEP)

                with m.Case(PHASE_SWEEP):
                    with m.If(self.sweep_done):
                        m.d.sync += self.phase.eq(PHASE_RELOCATE)

                with m.Case(PHASE_RELOCATE):
                    with m.If(self.mv_done):
                        m.d.sync += [
                            self.phase.eq(PHASE_COMPLETE),
                            self.total_relocs.eq(self.mv_relocs),
                        ]

                with m.Case(PHASE_COMPLETE):
                    with m.If(all_done):
                        m.d.sync += [
                            self.cycle_active.eq(0),
                            self.cycle_ticks.eq(tick_ctr),
                            self.cycle_count.eq(cyc_ctr),
                            self.epoch.eq(self.epoch + 1),
                        ]

        m.d.comb += self.epoch_advance.eq(all_done & (self.phase == PHASE_COMPLETE))
        m.d.comb += self.global_cycle_complete.eq(all_done & (self.phase == PHASE_COMPLETE))

        return m


def create_numa_ctrl(impl: str, **kwargs):
    if impl == "disabled":
        return GCNumaCtrlDisabled(**kwargs)
    elif impl == "enabled":
        return GCNumaCtrlEnabled(**kwargs)
    else:
        raise ValueError(f"Unknown numa_ctrl_impl: {impl}")
