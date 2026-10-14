# tests/test_reloc_chain_mv_chase.py
# Step48/Step74: verify MV_QUERY finite-depth forwarding chain chase.
#
# Program:
#   1) addi x1, x0, 1         => x1 = 1 (simulated handle)
#   2) addi x2, x0, 10        => x2 = 10
#   3) GC_MV_RELOC(1,2,rd=5)  => MV forwarding: 1 -> 10, x5 = 0 (RELOC return)
#   4) addi x4, x0, 20        => x4 = 20
#   5) GC_MV_RELOC(2,4,rd=6)  => MV forwarding: 10 -> 20, chase: 1->10->20
#   6) sw x1, 0(x0)           => store old handle 1
#   7) lw x3, 0(x0)           => load with read barrier: MV chases 1->10->20 => returns 20

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_mv_coproc import GCMvCoProc
from rtl.isa import enc_i, enc_s, OP_IMM, LOAD, STORE, enc_gc_mv_reloc


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbRelocChain(Elaboratable):
    def __init__(self):
        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 1),    # addi x1, x0, 1
            enc_i(OP_IMM, 2, 0b000, 0, 10),   # addi x2, x0, 10
            enc_gc_mv_reloc(1, 2, rd=5),       # 1 -> 10
        ]

        prog += [nop()] * 8

        prog += [
            enc_i(OP_IMM, 4, 0b000, 0, 20),   # addi x4, x0, 20
            enc_gc_mv_reloc(2, 4, rd=6),       # 10 -> 20
        ]

        prog += [nop()] * 8

        prog += [
            enc_s(STORE, 0b010, 0, 1, 0),     # sw x1, 0(x0)
            enc_i(LOAD, 3, 0b010, 0, 0),      # lw x3, 0(x0)
            nop(), nop(), nop(), nop(),
        ]

        # Fill rest with NOPs; avoid PC wrap by giving enough NOP cushion
        # so the pipeline settles before reaching the end of IMem.
        prog = prog + [nop()] * (256 - len(prog))

        dmem_init = [0] * 64

        self.core = RV12Core(core_id=0, rb_mode=0)  # all loads trigger MV_QUERY
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=64, init=dmem_init)
        # chase_depth=2 resolves 1->10->20 in one MV_QUERY
        self.mv = GCMvCoProc(ncores=1, chase_depth=2)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.submodules.mv = mv = self.mv

        m.d.comb += [
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
        ]

        m.d.comb += [
            dm.req_valid.eq(c.dmem_valid),
            dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
        ]

        # GC (sweep) not connected — GC_NEW not used
        m.d.comb += [
            c.gc_enq_ready.eq(0),
            c.gc_rsp_valid.eq(0),
            c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0),
        ]

        # write barrier: always ready
        m.d.comb += c.wb_enq_ready.eq(1)

        # core <-> mv (read barrier + direct GC_MV_RELOC)
        m.d.comb += [
            mv.cmd_enq_valid[0].eq(c.mv_cmd_valid),
            c.mv_cmd_ready.eq(mv.cmd_enq_ready[0]),
            mv.cmd_tag[0].eq(c.mv_cmd_tag),
            mv.cmd_op[0].eq(c.mv_cmd_op),
            mv.cmd_rd[0].eq(c.mv_cmd_rd),
            mv.cmd_rs1[0].eq(c.mv_cmd_rs1),
            mv.cmd_rs2[0].eq(c.mv_cmd_rs2),

            c.mv_rsp_valid.eq(mv.rsp_valid[0]),
            c.mv_rsp_tag.eq(mv.rsp_tag[0]),
            c.mv_rsp_rd.eq(mv.rsp_rd[0]),
            c.mv_rsp_data.eq(mv.rsp_data[0]),
            mv.rsp_take[0].eq(c.mv_rsp_take),
        ]

        return m


def main():
    dut = TbRelocChain()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core

    def proc():
        for _ in range(300):
            yield Tick()

        # read x3 (load with read barrier result)
        yield c.dbg_reg_addr.eq(3)
        yield Tick()
        x3 = (yield c.dbg_reg_rdata)

        print(f"x3={x3}")
        assert x3 == 20, "read barrier should chase 1->10->20 and return 20"
        print("OK: MV_QUERY chased forwarding chain (1->10->20).")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
