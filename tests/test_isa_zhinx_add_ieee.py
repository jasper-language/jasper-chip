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
def test_zhinx_add_overflow_zero_nan_boxing_and_illegal_rm(extensions):
    program = []
    program += li(1, 0xFFFF7BFF)  # maximum positive finite
    program += li(2, 0xFFFFFBFF)  # maximum negative finite
    program += li(3, 0xFFFF0000)  # +0
    program += li(4, 0xFFFF8000)  # -0
    program += li(5, 0xFFFF7C01)  # sNaN
    program += li(6, 0x00007BFF)  # unboxed maximum finite
    program += [
        addi(20, 0, 0x55),
        addi(21, 0, 0x66),
        addi(22, 0, 0x77),
        addi(23, 0, 1),
        addi(25, 0, 5),
        csr(0, 1, 0, 1),
        op_fp(10, 1, 1, 0b0000010, 0b000),  # RNE -> +inf
        op_fp(11, 1, 1, 0b0000010, 0b001),  # RTZ -> +max
        op_fp(12, 1, 1, 0b0000010, 0b010),  # RDN -> +max
        op_fp(13, 1, 1, 0b0000010, 0b011),  # RUP -> +inf
        op_fp(14, 1, 1, 0b0000010, 0b100),  # RMM -> +inf
        op_fp(15, 2, 2, 0b0000010, 0b010),  # RDN -> -inf
        op_fp(16, 2, 2, 0b0000010, 0b011),  # RUP -> -max
        op_fp(17, 3, 4, 0b0000010, 0b000),  # +0 + -0 -> +0
        op_fp(18, 3, 4, 0b0000010, 0b010),  # RDN zero -> -0
        op_fp(19, 5, 1, 0b0000010, 0b000),  # sNaN -> canonical, NV
        op_fp(26, 6, 1, 0b0000010, 0b000),  # unboxed -> canonical qNaN
        csr(0, 2, 23, 1),
        op_fp(27, 1, 1, 0b0000010, 0b111),  # dynamic RTZ -> +max
        op_fp(20, 1, 1, 0b0000010, 0b101),  # reserved static rm
        op_fp(21, 1, 1, 0b0000010, 0b110),  # reserved static rm
        csr(0, 2, 25, 1),
        op_fp(22, 1, 1, 0b0000010, 0b111),  # invalid dynamic frm
        NOP, NOP, NOP, NOP,
        csr(24, 1, 0),
    ]
    assert run(extensions, program, tuple(range(10, 28))) == (
        0xFFFF7C00,
        0xFFFF7BFF,
        0xFFFF7BFF,
        0xFFFF7C00,
        0xFFFF7C00,
        0xFFFFFC00,
        0xFFFFFBFF,
        0xFFFF0000,
        0xFFFF8000,
        0xFFFF7E00,
        0x55,
        0x66,
        0x77,
        1,
        0x15,
        5,
        0xFFFF7E00,
        0xFFFF7BFF,
    )
