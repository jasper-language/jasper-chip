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
def test_zhinx_div_rounding_nan_boxing_exceptions_and_illegal_rm(extensions):
    program = []
    program += li(1, 0xFFFF3C00)  # +1.0h
    program += li(2, 0xFFFF4200)  # +3.0h
    program += li(3, 0xFFFFBC00)  # -1.0h
    program += li(4, 0xFFFF0000)  # +0
    program += li(5, 0xFFFF7C00)  # +inf
    program += li(6, 0xFFFF7C01)  # sNaN
    program += li(7, 0x00003C00)  # unboxed +1.0h
    program += [
        addi(22, 0, 0x55),
        addi(23, 0, 0x66),
        addi(24, 0, 0x77),
        addi(25, 0, 3),
        addi(26, 0, 5),
        csr(0, 1, 0, 1),
        op_fp(10, 1, 2, 0b0001110, 0b000),  # RNE
        op_fp(11, 1, 2, 0b0001110, 0b001),  # RTZ
        op_fp(12, 1, 2, 0b0001110, 0b010),  # RDN
        op_fp(13, 1, 2, 0b0001110, 0b011),  # RUP
        op_fp(14, 1, 2, 0b0001110, 0b100),  # RMM
        op_fp(15, 3, 2, 0b0001110, 0b010),  # negative RDN
        op_fp(16, 3, 2, 0b0001110, 0b011),  # negative RUP
        op_fp(17, 1, 4, 0b0001110, 0b000),  # finite / zero, DZ
        op_fp(18, 4, 4, 0b0001110, 0b000),  # zero / zero, NV
        op_fp(19, 5, 5, 0b0001110, 0b000),  # inf / inf, NV
        op_fp(20, 6, 1, 0b0001110, 0b000),  # sNaN, NV
        op_fp(21, 7, 1, 0b0001110, 0b000),  # unboxed -> canonical qNaN
        csr(0, 2, 25, 1),
        op_fp(28, 1, 2, 0b0001110, 0b111),  # dynamic RUP
        op_fp(22, 1, 2, 0b0001110, 0b101),  # reserved static rm
        op_fp(23, 1, 2, 0b0001110, 0b110),  # reserved static rm
        csr(0, 2, 26, 1),
        op_fp(24, 1, 2, 0b0001110, 0b111),  # invalid dynamic frm
        NOP, NOP, NOP, NOP,
        csr(27, 1, 0),
    ]
    assert run(extensions, program, tuple(range(10, 25)) + (27, 28)) == (
        0xFFFF3555,
        0xFFFF3555,
        0xFFFF3555,
        0xFFFF3556,
        0xFFFF3555,
        0xFFFFB556,
        0xFFFFB555,
        0xFFFF7C00,
        0xFFFF7E00,
        0xFFFF7E00,
        0xFFFF7E00,
        0xFFFF7E00,
        0x55,
        0x66,
        0x77,
        0x19,
        0xFFFF3556,
    )
