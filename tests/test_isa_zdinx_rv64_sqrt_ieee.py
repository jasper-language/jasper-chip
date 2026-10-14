import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "zdinx_support", Path(__file__).with_name("test_isa_zdinx_rv64_sign_compare.py")
)
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)

run = _support.run
load_double_bits = _support.load_double_bits
op_fp = _support.op_fp
addi = _support.addi
NOP = _support.NOP


def csr(rd, address, rs1, funct3=2):
    return (address << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x73


EXTENSIONS = ["RV64I+GC+ZDINX", "RV64I+GC+*+ZDINX"]


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zdinx_rv64_sqrt_rounding_specials_and_illegal_rm(extensions):
    program = []
    program += load_double_bits(1, 0x40000000)  # +2.0
    program += load_double_bits(2, 0x80000000)  # -0.0
    program += load_double_bits(3, 0x7FF80000)
    program += [addi(3, 3, 1)]                 # qNaN
    program += load_double_bits(4, 0x7FF00000)
    program += [addi(4, 4, 1)]                 # sNaN
    program += load_double_bits(5, 0xC0100000)  # -4.0
    program += [
        addi(20, 0, 0x55),
        addi(21, 0, 0x66),
        addi(22, 0, 0x77),
        addi(23, 0, 2),
        csr(0, 1, 0, 1),
        op_fp(10, 1, 0, 0b0101101, 0b000),  # RNE
        op_fp(11, 1, 0, 0b0101101, 0b001),  # RTZ
        op_fp(12, 1, 0, 0b0101101, 0b010),  # RDN
        op_fp(13, 1, 0, 0b0101101, 0b011),  # RUP
        op_fp(14, 1, 0, 0b0101101, 0b100),  # RMM
        csr(0, 2, 23, 1),
        op_fp(15, 1, 0, 0b0101101, 0b111),  # dynamic RDN
        op_fp(16, 2, 0, 0b0101101, 0b000),  # preserve -0
        op_fp(17, 3, 0, 0b0101101, 0b000),  # qNaN, no NV
        op_fp(18, 4, 0, 0b0101101, 0b000),  # sNaN, NV
        op_fp(19, 5, 0, 0b0101101, 0b000),  # negative finite, NV
        op_fp(20, 1, 0, 0b0101101, 0b101),  # reserved static rm
        op_fp(21, 1, 0, 0b0101101, 0b110),  # reserved static rm
        addi(25, 0, 5),
        csr(0, 2, 25, 1),
        op_fp(22, 1, 0, 0b0101101, 0b111),  # invalid dynamic frm
        NOP, NOP, NOP, NOP,
        csr(24, 1, 0),
    ]
    assert run(extensions, program, tuple(range(10, 26))) == (
        0x3FF6A09E667F3BCD,
        0x3FF6A09E667F3BCC,
        0x3FF6A09E667F3BCC,
        0x3FF6A09E667F3BCD,
        0x3FF6A09E667F3BCD,
        0x3FF6A09E667F3BCC,
        0x8000000000000000,
        0x7FF8000000000000,
        0x7FF8000000000000,
        0x7FF8000000000000,
        0x55,
        0x66,
        0x77,
        2,
        0x11,
        5,
    )
