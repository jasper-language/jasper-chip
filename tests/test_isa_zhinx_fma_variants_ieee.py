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
def test_zhinx_fmsub_fnmsub_fnmadd_fused_rounding_and_exceptions(extensions):
    program = []
    program += li(1, 0xFFFF7BFF)   # maximum positive finite
    program += li(2, 0xFFFF4000)   # +2.0h
    program += li(3, 0xFFFF0000)   # +0
    program += li(4, 0xFFFF0001)   # minimum positive subnormal
    program += li(5, 0xFFFF3800)   # +0.5h
    program += li(6, 0xFFFF3C00)   # +1.0h
    program += li(7, 0xFFFF7C00)   # +inf
    program += li(8, 0xFFFF7C01)   # sNaN
    program += li(9, 0x00004000)   # unboxed +2.0h
    program += li(29, 0xFFFF3C01)  # 1 + 2^-10
    program += li(30, 0xFFFF3BFE)  # 1 - 2^-10
    program += li(31, 0xFFFFBC00)  # -1.0h
    program += [
        csr(0, 1, 0, 1),

        # FMSUB.H positive overflow under every static rounding mode.
        fma(0x47, 10, 1, 2, 3, 0b000),
        fma(0x47, 11, 1, 2, 3, 0b001),
        fma(0x47, 12, 1, 2, 3, 0b010),
        fma(0x47, 13, 1, 2, 3, 0b011),
        fma(0x47, 14, 1, 2, 3, 0b100),

        # FNMSUB.H negative halfway underflow under every static mode.
        fma(0x4B, 15, 4, 5, 3, 0b000),
        fma(0x4B, 16, 4, 5, 3, 0b001),
        fma(0x4B, 17, 4, 5, 3, 0b010),
        fma(0x4B, 18, 4, 5, 3, 0b011),
        fma(0x4B, 19, 4, 5, 3, 0b100),

        fma(0x4F, 20, 3, 7, 6, 0b000),  # -(0 * inf) - 1 -> qNaN, NV

        # These distinguish a fused operation from rounded multiply + add.
        fma(0x47, 21, 29, 30, 6, 0b000),   # product - 1 = -2^-20
        fma(0x4B, 22, 29, 30, 6, 0b000),   # -product + 1 = +2^-20
        fma(0x4F, 23, 29, 30, 31, 0b000),  # -product - (-1) = +2^-20
        NOP, NOP, NOP, NOP,
        csr(26, 1, 0),
    ]

    assert run(extensions, program, tuple(range(10, 24)) + (26,)) == (
        0xFFFF7C00,
        0xFFFF7BFF,
        0xFFFF7BFF,
        0xFFFF7C00,
        0xFFFF7C00,
        0xFFFF8000,
        0xFFFF8000,
        0xFFFF8001,
        0xFFFF8000,
        0xFFFF8001,
        0xFFFF7E00,
        0xFFFF8010,
        0xFFFF0010,
        0xFFFF0010,
        0x17,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zhinx_fma_variants_nan_box_dynamic_and_illegal_rm(extensions):
    program = []
    program += li(1, 0xFFFF0001)  # minimum positive subnormal
    program += li(2, 0xFFFF3800)  # +0.5h
    program += li(3, 0xFFFF0000)  # +0
    program += li(4, 0x00004000)  # unboxed +2.0h
    program += li(5, 0xFFFF3C00)  # +1.0h
    program += li(6, 0xFFFF7C01)  # sNaN
    program += [
        addi(7, 0, 3),
        addi(8, 0, 5),
        addi(11, 0, 0x55),
        addi(12, 0, 0x66),
        addi(13, 0, 0x77),
        csr(0, 1, 0, 1),
        csr(0, 2, 7, 1),
        fma(0x4F, 10, 1, 2, 3, 0b111),  # dynamic RUP -> -0
        fma(0x47, 14, 4, 5, 5, 0b000),  # unboxed operand -> qNaN
        fma(0x4B, 15, 6, 5, 5, 0b000),  # sNaN -> qNaN, NV
        fma(0x47, 11, 1, 2, 3, 0b101),  # reserved static rm
        fma(0x4B, 12, 1, 2, 3, 0b110),  # reserved static rm
        csr(0, 2, 8, 1),
        fma(0x4F, 13, 1, 2, 3, 0b111),  # invalid dynamic frm
        NOP, NOP, NOP, NOP,
    ]

    assert run(extensions, program, (10, 11, 12, 13, 14, 15)) == (
        0xFFFF8000,
        0x55,
        0x66,
        0x77,
        0xFFFF7E00,
        0xFFFF7E00,
    )
