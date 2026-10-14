"""Encoding and legality coverage for V floating divide."""

from amaranth.sim import Settle, Simulator

from rtl.vfdiv_decode import VFDivDecode


def encoding(funct6, funct3=0b001, vd=8, vs2=16, operand=24, vm=True):
    return ((funct6 << 26) | (int(vm) << 25) | (vs2 << 20) |
            (operand << 15) | (funct3 << 12) | (vd << 7) | 0x57)


def test_vfdiv_decode_forms_groups_widths_and_nan_boxing():
    dut = VFDivDecode()
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
        observed[name] = ((yield dut.match), (yield dut.legal),
                          (yield dut.reverse), (yield dut.scalar_value))

    def process():
        yield from sample("vv", encoding(0x20))
        yield from sample("vf", encoding(0x20, funct3=0b101))
        yield from sample("reverse", encoding(0x21, funct3=0b101))
        yield from sample("bad_reverse", encoding(0x21))
        yield from sample("bad_width", encoding(0x20), vtype=1 << 3)
        yield from sample("bad_lmul", encoding(0x20), vtype=(2 << 3) | 4)
        yield from sample("bad_align", encoding(0x20, vd=9),
                          vtype=(2 << 3) | 1)
        yield from sample("bad_frm", encoding(0x20), frm=5)
        yield from sample("vill", encoding(0x20),
                          vtype=(1 << 31) | (2 << 3))
        yield from sample("boxed", encoding(0x20, funct3=0b101),
                          scalar=0x3f800000)

    sim.add_process(process)
    sim.run()
    assert observed["vv"][:2] == (1, 1)
    assert observed["vf"][:2] == (1, 1)
    assert observed["reverse"][:3] == (1, 1, 1)
    assert observed["bad_reverse"][:2] == (0, 0)
    for name in ("bad_width", "bad_lmul", "bad_align", "bad_frm", "vill"):
        assert not observed[name][1], name
    assert observed["boxed"][3] == 0xffffffff7fc00000
