from pathlib import Path
import importlib.util

import pytest


_path = Path(__file__).with_name("test_isa_zfh_add_sub.py")
_spec = importlib.util.spec_from_file_location("jasper_zfinx_sign_support", _path)
support = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(support)
runtime = support.runtime


@pytest.mark.parametrize("extensions", ["RV32I+GC+ZFINX", "RV32I+GC+*+ZFINX"])
def test_zfinx_sign_injection_x_registers_forwarding_and_excluded_moves(extensions):
    prog = support._li(1, 0x3f800001) + support._li(2, 0x80000000)
    prog += support._li(10, 0x55) + support._li(11, 0x66)
    prog += [
        runtime.enc_r(runtime.OP_FP, 3, 0b000, 1, 2, 0b0010000),
        runtime.enc_r(runtime.OP_FP, 4, 0b001, 1, 2, 0b0010000),
        runtime.enc_r(runtime.OP_FP, 5, 0b010, 1, 2, 0b0010000),
        runtime.enc_i(runtime.OP_IMM, 6, 0, 3, 0),
        runtime.enc_r(runtime.OP_FP, 10, 0, 1, 0, 0b1110000),
        runtime.enc_r(runtime.OP_FP, 11, 0, 1, 0, 0b1111000),
    ]
    assert support._run(extensions, prog, (1, 2, 3, 4, 5, 6, 10, 11)) == (
        0x3f800001, 0x80000000, 0xbf800001, 0x3f800001,
        0xbf800001, 0xbf800001, 0x55, 0x66)


def test_plain_star_keeps_f_register_mode_when_finx_is_not_explicit():
    prog = support._li(1, 0x3f800001) + support._li(2, 0x80000000)
    prog += [runtime.enc_r(runtime.OP_FP, 3, 0b000, 1, 2, 0b0010000)]
    assert support._run("RV32I+GC+*", prog, (3,)) == (0,)
