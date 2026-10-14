import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "zhinx_convert_support", Path(__file__).with_name("test_isa_zhinx_integer_convert.py")
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
    "RV32I+GC+ZFINX+ZHINX",
    "RV32I+GC+*+ZFINX+ZHINX",
]


def fcvt_w_h(rd, rs1, rm=0, unsigned=False):
    return op_fp(rd, rs1, int(unsigned), 0b1100010, rm)


def fcvt_h_w(rd, rs1, rm=0, unsigned=False):
    return op_fp(rd, rs1, int(unsigned), 0b1101010, rm)


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_half_to_integer_specials_nan_box_and_flag_priority(extensions):
    program = []
    for reg, value in (
        (1, 0xFFFFC000),  # -2.0h
        (2, 0xFFFF7E01),  # qNaN
        (3, 0xFFFFFC00),  # -inf
        (4, 0xFFFF7C00),  # +inf
        (5, 0xFFFFB800),  # -0.5h
        (6, 0x00003C00),  # unboxed +1.0h
    ):
        program += li(reg, value)

    cases = (
        (10, 0, 1, False),  # exact signed -2
        (11, 0, 2, False),  # qNaN -> INT_MAX, NV
        (12, 0, 3, True),   # -inf -> 0, NV
        (13, 0, 4, True),   # +inf -> UINT_MAX, NV
        (14, 1, 5, True),   # -0.5 RTZ -> 0, NX
        (15, 2, 5, True),   # -0.5 RDN -> 0, NV (not NX)
        (16, 0, 6, False),  # unboxed -> canonical NaN -> INT_MAX, NV
    )
    for rd, rm, rs1, unsigned in cases:
        program += [
            csr(0, 1, 0, 1),
            fcvt_w_h(rd, rs1, rm, unsigned),
            NOP, NOP, NOP, NOP,
            csr(rd + 10, 1, 0),
        ]
    program += [
        addi(17, 0, 0x55),
        fcvt_w_h(17, 1, 0b110),  # reserved static rm preserves rd
        NOP, NOP, NOP, NOP,
    ]

    assert run(extensions, program, tuple(range(10, 18)) + tuple(range(20, 27))) == (
        0xFFFFFFFE,
        0x7FFFFFFF,
        0,
        0xFFFFFFFF,
        0,
        0,
        0x7FFFFFFF,
        0x55,
        0,
        0x10,
        0x10,
        0x10,
        0x01,
        0x10,
        0x10,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_integer_to_half_all_rounding_modes_and_dynamic_frm(extensions):
    program = []
    program += li(1, 2049)
    program += li(2, -2049)
    for rm, rd in enumerate(range(10, 15)):
        program.append(fcvt_h_w(rd, 1, rm))
    for rm, rd in enumerate(range(15, 20)):
        program.append(fcvt_h_w(rd, 2, rm))
    program += [
        addi(3, 0, 3),
        csr(0, 2, 3, 1),
        fcvt_h_w(20, 1, 0b111),  # dynamic RUP
        NOP, NOP, NOP, NOP,
        csr(21, 1, 0),
    ]

    assert run(extensions, program, tuple(range(10, 22))) == (
        0xFFFF6800,
        0xFFFF6800,
        0xFFFF6800,
        0xFFFF6801,
        0xFFFF6801,
        0xFFFFE800,
        0xFFFFE800,
        0xFFFFE801,
        0xFFFFE800,
        0xFFFFE801,
        0xFFFF6801,
        0x01,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_integer_to_half_unsigned_overflow_flags_and_illegal_dynamic(extensions):
    program = []
    for reg, value in (
        (1, -2),
        (2, 65504),
        (3, 65519),
        (4, 65520),
        (5, 65535),
        (6, -65520),
    ):
        program += li(reg, value)

    cases = (
        (10, 0, 1, False),
        (11, 0, 2, True),
        (12, 0, 3, True),
        (13, 0, 4, True),
        (14, 1, 5, True),
        (15, 2, 6, False),
    )
    for rd, rm, rs1, unsigned in cases:
        program += [
            csr(0, 1, 0, 1),
            fcvt_h_w(rd, rs1, rm, unsigned),
            NOP, NOP, NOP, NOP,
            csr(rd + 10, 1, 0),
        ]
    program += [
        addi(7, 0, 5),
        addi(16, 0, 0x55),
        csr(0, 2, 7, 1),
        fcvt_h_w(16, 1, 0b111, True),  # invalid dynamic frm preserves rd
        NOP, NOP, NOP, NOP,
    ]

    assert run(extensions, program, tuple(range(10, 17)) + tuple(range(20, 26))) == (
        0xFFFFC000,
        0xFFFF7BFF,
        0xFFFF7BFF,
        0xFFFF7C00,
        0xFFFF7BFF,
        0xFFFFFC00,
        0x55,
        0,
        0,
        0x01,
        0x05,
        0x05,
        0x05,
    )
