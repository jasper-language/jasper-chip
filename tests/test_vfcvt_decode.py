"""Exhaustive encoding audit for all 21 V conversion sub-operations."""

from amaranth.sim import Settle, Simulator

from rtl.vfcvt_decode import VFCvtDecode


SAME = (0x00, 0x01, 0x02, 0x03, 0x06, 0x07)
WIDEN = (0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0e, 0x0f)
NARROW = (0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17)


def encoding(subop, vd=8, vs2=16, vm=True, funct3=0b001):
    return ((0x12 << 26) | (int(vm) << 25) | (vs2 << 20) |
            (subop << 15) | (funct3 << 12) | (vd << 7) | 0x57)


def test_vfcvt_decode_all_subops_modes_flags_groups_and_overlaps():
    dut = VFCvtDecode()
    sim = Simulator(dut)
    observed = {}

    def sample(name, subop, vtype=2 << 3, vd=8, vs2=16, frm=0,
               funct3=0b001):
        yield dut.insn.eq(encoding(subop, vd=vd, vs2=vs2, funct3=funct3))
        yield dut.vtype.eq(vtype)
        yield dut.frm.eq(frm)
        yield Settle()
        keys = ("match", "legal", "mode", "to_int", "itof", "ftof",
                "unsigned", "rtz", "rod", "src_group", "dst_group",
                "high", "low")
        signals = (dut.match, dut.legal, dut.mode, dut.to_int,
                   dut.int_to_float, dut.float_to_float, dut.unsigned,
                   dut.fixed_rtz, dut.round_odd, dut.source_group,
                   dut.dest_group, dut.high_overlap, dut.low_overlap)
        values = []
        for signal in signals:
            values.append((yield signal))
        observed[name] = dict(zip(keys, values))

    def process():
        for subop in SAME:
            yield from sample(f"same_{subop:02x}", subop)
        for subop in WIDEN:
            yield from sample(f"widen_{subop:02x}", subop)
        for subop in NARROW:
            yield from sample(f"narrow_{subop:02x}", subop)
        yield from sample("widen_high", 0x0a, vd=8, vs2=9)
        yield from sample("narrow_low", 0x14, vd=8, vs2=8)
        yield from sample("fractional_widen", 0x0a,
                          vtype=(2 << 3) | 7)
        yield from sample("bad_lmul", 0x0a, vtype=(2 << 3) | 3)
        yield from sample("bad_overlap", 0x0a, vd=8, vs2=8)
        yield from sample("bad_frm", 0x02, frm=5)
        yield from sample("rtz_ignores_frm", 0x06, frm=7)
        yield from sample("rod_ignores_frm", 0x15, frm=7)
        yield from sample("bad_form", 0x00, funct3=0b101)
        yield from sample("reserved", 0x04)

    sim.add_process(process)
    sim.run()
    for subop in SAME:
        item = observed[f"same_{subop:02x}"]
        assert item["match"] and item["legal"] and item["mode"] == 0
    for subop in WIDEN:
        item = observed[f"widen_{subop:02x}"]
        assert item["match"] and item["legal"] and item["mode"] == 1
    for subop in NARROW:
        item = observed[f"narrow_{subop:02x}"]
        assert item["match"] and item["legal"] and item["mode"] == 2
    assert observed["widen_high"]["high"]
    assert observed["narrow_low"]["low"]
    assert observed["fractional_widen"]["legal"]
    assert not observed["bad_lmul"]["legal"]
    assert not observed["bad_overlap"]["legal"]
    assert not observed["bad_frm"]["legal"]
    assert observed["rtz_ignores_frm"]["legal"]
    assert observed["rod_ignores_frm"]["legal"]
    assert not observed["bad_form"]["match"]
    assert not observed["reserved"]["match"]
