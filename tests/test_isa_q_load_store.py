from amaranth import Elaboratable, Module
from amaranth.sim import Settle, Simulator, Tick

from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core


def flq(rd, rs1, imm):
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (0b100 << 12) | (rd << 7) | 0x07


def fsq(rs2, rs1, imm):
    uimm = imm & 0xFFF
    return (((uimm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) |
            (0b100 << 12) | ((uimm & 0x1F) << 7) | 0x27)


class QLoadStoreBench(Elaboratable):
    def __init__(self, extensions):
        self.core = RV12Core(xlen=32, extensions=extensions)
        program = [flq(1, 0, 0x100), fsq(1, 0, 0x120), 0x0000006F]
        self.imem = SimpleIMem(words=64, init=program + [0] * (64 - len(program)))
        source = [0] * 128
        self.payload_words = [0x89ABCDEF, 0x01234567, 0x00000001, 0x7FFF8000]
        source[0x100 // 4:0x100 // 4 + 4] = self.payload_words
        self.dmem = SimpleDMem(words=128, init=source)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = self.core
        m.submodules.imem = self.imem
        m.submodules.dmem = self.dmem
        m.d.comb += [
            self.imem.addr.eq(self.core.imem_addr),
            self.core.imem_rdata.eq(self.imem.rdata),
            self.dmem.req_valid.eq(self.core.dmem_valid),
            self.dmem.req_we.eq(self.core.dmem_we),
            self.dmem.req_addr.eq(self.core.dmem_addr),
            self.dmem.req_wdata.eq(self.core.dmem_wdata),
            self.core.dmem_rdata.eq(self.dmem.rsp_rdata),
        ]
        return m


def run_config(extensions):
    dut = QLoadStoreBench(extensions)
    writes = []
    diagnostics = {}
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        for _ in range(180):
            yield Settle()
            diagnostics.update({
                "recent_valid": (yield dut.core.dbg_q_recent_valid),
                "recent_rd": (yield dut.core.dbg_q_recent_rd),
                "recent_data": (yield dut.core.dbg_q_recent_data),
                "busy": (yield dut.core.dbg_q_mem_busy),
                "beat": (yield dut.core.dbg_q_mem_beat),
            })
            if (yield dut.core.dmem_valid) and (yield dut.core.dmem_we):
                address = (yield dut.core.dmem_addr)
                if 0x120 <= address < 0x130:
                    writes.append((address, (yield dut.core.dmem_wdata)))
            yield Tick()

    sim.add_process(process)
    sim.run()
    return dut, writes, diagnostics


def test_q_flq_fsq_execute_with_explicit_extension():
    dut, writes, diagnostics = run_config("RV32I+GC+Q")
    assert dut.core.enable_q
    assert writes == [(0x120 + index * 4, word)
                      for index, word in enumerate(dut.payload_words)], diagnostics


def test_q_flq_fsq_execute_with_star_extension():
    dut, writes, diagnostics = run_config("RV32I+GC+*")
    assert dut.core.enable_q
    assert writes == [(0x120 + index * 4, word)
                      for index, word in enumerate(dut.payload_words)], diagnostics
