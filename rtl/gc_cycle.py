# rtl/gc_cycle.py
# GC cycle closure: 协调 根扫描 → 堆遍历 → 标记 → 清扫 → 搬迁 完整 GC 周期
from amaranth import *
from amaranth.lib.fifo import SyncFIFO

class GCCycleController(Elaboratable):
    """GC cycle controller.

    Orchestrates a complete GC cycle:
      1. Acquire roots (from GCRootScanner)
      2. Walk heap (from GcHeapWalker)
      3. Mark/scan (from GCScanCoProc)
      4. Sweep (from GCSweepCoProc)
      5. Relocate (from GCMoveCoProc)

    States:
      IDLE → ROOT_SCAN → HEAP_WALK → MARK → SWEEP → RELOCATE → COMPLETE

    Each phase activates the relevant coprocessor and waits for it to complete.
    """
    def __init__(self):
        # Control signals for each coprocessor
        self.start_cycle = Signal()
        self.cycle_active = Signal()
        self.phase = Signal(3)

        # Root scanner control
        self.rs_start = Signal()
        self.rs_active = Signal()
        self.rs_done = Signal()
        self.rs_root_count = Signal(32)

        # Heap walker control
        self.hw_start = Signal()
        self.hw_active = Signal()
        self.hw_done = Signal()
        self.hw_objects = Signal(32)

        # Scan coprocessor control
        self.scan_start = Signal()
        self.scan_active = Signal()
        self.scan_done = Signal()

        # Sweep coprocessor control
        self.sweep_start = Signal()
        self.sweep_active = Signal()
        self.sweep_done = Signal()

        # Relocate/Move coprocessor control
        self.mv_start = Signal()
        self.mv_active = Signal()
        self.mv_done = Signal()
        self.mv_relocs = Signal(32)

        # Cycle statistics
        self.total_roots = Signal(32)
        self.total_objects = Signal(32)
        self.total_freed = Signal(32)
        self.total_relocs = Signal(32)
        self.cycle_count = Signal(32)
        self.cycle_ticks = Signal(32)
        # Epoch broadcast (shared)
        self.epoch = Signal(8)
        self.epoch_advance = Signal()
        # Per-core cycle done flags

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
            self.epoch_advance.eq(1),
            self.epoch.eq(self.epoch + 1),
                    ]



        return m
