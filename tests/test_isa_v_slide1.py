import pytest

from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.isa import OP_IMM, OP_V, enc_i
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def lui(rd, imm20):
    return (imm20 << 12) | (rd << 7) | 0b0110111


def vsetivli(rd, avl, vtypei):
    return ((0b11 << 30) | (vtypei << 20) | (avl << 15) |
            (0b111 << 12) | (rd << 7) | OP_V)


def vmv_s_x(vd, rs1):
    return ((0b010000 << 26) | (1 << 25) | (rs1 << 15) |
            (0b110 << 12) | (vd << 7) | OP_V)


def vmv_x_s(rd, vs2):
    return ((0b010000 << 26) | (1 << 25) | (vs2 << 20) |
            (0b010 << 12) | (rd << 7) | OP_V)


def slide1(vd, vs2, rs1, down=False, vm=1):
    funct6 = 0b001111 if down else 0b001110
    return ((funct6 << 26) | (vm << 25) | (vs2 << 20) | (rs1 << 15) |
            (0b110 << 12) | (vd << 7) | OP_V)


def csrrwi(csr, zimm):
    return ((csr << 20) | (zimm << 15) | (0b101 << 12) | 0b1110011)


class Bench(Elaboratable):
    def __init__(self, program, extensions):
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=16, init=[0] * 16)

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
            c.mv_rsp_data.eq(0),
        ]
        return m


def program():
    instructions = [
        vsetivli(0, 1, 0b010000),
        lui(10, 0x04030),
        enc_i(OP_IMM, 10, 0b000, 10, 0x201),
        vmv_s_x(2, 10),
        lui(12, 0x09091),
        enc_i(OP_IMM, 12, 0b000, 12, -0x6F7),
        vmv_s_x(6, 12),
        vmv_s_x(7, 12),
        vmv_s_x(8, 12),
        vmv_s_x(9, 12),
        vmv_s_x(10, 12),
        vmv_s_x(11, 12),
        vsetivli(0, 4, 0),
        enc_i(OP_IMM, 18, 0b000, 0, 0x7F),
        enc_i(OP_IMM, 11, 0b000, 0, 0x5),
        vmv_s_x(0, 11),
    ]
    instructions += [nop()] * 3
    instructions += [
        slide1(4, 2, 18),
        slide1(5, 2, 18, down=True),
        slide1(6, 2, 18, vm=0),
        slide1(7, 2, 18, down=True, vm=0),
        csrrwi(0x008, 2),
        slide1(8, 2, 18),
        csrrwi(0x008, 2),
        slide1(9, 2, 18, down=True),
        slide1(10, 2, 18, down=True),
        vsetivli(0, 0, 0),
        slide1(11, 2, 18),
        vsetivli(0, 1, 0b010000),
        vmv_x_s(20, 4),
        vmv_x_s(21, 5),
        vmv_x_s(22, 6),
        vmv_x_s(23, 7),
        vmv_x_s(24, 8),
        vmv_x_s(25, 9),
        vmv_x_s(26, 10),
        vmv_x_s(27, 11),
    ]
    instructions += [0x0000006F]
    instructions += [nop()] * (128 - len(instructions))
    return instructions


def run(extensions):
    bench = Bench(program(), extensions)
    sim = Simulator(bench)
    sim.add_clock(1e-6)
    result = {}

    def process():
        for _ in range(1100):
            yield Tick()
        for register in range(20, 28):
            yield bench.core.dbg_reg_addr.eq(register)
            yield Tick()
            result[register] = yield bench.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", ["RV32I+GC+V", "RV32I+GC+*"])
def test_vslide1_scalar_semantics(extensions):
    result = run(extensions)
    assert result[20] == 0x0302017F
    assert result[21] == 0x7F040302
    assert result[22] == 0x0902097F
    assert result[23] == 0x09040902
    assert result[24] == 0x03020909
    assert result[25] == 0x7F040909
    assert result[26] == 0x7F040302
    assert result[27] == 0x09090909


def test_vslide1_requires_v_extension():
    assert run("RV32I+GC") == {register: 0 for register in range(20, 28)}
