"""Executable Svinval invalidation and ordering-fence closure."""

import pytest
from amaranth import Elaboratable, Module
from amaranth.sim import Delay, Simulator, Tick

from rtl.isa import OP_IMM, SYSTEM, enc_i
from rtl.isa_svinval import Svinval
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


EXTENSIONS = ("RV32I+GC+SVINVAL", "RV32I+GC+*")


def nop():
    return enc_i(OP_IMM, 0, 0, 0, 0)


def sinval_vma(rs1, rs2):
    return ((0b0001011 << 25) | ((rs2 & 0x1F) << 20) |
            ((rs1 & 0x1F) << 15) | SYSTEM)


def sfence_w_inval():
    return (0x180 << 20) | SYSTEM


def sfence_inval_ir():
    return (0x181 << 20) | SYSTEM


class _SvinvalBench(Elaboratable):
    def __init__(self, extensions):
        program = [
            enc_i(OP_IMM, 1, 0, 0, 0x120),
            enc_i(OP_IMM, 2, 0, 0, 3),
            sfence_w_inval(),
            sinval_vma(1, 2),
            sinval_vma(0, 0),
            sfence_inval_ir(),
            enc_i(OP_IMM, 20, 0, 0, 0x55),
            0x0000006F,
        ]
        program += [nop()] * (48 - len(program))
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


def run(extensions):
    dut = _SvinvalBench(extensions)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}
    events = []

    def process():
        trap_cycles = 0
        for _ in range(320):
            if (yield dut.core.trap):
                trap_cycles += 1
            if (yield dut.core.svinval_valid):
                events.append((
                    (yield dut.core.svinval_vaddr),
                    (yield dut.core.svinval_asid),
                    (yield dut.core.svinval_vaddr_valid),
                    (yield dut.core.svinval_asid_valid),
                    (yield dut.core.svinval_ordered),
                ))
            yield Tick()
        yield dut.core.dbg_reg_addr.eq(20)
        yield Tick()
        result.update(
            x20=(yield dut.core.dbg_reg_rdata),
            sinval=(yield dut.core.dbg_sinval_vma_count),
            write_fence=(yield dut.core.dbg_sfence_w_inval_count),
            read_fence=(yield dut.core.dbg_sfence_inval_ir_count),
            epoch=(yield dut.core.svinval_epoch),
            completion_epoch=(yield dut.core.svinval_completion_epoch),
            barrier_active=(yield dut.core.svinval_barrier_active),
            events=events,
            traps=trap_cycles,
        )

    sim.add_process(process)
    sim.run()
    return result


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_svinval_sequence_executes_in_explicit_and_star(extensions):
    assert run(extensions) == {
        "x20": 0x55,
        "sinval": 2,
        "write_fence": 1,
        "read_fence": 1,
        "epoch": 2,
        "completion_epoch": 2,
        "barrier_active": 0,
        "events": [(0x120, 3, 1, 1, 1), (0, 0, 0, 0, 1)],
        "traps": 0,
    }


def test_svinval_disabled_traps_without_execution():
    result = run("RV32I+GC")
    assert result["x20"] == 0x55
    assert result["sinval"] == 0
    assert result["write_fence"] == 0
    assert result["read_fence"] == 0
    assert result["epoch"] == 0
    assert result["events"] == []
    assert result["traps"] >= 4


def test_svinval_decoder_rejects_reserved_fixed_fields():
    dut = Svinval(xlen=32)
    sim = Simulator(dut)

    def process():
        yield dut.valid.eq(1)
        yield dut.opcode.eq(SYSTEM)
        yield dut.funct3.eq(0)

        yield dut.funct7.eq(0b0001011)
        yield dut.rd.eq(0)
        yield Delay(1e-6)
        assert (yield dut.matched) == 1
        yield dut.rd.eq(1)
        yield Delay(1e-6)
        assert (yield dut.matched) == 0

        yield dut.funct7.eq(0b0001100)
        yield dut.rd.eq(0)
        yield dut.rs1.eq(0)
        yield dut.rs2.eq(0)
        yield dut.imm.eq(0x180)
        yield Delay(1e-6)
        assert (yield dut.matched) == 1
        yield dut.rs1.eq(1)
        yield Delay(1e-6)
        assert (yield dut.matched) == 0

        yield dut.rs1.eq(0)
        yield dut.imm.eq(0x182)
        yield Delay(1e-6)
        assert (yield dut.matched) == 0

    sim.add_process(process)
    sim.run()
