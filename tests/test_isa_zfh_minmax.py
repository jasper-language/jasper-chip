from pathlib import Path
import importlib.util

import pytest


_runtime_path = Path(__file__).with_name("test_extension_star_runtime.py")
_runtime_spec = importlib.util.spec_from_file_location("jasper_extension_runtime_minmax", _runtime_path)
runtime = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(runtime)


def _li(rd, value):
    upper = (value + 0x800) >> 12
    low = (value - (upper << 12)) & 0xfff
    return [
        runtime.enc_u(runtime.LUI, rd, upper),
        runtime.enc_i(runtime.OP_IMM, rd, 0b000, rd, low),
    ]


def _run_half_minmax_case(extensions):
    prog = []
    for reg, value in enumerate((0x0000, 0x8000, 0x7e01, 0x7d01, 0x3c00, 0xc000), 1):
        prog += _li(reg, value)
        prog.append(runtime.enc_r(runtime.OP_FP, reg, 0b000, reg, 0, 0b1111010))

    cases = (
        (7, 0b000, 1, 2),   # min(+0,-0) = -0
        (8, 0b001, 1, 2),   # max(+0,-0) = +0
        (9, 0b000, 3, 5),   # min(qNaN,+1) = +1
        (10, 0b001, 6, 3),  # max(-2,qNaN) = -2
        (11, 0b000, 4, 5),  # min(sNaN,+1) = +1, NV
        (12, 0b001, 3, 3),  # max(qNaN,qNaN) = canonical qNaN
        (13, 0b000, 6, 5),  # min(-2,+1) = -2
        (14, 0b001, 6, 5),  # max(-2,+1) = +1
    )
    for fd, funct3, fs1, fs2 in cases:
        prog.append(runtime.enc_r(runtime.OP_FP, fd, funct3, fs1, fs2, 0b0010110))
    for index, fd in enumerate(range(7, 15), 15):
        prog.append(runtime.enc_r(runtime.OP_FP, index, 0b000, fd, 0, 0b1110010))
    prog.append((0x001 << 20) | (0b010 << 12) | (23 << 7) | 0x73)  # CSRRS x23,fflags,x0
    prog.append(runtime.nop())

    imem_words = 96
    prog += [runtime.nop()] * (imem_words - len(prog))

    class _HalfMinmaxBench(runtime.Elaboratable):
        def __init__(self):
            self.core = runtime.RV12Core(core_id=0, xlen=32, extensions=extensions)
            self.imem = runtime.SimpleIMem(words=imem_words, init=prog)
            self.dmem = runtime.SimpleDMem(words=16)

        def elaborate(self, platform):
            m = runtime.Module()
            m.submodules.core = c = self.core
            m.submodules.imem = im = self.imem
            m.submodules.dmem = dm = self.dmem
            m.d.comb += [
                im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
                dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
                dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
                c.dmem_rdata.eq(dm.rsp_rdata), c.gc_enq_ready.eq(0),
                c.gc_rsp_valid.eq(0), c.gc_rsp_tag.eq(0), c.gc_rsp_rd.eq(0),
                c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1), c.mv_cmd_ready.eq(1),
                c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0), c.mv_rsp_rd.eq(0),
                c.mv_rsp_data.eq(0),
            ]
            return m

    dut = _HalfMinmaxBench()
    sim = runtime.Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def proc():
        for _ in range(500):
            yield runtime.Tick()
        for reg in range(15, 24):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield runtime.Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return tuple(result[reg] for reg in range(15, 24))


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_minmax_nan_zero_ordering_and_flags(extensions):
    assert _run_half_minmax_case(extensions) == (
        0xffff8000, 0x00000000, 0x00003c00, 0xffffc000,
        0x00003c00, 0x00007e00, 0xffffc000, 0x00003c00,
        0b10000,
    )
