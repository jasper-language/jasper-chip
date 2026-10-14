from pathlib import Path
import importlib.util

import pytest


_path = Path(__file__).with_name("test_isa_zfh_add_sub.py")
_spec = importlib.util.spec_from_file_location("jasper_zfinx_cmp_support", _path)
support = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(support)
runtime = support.runtime


def _compare(rd, function, a, b):
    return runtime.enc_r(runtime.OP_FP, rd, function, a, b, 0b1010000)


def _classify(rd, source):
    return runtime.enc_r(runtime.OP_FP, rd, 0b001, source, 0, 0b1110000)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_compare_nan_zero_order_flags_and_integer_dependency(extensions):
    values = ((1, 0x7fc01234), (2, 0x7f800001), (3, 0xc0000000),
              (4, 0x3fc00000), (5, 0x00000000), (6, 0x80000000))
    prog = []
    for reg, value in values:
        prog += support._li(reg, value)
    cases = ((10, 0b010, 1, 4), (11, 0b001, 1, 4),
             (12, 0b010, 2, 4), (13, 0b000, 3, 4),
             (14, 0b001, 4, 3), (15, 0b010, 5, 6))
    for rd, function, a, b in cases:
        prog += [support._csr_clear()] + [runtime.nop()] * 4 + [
            _compare(rd, function, a, b), support._csr_read(rd + 10)]
    prog += [_compare(16, 0b000, 3, 4),
             runtime.enc_i(runtime.OP_IMM, 17, 0, 16, 1)]
    assert support._run(extensions, prog, tuple(range(10, 18)) +
                        tuple(range(20, 26))) == (
        0, 0, 0, 1, 0, 1, 1, 2,
        0, 0b10000, 0b10000, 0, 0, 0)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_classify_all_representative_categories(extensions):
    values = ((1, 0xff800000), (2, 0xbf800000), (3, 0x80000001),
              (4, 0x80000000), (5, 0x00000000), (6, 0x00000001),
              (7, 0x3f800000), (8, 0x7f800000), (9, 0x7f800001),
              (10, 0x7fc00001))
    prog = []
    for reg, value in values:
        prog += support._li(reg, value)
    for rd, source in zip(range(20, 30), range(1, 11)):
        prog.append(_classify(rd, source))
    assert support._run(extensions, prog, tuple(range(20, 30))) == tuple(1 << bit for bit in range(10))
