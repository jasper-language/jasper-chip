"""Encoding and launch-parameter closure for V memory instructions."""

from amaranth.sim import Settle, Simulator

from rtl.vmemory_decode import VMemoryDecode


LOAD_FP = 0x07


def encoding(vd, *, width=0, rs2=0, mop=0, vm=1, nf=0, mew=0):
    return ((nf << 29) | (mew << 28) | (mop << 26) | (vm << 25) |
            (rs2 << 20) | (width << 12) | (vd << 7) | LOAD_FP)


def decode(insn, *, is_load=1, vtype=0, vl=4, vlmax=16, vstart=0):
    dut = VMemoryDecode()
    sim = Simulator(dut)
    result = {}

    def process():
        yield dut.insn.eq(insn)
        yield dut.is_load.eq(is_load)
        yield dut.vtype.eq(vtype)
        yield dut.vl.eq(vl)
        yield dut.vlmax.eq(vlmax)
        yield dut.vstart.eq(vstart)
        yield Settle()
        for name in ("legal", "indexed", "strided", "fof", "whole",
                     "mask", "eew_bytes", "index_bytes", "fields",
                     "field_stride", "element", "evl", "tail_limit"):
            result[name] = yield getattr(dut, name)

    sim.add_process(process)
    sim.run()
    return result


def test_vmemory_decode_legal_modes_and_launch_parameters():
    unit = decode(encoding(1))
    assert unit["legal"] and unit["eew_bytes"] == 1
    assert (unit["element"], unit["evl"], unit["tail_limit"]) == (0, 4, 16)

    strided = decode(encoding(2, rs2=3, mop=2), vstart=2)
    assert strided["legal"] and strided["strided"]
    assert strided["element"] == 2

    indexed = decode(encoding(8, width=1 + 4, rs2=2, mop=1), vtype=0)
    assert indexed["legal"] and indexed["indexed"]
    assert indexed["index_bytes"] == 2

    segment = decode(encoding(4, nf=1))
    assert segment["legal"] and segment["fields"] == 2

    whole = decode(encoding(8, rs2=0b01000, nf=3), vl=1)
    assert whole["legal"] and whole["whole"]
    assert whole["evl"] == 64 and whole["tail_limit"] == 64

    mask = decode(encoding(0, rs2=0b01011), vl=9)
    assert mask["legal"] and mask["mask"] and mask["evl"] == 2

    fof = decode(encoding(12, rs2=0b10000))
    assert fof["legal"] and fof["fof"]


def test_vmemory_decode_rejects_reserved_overlap_groups_masked_v0_and_vill():
    assert not decode(encoding(1, width=1))["legal"]
    assert not decode(encoding(1, mew=1))["legal"]
    assert not decode(encoding(1), vtype=1 << 31)["legal"]
    assert not decode(encoding(0, vm=0))["legal"]
    assert not decode(encoding(4, width=0b111, nf=1))["legal"]
    assert not decode(encoding(2, width=0b101, rs2=2, mop=1))["legal"]
    assert not decode(encoding(3, rs2=0b01000, nf=3))["legal"]
    assert not decode(encoding(1, rs2=0b01011, nf=1))["legal"]
