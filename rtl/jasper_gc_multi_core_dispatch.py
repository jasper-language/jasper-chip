from amaranth import *


class MultiCoreDispatch(Elaboratable):
    """Distributes commands across N accelerator cores using round-robin demux."""
    def __init__(self, config, num_cores=2, policy="ROUND_ROBIN"):
        self.num_cores = num_cores
        self.policy = policy

        self.cmd_valid = Signal()
        self.cmd_ready = Signal()
        self.cmd_correlation_id = Signal(16)

        self.comp_valid = Signal()
        self.comp_ready = Signal()
        self.comp_correlation_id = Signal(16)

        for i in range(num_cores):
            setattr(self, f'core{i}_cmd_valid', Signal())
            setattr(self, f'core{i}_cmd_ready', Signal())
            setattr(self, f'core{i}_cmd_correlation_id', Signal(16))
            setattr(self, f'core{i}_comp_valid', Signal())
            setattr(self, f'core{i}_comp_ready', Signal())
            setattr(self, f'core{i}_comp_correlation_id', Signal(16))

    def elaborate(self, platform):
        m = Module()

        rr = Signal(range(self.num_cores))

        for i in range(self.num_cores):
            m.d.comb += getattr(self, f'core{i}_cmd_valid').eq(0)
            m.d.comb += getattr(self, f'core{i}_comp_ready').eq(self.comp_ready)

        if self.num_cores == 2:
            sel = Signal()
            m.d.comb += sel.eq(
                Mux(rr, Mux(self.core1_cmd_ready, 1,
                        Mux(self.core0_cmd_ready, 0, 0)),
                        Mux(self.core0_cmd_ready, 0,
                        Mux(self.core1_cmd_ready, 1, 0))))
            any_ready = self.core0_cmd_ready | self.core1_cmd_ready
            m.d.comb += self.cmd_ready.eq(
                self.cmd_valid & any_ready)
            with m.If(self.cmd_valid & any_ready):
                with m.If(sel == 0):
                    m.d.comb += self.core0_cmd_valid.eq(1)
                    m.d.comb += self.core0_cmd_correlation_id.eq(
                        self.cmd_correlation_id)
                with m.Else():
                    m.d.comb += self.core1_cmd_valid.eq(1)
                    m.d.comb += self.core1_cmd_correlation_id.eq(
                        self.cmd_correlation_id)
                m.d.sync += rr.eq((sel + 1) % 2)
        elif self.num_cores == 4:
            free_bus = Cat(self.core0_cmd_ready, self.core1_cmd_ready,
                           self.core2_cmd_ready, self.core3_cmd_ready)
            any_ready = free_bus != 0
            m.d.comb += self.cmd_ready.eq(self.cmd_valid & any_ready)
            sel = Signal(range(4))
            with m.Switch(rr):
                with m.Case(0):
                    m.d.comb += sel.eq(Mux(self.core0_cmd_ready, 0,
                        Mux(self.core1_cmd_ready, 1,
                        Mux(self.core2_cmd_ready, 2,
                        Mux(self.core3_cmd_ready, 3, 0)))))
                with m.Case(1):
                    m.d.comb += sel.eq(Mux(self.core1_cmd_ready, 1,
                        Mux(self.core2_cmd_ready, 2,
                        Mux(self.core3_cmd_ready, 3,
                        Mux(self.core0_cmd_ready, 0, 1)))))
                with m.Case(2):
                    m.d.comb += sel.eq(Mux(self.core2_cmd_ready, 2,
                        Mux(self.core3_cmd_ready, 3,
                        Mux(self.core0_cmd_ready, 0,
                        Mux(self.core1_cmd_ready, 1, 2)))))
                with m.Case(3):
                    m.d.comb += sel.eq(Mux(self.core3_cmd_ready, 3,
                        Mux(self.core0_cmd_ready, 0,
                        Mux(self.core1_cmd_ready, 1,
                        Mux(self.core2_cmd_ready, 2, 3)))))
            with m.If(self.cmd_valid & any_ready):
                for idx in range(4):
                    with m.If(sel == idx):
                        m.d.comb += getattr(self, f'core{idx}_cmd_valid').eq(1)
                        m.d.comb += getattr(self, f'core{idx}_cmd_correlation_id'
                            ).eq(self.cmd_correlation_id)
                m.d.sync += rr.eq((sel + 1) % 4)
        else:
            m.d.comb += self.cmd_ready.eq(0)

        for i in range(self.num_cores):
            cv = getattr(self, f'core{i}_comp_valid')
            cid = getattr(self, f'core{i}_comp_correlation_id')
            with m.If(cv):
                m.d.comb += self.comp_valid.eq(1)
                m.d.comb += self.comp_correlation_id.eq(cid)
        return m
