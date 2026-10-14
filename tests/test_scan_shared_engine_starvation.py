# tests/test_scan_shared_engine_starvation.py
# Step16 实际测试效果（补充）：验证“共享扫描引擎”在极端负载下不会把小核饿死。
#
# 场景：
#   - core0：64 次 store（写屏障事件很多）
#   - core1/2/3：各 2 次 store（事件很少）
#   - scan：共享引擎 consume_every=4，fifo_depth=1（制造背压）
#
# 判定：
#   1) 每核 ev_count 达标（core0=64，其他=2）
#   2) 小核完成周期不会“离谱地晚”（粗略防饿死）
#
from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem, RRArbiter
from rtl.gc_scan_coproc import GCScanCoProc
from rtl.isa import enc_i, enc_s, enc_jal, OP_IMM, STORE


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbSharedScanStarve(Elaboratable):
    def __init__(self, ncores=4):
        self.ncores = ncores

        # programs
        imem_inits = []
        stores_list = [64, 2, 2, 2]
        for cid in range(ncores):
            stores = stores_list[cid]
            base = cid * 256  # bytes, keep separated
            # pointer-ish value: negative => MSB=1
            imm = -1 - cid
            stores_insn = [enc_s(STORE, 0b010, 0, 1, base + off) for off in range(0, stores * 4, 4)]
            prog = [
                enc_i(OP_IMM, 1, 0b000, 0, imm),
                *([nop()] * 16),
                *stores_insn,
                enc_jal(0, 0),
                nop(),
            ]
            prog = prog + [nop()] * (512 - len(prog))
            imem_inits.append(prog)

        self.cores = [RV12Core(core_id=i, wb_ptr_filter=1) for i in range(ncores)]
        self.imems = [SimpleIMem(words=512, init=imem_inits[i]) for i in range(ncores)]
        self.arb = RRArbiter(ncores)
        self.dmem = SimpleDMem(words=1024, init=[0]*1024)
        # Step18：该测试关注“共享 scan 引擎的公平性/背压”，希望事件条数等于 store 条数，关闭 card 去重。
        self.scan = GCScanCoProc(ncores=ncores, fifo_depth=1, consume_every=4, dedup_enable=False)

        # debug mux
        self.dbg_en = Signal(reset=0)
        self.dbg_addr = Signal(32, reset=0)

    def elaborate(self, platform):
        m = Module()
        sc = self.scan
        m.submodules.scan = sc

        dm = self.dmem
        arb = self.arb
        m.submodules.dmem = dm
        m.submodules.arb = arb

        for i in range(self.ncores):
            core = self.cores[i]
            imem = self.imems[i]
            m.submodules[f"core{i}"] = core
            m.submodules[f"imem{i}"] = imem

            # IMEM
            m.d.comb += [
                imem.addr.eq(core.imem_addr),
                core.imem_rdata.eq(imem.rdata),
            ]

            # DMEM master -> arb
            m.d.comb += [
                arb.m_valid[i].eq(core.dmem_valid),
                arb.m_we[i].eq(core.dmem_we),
                arb.m_addr[i].eq(core.dmem_addr),
                arb.m_wdata[i].eq(core.dmem_wdata),
                core.dmem_rdata.eq(arb.m_rdata[i]),
                core.dmem_grant.eq(arb.m_grant[i]),
            ]

            # write barrier -> scan
            m.d.comb += [
                sc.wb_valid[i].eq(core.wb_enq_valid),
                core.wb_enq_ready.eq(sc.wb_ready[i]),
                sc.wb_addr[i].eq(core.wb_addr),
                sc.wb_data[i].eq(core.wb_data),
            ]

            # disable gc/mv channels
            m.d.comb += [
                core.gc_enq_ready.eq(0),
                core.gc_rsp_valid.eq(0),
                core.gc_rsp_tag.eq(0),
                core.gc_rsp_rd.eq(0),
                core.gc_rsp_data.eq(0),

                core.mv_cmd_ready.eq(0),
                core.mv_rsp_valid.eq(0),
                core.mv_rsp_tag.eq(0),
                core.mv_rsp_rd.eq(0),
                core.mv_rsp_data.eq(0),
            ]

        # arb -> dmem with debug mux
        m.d.comb += [
            dm.req_valid.eq(Mux(self.dbg_en, 0, arb.s_valid)),
            dm.req_we.eq(Mux(self.dbg_en, 0, arb.s_we)),
            dm.req_addr.eq(Mux(self.dbg_en, self.dbg_addr, arb.s_addr)),
            dm.req_wdata.eq(arb.s_wdata),
            arb.s_rdata.eq(dm.rsp_rdata),
        ]

        return m


def main():
    ncores = 4
    dut = TbSharedScanStarve(ncores=ncores)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    target = [64, 2, 2, 2]
    done = [None]*ncores

    def proc():
        max_cycles = 40000
        for cyc in range(max_cycles):
            yield Tick()
            for i in range(ncores):
                if done[i] is None:
                    ev = (yield dut.scan.ev_count[i])
                    if ev == target[i]:
                        done[i] = cyc + 1
            if all(x is not None for x in done):
                break

        assert all(x is not None for x in done), f"not finished: {done}"

        # 小核不应被离谱饿死：它们完成周期不应比最早完成者晚太多
        mn = min(done)
        mx_small = max(done[1:])
        spread_small = mx_small - mn
        print(f"done_cycles={done} small_spread={spread_small}")
        assert spread_small < 15000, f"small cores may be starved: spread={spread_small}"

        print("OK: shared scan engine serves small cores under heavy core0 load.")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()