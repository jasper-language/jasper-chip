from pathlib import Path
import importlib.util

import pytest


_path = Path(__file__).with_name("test_isa_zfh_add_sub.py")
_spec = importlib.util.spec_from_file_location("jasper_zfa_round_h_support", _path)
support = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(support)
runtime = support.runtime


def _round(fd, rm, fs1, nx=False):
    return runtime.enc_r(runtime.OP_FP, fd, rm, fs1, 5 if nx else 4, 0b0100010)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH+ZFA", "RV32I+GC+*"])
def test_zfa_round_h_all_modes_dynamic_ties_zero_and_nx(extensions):
    prog = support._load_halves(((1, 0x3e00), (2, 0x4100), (3, 0xbe00),
                                 (4, 0x3a00), (5, 0xba00), (6, 0x3800),
                                 (7, 0x6800)))
    prog += [support._csr_clear(), _round(10, 0, 1), support._fmv_x_h(10, 10),
             support._csr_read(20), support._csr_clear(),
             _round(11, 0, 2, nx=True), support._fmv_x_h(11, 11),
             support._csr_read(21),
             _round(12, 2, 3), support._fmv_x_h(12, 12),
             _round(13, 3, 3), support._fmv_x_h(13, 13),
             _round(14, 1, 4), support._fmv_x_h(14, 14),
             _round(15, 3, 5), support._fmv_x_h(15, 15),
             _round(16, 4, 4), support._fmv_x_h(16, 16),
             _round(17, 0, 6), support._fmv_x_h(17, 17),
             _round(18, 4, 6), support._fmv_x_h(18, 18),
             _round(19, 0, 7), support._fmv_x_h(19, 19)]
    prog += support._li(9, 1)
    prog += [(0x002 << 20) | (9 << 15) | (0b001 << 12) | 0x73,
             _round(22, 7, 1), support._fmv_x_h(22, 22)]
    assert support._run(extensions, prog, tuple(range(10, 20)) +
                        (20, 21, 22)) == (
        0x4000, 0x4000, 0xffffc000, 0xffffbc00, 0, 0xffff8000,
        0x3c00, 0, 0x3c00, 0x6800, 0, 0b00001, 0x3c00)


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFH+ZFA", "RV32I+GC+*"])
def test_zfa_round_h_special_nan_box_and_reserved_rm(extensions):
    prog = support._load_halves(((1, 0x7e01), (2, 0x7d01), (3, 0x7c00),
                                 (10, 0x3c00), (11, 0x3c00)))
    prog += [support._csr_clear(), _round(12, 0, 1), support._fmv_x_h(12, 12),
             support._csr_read(20), support._csr_clear(),
             _round(13, 0, 2), support._fmv_x_h(13, 13), support._csr_read(21),
             _round(14, 0, 3), support._fmv_x_h(14, 14),
             _round(10, 5, 1), support._fmv_x_h(10, 10)]
    prog += support._li(7, 0x3e00)
    prog += [runtime.enc_r(runtime.OP_FP, 7, 0, 7, 0, 0b1111000),
             support._csr_clear(), _round(15, 0, 7), support._fmv_x_h(15, 15),
             support._csr_read(22)]
    prog += support._li(9, 5)
    prog += [(0x002 << 20) | (9 << 15) | (0b001 << 12) | 0x73,
             _round(11, 7, 1), support._fmv_x_h(11, 11)]
    assert support._run(extensions, prog, (10, 11, 12, 13, 14, 15, 20, 21, 22)) == (
        0x3c00, 0x3c00, 0x7e00, 0x7e00, 0x7c00, 0x7e00,
        0, 0b10000, 0)
