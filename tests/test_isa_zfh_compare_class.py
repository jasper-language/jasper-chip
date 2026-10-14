from pathlib import Path
import importlib.util

import pytest


_runtime_path = Path(__file__).with_name("test_extension_star_runtime.py")
_runtime_spec = importlib.util.spec_from_file_location("jasper_extension_runtime_hcmp", _runtime_path)
runtime = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(runtime)


def _li(rd, value):
    upper = (value + 0x800) >> 12
    low = (value - (upper << 12)) & 0xfff
    return [runtime.enc_u(runtime.LUI, rd, upper), runtime.enc_i(runtime.OP_IMM, rd, 0, rd, low)]


def _run(extensions, prog, registers, cycles=600):
    imem_words = 128
    prog = prog + [runtime.nop()] * (imem_words - len(prog))

    class _Bench(runtime.Elaboratable):
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

    dut = _Bench()
    sim = runtime.Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def proc():
        for _ in range(cycles):
            yield runtime.Tick()
        for reg in registers:
            yield dut.core.dbg_reg_addr.eq(reg)
            yield runtime.Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return tuple(result[reg] for reg in registers)


def _fmv_h_x(fd, rs1):
    return runtime.enc_r(runtime.OP_FP, fd, 0, rs1, 0, 0b1111010)


def _csr_read(rd):
    return (0x001 << 20) | (0b010 << 12) | (rd << 7) | 0x73


def _csr_clear():
    return (0x001 << 20) | (0b001 << 12) | 0x73


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_compare_ordering_nan_box_and_invalid_flags(extensions):
    prog = []
    for reg, value in enumerate((0x0000, 0x8000, 0x3c00, 0xc000, 0x7e01, 0x7d01), 1):
        prog += _li(reg, value)
        prog.append(_fmv_h_x(reg, reg))
    prog += [
        runtime.enc_r(runtime.OP_FP, 10, 0b010, 1, 2, 0b1010010),  # +0 == -0
        runtime.enc_r(runtime.OP_FP, 11, 0b001, 4, 3, 0b1010010),  # -2 < +1
        runtime.enc_r(runtime.OP_FP, 12, 0b000, 3, 3, 0b1010010),  # +1 <= +1
        runtime.enc_r(runtime.OP_FP, 13, 0b010, 5, 3, 0b1010010),  # qNaN == +1, quiet
        _csr_read(20),
        runtime.enc_r(runtime.OP_FP, 14, 0b001, 5, 3, 0b1010010),  # qNaN < +1, NV
        _csr_read(21),
        _csr_clear(),
        runtime.enc_r(runtime.OP_FP, 15, 0b010, 6, 3, 0b1010010),  # sNaN == +1, NV
        _csr_read(22),
        _csr_clear(),
    ]
    prog += _li(7, 0x3c00)
    prog += [
        runtime.enc_r(runtime.OP_FP, 7, 0, 7, 0, 0b1111000),      # FMV.W.X: invalid H box
        runtime.enc_r(runtime.OP_FP, 16, 0b010, 7, 3, 0b1010010), # canonical qNaN == +1
        _csr_read(23),
    ]
    assert _run(extensions, prog, tuple(range(10, 17)) + (20, 21, 22, 23)) == (
        1, 1, 1, 0, 0, 0, 0,
        0, 0b10000, 0b10000, 0,
    )


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_fclass_covers_all_ieee_half_categories(extensions):
    values = (0xfc00, 0xbc00, 0x8001, 0x8000, 0x0000, 0x0001, 0x3c00, 0x7c00, 0x7d01, 0x7e01)
    prog = []
    for index, value in enumerate(values):
        prog += _li(1, value)
        prog.append(_fmv_h_x(1, 1))
        prog.append(runtime.enc_r(runtime.OP_FP, 10 + index, 0b001, 1, 0, 0b1110010))
    assert _run(extensions, prog, tuple(range(10, 20))) == tuple(1 << bit for bit in range(10))
