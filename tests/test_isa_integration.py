from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import (
    enc_b, enc_i, enc_r, enc_u, BRANCH, JALR, OP_IMM, OP, LUI, AUIPC, SYSTEM,
    enc_fence,
)


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


# MUL = funct3=0b000, funct7=0b0000001
# DIV = funct3=0b100, funct7=0b0000001
MUL_F3 = 0b000
DIV_F3 = 0b100
M_F7  = 0b0000001


class TbIsaIntegration(Elaboratable):
    def __init__(self):
        # Subtest 1: AUIPC
        #   auipc x1,  0x10          -> x1  = 0 + (0x10 << 12) = 0x10000
        #   addi  x2,  x1, 0x100     -> x2  = 0x10000 + 0x100 = 0x10100
        # Subtest 2: MUL  (M extension)
        #   addi  x10, x0, 7         -> x10 = 7
        #   addi  x11, x0, 6         -> x11 = 6
        #   mul   x12, x10, x11      -> x12 = 42
        # Subtest 3: DIV  (M extension)
        #   addi  x13, x0, 42        -> x13 = 42
        #   addi  x14, x0, 7         -> x14 = 7
        #   div   x15, x13, x14      -> x15 = 6
        # Subtest 4: CSR  (Zicsr)
        #   csrrw x16, 0x300, x0     -> x16 = mstatus (Zicsr stub → 0)
        # Subtest 5: LUI / AUIPC / BRANCH / JALR (RV32I baseline)
        prog = [
            enc_u(AUIPC, 1, 0x10),                    # 0:  x1  = 0x10000
            enc_i(OP_IMM, 2, 0b000, 1, 0x100),        # 4:  x2  = 0x10100

            enc_i(OP_IMM, 10, 0b000, 0, 7),           # 8:  x10 = 7
            enc_i(OP_IMM, 11, 0b000, 0, 6),           # 12: x11 = 6
            enc_r(OP, 12, MUL_F3, 10, 11, M_F7),      # 16: x12 = 7 * 6 = 42

            enc_i(OP_IMM, 13, 0b000, 0, 42),          # 20: x13 = 42
            enc_i(OP_IMM, 14, 0b000, 0, 7),           # 24: x14 = 7
            enc_r(OP, 15, DIV_F3, 13, 14, M_F7),      # 28: x15 = 42 / 7 = 6

            enc_i(SYSTEM, 16, 0b001, 0, 0x300),       # 32: csrrw x16, 0x300, x0
            enc_u(LUI, 3, 0x1),                       # 36: x3  = 0x1000
            enc_u(AUIPC, 4, 0x1),                     # 40: x4  = 0x1004
            enc_i(OP_IMM, 5, 0b000, 0, 1),            # 44: x5  = 1
            enc_i(OP_IMM, 6, 0b000, 0, 1),            # 48: x6  = 1
            enc_b(BRANCH, 0b000, 5, 6, 8),            # 52: beq x5, x6, +8
            enc_i(OP_IMM, 7, 0b000, 0, 0x123),        # 56: x7  = 0x123 (skip)
            enc_i(OP_IMM, 7, 0b000, 0, 0x234),        # 60: x7  = 0x234
            enc_i(OP_IMM, 9, 0b000, 0, 76),           # 64: x9  = 76 (jump target)
            enc_i(JALR, 8, 0b000, 9, 0),              # 68: x8  = return, jump x9
            enc_i(OP_IMM, 10, 0b000, 0, 0x111),       # 72: x10 = 0x111 (skip)
            enc_i(OP_IMM, 10, 0b000, 0, 0x222),       # 76: x10 = 0x222
        ]
        IMEM_WORDS = 1024
        prog = prog + [nop()] * (IMEM_WORDS - len(prog))

        self.core = RV12Core(core_id=0, extensions="RV32I+GC+M+ZICSR")
        self.imem = SimpleIMem(words=IMEM_WORDS, init=prog)
        self.dmem = SimpleDMem(words=64)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem

        m.d.comb += [
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
            dm.req_valid.eq(c.dmem_valid),
            dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
            c.gc_enq_ready.eq(0),
            c.gc_rsp_valid.eq(0),
            c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0),
            c.wb_enq_ready.eq(1),
            c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0),
            c.mv_rsp_tag.eq(0),
            c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),
        ]
        return m


def main():
    dut = TbIsaIntegration()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        print(f"{'cyc':>4} {'pc':>4} {'opc':>3} {'ex1rd':>4} {'ex1v':>4}")
        for cyc in range(300):
            pc_val = (yield c.pc_dbg)
            opc_val = (yield c.imem_addr)
            ex1rd = (yield c.dbg_ex1_rd)
            ex1v  = (yield c.dbg_ex1_valid)
            if cyc < 60 or cyc % 50 == 0:
                print(f"{cyc:4d} {pc_val:4d} {opc_val:3d} {ex1rd:4d} {ex1v:4d}")
            yield Tick()

        reg_indices = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
        regs = {}
        for i in reg_indices:
            yield c.dbg_reg_addr.eq(i)
            yield Tick()
            regs[f"x{i}"] = (yield c.dbg_reg_rdata)

        print()
        print(f"x1=0x{regs['x1']:x}  x2=0x{regs['x2']:x}  x10={regs['x10']}  x11={regs['x11']}")
        print(f"x3=0x{regs['x3']:x}  x4=0x{regs['x4']:x}  x5={regs['x5']}  x6={regs['x6']}")
        print(f"x7=0x{regs['x7']:x}  x8=0x{regs['x8']:x}  x9={regs['x9']}  x10=0x{regs['x10']:x}")
        print(f"x12={regs['x12']}  x13={regs['x13']}  x14={regs['x14']}  x15={regs['x15']}  x16={regs['x16']}")
        print()

        errs = []

        # Subtest 1: AUIPC
        if regs['x1'] != 0x10000:
            errs.append(f"[AUIPC] x1 expected 0x10000, got 0x{regs['x1']:x}")
        else:
            print("PASS: Subtest 1 (AUIPC) x1 = 0x10000")
        if regs['x2'] != 0x10100:
            errs.append(f"[AUIPC] x2 expected 0x10100, got 0x{regs['x2']:x}")
        else:
            print("PASS: Subtest 1 (AUIPC) x2 = 0x10100")

        # Subtest 2: MUL
        if regs['x12'] != 42:
            errs.append(f"[MUL] x12 expected 42, got {regs['x12']}")
        else:
            print("PASS: Subtest 2 (MUL) x12 = 42")

        # Subtest 3: DIV
        if regs['x15'] != 6:
            errs.append(f"[DIV] x15 expected 6, got {regs['x15']}")
        else:
            print("PASS: Subtest 3 (DIV) x15 = 6")

        # Subtest 4: CSR (Zicsr)
        # Zicsr module matched and sets wb_en=1 / wb_data=0 (stub, no real CSR)
        if regs['x16'] != 0:
            errs.append(f"[CSR] x16 expected 0 (Zicsr stub), got {regs['x16']}")
        else:
            print("PASS: Subtest 4 (CSR) x16 = 0 (Zicsr stub returns 0 for mstatus)")
        print("      NOTE: Zicsr is a stub — CSR reads always return 0.")

        # Subtest 5: LUI / AUIPC / BRANCH / JALR
        if regs['x3'] != 0x1000:
            errs.append(f"[LUI] x3 expected 0x1000, got 0x{regs['x3']:x}")
        else:
            print("PASS: Subtest 5 (LUI) x3 = 0x1000")
        if regs['x4'] != 0x1028:
            errs.append(f"[AUIPC] x4 expected 0x1028, got 0x{regs['x4']:x}")
        else:
            print("PASS: Subtest 5 (AUIPC) x4 = 0x1028")
        if regs['x7'] != 0x234:
            errs.append(f"[BRANCH] x7 expected 0x234, got 0x{regs['x7']:x}")
        else:
            print("PASS: Subtest 5 (BRANCH) x7 = 0x234")
        if regs['x8'] != 0x48:
            errs.append(f"[JALR] x8 expected 0x48 (return addr), got 0x{regs['x8']:x}")
        else:
            print("PASS: Subtest 5 (JALR) x8 = 0x48")
        if regs['x10'] != 0x222:
            errs.append(f"[JALR] x10 expected 0x222, got 0x{regs['x10']:x}")
        else:
            print("PASS: Subtest 5 (JALR target) x10 = 0x222")
        print()

        if errs:
            for e in errs:
                print(f"FAIL: {e}")
        else:
            print("OK: All ISA integration subtests passed.")
        print()

        assert not errs, "\n".join(errs)

    sim.add_process(proc)
    sim.run()


def _run_isa_program(words, extensions="RV32I+GC+*"):
    IMEM_WORDS = 1024
    prog = words + [nop()] * (IMEM_WORDS - len(words))
    m = Module()
    core = RV12Core(core_id=0, extensions=extensions)
    imem = SimpleIMem(words=IMEM_WORDS, init=prog)
    dmem = SimpleDMem(words=64)
    m.submodules.core = core
    m.submodules.imem = imem
    m.submodules.dmem = dmem
    m.d.comb += [
        imem.addr.eq(core.imem_addr),
        core.imem_rdata.eq(imem.rdata),
        dmem.req_valid.eq(core.dmem_valid),
        dmem.req_we.eq(core.dmem_we),
        dmem.req_addr.eq(core.dmem_addr),
        dmem.req_wdata.eq(core.dmem_wdata),
        core.dmem_rdata.eq(dmem.rsp_rdata),
        core.gc_enq_ready.eq(0),
        core.gc_rsp_valid.eq(0),
        core.gc_rsp_tag.eq(0),
        core.gc_rsp_rd.eq(0),
        core.gc_rsp_data.eq(0),
        core.wb_enq_ready.eq(1),
        core.mv_cmd_ready.eq(1),
        core.mv_rsp_valid.eq(0),
        core.mv_rsp_tag.eq(0),
        core.mv_rsp_rd.eq(0),
        core.mv_rsp_data.eq(0),
    ]
    sim = Simulator(m)
    sim.add_clock(1e-6)
    return sim, core


def test_runtime_full_standard_set_prog():
    # Program includes: C (compressed), RV32I baseline, M, ZICSR, ZIFENCEI.
    c_nop = 0x0001
    c_li_x6_21 = 0x4355
    word0 = c_nop | (c_li_x6_21 << 16)      # two compressed instructions: C.NOP; C.LI x6,21
    program = [
        word0,
        enc_i(OP_IMM, 6, 0b000, 6, 21),      # x6 = 42
        enc_i(OP_IMM, 7, 0b000, 0, 99),      # x7 = 99
        enc_i(OP_IMM, 10, 0b000, 0, 7),      # x10 = 7
        enc_i(OP_IMM, 11, 0b000, 0, 6),      # x11 = 6
        enc_r(OP, 12, 0b000, 10, 11, 0b0000001),  # x12 = 42 (MUL)
        enc_fence(),                            # ZIFENCEI path expects legal fence.i-like opcode under SYSTEM in this RTL
        enc_i(SYSTEM, 16, 0b001, 0, 0x300),   # x16 = 0 (stub ZICSR read)
        enc_u(LUI, 3, 0x2),                    # x3 = 0x2000
        enc_i(OP_IMM, 3, 0b000, 3, 1),         # x3 = 0x2001 (sanity after LUI)
    ]

    sim, core = _run_isa_program(program)

    regs_seen = {}
    errs = []

    def proc():
        nonlocal core
        for _ in range(260):
            yield Tick()
        # Pull regs by debug port
        for i in [3, 6, 7, 10, 11, 12, 16]:
            yield core.dbg_reg_addr.eq(i)
            yield Tick()
            regs_seen[i] = (yield core.dbg_reg_rdata)

        if regs_seen[6] != 42:
            errs.append(f"C path not fully decoded: x6 expected 42, got {regs_seen[6]}")
        if regs_seen[7] != 99:
            errs.append(f"RV32I path failed: x7 expected 99, got {regs_seen[7]}")
        if regs_seen[12] != 42:
            errs.append(f"M path failed: x12 expected 42, got {regs_seen[12]}")
        if regs_seen[16] != 0:
            errs.append(f"ZICSR path failed: x16 expected 0, got {regs_seen[16]}")
        if regs_seen[3] != 0x2001:
            errs.append(f"LUI/OPI path failed: x3 expected 0x2001, got 0x{regs_seen[3]:x}")

        assert not errs, "\n".join(errs)

    sim.add_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
