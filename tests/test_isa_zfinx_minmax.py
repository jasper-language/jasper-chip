from pathlib import Path
import importlib.util

import pytest


_path = Path(__file__).with_name("test_isa_zfh_add_sub.py")
_spec = importlib.util.spec_from_file_location("jasper_zfinx_minmax_support", _path)
support = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(support)
runtime = support.runtime


def _minmax(rd, function, a, b):
    return runtime.enc_r(runtime.OP_FP, rd, function, a, b, 0b0010100)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_minmax_nan_signed_zero_order_flags_and_dependency(extensions):
    values = ((1, 0x00000000), (2, 0x80000000), (3, 0x7fc01234),
              (4, 0x7f800001), (5, 0x3f800000), (6, 0xc0000000))
    prog = []
    for reg, value in values:
        prog += support._li(reg, value)
    cases = ((10, 0b000, 1, 2), (11, 0b001, 1, 2),
             (12, 0b000, 3, 5), (13, 0b001, 6, 3),
             (14, 0b000, 4, 5), (15, 0b001, 3, 3))
    for rd, function, a, b in cases:
        prog += [support._csr_clear()] + [runtime.nop()] * 4 + [
            _minmax(rd, function, a, b), support._csr_read(rd + 10)]
    prog += [_minmax(16, 0b000, 6, 5),
             runtime.enc_i(runtime.OP_IMM, 17, 0, 16, 1),
             _minmax(18, 0b001, 6, 5)]
    assert support._run(extensions, prog, tuple(range(10, 19)) +
                        tuple(range(20, 26))) == (
        0x80000000, 0, 0x3f800000, 0xc0000000, 0x3f800000,
        0x7fc00000, 0xc0000000, 0xc0000001, 0x3f800000,
        0, 0, 0, 0, 0b10000, 0)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_minmax_never_modifies_f_register_file(extensions):
    prog = support._li(1, 0xbf800000) + support._li(2, 0x3f800000)
    prog += [_minmax(3, 0b000, 1, 2)]
    words = 64; prog += [runtime.nop()] * (words - len(prog))

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

    dut = _Bench(); sim = runtime.Simulator(dut); sim.add_clock(1e-6); observed = {}
    def process():
        for _ in range(500): yield runtime.Tick()
        yield dut.core.dbg_reg_addr.eq(3); yield runtime.Tick()
        observed["x"] = yield dut.core.dbg_reg_rdata
        yield dut.core.dbg_freg_addr.eq(3); yield runtime.Tick()
        observed["f"] = yield dut.core.dbg_freg_rdata
    sim.add_process(process); sim.run()
    assert observed == {"x": 0xbf800000, "f": 0}
