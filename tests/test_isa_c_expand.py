# tests/test_isa_c_expand.py
"""CExpander tests: all 27 compressed instruction expansions + core integration.

Run:  python3 -m tests.test_isa_c_expand
"""

from amaranth import *
from amaranth.sim import Simulator
from rtl.isa_c_expand import CExpander


TESTS = [
    # CR / CI (op=01)
    ('C.NOP',        0x0001, 0x00000013),
    ('C.ADDI x2,1',  0x0105, 0x00110113),
    ('C.LI x1,0',    0x4081, 0x00000093),
    ('C.LI x1,-1',   0x50FD, 0xfff00093),
    ('C.JR x1',      0x8082, 0x00008067),
    ('C.MV x1,x2',   0x808A, 0x002000b3),
    ('C.ADD x1,x2',  0x908A, 0x002080b3),
    ('C.EBREAK',     0x9002, 0x00100073),
    ('C.JALR x1',    0x9082, 0x000080e7),

    # CI shift / ALU (op=01, funct3=100)
    ('C.SLLI x9,1',  0x8085, 0x00149493),
    ('C.SRLI x8,1',  0x9005, 0x00145413),
    ('C.SRAI x8,1',  0x9405, 0x40145413),
    ('C.ANDI x8,-1', 0x987D, 0xfff47413),
    ('C.SUB x8,x9',  0x8C05, 0x40940433),
    ('C.XOR x8,x9',  0x8C25, 0x00944433),
    ('C.OR x8,x9',   0x8C45, 0x00946433),
    ('C.AND x8,x9',  0x8C65, 0x00947433),

    # JAL / J
    ('C.JAL +8',     0x2021, 0x008000ef),
    ('C.J +8',       0xA021, 0x0080006f),

    # BEQZ / BNEZ
    ('C.BEQZ x8,+8', 0xC401, 0x00040463),
    ('C.BNEZ x8,+8', 0xE401, 0x00041463),

    # CL / CS (op=00)
    ('C.LW x9,4(x10)', 0x4504, 0x00452483),
    ('C.SW x9,4(x10)', 0xC504, 0x00952223),

    # LWSP / SWSP (op=10)
    ('C.LWSP x1,4(sp)', 0x4086, 0x00412083),
    ('C.LWSP x1,8(sp)', 0x40A2, 0x00812083),
    ('C.SWSP x1,4(sp)', 0xC086, 0x00112223),
    ('C.SWSP x1,8(sp)', 0xC0A2, 0x00112423),
]


def test_all_expansions():
    dut = CExpander(xlen=32)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    results = {}

    def proc():
        for desc, c16, exp in TESTS:
            yield dut.valid.eq(1)
            yield dut.insn16.eq(c16)
            yield
            got = yield dut.insn32
            ill = yield dut.illegal
            ok = (ill == 0 and got == exp)
            results[desc] = (ok, c16, got, exp)

    sim.add_sync_process(proc)
    sim.run()
    return results


def test_core_elaboration():
    from rtl.rv12_core import RV12Core
    m = Module()
    core = RV12Core()
    m.submodules.core = core
    try:
        from amaranth.back import rtlil
        output = rtlil.convert(m, ports=[core.imem_addr, core.imem_rdata])
        return True, len(output)
    except Exception as e:
        return False, str(e)


def main():
    # 1. CExpander instruction expansion
    print("=" * 60)
    print("CExpander: 27 instruction expansions")
    print("=" * 60)
    results = test_all_expansions()
    passed = sum(1 for v in results.values() if v[0])
    failed = sum(1 for v in results.values() if not v[0])
    for desc, (ok, c16, got, exp) in sorted(results.items()):
        status = "OK" if ok else "FAIL"
        detail = f"0x{c16:04x} -> 0x{got:08x}" if ok else f"0x{c16:04x} -> 0x{got:08x} (expected 0x{exp:08x})"
        print(f"  {status:4s}  {desc:25s}  {detail}")
    print(f"\n  Passed: {passed}/{len(results)}")

    # 2. Core elaboration
    print("\n" + "=" * 60)
    print("RV12Core: CExpander integration elaboration")
    print("=" * 60)
    ok, detail = test_core_elaboration()
    if ok:
        print(f"  OK    Elaboration successful ({detail} chars)")
    else:
        print(f"  FAIL  {detail}")

    # summary
    all_ok = (passed == len(results)) and ok
    print("\n" + "=" * 60)
    print(f"{'ALL TESTS PASSED' if all_ok else 'SOME TESTS FAILED'}")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
