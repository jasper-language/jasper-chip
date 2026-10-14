# tests/test_epoch_via_gc_instruction.py
# -*- coding: utf-8 -*-
#
# Step20 实测：用 GC_EPOCH 指令驱动 scan 的 epoch_advance。
#
# 期望：
#   - 执行 3 次同一卡写入：uniq_enq=2、dup_drop=1、in_count=3
#   - epoch 从 0 翻转到 1（由 GC_EPOCH 指令触发）

from amaranth import Elaboratable, Module
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_scan_coproc import GCScanCoProc
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.isa import enc_i, enc_s, enc_jal, enc_gc_epoch, OP_IMM, STORE


def nop():
    # addi x0, x0, 0
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbEpochViaGC(Elaboratable):
    def __init__(self):
        # store_addr=64 => card_id=1 (>>6), obj_id=4 (>>4)
        # 注意：本项目的简化核没有整数旁路，且 store 合并/队列行为比较“研究化”。
        # 为了让 3 次 store 都明确产生写屏障事件，这里插入少量 NOP 拉开距离。
        gap = [nop()] * 8
        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 1),        # x1 = 1
            *gap,
            enc_s(STORE, 0b010, 0, 1, 64),        # sw x1,64(x0)  uniq
            *gap,
            enc_s(STORE, 0b010, 0, 1, 64),        # sw x1,64(x0)  dup
            *gap,
            enc_gc_epoch(),                       # epoch toggle (via sweep->scan)
            *gap,
            enc_s(STORE, 0b010, 0, 1, 64),        # sw x1,64(x0)  uniq in new epoch
            enc_jal(0, 0),                        # loop
        ]
        prog = prog + [nop()] * (64 - len(prog))

        self.core = RV12Core(core_id=0)
        self.imem = SimpleIMem(words=64, init=prog)
        self.dmem = SimpleDMem(words=64, init=[0] * 64)

        # scan 不消费，便于只观察 dedup/epoch 行为
        self.scan = GCScanCoProc(ncores=1, fifo_depth=4, consume_every=0, batch_size=1, dedup_enable=True, cardset_size=4)
        self.sweep = GCSweepCoProc(ncores=1)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.submodules.scan = sc = self.scan
        m.submodules.sweep = sw = self.sweep

        # IMEM
        m.d.comb += [im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata)]

        # DMEM
        m.d.comb += [
            dm.req_valid.eq(c.dmem_valid),
            dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
        ]

        # core <-> scan (write barrier)
        m.d.comb += [
            sc.wb_valid[0].eq(c.wb_enq_valid),
            c.wb_enq_ready.eq(sc.wb_ready[0]),
            sc.wb_addr[0].eq(c.wb_addr),
            sc.wb_data[0].eq(c.wb_data),
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

        # Step20：epoch 广播到 scan
        m.d.comb += sc.epoch_advance.eq(sw.epoch_tick[0])

        # disable mv
        m.d.comb += [
            c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0),
            c.mv_rsp_tag.eq(0),
            c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),
        ]

        return m


def main():
    dut = TbEpochViaGC()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        # 初始 epoch=0
        assert (yield dut.scan.epoch) == 0

        # 跑足够久，让 5 条指令都执行完
        for _ in range(200):
            yield Tick()

        ep = (yield dut.scan.epoch)
        in_cnt = (yield dut.scan.in_count[0])
        uniq = (yield dut.scan.uniq_enq[0])
        dup = (yield dut.scan.dup_drop[0])
        print(f"epoch={ep} in={in_cnt} uniq={uniq} dup={dup}")

        assert ep == 1, "epoch should have toggled to 1 via GC_EPOCH"
        assert in_cnt == 3, f"expected in_count=3 got {in_cnt}"
        assert uniq == 2, f"expected uniq_enq=2 got {uniq}"
        assert dup == 1, f"expected dup_drop=1 got {dup}"

    sim.add_sync_process(proc)
    sim.run()
    print("OK: GC_EPOCH drives scan epoch_advance and re-dirties same card in new epoch.")


if __name__ == "__main__":
    main()
