"""Shared combinational primitives for the RV32 scalar AES instructions."""

from amaranth import Array, C, Cat, Mux


def _gf_mul(a, b):
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        a = ((a << 1) ^ (0x11B if a & 0x80 else 0)) & 0xFF
        b >>= 1
    return result


def _rotl8(value, amount):
    return ((value << amount) | (value >> (8 - amount))) & 0xFF


def _make_sboxes():
    forward = []
    for value in range(256):
        inverse = 0 if value == 0 else next(x for x in range(1, 256) if _gf_mul(value, x) == 1)
        forward.append(inverse ^ _rotl8(inverse, 1) ^ _rotl8(inverse, 2) ^
                       _rotl8(inverse, 3) ^ _rotl8(inverse, 4) ^ 0x63)
    inverse = [0] * 256
    for index, value in enumerate(forward):
        inverse[value] = index
    return tuple(forward), tuple(inverse)


AES_SBOX, AES_INV_SBOX = _make_sboxes()


def aes_sbox(value, inverse=False):
    forward = Array(C(entry, 8) for entry in AES_SBOX)[value]
    backward = Array(C(entry, 8) for entry in AES_INV_SBOX)[value]
    return backward if inverse is True else forward if inverse is False else Mux(inverse, backward, forward)


def aes_xtime(value):
    shifted = Cat(C(0, 1), value[0:7])
    return shifted ^ Mux(value[7], C(0x1B, 8), C(0, 8))


def aes_mix_byte(value, inverse=False):
    x2 = aes_xtime(value)
    forward = Cat(x2, value, value, value ^ x2)
    x4 = aes_xtime(x2)
    x8 = aes_xtime(x4)
    backward = Cat(x2 ^ x4 ^ x8, value ^ x8,
                   value ^ x4 ^ x8, value ^ x2 ^ x8)
    return backward if inverse is True else forward if inverse is False else Mux(inverse, backward, forward)


def rol32_by_byte_select(value, bs):
    return Array([
        value,
        Cat(value[24:32], value[0:24]),
        Cat(value[16:32], value[0:16]),
        Cat(value[8:32], value[0:8]),
    ])[bs]


def aes32_result(rs1, rs2, funct7, inverse=False, mix=False):
    bs = funct7[5:7]
    selected = Array([rs2[0:8], rs2[8:16], rs2[16:24], rs2[24:32]])[bs]
    substituted = aes_sbox(selected, inverse=inverse)
    unmixed = Cat(substituted, C(0, 24))
    mixed = aes_mix_byte(substituted, inverse=inverse)
    transformed = mixed if mix is True else unmixed if mix is False else Mux(mix, mixed, unmixed)
    return rs1 ^ rol32_by_byte_select(transformed, bs)
