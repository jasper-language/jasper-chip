import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "zhinx_support", Path(__file__).with_name("test_isa_zhinx_arithmetic.py")
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


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_mul_overflow_underflow_specials_and_illegal_rm(extensions):
    program = []
    program += li(1, 0xFFFF7BFF)  # maximum positive finite
    program += li(2, 0xFFFF4000)  # +2.0h
    program += li(3, 0xFFFF0001)  # minimum positive subnormal
    program += li(4, 0xFFFF3800)  # +0.5h
    program += li(5, 0xFFFF8001)  # minimum negative subnormal
    program += li(6, 0xFFFF0000)  # +0
    program += li(7, 0xFFFF7C00)  # +inf
    program += li(8, 0xFFFF7C01)  # sNaN
    program += li(9, 0x00004000)  # unboxed +2.0h
    program += [
        addi(22, 0, 0x55),
        addi(23, 0, 0x66),
        addi(24, 0, 0x77),
        addi(25, 0, 3),
        addi(26, 0, 5),
        csr(0, 1, 0, 1),
        op_fp(10, 1, 2, 0b0001010, 0b000),  # overflow RNE -> +inf
        op_fp(11, 1, 2, 0b0001010, 0b001),  # overflow RTZ -> +max
        op_fp(12, 1, 2, 0b0001010, 0b010),  # overflow RDN -> +max
        op_fp(13, 1, 2, 0b0001010, 0b011),  # overflow RUP -> +inf
        op_fp(14, 1, 2, 0b0001010, 0b100),  # overflow RMM -> +inf
        op_fp(15, 3, 4, 0b0001010, 0b000),  # tie underflow RNE -> +0
        op_fp(16, 3, 4, 0b0001010, 0b010),  # tie underflow RDN -> +0
        op_fp(17, 3, 4, 0b0001010, 0b011),  # tie underflow RUP -> +min
        op_fp(18, 3, 4, 0b0001010, 0b100),  # tie underflow RMM -> +min
        op_fp(19, 5, 4, 0b0001010, 0b010),  # negative tie RDN -> -min
        op_fp(20, 5, 4, 0b0001010, 0b011),  # negative tie RUP -> -0
        op_fp(21, 6, 7, 0b0001010, 0b000),  # zero * inf -> qNaN, NV
        op_fp(28, 8, 2, 0b0001010, 0b000),  # sNaN -> canonical, NV
        op_fp(29, 9, 2, 0b0001010, 0b000),  # unboxed -> canonical qNaN
        csr(0, 2, 25, 1),
        op_fp(30, 3, 4, 0b0001010, 0b111),  # dynamic RUP -> +min
        op_fp(22, 1, 2, 0b0001010, 0b101),  # reserved static rm
        op_fp(23, 1, 2, 0b0001010, 0b110),  # reserved static rm
        csr(0, 2, 26, 1),
        op_fp(24, 1, 2, 0b0001010, 0b111),  # invalid dynamic frm
        NOP, NOP, NOP, NOP,
        csr(27, 1, 0),
    ]
    assert run(extensions, program, tuple(range(10, 25)) + tuple(range(27, 31))) == (
        0xFFFF7C00,
        0xFFFF7BFF,
        0xFFFF7BFF,
        0xFFFF7C00,
        0xFFFF7C00,
        0xFFFF0000,
        0xFFFF0000,
        0xFFFF0001,
        0xFFFF0001,
        0xFFFF8001,
        0xFFFF8000,
        0xFFFF7E00,
        0x55,
        0x66,
        0x77,
        0x17,
        0xFFFF7E00,
        0xFFFF7E00,
        0xFFFF0001,
    )
