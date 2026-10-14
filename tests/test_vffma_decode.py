"""Encoding and legality coverage for V floating fused operations."""

from amaranth.sim import Settle, Simulator

from rtl.vffma_decode import VFFMADecode


def encoding(funct6, vd=8, vs2=16, vs1=24, vv=True, vm=True):
    funct3 = 0b001 if vv else 0b101
    return ((funct6 << 26) | (int(vm) << 25) | (vs2 << 20) |
            (vs1 << 15) | (funct3 << 12) | (vd << 7) | 0x57)


def test_vffma_decode_all_families_constraints_and_nan_boxing():
    dut = VFFMADecode()
    sim = Simulator(dut)
    observed = {}

    def sample(name, insn, vtype=2 << 3, frm=0, scalar=0):
        yield dut.insn.eq(insn)
        yield dut.vtype.eq(vtype)
        yield dut.vl.eq(4)
        yield dut.vlmax.eq(8)
        yield dut.frm.eq(frm)
        yield dut.scalar.eq(scalar)
        yield Settle()
        match = yield dut.match
        legal = yield dut.legal
        widen = yield dut.widen
        accumulate = yield dut.accumulate
        multiply = yield dut.multiply_only
        add = yield dut.add_only
        wide_vs2 = yield dut.wide_vs2
        scalar_value = yield dut.scalar_value
        observed[name] = {
            "match": match, "legal": legal, "widen": widen,
            "accumulate": accumulate, "multiply": multiply,
            "add": add, "wide_vs2": wide_vs2, "scalar": scalar_value,
        }

    def process():
        yield from sample("normal", encoding(0x28))
        yield from sample("accum", encoding(0x2c))
        yield from sample("wmul", encoding(0x38))
        yield from sample("wfma", encoding(0x3c))
        yield from sample("wadd", encoding(0x30))
        yield from sample("wadd_wide", encoding(0x34))
        yield from sample("bad_sew", encoding(0x38), vtype=3 << 3)
        yield from sample("bad_frm", encoding(0x28), frm=5)
        yield from sample("vill", encoding(0x28), vtype=(1 << 31) | (2 << 3))
        yield from sample("overlap", encoding(0x38, vd=8, vs2=8))
        yield from sample("boxed", encoding(0x28, vv=False),
                          scalar=0x000000003f800000)
        yield from sample("not_fma", encoding(0x20))

    sim.add_process(process)
    sim.run()
    assert observed["normal"]["legal"] and not observed["normal"]["widen"]
    assert observed["accum"]["accumulate"]
    assert observed["wmul"]["widen"] and observed["wmul"]["multiply"]
    assert observed["wfma"]["widen"] and observed["wfma"]["accumulate"]
    assert observed["wadd"]["widen"] and observed["wadd"]["add"]
    assert observed["wadd_wide"]["wide_vs2"]
    assert not observed["bad_sew"]["legal"]
    assert not observed["bad_frm"]["legal"]
    assert not observed["vill"]["legal"]
    assert not observed["overlap"]["legal"]
    assert observed["boxed"]["scalar"] == 0xffffffff7fc00000
    assert not observed["not_fma"]["match"]
