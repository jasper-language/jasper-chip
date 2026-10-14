from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.mem import RRArbiter, SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core
from tests.test_extension_star_runtime import (
    LOAD, LOAD_FP, OP_IMM, STORE, STORE_FP, enc_i, enc_s, nop,
)


def _load_u64(rd, value):
    octets = [(value >> shift) & 0xFF for shift in range(56, -1, -8)]
    program = [enc_i(OP_IMM, rd, 0b000, 0, octets[0])]
    for octet in octets[1:]:
        program.extend([
            enc_i(OP_IMM, rd, 0b001, rd, 8),
            enc_i(OP_IMM, rd, 0b110, rd, octet),
        ])
    return program


def test_rv64_ld_sd_execute_as_two_32_bit_beats():
    value = 0x0123456789ABCDEF
    program = [
        enc_i(OP_IMM, 1, 0b000, 0, 8),
        *_load_u64(2, value),
        enc_s(STORE, 0b011, 1, 2, 0),
        enc_i(LOAD, 3, 0b011, 1, 0),
        nop(),
    ]
    program += [nop()] * (256 - len(program))

    class Bench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC")
            self.imem = SimpleIMem(words=256, init=program)
            self.dmem = SimpleDMem(words=16, init=[0] * 16)

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
                c.dmem_grant.eq(1),
                c.gc_enq_ready.eq(0),
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

    dut = Bench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []
    result = {}

    def process():
        for _ in range(180):
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                writes.append(((yield dut.core.dmem_addr),
                               (yield dut.core.dmem_wdata)))
            yield Tick()
        yield dut.core.dbg_reg_addr.eq(3)
        yield Tick()
        result["x3"] = yield dut.core.dbg_reg_rdata

    sim.add_process(process)
    sim.run()
    assert writes == [(8, 0x89ABCDEF), (12, 0x01234567)]
    assert result["x3"] == value


def test_rr_arbiter_holds_owner_until_lock_release():
    dut = RRArbiter(2)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    grants = []

    def process():
        yield dut.m_valid[0].eq(1)
        yield dut.m_lock[0].eq(1)
        yield Tick()
        grants.append(((yield dut.m_grant[0]), (yield dut.m_grant[1])))

        yield dut.m_valid[1].eq(1)
        for _ in range(3):
            yield Tick()
            grants.append(((yield dut.m_grant[0]), (yield dut.m_grant[1])))

        yield dut.m_lock[0].eq(0)
        yield dut.m_valid[0].eq(0)
        yield Tick()
        yield Tick()
        grants.append(((yield dut.m_grant[0]), (yield dut.m_grant[1])))

    sim.add_process(process)
    sim.run()
    assert grants[:4] == [(1, 0)] * 4
    assert grants[-1] == (0, 1)


def test_fld_fsd_preserve_all_64_payload_bits():
    payload = 0xFEDCBA9876543210
    program = [
        enc_i(OP_IMM, 1, 0b000, 0, 0),
        enc_i(LOAD_FP, 2, 0b011, 1, 0),
        enc_i(OP_IMM, 1, 0b000, 0, 8),
        enc_s(STORE_FP, 0b011, 1, 2, 0),
        nop(),
    ]
    program += [nop()] * (256 - len(program))

    class Bench(Elaboratable):
        def __init__(self):
            self.core = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC+D")
            self.imem = SimpleIMem(words=256, init=program)
            self.dmem = SimpleDMem(
                words=16,
                init=[payload & 0xFFFFFFFF, (payload >> 32) & 0xFFFFFFFF] + [0] * 14,
            )

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
                c.dmem_grant.eq(1),
                c.gc_enq_ready.eq(0),
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

    dut = Bench()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    writes = []
    result = {}

    def process():
        for _ in range(180):
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                writes.append(((yield dut.core.dmem_addr),
                               (yield dut.core.dmem_wdata)))
            yield Tick()
        yield dut.core.dbg_freg_addr.eq(2)
        yield Tick()
        result["f2"] = yield dut.core.dbg_freg_rdata

    sim.add_process(process)
    sim.run()
    assert result["f2"] == payload
    assert writes == [(8, 0x76543210), (12, 0xFEDCBA98)]
