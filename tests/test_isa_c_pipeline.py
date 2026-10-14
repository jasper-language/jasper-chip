from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import enc_i, OP_IMM


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbCExpPipeline(Elaboratable):
    def __init__(self):
        # Program with compressed (16-bit C extension) instructions at word 0:
        #
        # Word 0 (addr 0-3):  low halfword = C.NOP, high halfword = C.LI x6, 21
        #   0x0001 = C.NOP
        #   0x4355 = C.LI x6, 21   (ADDI x6, x0, 21)
        # Word 1 (addr 4-7):  ADDI x6, x6, 21     => x6 = 21 + 21 = 42
        # Word 2 (addr 8-11): ADDI x7, x0, 99      => x7 = 99
        # Rest: NOPs
        #
        # PC progression: 0 (C.NOP, 2b) -> 2 (C.LI, 2b) -> 4 (NOP, 4b) -> 8 (ADDI, 4b) -> 12 (ADDI, 4b) -> ...

        c_nop = 0x0001
        c_li_x6_21 = 0x4355
        word0 = c_nop | (c_li_x6_21 << 16)

        word1 = enc_i(OP_IMM, 0, 0b000, 0, 0)   # NOP (bypass bubble)
        word2 = enc_i(OP_IMM, 6, 0b000, 6, 21)   # ADDI x6, x6, 21
        word3 = enc_i(OP_IMM, 7, 0b000, 0, 99)   # ADDI x7, x0, 99

        prog = [word0, word1, word2, word3]
        IMEM_WORDS = 2048
        prog = prog + [nop()] * (IMEM_WORDS - len(prog))

        self.core = RV12Core(core_id=0)
        self.imem = SimpleIMem(words=2048, init=prog)
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
    dut = TbCExpPipeline()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    print(f"{'cyc':>4} {'pc':>4} {'ISpc':>4} {'v':>1} {'opc':>3} {'imm':>6} {'ex1v':>1} {'rd':>2}  {'x6':>6}")
    pcs_seen = []

    def proc():
        for cyc in range(300):
            pc_val = (yield c.imem_addr)
            is_pc = (yield c.pc_dbg)
            isv = (yield c.dbg_is_valid)
            is_op = (yield c.imem_addr)
            is_imm = (yield c.imem_addr)
            ex1v = (yield c.dbg_ex1_valid)
            ex1rd = (yield c.dbg_ex1_rd)
            yield c.dbg_reg_addr.eq(6)
            yield Tick()
            x6v = (yield c.dbg_reg_rdata)
            if cyc < 60:
                print(f"{cyc:4d} {pc_val:4d} {is_pc:4d} {isv:1d} {is_op:02x} {is_imm:6d} {ex1v:1d} {ex1rd:2d} {x6v:6d}")
            if cyc < 20:
                pcs_seen.append(pc_val)

        regs = {}
        for i in range(32):
            yield c.dbg_reg_addr.eq(i)
            yield Tick()
            regs[f"x{i}"] = (yield c.dbg_reg_rdata)

        print(f"\nx6={regs['x6']}  x7={regs['x7']}")

        # Check PC progression: 0, 2, 4, 8, 12, ...
        expected_pcs = [0, 2, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40]
        # Filter out redirects / duplicates — take unique ordered pcs
        ordered = []
        for p in pcs_seen:
            if not ordered or p != ordered[-1]:
                ordered.append(p)
        # The first few unique PCs should match expected
        match_len = min(len(ordered), len(expected_pcs))
        pc_ok = ordered[:match_len] == expected_pcs[:match_len]

        errs = []
        if regs['x6'] != 42:
            errs.append(f"x6 expected 42, got {regs['x6']}")
        if regs['x7'] != 99:
            errs.append(f"x7 expected 99, got {regs['x7']}")
        if not pc_ok:
            errs.append(f"PC progression mismatch: expected {expected_pcs[:8]}, got {ordered[:8]}")

        if errs:
            for e in errs:
                print(f"FAIL: {e}")
        else:
            print("PASS: C extension pipeline test verified (x6=42, x7=99, PC 0→2→4→8)")

        assert not errs, "\n".join(errs)

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
