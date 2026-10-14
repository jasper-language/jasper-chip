from amaranth import Elaboratable, Module, Mux, Signal


class QLoadStoreUnit(Elaboratable):
    """Four-beat FLQ/FSQ execution engine for the core's 32-bit data bus."""

    LOAD_FP = 0b0000111
    STORE_FP = 0b0100111
    WIDTH_Q = 0b100

    def __init__(self, xlen=32):
        if xlen not in (32, 64):
            raise ValueError("Q load/store supports RV32 and RV64")
        self.xlen = xlen

        self.enable = Signal()
        self.request_valid = Signal()
        self.request_ready = Signal()
        self.insn = Signal(32)
        self.rs1_value = Signal(xlen)
        self.fs2_value = Signal(128)

        self.busy = Signal()
        self.done = Signal()
        self.trap = Signal()
        self.decoded = Signal()
        self.illegal = Signal()

        self.fpr_write_valid = Signal()
        self.fpr_write_addr = Signal(5)
        self.fpr_write_data = Signal(128)

        self.mem_valid = Signal()
        self.mem_write = Signal()
        self.mem_addr = Signal(xlen)
        self.mem_wdata = Signal(32)
        self.mem_ready = Signal()
        self.mem_rdata = Signal(32)
        self.mem_fault = Signal()

    def elaborate(self, platform):
        m = Module()

        opcode = self.insn[0:7]
        funct3 = self.insn[12:15]
        is_flq = (opcode == self.LOAD_FP) & (funct3 == self.WIDTH_Q)
        is_fsq = (opcode == self.STORE_FP) & (funct3 == self.WIDTH_Q)
        is_q_mem = is_flq | is_fsq

        i_imm = self.insn[20:32].as_signed()
        s_imm = (self.insn[7:12] | (self.insn[25:32] << 5)).as_signed()
        selected_imm = Mux(is_fsq, s_imm, i_imm)
        effective_addr = self.rs1_value + selected_imm

        active = Signal()
        store = Signal()
        beat = Signal(2)
        base_addr = Signal(self.xlen)
        destination = Signal(5)
        store_payload = Signal(128)
        load_payload = Signal(128)

        m.d.comb += [
            self.decoded.eq(is_q_mem),
            self.illegal.eq(self.request_valid & is_q_mem & ~self.enable),
            self.request_ready.eq(~active),
            self.busy.eq(active),
            self.mem_valid.eq(active),
            self.mem_write.eq(active & store),
            self.mem_addr.eq(base_addr + (beat << 2)),
            self.mem_wdata.eq(store_payload.word_select(beat, 32)),
        ]

        m.d.sync += [
            self.done.eq(0),
            self.trap.eq(0),
            self.fpr_write_valid.eq(0),
        ]

        with m.If(self.request_valid & ~active & is_q_mem):
            with m.If(~self.enable | (effective_addr[0:2] != 0)):
                m.d.sync += [self.done.eq(1), self.trap.eq(1)]
            with m.Else():
                m.d.sync += [
                    active.eq(1),
                    store.eq(is_fsq),
                    beat.eq(0),
                    base_addr.eq(effective_addr),
                    destination.eq(self.insn[7:12]),
                    store_payload.eq(self.fs2_value),
                    load_payload.eq(0),
                ]

        with m.If(active & self.mem_ready):
            with m.If(self.mem_fault):
                m.d.sync += [active.eq(0), self.done.eq(1), self.trap.eq(1)]
            with m.Else():
                with m.If(~store):
                    m.d.sync += load_payload.word_select(beat, 32).eq(self.mem_rdata)
                with m.If(beat == 3):
                    m.d.sync += [active.eq(0), self.done.eq(1)]
                    with m.If(~store):
                        m.d.sync += [
                            self.fpr_write_valid.eq(1),
                            self.fpr_write_addr.eq(destination),
                            self.fpr_write_data.eq(
                                (load_payload & ((1 << 96) - 1))
                                | (self.mem_rdata << 96)
                            ),
                        ]
                with m.Else():
                    m.d.sync += beat.eq(beat + 1)

        return m
