from pathlib import Path
import importlib.util

import pytest


_runtime_path = Path(__file__).with_name("test_extension_star_runtime.py")
_runtime_spec = importlib.util.spec_from_file_location("jasper_extension_runtime", _runtime_path)
runtime = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(runtime)


def _run_half_fsgnj_case(extensions):
    prog = [
        runtime.enc_i(runtime.OP_IMM, 1, 0b000, 0, 1),
        runtime.enc_u(runtime.LUI, 2, 0x8),
        runtime.enc_i(runtime.OP_IMM, 2, 0b000, 2, 2),
        runtime.enc_r(runtime.OP_FP, 1, 0b000, 1, 0, 0b1111010),  # FMV.H.X f1,x1
        runtime.enc_r(runtime.OP_FP, 2, 0b000, 2, 0, 0b1111010),  # FMV.H.X f2,x2
        runtime.enc_r(runtime.OP_FP, 3, 0b000, 1, 2, 0b0010010),  # FSGNJ.H
        runtime.enc_r(runtime.OP_FP, 4, 0b001, 1, 2, 0b0010010),  # FSGNJN.H
        runtime.enc_r(runtime.OP_FP, 5, 0b010, 1, 2, 0b0010010),  # FSGNJX.H
        runtime.enc_r(runtime.OP_FP, 6, 0b000, 3, 0, 0b1110010),  # FMV.X.H x6,f3
        runtime.enc_r(runtime.OP_FP, 7, 0b000, 4, 0, 0b1110010),  # FMV.X.H x7,f4
        runtime.enc_r(runtime.OP_FP, 8, 0b000, 5, 0, 0b1110010),  # FMV.X.H x8,f5
        runtime.nop(),
    ]
    imem_words = 64
    prog += [runtime.nop()] * (imem_words - len(prog))

    class _HalfFsgnjBench(runtime.Elaboratable):
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
                im.addr.eq(c.imem_addr),
                c.imem_rdata.eq(im.rdata),
                dm.req_valid.eq(c.dmem_valid),
                dm.req_we.eq(c.dmem_we),
                dm.req_addr.eq(c.dmem_addr),
                dm.req_wdata.eq(c.dmem_wdata),
                c.dmem_rdata.eq(dm.rsp_rdata),
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

    dut = _HalfFsgnjBench()
    sim = runtime.Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    def proc():
        for _ in range(300):
            yield runtime.Tick()
        for reg in (6, 7, 8):
            yield dut.core.dbg_reg_addr.eq(reg)
            yield runtime.Tick()
            result[reg] = yield dut.core.dbg_reg_rdata

    sim.add_process(proc)
    sim.run()
    return result[6], result[7], result[8]


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_fsgnj_family_executes_with_nan_boxed_half_operands(extensions):
    assert _run_half_fsgnj_case(extensions) == (
        0xFFFF8001,
        0x00000001,
        0xFFFF8001,
    )
