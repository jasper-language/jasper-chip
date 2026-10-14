"""Complete RV32 Zcf and Zcd compressed floating-memory matrix."""

from amaranth import Elaboratable, Module
from amaranth.sim import Settle, Simulator, Tick

from rtl.isa import LOAD, LOAD_FP, OP_IMM, STORE_FP, enc_i
from rtl.isa_c_expand import CExpander
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def enc_s(opcode, funct3, rs1, rs2, imm):
    return ((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | ((imm & 0x1F) << 7) | opcode


def cl(funct3):
    return (funct3 << 13) | (0b111 << 10) | (2 << 7) | (0b11 << 5) | (1 << 2)


def ci_sp(funct3):
    return (funct3 << 13) | (1 << 12) | (9 << 7) | (0b11111 << 2) | 0b10


def css_sp(funct3):
    return (funct3 << 13) | (0b111111 << 7) | (9 << 2) | 0b10


def test_rv32_zcf_zcd_all_eight_standard_encodings_expand():
    dut = CExpander(xlen=32)
    sim = Simulator(dut)
    cases = [
        (cl(0b011), enc_i(LOAD_FP, 9, 0b010, 10, 0x7C)),
        (cl(0b111), enc_s(STORE_FP, 0b010, 10, 9, 0x7C)),
        (ci_sp(0b011), enc_i(LOAD_FP, 9, 0b010, 2, 0xFC)),
        (css_sp(0b111), enc_s(STORE_FP, 0b010, 2, 9, 0xFC)),
        (cl(0b001), enc_i(LOAD_FP, 9, 0b011, 10, 0xF8)),
        (cl(0b101), enc_s(STORE_FP, 0b011, 10, 9, 0xF8)),
        (ci_sp(0b001), enc_i(LOAD_FP, 9, 0b011, 2, 0x1F8)),
        (css_sp(0b101), enc_s(STORE_FP, 0b011, 2, 9, 0x1F8)),
    ]

    def process():
        yield dut.valid.eq(1)
        for compressed, expanded in cases:
            yield dut.insn16.eq(compressed)
            yield Settle()
            assert (yield dut.illegal) == 0
            assert (yield dut.insn32) == expanded

    sim.add_process(process)
    sim.run()


def test_zcf_zcd_explicit_and_star_configurations_enable_compressed_path():
    zcf = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+ZCF")
    zcd = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+ZCD")
    star = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+*")
    assert "C" in zcf.extensions
    assert "C" in zcd.extensions
    assert "C" in star.extensions


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def compressed_word(insn16):
    return insn16 | (0x0001 << 16)  # Requested instruction followed by C.NOP.


class _CompressedFloatingMemoryBench(Elaboratable):
    def __init__(self):
        gap = [nop()] * 4
        program = [
            enc_i(OP_IMM, 10, 0b000, 0, 0),
            compressed_word(cl(0b011)),               # C.FLW f9,124(x10)
            *gap,
            enc_i(OP_IMM, 10, 0b000, 0, 384),
            compressed_word(cl(0b111)),               # C.FSW f9,124(x10) -> 508
            *gap,
            enc_i(LOAD, 11, 0b010, 0, 508),
            enc_i(OP_IMM, 2, 0b000, 0, 256),
            compressed_word(ci_sp(0b011)),            # C.FLWSP f9,252(sp) <- 508
            *gap,
            enc_i(OP_IMM, 2, 0b000, 0, 640),
            compressed_word(css_sp(0b111)),           # C.FSWSP f9,252(sp) -> 892
            *gap,
            enc_i(LOAD, 12, 0b010, 0, 892),
            enc_i(OP_IMM, 10, 0b000, 0, 0),
            compressed_word(cl(0b001)),               # C.FLD f9,248(x10)
            *gap,
            enc_i(OP_IMM, 10, 0b000, 0, 512),
            compressed_word(cl(0b101)),               # C.FSD f9,248(x10) -> 760
            *gap,
            enc_i(LOAD, 13, 0b010, 0, 760),
            enc_i(LOAD, 14, 0b010, 0, 764),
            enc_i(OP_IMM, 2, 0b000, 0, 256),
            compressed_word(ci_sp(0b001)),            # C.FLDSP f9,504(sp) <- 760
            *gap,
            enc_i(OP_IMM, 2, 0b000, 0, 768),
            compressed_word(css_sp(0b101)),           # C.FSDSP f9,504(sp) -> 1272
            *gap,
            enc_i(LOAD, 15, 0b010, 0, 1272),
            *gap,
            enc_i(LOAD, 16, 0b010, 0, 1276),
        ]
        program += [nop()] * (256 - len(program))
        data = [0] * 512
        data[31] = 0x3FC00000
        data[62] = 0x09ABCDEF
        data[63] = 0x01234567

        self.core = RV12Core(core_id=0, xlen=32, rb_mode=1, extensions="RV32I+GC")
        self.imem = SimpleIMem(words=256, init=program)
        self.dmem = SimpleDMem(words=512, init=data)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.d.comb += [
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
            dm.req_valid.eq(c.dmem_valid),
            dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
            c.gc_enq_ready.eq(1),
            c.gc_rsp_valid.eq(0),
            c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0),
            c.wb_enq_ready.eq(1),
            c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0),
            c.mv_rsp_tag.eq(0),
            c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),
        ]
        return m


def test_rv32_gc_executes_all_zcf_zcd_compressed_memory_forms():
    dut = _CompressedFloatingMemoryBench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    results = {}

    def process():
        for _ in range(600):
            yield Tick()
        for reg in range(11, 17):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            results[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    assert results == {
        11: 0x3FC00000,
        12: 0x3FC00000,
        13: 0x09ABCDEF,
        14: 0x01234567,
        15: 0x09ABCDEF,
        16: 0x01234567,
    }
