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
def test_zhinx_sqrt_rounding_nan_boxing_specials_and_illegal_rm(extensions):
    program = []
    program += li(1, 0xFFFF4000)  # +2.0h
    program += li(2, 0xFFFF8000)  # -0.0h
    program += li(3, 0xFFFF7E01)  # qNaN
    program += li(4, 0xFFFF7C01)  # sNaN
    program += li(5, 0xFFFFC400)  # -4.0h
    program += li(6, 0x00004400)  # unboxed +4.0h
    program += [
        addi(20, 0, 0x55),
        addi(21, 0, 0x66),
        addi(22, 0, 0x77),
        addi(23, 0, 3),
        csr(0, 1, 0, 1),
        op_fp(10, 1, 0, 0b0101110, 0b000),  # RNE
        op_fp(11, 1, 0, 0b0101110, 0b001),  # RTZ
        op_fp(12, 1, 0, 0b0101110, 0b010),  # RDN
        op_fp(13, 1, 0, 0b0101110, 0b011),  # RUP
        op_fp(14, 1, 0, 0b0101110, 0b100),  # RMM
        csr(0, 2, 23, 1),
        op_fp(15, 1, 0, 0b0101110, 0b111),  # dynamic RUP
        op_fp(16, 2, 0, 0b0101110, 0b000),  # preserve -0
        op_fp(17, 3, 0, 0b0101110, 0b000),  # qNaN, no NV
        op_fp(18, 4, 0, 0b0101110, 0b000),  # sNaN, NV
        op_fp(19, 5, 0, 0b0101110, 0b000),  # negative finite, NV
        op_fp(26, 6, 0, 0b0101110, 0b000),  # unboxed -> canonical qNaN
        op_fp(20, 1, 0, 0b0101110, 0b101),  # reserved static rm
        op_fp(21, 1, 0, 0b0101110, 0b110),  # reserved static rm
        addi(25, 0, 5),
        csr(0, 2, 25, 1),
        op_fp(22, 1, 0, 0b0101110, 0b111),  # invalid dynamic frm
        NOP, NOP, NOP, NOP,
        csr(24, 1, 0),
    ]
    assert run(extensions, program, tuple(range(10, 27))) == (
        0xFFFF3DA8,
        0xFFFF3DA8,
        0xFFFF3DA8,
        0xFFFF3DA9,
        0xFFFF3DA8,
        0xFFFF3DA9,
        0xFFFF8000,
        0xFFFF7E00,
        0xFFFF7E00,
        0xFFFF7E00,
        0x55,
        0x66,
        0x77,
        3,
        0x11,
        5,
        0xFFFF7E00,
    )
