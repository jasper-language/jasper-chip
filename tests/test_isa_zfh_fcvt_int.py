from pathlib import Path
import importlib.util

import pytest


_runtime_path = Path(__file__).with_name("test_extension_star_runtime.py")
_spec = importlib.util.spec_from_file_location("jasper_extension_runtime_h2i", _runtime_path)
runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime)


def _li(rd, value):
    upper = (value + 0x800) >> 12
    low = (value - (upper << 12)) & 0xfff
    return [runtime.enc_u(runtime.LUI, rd, upper), runtime.enc_i(runtime.OP_IMM, rd, 0, rd, low)]


def _fmv_h_x(fd, rs1):
    return runtime.enc_r(runtime.OP_FP, fd, 0, rs1, 0, 0b1111010)


def _fcvt(rd, rm, fs1, unsigned=False):
    return runtime.enc_r(runtime.OP_FP, rd, rm, fs1, int(unsigned), 0b1100010)


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
        for _ in range(700):
            yield runtime.Tick()
        for reg in registers:
            yield dut.core.dbg_reg_addr.eq(reg)
            yield runtime.Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return tuple(result[reg] for reg in registers)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_fcvt_w_h_all_rounding_modes_and_dynamic_frm(extensions):
    prog = []
    for reg, value in ((1, 0x3e00), (2, 0xbe00)):
        prog += _li(reg, value)
        prog.append(_fmv_h_x(reg, reg))
    for index, rm in enumerate(range(5), 10):
        prog.append(_fcvt(index, rm, 1))
    for index, rm in enumerate(range(5), 15):
        prog.append(_fcvt(index, rm, 2))
    prog += _li(9, 1)
    prog.append((0x002 << 20) | (9 << 15) | (0b001 << 12) | 0x73)  # frm=RTZ
    prog.append(_fcvt(20, 0b111, 1))
    prog.append(_csr_read(21))
    assert _run(extensions, prog, tuple(range(10, 22))) == (
        2, 1, 1, 2, 2,
        0xfffffffe, 0xffffffff, 0xfffffffe, 0xffffffff, 0xfffffffe,
        1, 0b00001,
    )


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_fcvt_w_h_special_unsigned_and_flag_priority(extensions):
    prog = []
    for reg, value in ((1, 0xc000), (2, 0x7e01), (3, 0xfc00), (4, 0xbc00), (5, 0xb800)):
        prog += _li(reg, value)
        prog.append(_fmv_h_x(reg, reg))
    prog += [
        _csr_clear(),
        _fcvt(10, 0, 1), _csr_read(20), _csr_clear(),                 # exact -2
        _fcvt(15, 4, 1), _csr_read(19), _csr_clear(),                 # exact -2 under RMM
        _fcvt(11, 0, 2), _csr_read(21), _csr_clear(),                 # qNaN -> INT_MAX, NV
        _fcvt(12, 0, 3, True), _csr_read(22), _csr_clear(),           # -inf -> 0, NV
        _fcvt(13, 1, 5, True), _csr_read(23), _csr_clear(),           # -0.5 RTZ -> 0, NX
        _fcvt(14, 2, 5, True), _csr_read(24),                         # -0.5 RDN -> 0, NV only
    ]
    assert _run(extensions, prog, (10, 15, 11, 12, 13, 14, 20, 19, 21, 22, 23, 24)) == (
        0xfffffffe, 0xfffffffe, 0x7fffffff, 0, 0, 0,
        0, 0, 0b10000, 0b10000, 0b00001, 0b10000,
    )
