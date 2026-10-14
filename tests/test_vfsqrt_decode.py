"""Encoding and legality coverage for VFSQRT.V."""

from amaranth.sim import Settle, Simulator

from rtl.vfsqrt_decode import VFSqrtDecode


def encoding(vd=8, vs2=16, rs1=0, funct3=0b001, vm=True):
    return ((0x13 << 26) | (int(vm) << 25) | (vs2 << 20) |
            (rs1 << 15) | (funct3 << 12) | (vd << 7) | 0x57)


def test_vfsqrt_decode_reserved_fields_width_lmul_and_mask_rules():
    dut = VFSqrtDecode()
    sim = Simulator(dut)
    observed = {}

    def sample(name, insn, vtype=2 << 3, frm=0):
        yield dut.insn.eq(insn)
        yield dut.vtype.eq(vtype)
        yield dut.frm.eq(frm)
        yield Settle()
        observed[name] = ((yield dut.match), (yield dut.legal))

    def process():
        yield from sample("f32", encoding())
        yield from sample("f64", encoding(), vtype=3 << 3)
        yield from sample("fractional", encoding(), vtype=(2 << 3) | 7)
        yield from sample("bad_rs1", encoding(rs1=1))
        yield from sample("bad_form", encoding(funct3=0b101))
        yield from sample("bad_width", encoding(), vtype=1 << 3)
        yield from sample("reserved_lmul", encoding(), vtype=(2 << 3) | 4)
        yield from sample("bad_align", encoding(vd=9),
                          vtype=(2 << 3) | 1)
        yield from sample("bad_mask", encoding(vd=0, vm=False))
        yield from sample("bad_frm", encoding(), frm=5)
        yield from sample("vill", encoding(),
                          vtype=(1 << 31) | (2 << 3))

    sim.add_process(process)
    sim.run()
    assert observed["f32"] == (1, 1)
    assert observed["f64"] == (1, 1)
    assert observed["fractional"] == (1, 1)
    assert observed["bad_rs1"] == (0, 0)
    assert observed["bad_form"] == (0, 0)
    for name in ("bad_width", "reserved_lmul", "bad_align", "bad_mask",
                 "bad_frm", "vill"):
        assert not observed[name][1], name
