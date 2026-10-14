# -*- coding: utf-8 -*-
"""纯 Python 轻量自检：验证 GC 指令编码。

这个测试不依赖 amaranth，也不需要任何 HDL 工具。

运行：
    python -m tests.test_isa
"""

from rtl.isa import (
    CUSTOM0, GC_NEW, GC_DROP, GC_CLONE, GC_PIN, GC_UNPIN, GC_RELOC, GC_EPOCH,
    GC_F7,
    enc_gc_new, enc_gc_drop, enc_gc_clone, enc_gc_pin, enc_gc_unpin, enc_gc_reloc, enc_gc_epoch,
)


def fields(insn: int):
    """把 32-bit 指令拆字段，便于断言。"""
    opcode = insn & 0x7F
    rd     = (insn >> 7) & 0x1F
    funct3 = (insn >> 12) & 0x7
    rs1    = (insn >> 15) & 0x1F
    rs2    = (insn >> 20) & 0x1F
    funct7 = (insn >> 25) & 0x7F
    return opcode, rd, funct3, rs1, rs2, funct7


def __test_one(name, insn, exp):
    got = fields(insn)
    assert got == exp, f"{name}: got {got}, expected {exp}"


def main():
    # GC_NEW rd=2
    __test_one(
        "GC_NEW",
        enc_gc_new(rd=2, rs1=0, rs2=0),
        (CUSTOM0, 2, GC_NEW, 0, 0, GC_F7),
    )

    # GC_CLONE rd=3 rs1=2
    __test_one(
        "GC_CLONE",
        enc_gc_clone(rd=3, rs1=2),
        (CUSTOM0, 3, GC_CLONE, 2, 0, GC_F7),
    )

    # GC_DROP rs1=2 (rd=0)
    __test_one(
        "GC_DROP",
        enc_gc_drop(rs1=2),
        (CUSTOM0, 0, GC_DROP, 2, 0, GC_F7),
    )

    # GC_PIN rs1=2
    __test_one(
        "GC_PIN",
        enc_gc_pin(rs1=2),
        (CUSTOM0, 0, GC_PIN, 2, 0, GC_F7),
    )

    # GC_UNPIN rs1=2
    __test_one(
        "GC_UNPIN",
        enc_gc_unpin(rs1=2),
        (CUSTOM0, 0, GC_UNPIN, 2, 0, GC_F7),
    )

    # GC_RELOC rs1_old=2 rs2_new=5
    __test_one(
        "GC_RELOC",
        enc_gc_reloc(rs1_old=2, rs2_new=5),
        (CUSTOM0, 0, GC_RELOC, 2, 5, GC_F7),
    )

    # GC_EPOCH (rd=0, rs1/rs2=0)
    __test_one(
        "GC_EPOCH",
        enc_gc_epoch(),
        (CUSTOM0, 0, GC_EPOCH, 0, 0, GC_F7),
    )

    print("OK: ISA encoders look consistent.")


if __name__ == "__main__":
    main()
