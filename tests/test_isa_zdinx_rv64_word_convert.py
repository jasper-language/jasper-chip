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
def test_zdinx_rv64_word_to_double_conversions(extensions):
    program = [
        addi(1, 0, -2),
        addi(2, 0, -1),
        op_fp(10, 1, 0, 0b1101001),
        op_fp(11, 2, 1, 0b1101001),
        NOP, NOP, NOP, NOP,
    ]
    assert run(extensions, program, (10, 11)) == (
        0xC000000000000000,
        0x41EFFFFFFFE00000,
    )


@pytest.mark.parametrize("extensions", EXTENSIONS)
def test_zdinx_rv64_double_to_word_rounding_saturation_and_flags(extensions):
    program = []
    program += load_double_bits(1, 0x40040000)  # +2.5
    program += load_double_bits(2, 0xC0040000)  # -2.5
    program += load_double_bits(3, 0x41E00000)  # +2^31
    program += load_double_bits(4, 0xBFF00000)  # -1.0
    program += [
        addi(5, 0, 2),
        csr(0, 1, 0, 1),
        op_fp(10, 1, 0, 0b1100001, 0b000),  # RNE: +2.5 -> 2
        op_fp(11, 1, 0, 0b1100001, 0b100),  # RMM: +2.5 -> 3
        csr(0, 2, 5, 1),
        op_fp(12, 2, 0, 0b1100001, 0b111),  # dynamic RDN: -2.5 -> -3
        op_fp(13, 3, 0, 0b1100001, 0b001),  # signed overflow
        op_fp(14, 4, 1, 0b1100001, 0b001),  # negative to unsigned
        NOP, NOP, NOP, NOP,
        csr(15, 1, 0),
    ]
    assert run(extensions, program, (10, 11, 12, 13, 14, 15)) == (
        2,
        3,
        0xFFFFFFFFFFFFFFFD,
        0x000000007FFFFFFF,
        0,
        0x11,
    )
