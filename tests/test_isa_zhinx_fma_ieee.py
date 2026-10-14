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
fma = _support.fma
addi = _support.addi
csr = _support.csr
NOP = _support.NOP


EXTENSIONS = [
    "RV32I+GC+ZFINX+ZHINX",
    "RV32I+GC+*+ZFINX+ZHINX",
]


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_fma_overflow_underflow_specials_and_illegal_rm(extensions):
    program = []
    program += li(1, 0xFFFF7BFF)  # maximum positive finite
    program += li(2, 0xFFFF4000)  # +2.0h
    program += li(3, 0xFFFF0000)  # +0
    program += li(4, 0xFFFF0001)  # minimum positive subnormal
    program += li(5, 0xFFFF3800)  # +0.5h
    program += li(6, 0xFFFF3C00)  # +1.0h
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
        fma(0x43, 10, 1, 2, 3, 0b000),  # overflow RNE -> +inf
        fma(0x43, 11, 1, 2, 3, 0b001),  # overflow RTZ -> +max
        fma(0x43, 12, 1, 2, 3, 0b010),  # overflow RDN -> +max
        fma(0x43, 13, 1, 2, 3, 0b011),  # overflow RUP -> +inf
        fma(0x43, 14, 1, 2, 3, 0b100),  # overflow RMM -> +inf
        fma(0x43, 15, 4, 5, 3, 0b000),  # tie underflow RNE -> +0
        fma(0x43, 16, 4, 5, 3, 0b010),  # tie underflow RDN -> +0
        fma(0x43, 17, 4, 5, 3, 0b011),  # tie underflow RUP -> +min
        fma(0x43, 18, 4, 5, 3, 0b100),  # tie underflow RMM -> +min
        fma(0x43, 19, 3, 7, 6, 0b000),  # zero * inf + one -> qNaN, NV
        fma(0x43, 20, 8, 6, 6, 0b000),  # sNaN -> canonical, NV
        fma(0x43, 21, 9, 6, 6, 0b000),  # unboxed -> canonical qNaN
        csr(0, 2, 25, 1),
        fma(0x43, 28, 4, 5, 3, 0b111),  # dynamic RUP -> +min
        fma(0x43, 22, 1, 2, 3, 0b101),  # reserved static rm
        fma(0x43, 23, 1, 2, 3, 0b110),  # reserved static rm
        csr(0, 2, 26, 1),
        fma(0x43, 24, 1, 2, 3, 0b111),  # invalid dynamic frm
        NOP, NOP, NOP, NOP,
        csr(27, 1, 0),
    ]
    assert run(extensions, program, tuple(range(10, 25)) + (27, 28)) == (
        0xFFFF7C00,
        0xFFFF7BFF,
        0xFFFF7BFF,
        0xFFFF7C00,
        0xFFFF7C00,
        0xFFFF0000,
        0xFFFF0000,
        0xFFFF0001,
        0xFFFF0001,
        0xFFFF7E00,
        0xFFFF7E00,
        0xFFFF7E00,
        0x55,
        0x66,
        0x77,
        0x17,
        0xFFFF0001,
    )
