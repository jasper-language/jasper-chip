import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "zhinx_sign_support", Path(__file__).with_name("test_isa_zhinx_sign_compare.py")
)
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)

run = _support._run
li = _support.li
op_fp = _support.op_fp
addi = _support.addi
NOP = _support.NOP


EXTENSIONS = [
    "RV32I+GC+ZFINX+ZHINX",
    "RV32I+GC+*+ZFINX+ZHINX",
]


def csr(rd, address, rs1=0, funct3=2):
    return (address << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x73


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_sign_injection_nan_box_signed_zero_and_reserved_encodings(extensions):
    program = []
    program += li(1, 0xFFFF3E00)  # +1.5h
    program += li(2, 0xFFFFC000)  # -2.0h
    program += li(3, 0xFFFF0000)  # +0
    program += li(4, 0xFFFF8000)  # -0
    program += li(5, 0x00003E00)  # unboxed +1.5h
    program += [
        addi(30, 0, 0x55),
        addi(31, 0, 0x66),
        op_fp(10, 1, 2, 0b0010010, 0),  # FSGNJ.H -> -1.5
        op_fp(11, 1, 2, 0b0010010, 1),  # FSGNJN.H -> +1.5
        op_fp(12, 1, 2, 0b0010010, 2),  # FSGNJX.H -> -1.5
        op_fp(13, 5, 2, 0b0010010, 0),  # canonical NaN with negative sign
        op_fp(14, 5, 2, 0b0010010, 1),  # canonical NaN with positive sign
        op_fp(15, 5, 2, 0b0010010, 2),  # canonical NaN with negative sign
        op_fp(16, 3, 4, 0b0010110, 0),  # FMIN(+0, -0) -> -0
        op_fp(17, 3, 4, 0b0010110, 1),  # FMAX(+0, -0) -> +0
        op_fp(30, 1, 2, 0b0010010, 3),  # reserved FSGNJ.H funct3
        op_fp(31, 1, 2, 0b1010010, 3),  # reserved compare funct3
        NOP, NOP, NOP, NOP,
    ]
    assert run(extensions, program, tuple(range(10, 18)) + (30, 31)) == (
        0xFFFFBE00,
        0xFFFF3E00,
        0xFFFFBE00,
        0xFFFFFE00,
        0xFFFF7E00,
        0xFFFFFE00,
        0xFFFF8000,
        0xFFFF0000,
        0x55,
        0x66,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_minmax_nan_selection_and_snan_flags(extensions):
    program = []
    program += li(1, 0xFFFF3E00)  # +1.5h
    program += li(2, 0xFFFF7E01)  # qNaN
    program += li(3, 0xFFFF7C01)  # sNaN
    program += li(4, 0x00003E00)  # unboxed -> canonical qNaN
    cases = (
        (10, 0, 2, 1),  # FMIN(qNaN, number) -> number, no NV
        (11, 1, 3, 1),  # FMAX(sNaN, number) -> number, NV
        (12, 0, 2, 3),  # both NaN -> canonical qNaN, NV from sNaN
        (13, 1, 4, 1),  # unboxed qNaN and number -> number, no NV
    )
    for rd, funct3, rs1, rs2 in cases:
        program += [
            csr(0, 1, 0, 1),
            op_fp(rd, rs1, rs2, 0b0010110, funct3),
            NOP, NOP, NOP, NOP,
            csr(rd + 10, 1),
        ]
    assert run(extensions, program, tuple(range(10, 14)) + tuple(range(20, 24))) == (
        0xFFFF3E00,
        0xFFFF3E00,
        0xFFFF7E00,
        0xFFFF3E00,
        0,
        0x10,
        0x10,
        0,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_compare_quiet_signaling_nan_and_zero_flags(extensions):
    program = []
    program += li(1, 0xFFFF0000)  # +0
    program += li(2, 0xFFFF8000)  # -0
    program += li(3, 0xFFFF7E01)  # qNaN
    program += li(4, 0xFFFF7C01)  # sNaN
    program += li(5, 0xFFFFC000)  # -2.0h
    program += li(6, 0xFFFF3E00)  # +1.5h
    program += li(7, 0x00003E00)  # unboxed -> canonical qNaN
    cases = (
        (10, 2, 1, 2),  # FEQ(+0, -0) -> true, no NV
        (11, 2, 3, 6),  # FEQ(qNaN, number) -> false, no NV
        (12, 2, 4, 6),  # FEQ(sNaN, number) -> false, NV
        (13, 1, 3, 6),  # FLT(qNaN, number) -> false, NV
        (14, 0, 7, 6),  # FLE(unboxed, number) -> false, NV
        (15, 1, 5, 6),  # FLT(-2, +1.5) -> true, no NV
    )
    for rd, funct3, rs1, rs2 in cases:
        program += [
            csr(0, 1, 0, 1),
            op_fp(rd, rs1, rs2, 0b1010010, funct3),
            NOP, NOP, NOP, NOP,
            csr(rd + 10, 1),
        ]
    assert run(extensions, program, tuple(range(10, 16)) + tuple(range(20, 26))) == (
        1, 0, 0, 0, 0, 1,
        0, 0, 0x10, 0x10, 0x10, 0,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_fclass_all_categories_and_unboxed(extensions):
    values = (
        0xFFFFFC00,  # -inf
        0xFFFFC000,  # negative normal
        0xFFFF8001,  # negative subnormal
        0xFFFF8000,  # -0
        0xFFFF0000,  # +0
        0xFFFF0001,  # positive subnormal
        0xFFFF3C00,  # positive normal
        0xFFFF7C00,  # +inf
        0xFFFF7C01,  # sNaN
        0xFFFF7E00,  # qNaN
        0x00003C00,  # unboxed -> canonical qNaN
    )
    program = []
    for reg, value in enumerate(values, 1):
        program += li(reg, value)
    for source, destination in zip(range(1, 12), range(12, 23)):
        program.append(op_fp(destination, source, 0, 0b1110010, 1))
    program += [NOP, NOP, NOP, NOP]
    assert run(extensions, program, tuple(range(12, 23))) == tuple(
        1 << category for category in range(10)
    ) + (1 << 9,)
