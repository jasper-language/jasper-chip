from pathlib import Path
import importlib.util

import pytest


_runtime_path = Path(__file__).with_name("test_extension_star_runtime.py")
_spec = importlib.util.spec_from_file_location("jasper_extension_runtime_i2h", _runtime_path)
runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime)


def _li(rd, value):
    value &= 0xffffffff
    upper = (value + 0x800) >> 12
    low = (value - (upper << 12)) & 0xfff
    return [runtime.enc_u(runtime.LUI, rd, upper), runtime.enc_i(runtime.OP_IMM, rd, 0, rd, low)]


def _fcvt(fd, rm, rs1, unsigned=False):
    return runtime.enc_r(runtime.OP_FP, fd, rm, rs1, int(unsigned), 0b1101010)


def _fmv_x_h(rd, fs1):
    return runtime.enc_r(runtime.OP_FP, rd, 0, fs1, 0, 0b1110010)


def _csr_read(rd):
    return (0x001 << 20) | (0b010 << 12) | (rd << 7) | 0x73


def _csr_clear():
    return (0x001 << 20) | (0b001 << 12) | 0x73


def _run(extensions, prog, registers):
    imem_words = 128
    prog += [runtime.nop()] * (imem_words - len(prog))

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
        for _ in range(750):
            yield runtime.Tick()
        for reg in registers:
            yield dut.core.dbg_reg_addr.eq(reg)
            yield runtime.Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return tuple(result[reg] for reg in registers)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_fcvt_h_w_all_rounding_modes_and_dynamic_frm(extensions):
    prog = _li(1, 2049) + _li(2, -2049)
    for index, rm in enumerate(range(5), 10):
        prog += [_fcvt(index, rm, 1), _fmv_x_h(index, index)]
    for index, rm in enumerate(range(5), 15):
        prog += [_fcvt(index, rm, 2), _fmv_x_h(index, index)]
    prog += _li(9, 3)
    prog += [
        (0x002 << 20) | (9 << 15) | (0b001 << 12) | 0x73,
        _fcvt(20, 0b111, 1), _fmv_x_h(20, 20), _csr_read(21),
    ]
    assert _run(extensions, prog, tuple(range(10, 22))) == (
        0x6800, 0x6800, 0x6800, 0x6801, 0x6801,
        0xffffe800, 0xffffe800, 0xffffe801, 0xffffe800, 0xffffe801,
        0x6801, 0b00001,
    )


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_fcvt_h_w_exact_unsigned_overflow_and_flags(extensions):
    values = ((1, -2), (2, 65504), (3, 65519), (4, 65520), (5, 65535), (6, -65520))
    prog = []
    for reg, value in values:
        prog += _li(reg, value)
    cases = (
        (10, 0, 1, False), (11, 0, 2, True), (12, 0, 3, True),
        (13, 0, 4, True), (14, 1, 5, True), (15, 2, 6, False),
    )
    for fd, rm, rs1, unsigned in cases:
        prog += [_csr_clear(), _fcvt(fd, rm, rs1, unsigned), _fmv_x_h(fd, fd), _csr_read(fd + 10)]
    assert _run(extensions, prog, tuple(range(10, 16)) + tuple(range(20, 26))) == (
        0xffffc000, 0x7bff, 0x7bff, 0x7c00, 0x7bff, 0xfffffc00,
        0, 0, 0b00001, 0b00101, 0b00101, 0b00101,
    )
