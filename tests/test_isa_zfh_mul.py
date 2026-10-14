from pathlib import Path
import importlib.util

import pytest


_path = Path(__file__).with_name("test_isa_zfh_add_sub.py")
_spec = importlib.util.spec_from_file_location("jasper_zfh_add_support", _path)
support = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(support)
runtime = support.runtime


def _fmul(fd, rm, a, b): return runtime.enc_r(runtime.OP_FP, fd, rm, a, b, 0b0001010)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_mul_all_rounding_modes_dynamic_and_underflow(extensions):
    prog = support._load_halves(((1, 0x3e00), (2, 0x4000), (3, 0xbe00),
                                 (4, 0x3c01), (5, 0x0001), (6, 0x3800)))
    prog.append(support._csr_clear())
    cases = ((10, 0, 1, 2), (11, 0, 3, 2), (12, 0, 4, 4),
             (13, 1, 4, 4), (14, 2, 4, 4), (15, 3, 4, 4), (16, 4, 4, 4))
    for fd, rm, a, b in cases:
        prog += [_fmul(fd, rm, a, b), support._fmv_x_h(fd, fd)]
    prog += support._li(9, 3)
    prog += [(0x002 << 20) | (9 << 15) | (0b001 << 12) | 0x73,
             _fmul(17, 7, 4, 4), support._fmv_x_h(17, 17), support._csr_read(20),
             support._csr_clear(), _fmul(18, 0, 5, 6), support._fmv_x_h(18, 18),
             support._csr_read(21)]
    assert support._run(extensions, prog, tuple(range(10, 19)) + (20, 21)) == (
        0x4200, 0xffffc200, 0x3c02, 0x3c02, 0x3c02, 0x3c03, 0x3c02,
        0x3c03, 0, 0b00001, 0b00011)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH", "RV32I+GC+*"])
def test_zfh_mul_special_overflow_nan_box_and_flags(extensions):
    prog = support._load_halves(((1, 0x7bff), (2, 0x4000), (3, 0x7c00),
                                 (4, 0x0000), (5, 0x7d01), (6, 0x7e01), (7, 0x3c00)))
    cases = ((10, 0, 1, 2), (11, 1, 1, 2), (12, 0, 3, 4),
             (13, 0, 5, 7), (14, 0, 6, 7))
    for fd, rm, a, b in cases:
        prog += [support._csr_clear(), _fmul(fd, rm, a, b), support._fmv_x_h(fd, fd),
                 support._csr_read(fd + 10)]
    prog += support._li(8, 0x3c00)
    prog += [runtime.enc_r(runtime.OP_FP, 8, 0, 8, 0, 0b1111000), support._csr_clear(),
             _fmul(15, 0, 8, 7), support._fmv_x_h(15, 15), support._csr_read(25)]
    assert support._run(extensions, prog, tuple(range(10, 16)) + tuple(range(20, 26))) == (
        0x7c00, 0x7bff, 0x7e00, 0x7e00, 0x7e00, 0x7e00,
        0b00101, 0b00101, 0b10000, 0b10000, 0, 0)
