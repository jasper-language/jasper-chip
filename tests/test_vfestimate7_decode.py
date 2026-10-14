"""Encoding and legality coverage for VFREC7.V and VFRSQRT7.V."""

from amaranth.sim import Settle, Simulator

from rtl.vfestimate7_decode import VFEstimate7Decode


def encoding(rs1, vd=8, vs2=16, funct3=0b001, vm=True):
    return ((0x13 << 26) | (int(vm) << 25) | (vs2 << 20) |
            (rs1 << 15) | (funct3 << 12) | (vd << 7) | 0x57)


def test_vfestimate7_decode_encodings_width_lmul_mask_and_rounding():
    dut = VFEstimate7Decode()
    sim = Simulator(dut)
    observed = {}

    def sample(name, insn, vtype=2 << 3, frm=0):
        yield dut.insn.eq(insn)
        yield dut.vtype.eq(vtype)
        yield dut.frm.eq(frm)
        yield Settle()
        observed[name] = ((yield dut.match), (yield dut.legal),
                          (yield dut.reciprocal_sqrt))

    def process():
        yield from sample("rsqrt", encoding(4))
        yield from sample("rec", encoding(5))
        yield from sample("f64", encoding(4), vtype=3 << 3)
        yield from sample("fractional", encoding(5), vtype=(2 << 3) | 7)
        yield from sample("reserved", encoding(6))
        yield from sample("bad_form", encoding(4, funct3=0b101))
        yield from sample("bad_width", encoding(4), vtype=1 << 3)
        yield from sample("bad_align", encoding(4, vd=9),
                          vtype=(2 << 3) | 1)
        yield from sample("bad_mask", encoding(4, vd=0, vm=False))
        yield from sample("bad_rec_frm", encoding(5), frm=5)
        yield from sample("rsqrt_ignores_frm", encoding(4), frm=7)

    sim.add_process(process)
    sim.run()
    assert observed["rsqrt"] == (1, 1, 1)
    assert observed["rec"] == (1, 1, 0)
    assert observed["f64"][1]
    assert observed["fractional"][1]
    assert observed["rsqrt_ignores_frm"][1]
    for name in ("reserved", "bad_form", "bad_width", "bad_align",
                 "bad_mask", "bad_rec_frm"):
        assert not observed[name][1], name
