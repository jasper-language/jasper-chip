# tests/test_store_wb_event_dep.py
# Step13 “实际测试效果”：验证“写屏障 + 依赖阻塞”在最容易出坑的场景下仍正确。
#
# 场景：
#   GC_NEW x1          (x1 的值要等 sweep 协处理器返回)
#   SW x1, 0(x0)       (紧跟其后的 store 立即依赖 x1)
#
# 过去的坑：
#   如果 scoreboard 的 pending 位同步更新太晚，
#   SW 可能在进入 ID2 的那个时钟沿就把 rs2v 锁存成旧 x1=0，
#   之后即使 stall 也来不及，最终会把 0 写进内存。
#
# 本测试通过两件事来判定正确性：
#   1) dmem[0] 最终必须写成 x1 的新值（alloc_ptr，当前实现为 1）
#   2) scan 协处理器必须接收到 1 条写屏障事件，且事件内容符合 Step17 的格式：
#      (card_id, obj_id)

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_scan_coproc import GCScanCoProc
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.isa import enc_i, enc_s, enc_gc_new, enc_jal, OP_IMM, STORE


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbStoreWB(Elaboratable):
    def __init__(self):
        prog = [
            enc_gc_new(1),                     # x1 <- 1 (after GC)
            enc_s(STORE, 0b010, 0, 1, 64),     # sw x1, 64(x0)  (用于验证 card_id / obj_id)
            enc_jal(0, 0),                      # 死循环：避免 IMEM 地址溢出后“绕回 0”导致程序重复执行
            nop(), nop(),
        ] + [nop()] * (64 - 5)

        dmem_init = [0] * 64

        self.core = RV12Core(core_id=0)
        self.imem = SimpleIMem(words=64, init=prog)
        self.dmem = SimpleDMem(words=64, init=dmem_init)
        # sweep 故意变慢：制造“x1 很久以后才就绪”的压力
        self.sweep = GCSweepCoProc(ncores=1, engine_latency=30)
        self.scan  = GCScanCoProc(ncores=1)

        # Debug mux: allow reading DMEM without poking core ports
        self.dbg_en   = Signal(reset=0)
        self.dbg_addr = Signal(32, reset=0)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core  = c  = self.core
        m.submodules.imem  = im = self.imem
        m.submodules.dmem  = dm = self.dmem
        m.submodules.sweep = sw = self.sweep
        m.submodules.scan  = sc = self.scan

        # IMEM
        m.d.comb += [
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
        ]

        # DMEM with debug mux
        m.d.comb += [
            dm.req_valid.eq(Mux(self.dbg_en, 0, c.dmem_valid)),
            dm.req_we.eq(Mux(self.dbg_en, 0, c.dmem_we)),
            dm.req_addr.eq(Mux(self.dbg_en, self.dbg_addr, c.dmem_addr)),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
        ]

        # core <-> sweep (GC)
        m.d.comb += [
            sw.cmd_enq_valid[0].eq(c.gc_enq_valid),
            c.gc_enq_ready.eq(sw.cmd_enq_ready[0]),
            sw.cmd_tag[0].eq(c.gc_tag),
            sw.cmd_op[0].eq(c.gc_op),
            sw.cmd_rd[0].eq(c.gc_rd),
            sw.cmd_rs1[0].eq(c.gc_rs1),
            sw.cmd_rs2[0].eq(c.gc_rs2),

            c.gc_rsp_valid.eq(sw.rsp_valid[0]),
            c.gc_rsp_tag.eq(sw.rsp_tag[0]),
            c.gc_rsp_rd.eq(sw.rsp_rd[0]),
            c.gc_rsp_data.eq(sw.rsp_data[0]),
            sw.rsp_take[0].eq(c.gc_rsp_take),
        ]

        # core <-> scan (write barrier)
        m.d.comb += [
            sc.wb_valid[0].eq(c.wb_enq_valid),
            c.wb_enq_ready.eq(sc.wb_ready[0]),
            sc.wb_addr[0].eq(c.wb_addr),
            sc.wb_data[0].eq(c.wb_data),
        ]

        # disable mv (not used)
        m.d.comb += [
            c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0),
            c.mv_rsp_tag.eq(0),
            c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),
        ]

        return m


def main():
    dut = TbStoreWB()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core

    def proc():
        # 早期检查：GC 还没回，内存/scan 也不该被写
        for _ in range(20):
            yield Tick()

        # 读 x1（应为 0）
        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        x1_early = (yield c.dbg_reg_rdata)

        # 读 dmem[64]（应为 0）
        yield dut.dbg_en.eq(1)
        yield dut.dbg_addr.eq(64)
        yield Tick()
        d0_early = (yield dut.dmem.rsp_rdata)
        yield dut.dbg_en.eq(0)

        ev_early = (yield dut.scan.ev_count[0])

        print(f"C20: x1=0x{x1_early:08x} dmem64=0x{d0_early:08x} ev={ev_early}")
        assert x1_early == 0
        assert d0_early == 0
        assert ev_early == 0

        # 跑到足够久，让 GC_NEW 返回并完成 store+写屏障
        for _ in range(200):
            yield Tick()

        # 读 x1（应为 1）
        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        x1 = (yield c.dbg_reg_rdata)

        # 读 dmem[64]
        yield dut.dbg_en.eq(1)
        yield dut.dbg_addr.eq(64)
        yield Tick()
        d0 = (yield dut.dmem.rsp_rdata)
        yield dut.dbg_en.eq(0)

        ev = (yield dut.scan.ev_count[0])
        last_addr = (yield dut.scan.last_addr[0])
        last_data = (yield dut.scan.last_data[0])

        print(f"C220: x1=0x{x1:08x} dmem64=0x{d0:08x} ev={ev} last_card=0x{last_addr:08x} last_obj=0x{last_data:08x}")

        assert x1 == 1, "GC_NEW should return alloc_ptr=1"
        assert d0 == 1, "dependent SW must store new x1, not stale 0"
        assert ev == 1, "scan should accept exactly one write-barrier event"
        # Step17：事件为 (card_id, obj_id)
        # store_addr=64 => card_id=64>>6=1, obj_id=64>>4=4
        assert last_addr == 1, "write-barrier last_addr should be card_id=1"
        assert last_data == 4, "write-barrier last_data should be obj_id=4"

        print("OK: immediate dependent store is blocked by scoreboard, and write-barrier event matches committed store.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
