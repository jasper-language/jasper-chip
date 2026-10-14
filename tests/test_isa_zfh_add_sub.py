from pathlib import Path
import importlib.util

import pytest


_path = Path(__file__).with_name("test_extension_star_runtime.py")
_spec = importlib.util.spec_from_file_location("jasper_extension_runtime_hadd", _path)
runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime)


def _li(rd, value):
    upper = (value + 0x800) >> 12
    low = (value - (upper << 12)) & 0xfff
    return [runtime.enc_u(runtime.LUI, rd, upper), runtime.enc_i(runtime.OP_IMM, rd, 0, rd, low)]


def _fmv_h_x(fd, rs1): return runtime.enc_r(runtime.OP_FP, fd, 0, rs1, 0, 0b1111010)
def _fmv_x_h(rd, fs1): return runtime.enc_r(runtime.OP_FP, rd, 0, fs1, 0, 0b1110010)
def _fadd(fd, rm, fs1, fs2): return runtime.enc_r(runtime.OP_FP, fd, rm, fs1, fs2, 0b0000010)
def _fsub(fd, rm, fs1, fs2): return runtime.enc_r(runtime.OP_FP, fd, rm, fs1, fs2, 0b0000110)
def _csr_read(rd): return (0x001 << 20) | (0b010 << 12) | (rd << 7) | 0x73
def _csr_clear(): return (0x001 << 20) | (0b001 << 12) | 0x73


def _run(extensions, prog, registers):
    words = 128
    prog += [runtime.nop()] * (words - len(prog))
    class _Bench(runtime.Elaboratable):
        def __init__(self):
            self.core = runtime.RV12Core(core_id=0, xlen=32, extensions=extensions)
            self.imem = runtime.SimpleIMem(words=words, init=prog)
            self.dmem = runtime.SimpleDMem(words=16)
        def elaborate(self, platform):
            m = runtime.Module(); m.submodules.core = c = self.core
            m.submodules.imem = im = self.imem; m.submodules.dmem = dm = self.dmem
            m.d.comb += [im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
                dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
                dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
                c.dmem_rdata.eq(dm.rsp_rdata), c.gc_enq_ready.eq(0),
                c.gc_rsp_valid.eq(0), c.gc_rsp_tag.eq(0), c.gc_rsp_rd.eq(0),
                c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1), c.mv_cmd_ready.eq(1),
                c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0), c.mv_rsp_rd.eq(0),
                c.mv_rsp_data.eq(0)]
            return m
    dut = _Bench(); sim = runtime.Simulator(dut); sim.add_clock(1e-6); result = {}
    def proc():
        for _ in range(800): yield runtime.Tick()
        for reg in registers:
            yield dut.core.dbg_reg_addr.eq(reg); yield runtime.Tick()
            result[reg] = yield dut.core.dbg_reg_rdata
    sim.add_process(proc); sim.run()
    return tuple(result[r] for r in registers)


def _load_halves(items):
    prog = []
    for reg, value in items:
        prog += _li(reg, value); prog.append(_fmv_h_x(reg, reg))
    return prog


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_add_sub_rounding_cancellation_and_dynamic_frm(extensions):
    prog = _load_halves(((1, 0x3e00), (2, 0x4080), (3, 0x3c00), (4, 0x0001), (5, 0xbc00)))
    prog += [_csr_clear(),
        _fadd(10, 0, 1, 2), _fmv_x_h(10, 10),
        _fsub(11, 0, 1, 2), _fmv_x_h(11, 11),
        _fadd(12, 0, 3, 4), _fmv_x_h(12, 12),
        _fadd(13, 3, 3, 4), _fmv_x_h(13, 13),
        _fadd(14, 2, 3, 5), _fmv_x_h(14, 14),
        _fadd(15, 0, 3, 5), _fmv_x_h(15, 15),
        _fadd(16, 4, 3, 4), _fmv_x_h(16, 16),
    ]
    prog += _li(9, 3)
    prog += [
        (0x002 << 20) | (9 << 15) | (0b001 << 12) | 0x73,
        _fadd(17, 7, 3, 4), _fmv_x_h(17, 17),
        _csr_read(20)]
    assert _run(extensions, prog, (10, 11, 12, 13, 14, 15, 16, 17, 20)) == (
        0x4380, 0xffffba00, 0x3c00, 0x3c01, 0xffff8000, 0,
        0x3c00, 0x3c01, 0b00001)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_add_special_nan_box_overflow_and_flags(extensions):
    prog = _load_halves(((1, 0x7bff), (2, 0x7c00), (3, 0xfc00),
                         (4, 0x7d01), (5, 0x7e01), (6, 0x3c00)))
    cases = ((_fadd, 10, 0, 1, 1), (_fadd, 11, 1, 1, 1),
             (_fadd, 12, 0, 2, 3), (_fadd, 13, 0, 4, 6),
             (_fadd, 14, 0, 5, 6))
    for operation, fd, rm, a, b in cases:
        prog += [_csr_clear(), operation(fd, rm, a, b), _fmv_x_h(fd, fd), _csr_read(fd + 10)]
    prog += _li(7, 0x3c00)
    prog += [runtime.enc_r(runtime.OP_FP, 7, 0, 7, 0, 0b1111000), _csr_clear(),
             _fadd(15, 0, 7, 6), _fmv_x_h(15, 15), _csr_read(25)]
    assert _run(extensions, prog, tuple(range(10, 16)) + tuple(range(20, 26))) == (
        0x7c00, 0x7bff, 0x7e00, 0x7e00, 0x7e00, 0x7e00,
        0b00101, 0b00101, 0b10000, 0b10000, 0, 0)
