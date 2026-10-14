from rtl.rv12_core import normalize_extension_spec
from rtl.rv12_core import RV12Core
from rtl.rv12_core import _STANDARD_EXTENSIONS


FULL_STANDARD_EXTENSIONS = {"RV32I", "GC"} | set(_STANDARD_EXTENSIONS)
LEGACY_EXPLICIT_EXTENSIONS = {
    "RV32I", "GC", "M", "A", "B", "C", "F", "D", "ZICSR",
    "ZIFENCEI", "ZICOND",
}


def test_default_is_baseline():
    assert normalize_extension_spec(None) == {"RV32I", "GC"}


def test_gc_plus_star_enables_standard_set():
    ext = normalize_extension_spec("RV32I+GC+*")
    assert "RV32I" in ext and "GC" in ext
    assert "M" in ext and "A" in ext and "F" in ext
    assert "D" in ext and "C" in ext
    assert "ZICSR" in ext and "ZIFENCEI" in ext


def test_lowercase_alias_and_noisy_chars():
    ext = normalize_extension_spec("rv32i + gc + m + a + zicsr ")
    assert ext == {"RV32I", "GC", "M", "A", "ZICSR"}


def test_duplicate_tokens_and_order_independent_parse():
    ext = normalize_extension_spec("RV32I+GC+M+M+A+GC+F")
    assert ext == {"RV32I", "GC", "M", "A", "F"}


def test_i_alias_normalizes_to_base_and_gc():
    ext = normalize_extension_spec("I+M")

    assert ext == {"RV32I", "GC", "M"}


def test_unknown_items_are_ignored():
    ext = normalize_extension_spec("RV32I+GC+NOPE+C")
    assert "C" in ext
    assert "NOPE" not in ext


def test_runtime_extension_flags_include_requested_set_rv64():
    c = RV12Core(core_id=0, xlen=64, extensions="RV32I+GC+M+A+ZICSR")

    assert c.enable_m is True
    assert c.enable_a is True
    assert c.enable_zicsr is True
    assert c.enable_c is False
    assert c.enable_f is False
    assert c.enable_d is False


def test_runtime_extension_flags_star_rv32_and_rv64():
    c32 = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+*")
    c64 = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC+*")

    assert c32.enable_m and c32.enable_a and c32.enable_f and c32.enable_d and c32.enable_c
    assert c32.enable_zicsr and c32.enable_zifencei
    assert c64.enable_m and c64.enable_a and c64.enable_f and c64.enable_d and c64.enable_c
    assert c64.enable_zicsr and c64.enable_zifencei


def test_explicit_zifencei_flag_settable():
    c = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+ZIFENCEI")
    assert c.enable_zifencei is True
    assert c.enable_zicsr is False


def test_rv64_star_and_explicit_zifencei_mixed_case_parse():
    ext = normalize_extension_spec(" rv64I + GC + * ")
    assert "RV32I" in ext and "GC" in ext
    assert "ZIFENCEI" in ext and "ZICSR" in ext

    c = RV12Core(core_id=0, xlen=64, extensions="rv64i + gc + zifencei")
    assert c.enable_zifencei is True
    assert c.enable_zicsr is False


def test_explicit_floating_extensions_rv64_alias():
    c = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC+F+D")
    assert c.enable_f is True
    assert c.enable_d is True
    assert c.enable_m is False
    assert c.enable_a is False


def test_standard_floating_dependency_flags_are_closed():
    d = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+D")
    q = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+Q")
    zfh = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+ZFH")
    zfhmin = RV12Core(core_id=0, xlen=32,
                      extensions="RV32I+GC+ZFHMIN")

    assert d.enable_f and d.enable_d and not d.enable_q
    assert q.enable_f and q.enable_d and q.enable_q
    assert zfh.enable_f and zfh.enable_zfh and zfh.enable_zfhmin
    assert zfhmin.enable_f and not zfhmin.enable_zfh and zfhmin.enable_zfhmin


def test_star_set_includes_f_and_d_on_rv64():
    c64 = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC+*")
    assert c64.enable_f is True
    assert c64.enable_d is True
    assert c64.enable_m is True
    assert c64.enable_a is True
    assert c64.enable_c is True
    assert c64.enable_zicsr is True
    assert c64.enable_zifencei is True

def test_star_with_aliases_and_unknown_tokens_is_stable_on_rv64_like_specs():
    ext = normalize_extension_spec("  rv64i + gc + * + zba + zbb + ZBK + zifencei + zicsr + ZICOND + ??? + unknown + ")
    assert ext == FULL_STANDARD_EXTENSIONS

def test_star_with_redundant_tokens_and_case_noise_on_rv32_stays_full_set():
    ext = normalize_extension_spec("  rv32i + gc + * + * + Zba + m + M + zICOND + zicsr + ZIFENCEI + ??? + zbb + b + ")
    assert ext == FULL_STANDARD_EXTENSIONS

def test_mixed_width_alias_noise_stays_full_star_for_rv32_set():
    ext = normalize_extension_spec("RV64I + GC + * + rv32I + zba + zbb + zbh + ZBK + unknown + ??? +")
    assert ext == FULL_STANDARD_EXTENSIONS

def test_runtime_flags_match_star_with_explicit_full_standard_set_rv32():
    explicit = RV12Core(core_id=0, xlen=32,
                        extensions="RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND")
    star = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+*")

    assert explicit.enable_m == star.enable_m
    assert explicit.enable_a == star.enable_a
    assert explicit.enable_b == star.enable_b
    assert explicit.enable_c == star.enable_c
    assert explicit.enable_f == star.enable_f
    assert explicit.enable_d == star.enable_d
    assert explicit.enable_zicond == star.enable_zicond
    assert explicit.enable_zicsr == star.enable_zicsr
    assert explicit.enable_zifencei == star.enable_zifencei


def test_runtime_flags_with_noisy_aliases_match_star_rv32():
    noisy = RV12Core(core_id=0, xlen=32,
                    extensions="  rv32i + gc + * + zba + zbb + ZBK + ZBH + ??? + unknown + ")
    star = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+*")

    assert noisy.enable_m == star.enable_m
    assert noisy.enable_a == star.enable_a
    assert noisy.enable_b == star.enable_b
    assert noisy.enable_c == star.enable_c
    assert noisy.enable_f == star.enable_f
    assert noisy.enable_d == star.enable_d
    assert noisy.enable_zicond == star.enable_zicond
    assert noisy.enable_zicsr == star.enable_zicsr
    assert noisy.enable_zifencei == star.enable_zifencei

def test_star_expands_to_canonical_std_tokens_only():
    ext = normalize_extension_spec("rv32i + gc + * + zba + zbb + zbk + zbh + zicond + zicsr + zifencei")

    assert ext == FULL_STANDARD_EXTENSIONS
    assert "ZBA" not in ext
    assert "ZBB" not in ext
    assert "ZBK" not in ext
    assert "ZBH" not in ext

def test_star_with_empty_and_unknown_tokens_still_full_set_rv32():
    ext = normalize_extension_spec("rv32i+gc+*+++???+ +no_such_ext+zba+")

    assert ext == FULL_STANDARD_EXTENSIONS


def test_rv64i_token_defaults_to_base_rv32i_gc():
    assert normalize_extension_spec("RV64I") == {"RV32I", "GC"}


def test_star_extension_set_is_exactly_standard_full_set_rv32():
    ext = normalize_extension_spec("RV32I + GC + *")

    assert ext == FULL_STANDARD_EXTENSIONS

def test_rv64_star_matches_explicit_full_standard_set_flags():
    explicit = RV12Core(
        core_id=0,
        xlen=64,
        extensions="RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND"
    )
    star = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC+*")

    assert explicit.enable_m == star.enable_m
    assert explicit.enable_a == star.enable_a
    assert explicit.enable_b == star.enable_b
    assert explicit.enable_c == star.enable_c
    assert explicit.enable_f == star.enable_f
    assert explicit.enable_d == star.enable_d
    assert explicit.enable_zicond == star.enable_zicond
    assert explicit.enable_zicsr == star.enable_zicsr
    assert explicit.enable_zifencei == star.enable_zifencei

def test_star_with_noise_on_rv64_is_exact_standard_full_set():
    ext = normalize_extension_spec(" RV64I + GC + * + ZBA + ??? + zifencei + zicsr + ZICOND + unknown + ")

    assert ext == FULL_STANDARD_EXTENSIONS

def test_star_noise_is_format_agnostic_between_rv32_and_rv64():
    noisy_32 = "  rv32i   + gc + * +  +\n+ zba + zbb + ??? +   zifencei + zicsr + zicond +"
    noisy_64 = "  RV64I + GC + * +\t+ +\t\nZBA + ??? + zifencei + zicsr + zicond +"
    expected = FULL_STANDARD_EXTENSIONS

    assert normalize_extension_spec(noisy_32) == expected
    assert normalize_extension_spec(noisy_64) == expected

def test_star_set_order_variants_canonicalize_to_same_full_set():
    canonical = FULL_STANDARD_EXTENSIONS
    specs = [
        "RV32I+GC+*",
        "*+RV32I+GC",
        "gc+*+rv32i",
        "rv32i+*+zba+gc+zifencei+zicsr",
    ]

    assert all(normalize_extension_spec(spec) == canonical for spec in specs)


def test_unlisted_zb_prefix_aliases_fall_back_to_b():
    ext = normalize_extension_spec("rv32i + gc + ZBZZ + zbx + zBq + ZBfoo")

    assert ext == {"RV32I", "GC", "B"}


def test_rv64_iterable_with_star_and_none_tokens_normalizes_to_full_standard_set():
    iterable = ["rv64i", "gc", "*", "zicond", "zicsr", "zifencei", None, "", "???", "zba"]
    canonical = FULL_STANDARD_EXTENSIONS

    assert normalize_extension_spec(iterable) == canonical


def test_generator_specification_normalizes_like_string_spec():
    spec_tokens = iter(["rv64i", "+", "gc", "+", "m", "a", "+", "zba", "zifencei", "ZICOND"])

    assert normalize_extension_spec(spec_tokens) == normalize_extension_spec("RV64I+GC+M+A+ZIFENCEI+ZICOND+ZBA")


def test_rv64_iterable_extension_specs_normalize_the_same_as_string_specs():
    iterable = [" rv64i", "GC", "m", "A", "ZIFENCEI", "zicond", "zicsr", "zba", "???"]
    string_spec = "RV64I+GC+M+A+ZBA+ZIFENCEI+ZICOND+ZICSR"

    assert normalize_extension_spec(iterable) == normalize_extension_spec(string_spec)


def test_star_runtime_flags_with_noisy_standard_aliases_match_explicit_full_set_rv32_and_rv64():
    canonical = FULL_STANDARD_EXTENSIONS

    noisy_32 = "  rv32i + gc + * + zba + ZBH + ??? + zifencei + zicsr + zicond + unknown + "
    noisy_64 = "  rv64i + gc + * + zbb + zba + ZBK + ??? + m + a + B + C + F + D + "
    canonical_star_32 = normalize_extension_spec(noisy_32)
    canonical_star_64 = normalize_extension_spec(noisy_64)
    canonical_explicit_32 = normalize_extension_spec("RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND")
    canonical_explicit_64 = normalize_extension_spec("RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND")

    assert canonical_star_32 == canonical
    assert canonical_star_64 == canonical
    assert canonical_explicit_32 == LEGACY_EXPLICIT_EXTENSIONS
    assert canonical_explicit_64 == LEGACY_EXPLICIT_EXTENSIONS
    assert canonical_explicit_32 < canonical_star_32
    assert canonical_explicit_64 < canonical_star_64

    star_32 = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+*")
    star_64 = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC+*")
    explicit_32 = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND")
    explicit_64 = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND")

    assert (star_32.enable_m, star_32.enable_a, star_32.enable_b, star_32.enable_c,
            star_32.enable_f, star_32.enable_d, star_32.enable_zicond, star_32.enable_zicsr, star_32.enable_zifencei) == (
            explicit_32.enable_m, explicit_32.enable_a, explicit_32.enable_b, explicit_32.enable_c,
            explicit_32.enable_f, explicit_32.enable_d, explicit_32.enable_zicond, explicit_32.enable_zicsr, explicit_32.enable_zifencei)

    assert (star_64.enable_m, star_64.enable_a, star_64.enable_b, star_64.enable_c,
            star_64.enable_f, star_64.enable_d, star_64.enable_zicond, star_64.enable_zicsr, star_64.enable_zifencei) == (
            explicit_64.enable_m, explicit_64.enable_a, explicit_64.enable_b, explicit_64.enable_c,
            explicit_64.enable_f, explicit_64.enable_d, explicit_64.enable_zicond, explicit_64.enable_zicsr, explicit_64.enable_zifencei)


def test_star_fullset_alias_contract_stable_for_string_and_iterable_inputs():
    canonical = FULL_STANDARD_EXTENSIONS
    noisy_iterable_32 = [
        "  rv32i ",
        "GC",
        "???",
        "",
        "m",
        "a",
        "b",
        "c",
        "f",
        "d",
        "zicsr",
        "zifencei",
        "zicond",
        None,
        "+",
        "unknown.ext",
        "M",
        "A",
    ]
    noisy_iterable_64 = [
        "  RV64I ",
        "gC",
        "??",
        "M",
        "A",
        "B",
        "C",
        "F",
        "D",
        "ZICOND",
        "ZIFENCEI",
        "ZICSR",
        "",
        "junk",
        None,
        "???",
        "zba",
        "zbb",
    ]

    assert normalize_extension_spec("RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND") == LEGACY_EXPLICIT_EXTENSIONS
    assert normalize_extension_spec("RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND") == LEGACY_EXPLICIT_EXTENSIONS
    assert normalize_extension_spec(noisy_iterable_32) == LEGACY_EXPLICIT_EXTENSIONS
    assert normalize_extension_spec(noisy_iterable_64) == LEGACY_EXPLICIT_EXTENSIONS


def test_iterable_tokens_with_embedded_separators_still_normalize_to_full_set():
    noisy_iterable = [
        "rv32i+gc",
        "+*+",
        "  M",
        "A ",
        "b",
        "c",
        "f+d",
        "zicsr",
        "zifencei",
        "zicond",
        "???",
        None,
        "",
        "no_such_ext",
    ]
    canonical = FULL_STANDARD_EXTENSIONS

    assert normalize_extension_spec(noisy_iterable) == canonical


def test_iterable_with_noisy_zb_aliases_and_star_still_normalizes_to_full_set():
    noisy_iterable = [
        "  RV64I ",
        "+*+",
        "ZBA",
        "ZBZZ",
        "zbx",
        "zBq",
        "  zbs ",
        "",
        None,
        "zicsr",
        "zifencei",
        "zicond",
        "???",
    ]

    expected = FULL_STANDARD_EXTENSIONS
    assert normalize_extension_spec(noisy_iterable) == expected


def test_rv32_iterable_star_runtime_flags_stable_against_string_full_set():
    spec_iterable = [
        "rv32I",
        "gc",
        "*",
        "  m ",
        "a",
        "zba",
        "ZBH",
        "zicsr",
        "zifencei",
        "zicond",
        None,
        "???",
    ]
    core_iterable = RV12Core(core_id=0, xlen=32, extensions=spec_iterable)
    core_string = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND")

    assert core_iterable.enable_m == core_string.enable_m
    assert core_iterable.enable_a == core_string.enable_a
    assert core_iterable.enable_b == core_string.enable_b
    assert core_iterable.enable_c == core_string.enable_c
    assert core_iterable.enable_f == core_string.enable_f
    assert core_iterable.enable_d == core_string.enable_d
    assert core_iterable.enable_zicsr == core_string.enable_zicsr
    assert core_iterable.enable_zifencei == core_string.enable_zifencei
    assert core_iterable.enable_zicond == core_string.enable_zicond


def test_noisy_rv64_star_mix_preserves_standard_full_set_and_alias_rules():
    noisy = "  RV64I + GC + * + ZBA + ? + ZBfoo + zbz + ZBS + zicond + zicsr + zifencei + unknown "

    assert normalize_extension_spec(noisy) == FULL_STANDARD_EXTENSIONS


def test_i_token_runtime_flags_stable_with_64_and_32():
    core32 = RV12Core(core_id=0, xlen=32, extensions="I")
    core64 = RV12Core(core_id=0, xlen=64, extensions="i")

    for core in (core32, core64):
        assert core.enable_m is False
        assert core.enable_a is False
        assert core.enable_b is False
        assert core.enable_c is False
        assert core.enable_f is False
        assert core.enable_d is False
        assert core.enable_zicond is False
        assert core.enable_zicsr is False
        assert core.enable_zifencei is False


def test_noise_only_inputs_still_fallback_to_rv32i_gc():
    noisy_string_spec = " + ?? + + no_such + ??? + "
    noisy_iterable_spec = ["+", "?", None, " ", "", "???", "no_such", "+"]

    assert normalize_extension_spec(noisy_string_spec) == {"RV32I", "GC"}
    assert normalize_extension_spec(noisy_iterable_spec) == {"RV32I", "GC"}


def test_gc_alias_and_redundant_base_tokens_stabilize_runtime_set():
    canonical = {"RV32I", "GC", "M", "B", "ZIFENCEI"}
    noisy_spec = "rv64i + gc + GC + RV32I + gc + RV64I + m + ZBA + zbh + zifencei"

    core = RV12Core(core_id=0, xlen=64, extensions=noisy_spec)
    canonical_core = RV12Core(core_id=0, xlen=64, extensions="rv64i+gc+m+zba+zifencei")

    assert normalize_extension_spec(noisy_spec) == canonical
    assert core.enable_m == canonical_core.enable_m
    assert core.enable_a == canonical_core.enable_a
    assert core.enable_b == canonical_core.enable_b
    assert core.enable_c == canonical_core.enable_c
    assert core.enable_f is False
    assert core.enable_d is False
    assert core.enable_zicond is False
    assert core.enable_zicsr == canonical_core.enable_zicsr
    assert core.enable_zifencei == canonical_core.enable_zifencei


def test_whitespace_and_star_mix_expands_to_standard_full_set():
    canonical = FULL_STANDARD_EXTENSIONS
    noisy_rv32 = "  RV32I    + gc  + *   +   + ??? + ZBA +  "
    noisy_rv64 = "\nRV64I+GC+*+zba+\t+zifencei+zicsr+zicond+\n"

    assert normalize_extension_spec(noisy_rv32) == canonical
    assert normalize_extension_spec(noisy_rv64) == canonical

    core32 = RV12Core(core_id=0, xlen=32, extensions=noisy_rv32)
    core64 = RV12Core(core_id=0, xlen=64, extensions=noisy_rv64)
    canonical_core32 = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND")
    canonical_core64 = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC+M+A+B+C+F+D+ZICSR+ZIFENCEI+ZICOND")

    for lhs, rhs in ((core32, canonical_core32), (core64, canonical_core64)):
        assert lhs.enable_m == rhs.enable_m
        assert lhs.enable_a == rhs.enable_a
        assert lhs.enable_b == rhs.enable_b
        assert lhs.enable_c == rhs.enable_c
        assert lhs.enable_f == rhs.enable_f
        assert lhs.enable_d == rhs.enable_d
        assert lhs.enable_zicond == rhs.enable_zicond
        assert lhs.enable_zicsr == rhs.enable_zicsr
        assert lhs.enable_zifencei == rhs.enable_zifencei


def test_trailing_separator_and_lowercase_i_do_not_expand_to_nonbaseline():
    assert normalize_extension_spec("RV32I+") == {"RV32I", "GC"}
    assert normalize_extension_spec("rv64i+") == {"RV32I", "GC"}

    c32 = RV12Core(core_id=0, xlen=32, extensions="RV32I+")
    c64 = RV12Core(core_id=0, xlen=64, extensions="rv64i+")
    assert c32.enable_m is False
    assert c32.enable_a is False
    assert c32.enable_b is False
    assert c32.enable_c is False
    assert c32.enable_f is False
    assert c32.enable_d is False
    assert c32.enable_zicond is False
    assert c32.enable_zicsr is False
    assert c32.enable_zifencei is False
    assert c64.extensions == c32.extensions


def test_empty_and_none_specs_stabilize_to_rv32i_gc_both_runtime_and_normalized():
    string_empty = RV12Core(core_id=0, xlen=32, extensions="")
    string_spaces = RV12Core(core_id=0, xlen=64, extensions="   ")
    string_none = RV12Core(core_id=0, xlen=64, extensions=None)
    iterable_empty = RV12Core(core_id=0, xlen=32, extensions=["", " ", None, "+", "???"])
    iterable_noop = RV12Core(core_id=0, xlen=64, extensions=[None, "", "+", " ??? "])
    canonical = {"RV32I", "GC"}

    assert normalize_extension_spec("") == canonical
    assert normalize_extension_spec("   ") == canonical
    assert normalize_extension_spec([]) == canonical
    assert normalize_extension_spec(["", " ", None, "+", "???"]) == canonical
    assert normalize_extension_spec([None, "", "+", " ??? "]) == canonical

    for core in (string_empty, string_spaces, string_none, iterable_empty, iterable_noop):
        assert core.extensions == canonical
        assert core.enable_m is False
        assert core.enable_a is False
        assert core.enable_b is False
        assert core.enable_c is False
        assert core.enable_f is False
        assert core.enable_d is False
        assert core.enable_zicsr is False
        assert core.enable_zifencei is False


def test_standard_full_set_is_stable_across_reorder_noise_iterable_and_string_inputs():
    canonical = FULL_STANDARD_EXTENSIONS
    canonical_string = "RV32I+GC+*+B+ZICOND+ZICSR+ZIFENCEI"

    noisy_string = "  ZBA + rv32i + GC + ? + zbb + m + d + a + zba + ??? + zicond + f + c + zifencei + zicsr + zbh + ZBK + + "
    noisy_iterable = [
        "", " ", None,
        "RV64I", "gc", "M", "A", "B",
        "ZBA", "ZBB", "ZBH", "ZBK",
        "F", "D", "C", "ZICSR", "ZIFENCEI", "ZICOND",
        "+", "zicond",
        "???",
    ]

    assert normalize_extension_spec(canonical_string) == canonical
    assert normalize_extension_spec(noisy_string) == LEGACY_EXPLICIT_EXTENSIONS
    assert normalize_extension_spec(noisy_iterable) == LEGACY_EXPLICIT_EXTENSIONS

    c32 = RV12Core(core_id=0, xlen=32, extensions=noisy_string)
    c32_iter = RV12Core(core_id=0, xlen=32, extensions=noisy_iterable)
    c64 = RV12Core(core_id=0, xlen=64, extensions=noisy_string)
    c64_iter = RV12Core(core_id=0, xlen=64, extensions=noisy_iterable)
    c32_star = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+*")
    c64_star = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC+*")

    assert c32.extensions == LEGACY_EXPLICIT_EXTENSIONS
    assert c32_iter.extensions == LEGACY_EXPLICIT_EXTENSIONS
    assert (c32.enable_m, c32.enable_a, c32.enable_b, c32.enable_c, c32.enable_f, c32.enable_d, c32.enable_zicond, c32.enable_zicsr, c32.enable_zifencei) == (
        c32_star.enable_m, c32_star.enable_a, c32_star.enable_b, c32_star.enable_c, c32_star.enable_f, c32_star.enable_d,
        c32_star.enable_zicond, c32_star.enable_zicsr, c32_star.enable_zifencei
    )
    assert (c32_iter.enable_m, c32_iter.enable_a, c32_iter.enable_b, c32_iter.enable_c, c32_iter.enable_f, c32_iter.enable_d, c32_iter.enable_zicond, c32_iter.enable_zicsr, c32_iter.enable_zifencei) == (
        c32_star.enable_m, c32_star.enable_a, c32_star.enable_b, c32_star.enable_c, c32_star.enable_f, c32_star.enable_d,
        c32_star.enable_zicond, c32_star.enable_zicsr, c32_star.enable_zifencei
    )
    assert c64.extensions == LEGACY_EXPLICIT_EXTENSIONS
    assert c64_iter.extensions == LEGACY_EXPLICIT_EXTENSIONS
    assert (c64.enable_m, c64.enable_a, c64.enable_b, c64.enable_c, c64.enable_f, c64.enable_d, c64.enable_zicond, c64.enable_zicsr, c64.enable_zifencei) == (
        c64_star.enable_m, c64_star.enable_a, c64_star.enable_b, c64_star.enable_c, c64_star.enable_f, c64_star.enable_d,
        c64_star.enable_zicond, c64_star.enable_zicsr, c64_star.enable_zifencei
    )
    assert (c64_iter.enable_m, c64_iter.enable_a, c64_iter.enable_b, c64_iter.enable_c, c64_iter.enable_f, c64_iter.enable_d, c64_iter.enable_zicond, c64_iter.enable_zicsr, c64_iter.enable_zifencei) == (
        c64_star.enable_m, c64_star.enable_a, c64_star.enable_b, c64_star.enable_c, c64_star.enable_f, c64_star.enable_d,
        c64_star.enable_zicond, c64_star.enable_zicsr, c64_star.enable_zifencei
    )


def test_full_zb_alias_coverage_maps_to_b_without_star():
    spec = "RV32I + GC + m + a + f + d + zicsr + zifencei + zicond + " \
           "zba + zbb + zbc + zbe + zbf + zbg + zbh + zbi + zbk + zbl + zbm + zbn + zbp + zbr + zbs + zbt + zbu + zbv + zbx + zbz + b"
    expected = {"RV32I", "GC", "M", "A", "B", "F", "D", "ZICSR", "ZIFENCEI", "ZICOND"}

    assert normalize_extension_spec(spec) == expected

    c = RV12Core(core_id=0, xlen=32, extensions=spec)
    c_star = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+*")
    assert (c.enable_m, c.enable_a, c.enable_b, c.enable_f, c.enable_d, c.enable_zicond, c.enable_zicsr, c.enable_zifencei) == (
        c_star.enable_m, c_star.enable_a, c_star.enable_b, c_star.enable_f, c_star.enable_d,
        c_star.enable_zicond, c_star.enable_zicsr, c_star.enable_zifencei
    )
    assert c.enable_c is False

    c64 = RV12Core(core_id=0, xlen=64, extensions="rv64i+gc+zba+zbb+zbc+zbe+zbf+zbg+zbh+zbi+zbk+zbl+zbm+zbn+zbp+zbr+zbs+zbt+zbu+zbv+zbx+zbz+b+m+a+f+d+zifencei+zicsr+zicond")
    c64_star = RV12Core(core_id=0, xlen=64, extensions="rv64i+gc+*")
    assert (c64.enable_m, c64.enable_a, c64.enable_b, c64.enable_f, c64.enable_d, c64.enable_zicond, c64.enable_zicsr, c64.enable_zifencei) == (
        c64_star.enable_m, c64_star.enable_a, c64_star.enable_b, c64_star.enable_f, c64_star.enable_d,
        c64_star.enable_zicond, c64_star.enable_zicsr, c64_star.enable_zifencei
    )
    assert c64.enable_c is False


def test_no_star_does_not_inject_full_standard_set_from_aliases():
    spec = "rv64i+gc+zba+zicond+zifencei+zicsr+m"
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "B", "M", "ZICOND", "ZIFENCEI", "ZICSR"}

    c = RV12Core(core_id=0, xlen=64, extensions=spec)
    assert c.enable_m is True
    assert c.enable_a is False
    assert c.enable_b is True
    assert c.enable_c is False
    assert c.enable_f is False
    assert c.enable_d is False
    assert c.enable_zicond is True
    assert c.enable_zicsr is True
    assert c.enable_zifencei is True


def test_no_star_does_not_inject_full_standard_set_from_aliases_rv32():
    spec = "RV32I+GC+zba+zifencei+zicsr+zicond+m"
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "B", "M", "ZICOND", "ZIFENCEI", "ZICSR"}

    c = RV12Core(core_id=0, xlen=32, extensions=spec)
    assert c.enable_m is True
    assert c.enable_a is False
    assert c.enable_b is True
    assert c.enable_c is False
    assert c.enable_f is False
    assert c.enable_d is False
    assert c.enable_zicond is True
    assert c.enable_zicsr is True
    assert c.enable_zifencei is True


def test_no_star_iterable_aliases_rv32_matches_expected_flag_set():
    spec = ["  ", "RV32I", "gc", "", None, "zba", "ZBH", "zifencei", "zicsr", "zicond", "m", "???", "+"]
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "B", "M", "ZICOND", "ZIFENCEI", "ZICSR"}

    c = RV12Core(core_id=0, xlen=32, extensions=spec)
    assert c.enable_m is True
    assert c.enable_a is False
    assert c.enable_b is True
    assert c.enable_c is False
    assert c.enable_f is False
    assert c.enable_d is False
    assert c.enable_zicond is True
    assert c.enable_zicsr is True
    assert c.enable_zifencei is True


def test_no_star_explicit_c_requires_no_full_set_growth_on_rv64_alias():
    spec = "RV64I+GC+C+zba+M+ZIFENCEI+ZICSR+ZICOND"
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "M", "C", "B", "ZICSR", "ZIFENCEI", "ZICOND"}

    c = RV12Core(core_id=0, xlen=64, extensions=spec)
    assert c.enable_m is True
    assert c.enable_a is False
    assert c.enable_b is True
    assert c.enable_c is True
    assert c.enable_f is False
    assert c.enable_d is False
    assert c.enable_zicond is True
    assert c.enable_zicsr is True
    assert c.enable_zifencei is True


def test_no_star_alias_set_keeps_only_requested_core_extensions_rv32():
    spec = ["RV32I", "gc", "A", "f", "zba", "zicond", "zifencei", "zicsr", "???", "", None]
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "A", "B", "F", "ZICOND", "ZIFENCEI", "ZICSR"}

    c = RV12Core(core_id=0, xlen=32, extensions=spec)
    assert c.enable_m is False
    assert c.enable_a is True
    assert c.enable_b is True
    assert c.enable_c is False
    assert c.enable_f is True
    assert c.enable_d is False
    assert c.enable_zicond is True
    assert c.enable_zicsr is True
    assert c.enable_zifencei is True


def test_no_star_explicit_d_promotes_required_f_but_not_c_on_rv64():
    spec = "RV64I+GC+D+ZBA+M+ZIFENCEI+ZICOND"
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "M", "B", "D", "ZICOND", "ZIFENCEI"}

    c = RV12Core(core_id=0, xlen=64, extensions=spec)
    assert c.enable_m is True
    assert c.enable_a is False
    assert c.enable_b is True
    assert c.enable_c is False
    assert c.enable_f is True
    assert c.enable_d is True
    assert c.enable_zicond is True
    assert c.enable_zifencei is True
    assert c.enable_zicsr is True


def test_no_star_explicit_a_and_f_do_not_imply_unrequested_core_sets():
    spec = "RV64I+GC+A+F+ZBA+ZIFENCEI+ZBA"
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "A", "B", "F", "ZIFENCEI"}

    c = RV12Core(core_id=0, xlen=64, extensions=spec)
    assert c.enable_m is False
    assert c.enable_a is True
    assert c.enable_b is True
    assert c.enable_c is False
    assert c.enable_f is True
    assert c.enable_d is False
    assert c.enable_zifencei is True
    assert c.enable_zicsr is True
    assert c.enable_zicond is False


def test_no_star_explicit_zicsr_and_zicond_does_not_enable_zifencei_or_other_core_sets():
    spec = "RV32I+GC+ZICSR+ZICOND+ZBA"
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "B", "ZICSR", "ZICOND"}

    c = RV12Core(core_id=0, xlen=32, extensions=spec)
    assert c.enable_m is False
    assert c.enable_a is False
    assert c.enable_b is True
    assert c.enable_c is False
    assert c.enable_f is False
    assert c.enable_d is False
    assert c.enable_zicond is True
    assert c.enable_zicsr is True
    assert c.enable_zifencei is False


def test_no_star_explicit_zifencei_only_keeps_only_requested_parts_on_rv64():
    spec = "RV64I+GC+ZIFENCEI+ZBA+M"
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "M", "B", "ZIFENCEI"}

    c = RV12Core(core_id=0, xlen=64, extensions=spec)
    assert c.enable_m is True
    assert c.enable_a is False
    assert c.enable_b is True
    assert c.enable_c is False
    assert c.enable_f is False
    assert c.enable_d is False
    assert c.enable_zicond is False
    assert c.enable_zicsr is False
    assert c.enable_zifencei is True


def test_no_star_with_rv64_alias_and_zb_aliases_does_not_widen_unrequested_core_set():
    spec = "rv64i + gc + zicond + zba + zbb + zbh + m + ZIFENCEI"
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "M", "B", "ZICOND", "ZIFENCEI"}

    c = RV12Core(core_id=0, xlen=64, extensions=spec)
    assert c.enable_m is True
    assert c.enable_a is False
    assert c.enable_b is True
    assert c.enable_c is False
    assert c.enable_f is False
    assert c.enable_d is False
    assert c.enable_zicond is True
    assert c.enable_zicsr is False
    assert c.enable_zifencei is True


def test_iterable_spec_with_rv64_noise_and_zicond_bundle_is_stable():
    spec = [
        " rv64I ",
        "gc",
        "",
        "zba",
        "zbb",
        "zifencei",
        "zicsr",
        "zicond",
        None,
        "+",
        "???",
    ]
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "B", "ZICOND", "ZICSR", "ZIFENCEI"}

    c = RV12Core(core_id=0, xlen=64, extensions=spec)
    assert c.enable_m is False
    assert c.enable_a is False
    assert c.enable_b is True
    assert c.enable_c is False
    assert c.enable_f is False
    assert c.enable_d is False
    assert c.enable_zicond is True
    assert c.enable_zicsr is True
    assert c.enable_zifencei is True


def test_iterable_spec_no_star_rv32_controls_zicsr_bundle_without_growth():
    spec = [
        " ",
        "rv32i",
        "GC",
        "ZICSR",
        "zicond",
        "zifencei",
        "zba",
        None,
        "+",
    ]
    ext = normalize_extension_spec(spec)

    assert ext == {"RV32I", "GC", "B", "ZICOND", "ZICSR", "ZIFENCEI"}

    c = RV12Core(core_id=0, xlen=32, extensions=spec)
    assert c.enable_m is False
    assert c.enable_a is False
    assert c.enable_b is True
    assert c.enable_c is False
    assert c.enable_f is False
    assert c.enable_d is False
    assert c.enable_zicond is True
    assert c.enable_zicsr is True
    assert c.enable_zifencei is True

def test_iterable_star_with_only_markers_normalizes_to_full_standard_set():
    canonical = FULL_STANDARD_EXTENSIONS

    spec_iter = ["*", "rv64I", "GC", "???", "", None]

    assert normalize_extension_spec(spec_iter) == canonical

    core = RV12Core(core_id=0, xlen=64, extensions=spec_iter)
    star = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC+*")

    assert core.extensions == canonical
    assert core.enable_m == star.enable_m
    assert core.enable_a == star.enable_a
    assert core.enable_b == star.enable_b
    assert core.enable_c == star.enable_c
    assert core.enable_f == star.enable_f
    assert core.enable_d == star.enable_d
    assert core.enable_zicond == star.enable_zicond
    assert core.enable_zicsr == star.enable_zicsr
    assert core.enable_zifencei == star.enable_zifencei

def test_star_only_string_plus_noise_still_maps_to_full_set_for_rv32i_gc_runtime():
    noisy_star = " * + ??? + ZBA + + "
    canonical = FULL_STANDARD_EXTENSIONS

    assert normalize_extension_spec(noisy_star) == canonical

    core = RV12Core(core_id=0, xlen=32, extensions=noisy_star)
    star = RV12Core(core_id=0, xlen=32, extensions="RV32I+GC+*")

    assert core.extensions == canonical
    assert (core.enable_m, core.enable_a, core.enable_b, core.enable_c, core.enable_f, core.enable_d, core.enable_zicond, core.enable_zicsr, core.enable_zifencei) == (
        star.enable_m, star.enable_a, star.enable_b, star.enable_c, star.enable_f, star.enable_d,
        star.enable_zicond, star.enable_zicsr, star.enable_zifencei
    )

def test_iterable_with_only_unknown_and_star_expands_to_full_standard_set_rv64_and_noise_ignored():
    spec_iter = [None, "", "  ", "???", "*", "unknown.ext", "--", "RV64I", "gc", "ZBA", "ZBB", "ZZZ"]
    canonical = FULL_STANDARD_EXTENSIONS

    assert normalize_extension_spec(spec_iter) == canonical

    core = RV12Core(core_id=0, xlen=64, extensions=spec_iter)
    star = RV12Core(core_id=0, xlen=64, extensions="RV64I+GC+*")

    assert core.extensions == canonical
    assert (core.enable_m, core.enable_a, core.enable_b, core.enable_c, core.enable_f, core.enable_d,
            core.enable_zicond, core.enable_zicsr, core.enable_zifencei) == (
        star.enable_m, star.enable_a, star.enable_b, star.enable_c, star.enable_f, star.enable_d,
        star.enable_zicond, star.enable_zicsr, star.enable_zifencei
    )

def test_non_string_scalar_input_falls_back_to_baseline_only():
    assert normalize_extension_spec(123) == {"RV32I", "GC"}
    assert normalize_extension_spec(0.0) == {"RV32I", "GC"}
    assert normalize_extension_spec(object()) == {"RV32I", "GC"}

    c_num = RV12Core(core_id=0, xlen=32, extensions=123)
    assert c_num.enable_m is False
    assert c_num.enable_a is False
    assert c_num.enable_b is False
    assert c_num.enable_c is False
    assert c_num.enable_f is False
    assert c_num.enable_d is False
    assert c_num.enable_zicond is False
    assert c_num.enable_zicsr is False
    assert c_num.enable_zifencei is False
