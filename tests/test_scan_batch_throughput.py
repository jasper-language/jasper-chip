# tests/test_scan_batch_throughput.py
# Step17 “实际测试效果”：验证 scan 引擎的“批处理/突发消费(batch_size)”确实能提升吞吐。
#
# 思路：
#   - 单核连续产生 N 次 store（每次都需要写屏障事件）
#   - scan 设置 consume_every=8，制造“慢扫描”
#   - 对比 batch_size=1 vs batch_size=4 时，到达 ev_count==N 的 cycle 数
#
# 预期：batch_size=4 明显更快（至少快几十个 cycle）。

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_scan_coproc import GCScanCoProc
from rtl.isa import enc_i, enc_s, enc_jal, OP_IMM, STORE


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbBatch(Elaboratable):
    def __init__(self, nstores: int, batch_size: int):
        self.nstores = int(nstores)
        self.batch_size = int(batch_size)

        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 1),  # x1=1
            *([nop()] * 16),
        ]
        for i in range(self.nstores):
            prog.append(enc_s(STORE, 0b010, 0, 1, i * 4))  # sw x1, i*4(x0)
        prog += [enc_jal(0, 0), nop()]
        prog = prog + [nop()] * (256 - len(prog))

        self.core = RV12Core(core_id=0, wb_ptr_filter=0)  # 不过滤，所有 store 上报
        self.imem = SimpleIMem(words=256, init=prog)
        self.dmem = SimpleDMem(words=256, init=[0] * 256)
        # Step18：该测试对比 batch_size 对吞吐的影响，需要 ev_count==store 条数，因此关闭 card 去重。
        self.scan = GCScanCoProc(ncores=1, fifo_depth=8, consume_every=8, batch_size=batch_size, dedup_enable=False)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.submodules.scan = sc = self.scan

        # IMEM
        m.d.comb += [
            im.addr.eq(c.imem_addr),
            c.imem_rdata.eq(im.rdata),
        ]

        # DMEM（单核永远 grant）
        m.d.comb += [
            dm.req_valid.eq(c.dmem_valid),
            dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
            c.dmem_grant.eq(1),
        ]

        # write barrier -> scan
        m.d.comb += [
            sc.wb_valid[0].eq(c.wb_enq_valid),
            c.wb_enq_ready.eq(sc.wb_ready[0]),
            sc.wb_addr[0].eq(c.wb_addr),
            sc.wb_data[0].eq(c.wb_data),
        ]

        # 禁用 sweep/mv（本测试只关心 scan 吞吐）
        m.d.comb += [
            c.gc_enq_ready.eq(0),
            c.gc_rsp_valid.eq(0),
            c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0),
            c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0),
            c.mv_rsp_tag.eq(0),
            c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),
        ]

        return m


def run_case(nstores: int, batch_size: int, max_cycles: int = 5000) -> int:
    dut = TbBatch(nstores=nstores, batch_size=batch_size)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    result = {"cycles": None}

    def proc():
        for cyc in range(max_cycles):
            yield Tick()
            ev = (yield dut.scan.ev_count[0])
            if ev == nstores:
                result["cycles"] = cyc + 1
                return
        raise AssertionError(f"timeout: ev_count never reached {nstores} (got {ev})")

    sim.add_sync_process(proc)
    sim.run()
    assert result["cycles"] is not None
    return int(result["cycles"])


def main():
    n = 32
    c1 = run_case(nstores=n, batch_size=1)
    c4 = run_case(nstores=n, batch_size=4)

    print(f"batch_size=1 cycles={c1}, batch_size=4 cycles={c4}")
    # 经验阈值：batch=4 至少快 80 cycle（在 consume_every=8 时应更明显）
    assert c4 < c1 - 80, (c1, c4)
    print("OK: scan batch_size increases effective throughput under bandwidth limit.")


if __name__ == "__main__":
    main()
