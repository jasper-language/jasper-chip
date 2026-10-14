# tests/test_wb_ptr_filter.py
# Step16 实际测试效果：验证“写屏障指针过滤”。
#
# 目标：
#   - 当 wb_ptr_filter=1 时，仅对“看起来像指针”的写入上报写屏障事件。
#   - 当前最小判定：wdata[31]==1（MSB 为 1）。
#
# 场景：
#   sw 7           -> 非指针（MSB=0） -> 不上报
#   sw -1 (0xFFFF...) -> 指针（MSB=1） -> 上报
#   sw 8           -> 非指针（MSB=0） -> 不上报
#   sw -2 (0xFFFF...) -> 指针（MSB=1） -> 上报
#
# 判定：
#   - scan.ev_count 最终必须为 2
#   - dmem[0..12] 四次写入都必须正确落到内存（过滤不影响内存写）

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_scan_coproc import GCScanCoProc
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.gc_mv_coproc import GCMvCoProc
from rtl.isa import enc_i, enc_s, enc_jal, OP_IMM, STORE


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbPtrFilter(Elaboratable):
    def __init__(self):
        prog = [
            # x1=7 (non-pointer), sw x1,0
            enc_i(OP_IMM, 1, 0b000, 0, 7),
            *([nop()] * 16),
            enc_s(STORE, 0b010, 0, 1, 0),

            # x2=-1 (pointer), sw x2,4
            enc_i(OP_IMM, 2, 0b000, 0, -1),
            *([nop()] * 16),
            enc_s(STORE, 0b010, 0, 2, 4),

            # x3=8 (non-pointer), sw x3,8
            enc_i(OP_IMM, 3, 0b000, 0, 8),
            *([nop()] * 16),
            enc_s(STORE, 0b010, 0, 3, 8),

            # x4=-2 (pointer), sw x4,12
            enc_i(OP_IMM, 4, 0b000, 0, -2),
            *([nop()] * 16),
            enc_s(STORE, 0b010, 0, 4, 12),

            enc_jal(0, 0),
            nop(),
        ]
        prog = prog + [nop()] * (256 - len(prog))

        self.core = RV12Core(core_id=0, wb_ptr_filter=1)
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=64, init=[0] * 64)

        # scan 共享引擎在单核时等价于普通 consumer
        # Step18：本测试只验证“指针过滤”，不希望被 card 去重影响。
        self.scan = GCScanCoProc(ncores=1, fifo_depth=8, consume_every=1, dedup_enable=False)
        self.sweep = GCSweepCoProc(ncores=1, engine_latency=0)
        self.mv = GCMvCoProc(ncores=1)

        # debug mux
        self.dbg_en = Signal(reset=0)
        self.dbg_addr = Signal(32, reset=0)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.submodules.scan = sc = self.scan
        m.submodules.sweep = sw = self.sweep
        m.submodules.mv = mv = self.mv

        # IMEM
        m.d.comb += [
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
        ]

        # DMEM (no arb in single-core)
        m.d.comb += [
            dm.req_valid.eq(Mux(self.dbg_en, 0, c.dmem_valid)),
            dm.req_we.eq(Mux(self.dbg_en, 0, c.dmem_we)),
            dm.req_addr.eq(Mux(self.dbg_en, self.dbg_addr, c.dmem_addr)),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
            c.dmem_grant.eq(1),  # single-core always grant
        ]

        # write barrier -> scan
        m.d.comb += [
            sc.wb_valid[0].eq(c.wb_enq_valid),
            c.wb_enq_ready.eq(sc.wb_ready[0]),
            sc.wb_addr[0].eq(c.wb_addr),
            sc.wb_data[0].eq(c.wb_data),
        ]

                # GC sweep（本测试不使用 GC 指令，因此直接禁用通道）
        m.d.comb += [
            c.gc_enq_ready.eq(0),
            c.gc_rsp_valid.eq(0),
            c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0),
        ]

# MV (unused)
        m.d.comb += [
            mv.cmd_enq_valid[0].eq(c.mv_cmd_valid),
            c.mv_cmd_ready.eq(mv.cmd_enq_ready[0]),
            mv.cmd_op[0].eq(c.mv_cmd_op),
            mv.cmd_rd[0].eq(c.mv_cmd_rd),
            mv.cmd_rs1[0].eq(c.mv_cmd_rs1),
            mv.cmd_rs2[0].eq(c.mv_cmd_rs2),
            mv.cmd_tag[0].eq(c.mv_cmd_tag),

            c.mv_rsp_valid.eq(mv.rsp_valid[0]),
            c.mv_rsp_rd.eq(mv.rsp_rd[0]),
            c.mv_rsp_data.eq(mv.rsp_data[0]),
            c.mv_rsp_tag.eq(mv.rsp_tag[0]),
            mv.rsp_take[0].eq(c.mv_rsp_take),
        ]

        return m


def main():
    dut = TbPtrFilter()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # wait until 2 pointer events consumed
        for cyc in range(2000):
            yield Tick()
            ev = (yield dut.scan.ev_count[0])
            if ev == 2:
                break
        ev = (yield dut.scan.ev_count[0])
        assert ev == 2, f"expected 2 pointer events, got {ev}"

        # read memory words at 0,4,8,12
        mem = {}
        for addr in [0,4,8,12]:
            yield dut.dbg_en.eq(1)
            yield dut.dbg_addr.eq(addr)
            yield Tick()
            mem[addr] = (yield dut.dmem.rsp_rdata)
        yield dut.dbg_en.eq(0)

        assert mem[0] == 7, mem
        assert mem[4] == 0xFFFFFFFF, mem
        assert mem[8] == 8, mem
        assert mem[12] == 0xFFFFFFFE, mem

        print(f"OK: ptr_filter works: ev_count={ev} mem={mem}")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
