from pathlib import Path
import importlib.util

import pytest


_path = Path(__file__).with_name("test_isa_zfh_add_sub.py")
_spec = importlib.util.spec_from_file_location("jasper_zfh_div_support", _path)
support = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(support)
runtime = support.runtime


def _fdiv(fd, rm, a, b): return runtime.enc_r(runtime.OP_FP, fd, rm, a, b, 0b0001110)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_div_all_rounding_modes_dynamic_and_underflow(extensions):
    prog = support._load_halves(((1, 0x4600), (2, 0x4000), (3, 0x3c00),
                                 (4, 0x4200), (5, 0xbc00), (6, 0x0001), (7, 0x3800)))
    prog.append(support._csr_clear())
    cases = ((10, 0, 1, 2), (11, 0, 3, 4), (12, 1, 3, 4),
             (13, 2, 3, 4), (14, 3, 3, 4), (15, 4, 3, 4),
             (16, 2, 5, 4), (17, 3, 5, 4))
    for fd, rm, a, b in cases:
        prog += [_fdiv(fd, rm, a, b), support._fmv_x_h(fd, fd)]
    prog += support._li(9, 3)
    prog += [(0x002 << 20) | (9 << 15) | (0b001 << 12) | 0x73,
             _fdiv(18, 7, 3, 4), support._fmv_x_h(18, 18), support._csr_read(20),
             support._csr_clear(), _fdiv(19, 0, 6, 2), support._fmv_x_h(19, 19),
             support._csr_read(21)]
    assert support._run(extensions, prog, tuple(range(10, 20)) + (20, 21)) == (
        0x4200, 0x3555, 0x3555, 0x3555, 0x3556, 0x3555,
        0xffffb556, 0xffffb555, 0x3556, 0, 0b00001, 0b00011)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_div_special_overflow_zero_nan_box_and_flags(extensions):
    prog = support._load_halves(((1, 0x7bff), (2, 0x0001), (3, 0x3c00),
                                 (4, 0xbc00), (5, 0x0000), (6, 0x7c00),
                                 (7, 0x7e01), (8, 0x7d01)))
    cases = ((10, 0, 1, 2), (11, 1, 1, 2), (12, 0, 3, 5),
             (13, 0, 4, 5), (14, 0, 5, 5), (15, 0, 6, 6),
             (16, 0, 7, 3), (17, 0, 8, 3))
    for fd, rm, a, b in cases:
        prog += [support._csr_clear()] + [runtime.nop()] * 4 + [
                 _fdiv(fd, rm, a, b), support._fmv_x_h(fd, fd),
                 support._csr_read(fd + 10)]
    assert support._run(extensions, prog, tuple(range(10, 18)) + tuple(range(20, 28))) == (
        0x7c00, 0x7bff, 0x7c00, 0xfffffc00, 0x7e00, 0x7e00, 0x7e00, 0x7e00,
        0b00101, 0b00101, 0b01000, 0b01000, 0b10000, 0b10000, 0, 0b10000)
