import pytest
from amaranth import Elaboratable, Module, Signal
from amaranth.sim import Settle, Simulator

from rtl.base_rd_write_control import BaseRDWriteControl
from rtl.base_rs1_usage_control import BaseRS1UsageControl
from rtl.dependency_stall_control import DependencyStallControl
from rtl.isa import JALR
from rtl.jump_control import JumpControl
from rtl.pending_mask_control import PendingMaskControl
from rtl.pending_register_hazard import PendingRegisterHazard


class JALRDependencyHarness(Elaboratable):
    def __init__(self, xlen):
        self.xlen = xlen
        self.pc = Signal(xlen)
        self.base = Signal(xlen)
        self.imm = Signal(xlen)
        self.compressed = Signal()
        self.rs1 = Signal(5)
        self.rd = Signal(5)
        self.pending_mask = Signal(32)
        self.clear_valid = Signal()
        self.clear_rd = Signal(5)
        self.duplicate = Signal()
        self.fp_store_hazard = Signal()
        self.link = Signal(xlen)
        self.target = Signal(xlen)
        self.visible_mask = Signal(32)
        self.id1_stall = Signal()
        self.id2_stall = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.rs1_usage = rs1_usage = BaseRS1UsageControl()
        m.submodules.rd_write = rd_write = BaseRDWriteControl()
        m.submodules.mask = mask = PendingMaskControl(clear_ports=1)
        m.submodules.hazard = hazard = PendingRegisterHazard()
        m.submodules.id1_stall = id1_stall = DependencyStallControl()
        m.submodules.id2_stall = id2_stall = DependencyStallControl()
        m.submodules.jump = jump = JumpControl(self.xlen)

        m.d.comb += [
            rs1_usage.valid.eq(1),
            rs1_usage.is_jal.eq(0),
            rs1_usage.is_fence.eq(0),
            rd_write.opcode.eq(JALR),
            rd_write.integer_load.eq(0),
            rd_write.is_jal.eq(0),
            rd_write.enable_a.eq(0),
            mask.pending_mask.eq(self.pending_mask),
            mask.clear_valid[0].eq(self.clear_valid),
            mask.clear_rd[0].eq(self.clear_rd),
            self.visible_mask.eq(mask.visible_mask),
            hazard.uses_rs1.eq(rs1_usage.uses_rs1),
            hazard.uses_rs2.eq(0),
            hazard.writes_rd.eq(rd_write.writes_rd & (self.rd != 0)),
            hazard.rs1.eq(self.rs1),
            hazard.rs2.eq(0),
            hazard.rd.eq(self.rd),
            hazard.pending_mask.eq(mask.visible_mask),
            id1_stall.rs1_hazard.eq(hazard.rs1_hazard),
            id1_stall.rs2_hazard.eq(0),
            id1_stall.waw_hazard.eq(hazard.waw_hazard),
            id1_stall.include_waw.eq(1),
            id1_stall.suppress_integer.eq(0),
            id1_stall.fp_store_hazard.eq(self.fp_store_hazard),
            id2_stall.rs1_hazard.eq(hazard.rs1_hazard),
            id2_stall.rs2_hazard.eq(0),
            id2_stall.waw_hazard.eq(hazard.waw_hazard),
            id2_stall.include_waw.eq(0),
            id2_stall.suppress_integer.eq(self.duplicate),
            id2_stall.fp_store_hazard.eq(self.fp_store_hazard),
            self.id1_stall.eq(id1_stall.stall),
            self.id2_stall.eq(id2_stall.stall),
            jump.pc.eq(self.pc),
            jump.base.eq(self.base),
            jump.imm.eq(self.imm),
            jump.compressed.eq(self.compressed),
            jump.jalr.eq(1),
            self.link.eq(jump.link),
            self.target.eq(jump.target),
        ]
        return m


@pytest.mark.parametrize("xlen", [32, 64])
def test_jalr_dependency_and_address_equivalence(xlen):
    dut = JALRDependencyHarness(xlen)
    sim = Simulator(dut)
    mask = (1 << xlen) - 1
    addresses = (0, 1, mask, 1 << (xlen - 1))
    registers = (0, 1, 31)

    def proc():
        for compressed in (0, 1):
            yield dut.compressed.eq(compressed)
            for rs1 in registers:
                yield dut.rs1.eq(rs1)
                yield dut.clear_rd.eq(rs1)
                for rd in registers:
                    yield dut.rd.eq(rd)
                    pending_values = {
                        0, 1 << rs1, 1 << rd, (1 << rs1) | (1 << rd)
                    }
                    for pending in pending_values:
                        yield dut.pending_mask.eq(pending)
                        for clear, duplicate, fp_hazard in (
                                (0, 0, 0), (0, 1, 0), (1, 0, 0),
                                (1, 1, 0), (0, 0, 1), (1, 1, 1)):
                            yield dut.clear_valid.eq(clear)
                            yield dut.duplicate.eq(duplicate)
                            yield dut.fp_store_hazard.eq(fp_hazard)
                            for pc, base, imm in zip(
                                    addresses, reversed(addresses), addresses):
                                yield dut.pc.eq(pc)
                                yield dut.base.eq(base)
                                yield dut.imm.eq(imm)
                                yield Settle()
                                visible = pending & ~(1 << rs1) if clear else pending
                                raw = bool(rs1 != 0 and visible & (1 << rs1))
                                waw = bool(rd != 0 and visible & (1 << rd))
                                assert (yield dut.visible_mask) == visible
                                assert bool((yield dut.id1_stall)) == bool(
                                    raw or waw or fp_hazard
                                )
                                assert bool((yield dut.id2_stall)) == bool(
                                    (raw and not duplicate) or fp_hazard
                                )
                                assert (yield dut.link) == (
                                    pc + (2 if compressed else 4)
                                ) & mask
                                assert (yield dut.target) == (
                                    ((base + imm) & mask) & ~1
                                )

    sim.add_process(proc)
    sim.run()
