from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import enc_i, enc_b, enc_jal, OP_IMM, BRANCH, JAL


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


def trace_inst(idx, label="", pc=None):
    return None


class TbBranchPred(Elaboratable):
    def __init__(self):
        # Step79: 分支预测 + JAL 回归测试
        # idx  addr  insn
        # 0    0     addi x1, x0, 3        # x1 = 3 (loop count)
        # 1    4     addi x2, x0, 0        # x2 = 0 (accumulator)
        # 2    8     addi x3, x0, 0x11     # x3 = 0x11
        # 3    12    beq  x0, x0, +8       # -> idx 5 (无条件, 第一次BTB不命中)
        # 4    16    addi x4, x0, 0xff     # 不应执行
        # 5    20    addi x4, x0, 0x22     # x4 = 0x22
        # 6    24    jal  x5, +20          # -> idx 11 (jal target), x5 = 28
        # 7    28    addi x6, x0, 0xff     # 不应执行
        # 8    32    nop
        # 9    36    nop
        # 10   40    nop
        # 11   44    addi x6, x5, 0        # x6 = x5 = 28
        # 12   48    addi x2, x2, 1        # x2++
        # 13   52    addi x1, x1, -1       # x1--
        # 14   56    bne  x1, x0, -8       # -> idx 12 if x1!=0
        # 15   60    addi x7, x0, 0x55     # done marker

        jal_offset = (11 - 6) * 4  # index 11 - index 6 = 5 * 4 = 20

        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 3),       # 0:  x1 = 3
            enc_i(OP_IMM, 2, 0b000, 0, 0),       # 4:  x2 = 0
            enc_i(OP_IMM, 3, 0b000, 0, 0x11),    # 8:  x3 = 0x11
            enc_b(BRANCH, 0b000, 0, 0, 8),       # 12: beq x0,x0,+8 -> 20
            enc_i(OP_IMM, 4, 0b000, 0, 0xff),    # 16: 不应执行
            enc_i(OP_IMM, 4, 0b000, 0, 0x22),    # 20: x4 = 0x22
            enc_jal(5, 20),                       # 24: jal x5, +20 -> 44
            enc_i(OP_IMM, 6, 0b000, 0, 0xff),    # 28: 不应执行
            nop(), nop(), nop(),                  # 32,36,40
            enc_i(OP_IMM, 6, 0b000, 5, 0),       # 44: x6 = x5
            enc_i(OP_IMM, 2, 0b000, 2, 1),       # 48: x2++
            enc_i(OP_IMM, 1, 0b000, 1, -1),      # 52: x1--
            enc_b(BRANCH, 0b001, 1, 0, -8),      # 56: bne x1,x0,-8 -> 48
            enc_i(OP_IMM, 7, 0b000, 0, 0x55),    # 60: done
        ]
        # Pad to 1024 words so PC doesn't wrap in 300 cycles
        IMEM_WORDS = 1024
        prog = prog + [nop()] * (IMEM_WORDS - len(prog))

        self.core = RV12Core(core_id=0)
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
    dut = TbBranchPred()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    c = dut.core

    def proc():
        for cyc in range(300):
            pc_val = (yield c.imem_addr)
            isv = (yield c.dbg_is_valid)
            ispc = (yield c.pc_dbg)
            is_op = (yield c.imem_addr)
            is_imm = (yield c.imem_addr)
            ex1v = (yield c.dbg_ex1_valid)
            ex1rd = (yield c.dbg_ex1_rd)
            misp = 0
            red = 0
            red_pc = 0
            yield c.dbg_reg_addr.eq(1)
            yield Tick()
            x1v = (yield c.dbg_reg_rdata)
            if cyc < 200:
                print(f"c{cyc:3d}: pc={pc_val:3d} ispc={ispc:3d} isv={isv} op={is_op:02x} imm={is_imm:5d} ex1v={ex1v} rdx={ex1rd:2d} red={red} red_pc={red_pc:3d} misp={misp} x1={x1v}")

        regs = {}
        for i in range(8):
            yield c.dbg_reg_addr.eq(i)
            yield Tick()
            regs[f"x{i}"] = (yield c.dbg_reg_rdata)

        print(f"x1={regs['x1']} x2={regs['x2']} x3=0x{regs['x3']:x} "
              f"x4=0x{regs['x4']:x} x5={regs['x5']} x6={regs['x6']} x7=0x{regs['x7']:x}")

        errs = []
        if regs['x1'] != 0: errs.append(f"x1=0 expected 0, got {regs['x1']}")
        if regs['x2'] != 3: errs.append(f"x2=3 expected 3, got {regs['x2']}")
        if regs['x3'] != 0x11: errs.append(f"x3=0x11 expected 0x11, got {regs['x3']}")
        if regs['x4'] != 0x22: errs.append(f"x4=0x22 expected 0x22, got {regs['x4']}")
        if regs['x5'] != 28: errs.append(f"x5=28 expected 28, got {regs['x5']}")
        if regs['x6'] != 28: errs.append(f"x6=28 expected 28, got {regs['x6']}")
        if regs['x7'] != 0x55: errs.append(f"x7=0x55 expected 0x55, got {regs['x7']}")

        if errs:
            for e in errs:
                print(f"FAIL: {e}")
        else:
            print("OK: branch prediction (Step79) test passed.")

        assert not errs, "\n".join(errs)

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
