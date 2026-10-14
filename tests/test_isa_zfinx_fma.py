import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "zfh_runner", Path(__file__).with_name("test_isa_zfh_add_sub.py")
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
_run = _module._run


def lui(rd, value):
    return (value & 0xFFFFF000) | (rd << 7) | 0x37


def addi(rd, rs1, immediate):
    return ((immediate & 0xFFF) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def load_immediate(rd, value):
    value &= 0xFFFFFFFF
    high = (value + 0x800) & 0xFFFFF000
    return [lui(rd, high), addi(rd, rd, (value - high) & 0xFFF)]


def fma(opcode, rd, rs1, rs2, rs3, rm=0):
    return (
        (rs3 << 27)
        | (rs2 << 20)
        | (rs1 << 15)
        | (rm << 12)
        | (rd << 7)
        | opcode
    )


def csr(rd, address, rs1, funct3=2):
    return (address << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x73


NOP = addi(0, 0, 0)


@pytest.mark.parametrize("extension", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_fma_is_fused_and_supports_all_operations(extension):
    program = []
    program += load_immediate(1, 0x3FC00000)  # 1.5
    program += load_immediate(2, 0x40000000)  # 2.0
    program += load_immediate(3, 0x3F800000)  # 1.0
    for opcode, rd in zip((0x43, 0x47, 0x4B, 0x4F), range(10, 14)):
        program += [fma(opcode, rd, 1, 2, 3), NOP, NOP, NOP, NOP]

    # (4097 * 4097) + (-16785408) is exactly +1.  A non-fused
    # multiply followed by add rounds the product first and yields zero.
    program += load_immediate(4, 0x45800800)
    program += load_immediate(5, 0x45800800)
    program += load_immediate(6, 0xCB801000)
    program += [fma(0x43, 14, 4, 5, 6), NOP, NOP, NOP, NOP]

    assert _run(extension, program, (10, 11, 12, 13, 14)) == (
        0x40800000,
        0x40000000,
        0xC0000000,
        0xC0800000,
        0x3F800000,
    )


@pytest.mark.parametrize("extension", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_fma_rounding_dynamic_frm_and_invalid_flag(extension):
    program = []
    program += load_immediate(1, 0x3FC00000)
    program += load_immediate(2, 0x40000000)
    program += load_immediate(3, 0x3F800000)
    registers = []
    for rm, rd in enumerate(range(10, 15)):
        program += [csr(0, 1, 0, 1), fma(0x43, rd, 1, 2, 3, rm), NOP, NOP, NOP, NOP]
        registers.append(rd)

    program += [csr(0, 2, 3, 5), fma(0x43, 15, 1, 2, 3, 7), NOP, NOP, NOP, NOP]
    registers.append(15)

    program += load_immediate(4, 0x00000000)
    program += load_immediate(5, 0x7F800000)
    program += [csr(0, 1, 0, 1), fma(0x43, 16, 4, 5, 3), NOP, NOP, NOP, NOP, csr(17, 1, 0)]
    registers += [16, 17]

    assert _run(extension, program, tuple(registers)) == (
        0x40800000,
        0x40800000,
        0x40800000,
        0x40800000,
        0x40800000,
        0x40800000,
        0x7FC00000,
        0x10,
    )


@pytest.mark.parametrize("extension", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_fma_rs3_forwarding_and_illegal_rounding(extension):
    program = []
    program += load_immediate(1, 0x3FC00000)
    program += load_immediate(2, 0x40000000)
    program += load_immediate(3, 0x3F800000)
    program += load_immediate(18, 0x12345678)
    program += [
        fma(0x43, 10, 1, 2, 3),
        fma(0x43, 11, 1, 2, 10),
        fma(0x43, 18, 1, 2, 3, 5),
        csr(0, 2, 6, 5),
        fma(0x43, 19, 1, 2, 3, 7),
        NOP,
        NOP,
        NOP,
        NOP,
    ]
    assert _run(extension, program, (10, 11, 18, 19)) == (
        0x40800000,
        0x40E00000,
        0x12345678,
        0,
    )
