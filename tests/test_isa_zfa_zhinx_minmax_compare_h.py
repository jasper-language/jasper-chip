import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "zfa_zhinx_minmax_support", Path(__file__).with_name("test_isa_zhinx_sign_compare.py")
)
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)

run = _support._run
li = _support.li
op_fp = _support.op_fp
addi = _support.addi
NOP = _support.NOP


EXTENSIONS = [
    "RV32I+GC+ZFINX+ZHINX+ZFA",
    "RV32I+GC+*+ZFINX+ZHINX",
]


def csr(rd, address, rs1=0, funct3=2):
    return (address << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x73


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zfa_zhinx_minimum_maximum_nan_zero_flags_and_reserved_encoding(extensions):
    program = []
    for reg, value in (
        (1, 0xFFFF0000),  # +0
        (2, 0xFFFF8000),  # -0
        (3, 0xFFFF7E01),  # qNaN
        (4, 0xFFFF7C01),  # sNaN
        (5, 0xFFFF3C00),  # +1.0
        (6, 0xFFFFC000),  # -2.0
        (7, 0x00003C00),  # unboxed -> canonical qNaN
    ):
        program += li(reg, value)
    cases = (
        (10, 0b010, 1, 2),  # FMINM(+0, -0) -> -0
        (11, 0b011, 1, 2),  # FMAXM(+0, -0) -> +0
        (12, 0b010, 3, 5),  # qNaN is always propagated
        (13, 0b011, 6, 3),  # qNaN is always propagated
        (14, 0b010, 4, 5),  # sNaN -> canonical qNaN, NV
        (15, 0b011, 7, 5),  # unboxed qNaN -> canonical, no NV
        (16, 0b010, 6, 5),  # ordinary minimum
    )
    for rd, funct3, rs1, rs2 in cases:
        program += [
            csr(0, 1, 0, 1),
            op_fp(rd, rs1, rs2, 0b0010110, funct3),
            NOP, NOP, NOP, NOP,
            csr(rd + 10, 1),
        ]
    program += [
        addi(17, 0, 0x55),
        op_fp(17, 6, 5, 0b0010110, 0b100),  # reserved funct3
        NOP, NOP, NOP, NOP,
    ]
    assert run(extensions, program, tuple(range(10, 18)) + tuple(range(20, 27))) == (
        0xFFFF8000,
        0xFFFF0000,
        0xFFFF7E00,
        0xFFFF7E00,
        0xFFFF7E00,
        0xFFFF7E00,
        0xFFFFC000,
        0x55,
        0,
        0,
        0,
        0,
        0x10,
        0,
        0,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zfa_zhinx_quiet_compare_nan_zero_dependency_and_reserved_encoding(extensions):
    program = []
    for reg, value in (
        (1, 0xFFFF7E01),  # qNaN
        (2, 0xFFFF7C01),  # sNaN
        (3, 0xFFFFC000),  # -2.0
        (4, 0xFFFF3E00),  # +1.5
        (5, 0xFFFF0000),  # +0
        (6, 0xFFFF8000),  # -0
        (7, 0x00003E00),  # unboxed -> canonical qNaN
    ):
        program += li(reg, value)
    cases = (
        (10, 0b100, 1, 4),  # FLEQ(qNaN, number) -> false, no NV
        (11, 0b101, 1, 4),  # FLTQ(qNaN, number) -> false, no NV
        (12, 0b100, 3, 4),  # -2 <= +1.5
        (13, 0b101, 4, 3),  # +1.5 < -2 is false
        (14, 0b100, 5, 6),  # +0 <= -0
        (15, 0b101, 2, 4),  # sNaN -> false, NV
        (16, 0b100, 7, 4),  # unboxed qNaN -> false, no NV
    )
    for rd, funct3, rs1, rs2 in cases:
        program += [
            csr(0, 1, 0, 1),
            op_fp(rd, rs1, rs2, 0b1010010, funct3),
            NOP, NOP, NOP, NOP,
            csr(rd + 10, 1),
        ]
    program += [
        op_fp(17, 3, 4, 0b1010010, 0b101),
        addi(18, 17, 1),
        addi(19, 0, 0x55),
        op_fp(19, 3, 4, 0b1010010, 0b110),  # reserved funct3
        NOP, NOP, NOP, NOP,
    ]
    assert run(extensions, program, tuple(range(10, 20)) + tuple(range(20, 27))) == (
        0, 0, 1, 0, 1, 0, 0,
        1, 2, 0x55,
        0, 0, 0, 0, 0, 0x10, 0,
    )
