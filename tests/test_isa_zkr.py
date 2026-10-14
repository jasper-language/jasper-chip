import pytest
from amaranth import Elaboratable, Module
from amaranth.hdl import Fragment
from amaranth.sim import Settle, Simulator, Tick

from rtl.isa import OP_IMM, SYSTEM, enc_i
from rtl.isa_zkr import Zkr
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core, normalize_extension_spec


@pytest.mark.parametrize("valid,entropy,expected", [
    (0, 0x0000, 0x40000000),
    (1, 0x0000, 0x80000000),
    (1, 0xBEEF, 0x8000BEEF),
])
def test_seed_csr_returns_wait_or_es16(valid, entropy, expected):
    dut = Zkr(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(SYSTEM)
        yield dut.imm.eq(0x015)
        yield dut.funct3.eq(0b010)
        yield dut.rs1.eq(0)
        yield dut.entropy_valid.eq(valid)
        yield dut.entropy.eq(entropy)
        yield Settle()
        assert (yield dut.matched) == 1
        assert (yield dut.wb_en) == 1
        assert (yield dut.wb_data) == expected
        assert (yield dut.trap) == 0

    sim.add_process(process)
    sim.run()


@pytest.mark.parametrize("funct3,rs1", [(0b001, 0), (0b010, 1), (0b101, 0), (0b110, 0)])
def test_seed_csr_rejects_write_capable_accesses(funct3, rs1):
    dut = Zkr(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(SYSTEM)
        yield dut.imm.eq(0x015)
        yield dut.funct3.eq(funct3)
        yield dut.rs1.eq(rs1)
        yield Settle()
        assert (yield dut.matched) == 1
        assert (yield dut.wb_en) == 0
        assert (yield dut.trap) == 1

    sim.add_process(process)
    sim.run()


class _SeedBench(Elaboratable):
    def __init__(self, entropy_valid, entropy):
        program = [
            enc_i(SYSTEM, 1, 0b010, 0, 0x015),
            enc_i(OP_IMM, 2, 0b000, 0, 7),
        ]
        program += [enc_i(OP_IMM, 0, 0, 0, 0)] * (128 - len(program))
        self.core = RV12Core(xlen=32, extensions="RV32I+GC+ZKR")
        self.imem = SimpleIMem(words=128, init=program)
        self.dmem = SimpleDMem(words=16)
        self.entropy_valid = entropy_valid
        self.entropy = entropy

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.d.comb += [
            im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
            dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata), c.gc_enq_ready.eq(1),
            c.gc_rsp_valid.eq(0), c.gc_rsp_tag.eq(0), c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1), c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0), c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0), c.seed_entropy_valid.eq(self.entropy_valid),
            c.seed_entropy.eq(self.entropy),
        ]
        return m


@pytest.mark.parametrize("valid,entropy,expected", [
    (0, 0x0000, 0x40000000),
    (1, 0xCAFE, 0x8000CAFE),
])
def test_seed_csr_executes_through_core_pipeline(valid, entropy, expected):
    dut = _SeedBench(valid, entropy)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        for _ in range(120):
            yield Tick()
        yield dut.core.dbg_reg_addr.eq(1)
        yield Tick()
        assert (yield dut.core.dbg_reg_rdata) == expected
        yield dut.core.dbg_reg_addr.eq(2)
        yield Tick()
        assert (yield dut.core.dbg_reg_rdata) == 7

    sim.add_process(process)
    sim.run()


def test_zkr_is_retained_and_star_core_elaborates():
    assert "ZKR" in normalize_extension_spec("RV32I+GC+ZKR")
    assert "ZKR" in normalize_extension_spec("RV32I+GC+*")
    core = RV12Core(xlen=32, extensions="RV32I+GC+*")
    assert core.enable_zkr
    Fragment.get(core, platform=None)
