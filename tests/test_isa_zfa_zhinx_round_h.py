import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "zfa_zhinx_round_support", Path(__file__).with_name("test_isa_zhinx_integer_convert.py")
)
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)

run = _support._run
li = _support.li
op_fp = _support.op_fp
addi = _support.addi
csr = _support.csr
NOP = _support.NOP


EXTENSIONS = [
    "RV32I+GC+ZFINX+ZHINX+ZFA",
    "RV32I+GC+*+ZFINX+ZHINX",
]


def fround_h(rd, rs1, rm=0, nx=False, rs2=None):
    source2 = (5 if nx else 4) if rs2 is None else rs2
    return op_fp(rd, rs1, source2, 0b0100010, rm)


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zfa_zhinx_round_h_all_modes_dynamic_ties_zero_and_nx(extensions):
    program = []
    for reg, value in (
        (1, 0xFFFF3E00),  # +1.5
        (2, 0xFFFF4100),  # +2.5
        (3, 0xFFFFBE00),  # -1.5
        (4, 0xFFFF3A00),  # +0.75
        (5, 0xFFFFBA00),  # -0.75
        (6, 0xFFFF3800),  # +0.5
        (7, 0xFFFF6800),  # +2048, already integral
    ):
        program += li(reg, value)
    program += [
        csr(0, 1, 0, 1),
        fround_h(10, 1, 0b000),
        fround_h(11, 2, 0b000, nx=True),
        fround_h(12, 3, 0b010),
        fround_h(13, 3, 0b011),
        fround_h(14, 4, 0b001),
        fround_h(15, 5, 0b011),
        fround_h(16, 4, 0b100),
        fround_h(17, 6, 0b000),
        fround_h(18, 6, 0b100),
        fround_h(19, 7, 0b000),
        addi(8, 0, 1),
        csr(0, 2, 8, 1),
        fround_h(20, 1, 0b111),  # dynamic RTZ
        NOP, NOP, NOP, NOP,
        csr(21, 1, 0),
    ]
    assert run(extensions, program, tuple(range(10, 22))) == (
        0xFFFF4000,
        0xFFFF4000,
        0xFFFFC000,
        0xFFFFBC00,
        0xFFFF0000,
        0xFFFF8000,
        0xFFFF3C00,
        0xFFFF0000,
        0xFFFF3C00,
        0xFFFF6800,
        0xFFFF3C00,
        0x01,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zfa_zhinx_round_h_special_nan_box_and_illegal_encodings(extensions):
    program = []
    for reg, value in (
        (1, 0xFFFF7E01),  # qNaN
        (2, 0xFFFF7C01),  # sNaN
        (3, 0xFFFF7C00),  # +inf
        (4, 0x00003E00),  # unboxed
        (5, 0xFFFF8000),  # -0
    ):
        program += li(reg, value)
    program += [
        csr(0, 1, 0, 1),
        fround_h(10, 1),
        NOP, NOP, NOP, NOP,
        csr(15, 1, 0),
        csr(0, 1, 0, 1),
        fround_h(11, 2),
        NOP, NOP, NOP, NOP,
        csr(16, 1, 0),
        fround_h(12, 3),
        fround_h(13, 4),
        fround_h(14, 5),
        addi(20, 0, 0x55),
        addi(21, 0, 0x66),
        addi(22, 0, 0x77),
        addi(6, 0, 5),
        fround_h(20, 1, 0b101),          # reserved static rm
        csr(0, 2, 6, 1),
        fround_h(21, 1, 0b111),          # invalid dynamic frm
        fround_h(22, 1, 0b000, rs2=6),   # reserved rs2
        NOP, NOP, NOP, NOP,
    ]
    assert run(extensions, program, tuple(range(10, 17)) + (20, 21, 22)) == (
        0xFFFF7E00,
        0xFFFF7E00,
        0xFFFF7C00,
        0xFFFF7E00,
        0xFFFF8000,
        0,
        0x10,
        0x55,
        0x66,
        0x77,
    )
