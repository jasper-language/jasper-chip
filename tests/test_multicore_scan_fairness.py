# tests/test_multicore_scan_fairness.py
# Step15 实际测试效果：4 核同时 burst store，在 scan 背压下验证
#   - 每核写屏障事件不丢（ev_count 达标）
#   - 内存写入正确
#   - 完成周期差异不过分悬殊（无明显饥饿）

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem, RRArbiter
from rtl.gc_scan_coproc import GCScanCoProc
from rtl.isa import enc_i, enc_s, enc_jal, OP_IMM, STORE


def nop():
    # addi x0, x0, 0
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbMultiCoreBurst(Elaboratable):
    def __init__(self, ncores=4, stores_per_core=8, scan_fifo_depth=1, scan_consume_every=8):
        self.ncores = ncores
        self.stores_per_core = stores_per_core

        # per-core programs
        imem_inits = []
        for cid in range(ncores):
            base = cid * 64  # bytes
            imm = cid + 1
            stores = [enc_s(STORE, 0b010, 0, 1, base + off) for off in range(0, stores_per_core * 4, 4)]
            prog = [
                enc_i(OP_IMM, 1, 0b000, 0, imm),
                *([nop()] * 16),  # 留出足够空拍，避免 addi->store 数据相关（无整数旁路时会读旧值）
                *stores,
                enc_jal(0, 0),
                nop(),
            ]
            prog = prog + [nop()] * (128 - len(prog))
            imem_inits.append(prog)

        self.cores = [RV12Core(core_id=i) for i in range(ncores)]
        self.imems = [SimpleIMem(words=128, init=imem_inits[i]) for i in range(ncores)]

        # shared dmem + arb
        self.dmem = SimpleDMem(words=256, init=[0] * 256)
        self.arb = RRArbiter(n=ncores)

        # scan (write barrier)
        # Step18：该测试验证多核写屏障事件“不丢/公平”，需要 ev_count==store 条数，因此关闭 card 去重。
        self.scan = GCScanCoProc(ncores=ncores, fifo_depth=scan_fifo_depth, consume_every=scan_consume_every, dedup_enable=False)

        # debug read mux for dmem
        self.dbg_en = Signal(reset=0)
        self.dbg_addr = Signal(32, reset=0)

    def elaborate(self, platform):
        m = Module()
        m.submodules.dmem = dm = self.dmem
        m.submodules.arb = arb = self.arb
        m.submodules.scan = sc = self.scan

        # cores + imem
        for i in range(self.ncores):
            core = self.cores[i]
            imem = self.imems[i]
            m.submodules[f"core{i}"] = core
            m.submodules[f"imem{i}"] = imem

            m.d.comb += [
                imem.addr.eq(core.imem_addr),
                core.imem_rdata.eq(imem.rdata),

                arb.m_valid[i].eq(core.dmem_valid),
                arb.m_we[i].eq(core.dmem_we),
                arb.m_addr[i].eq(core.dmem_addr),
                arb.m_wdata[i].eq(core.dmem_wdata),
                core.dmem_rdata.eq(arb.m_rdata[i]),
                # Step15：仲裁 grant 反馈到 core，避免多核下单拍请求丢失。
                core.dmem_grant.eq(arb.m_grant[i]),

                # write barrier -> scan
                sc.wb_valid[i].eq(core.wb_enq_valid),
                core.wb_enq_ready.eq(sc.wb_ready[i]),
                sc.wb_addr[i].eq(core.wb_addr),
                sc.wb_data[i].eq(core.wb_data),

                # disable GC/MV (this test focuses on store/write-barrier)
                core.gc_enq_ready.eq(1),
                core.gc_rsp_valid.eq(0),
                core.gc_rsp_tag.eq(0),
                core.gc_rsp_rd.eq(0),
                core.gc_rsp_data.eq(0),

                core.mv_cmd_ready.eq(1),
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
    stores = 8

    dut = TbMultiCoreBurst(ncores=ncores, stores_per_core=stores, scan_fifo_depth=1, scan_consume_every=8)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    done_cycle = [None] * ncores

    def proc():
        max_cycles = 20000
        for cyc in range(max_cycles):
            yield Tick()

            for i in range(ncores):
                if done_cycle[i] is None:
                    ev = (yield dut.scan.ev_count[i])
                    if ev == stores:
                        done_cycle[i] = cyc + 1

            if all(x is not None for x in done_cycle):
                break

        assert all(x is not None for x in done_cycle), f"not all cores finished within {max_cycles} cycles: {done_cycle}"

        # verify memory at each core's last store address
        last_values = []
        for cid in range(ncores):
            base = cid * 64
            last_addr = base + (stores - 1) * 4
            yield dut.dbg_en.eq(1)
            yield dut.dbg_addr.eq(last_addr)
            yield Tick()
            v = (yield dut.dmem.rsp_rdata)
            last_values.append((last_addr, v))
        yield dut.dbg_en.eq(0)

        print("last_values=", last_values)
        for cid, (addr, v) in enumerate(last_values):
            exp = cid + 1
            assert v == exp, f"dmem[{addr}] expected {exp}, got {v}"

        # fairness heuristic: max-min within bound
        mn = min(done_cycle)
        mx = max(done_cycle)
        spread = mx - mn
        print(f"done_cycles={done_cycle} spread={spread}")
        # keep bound conservative: we only need to catch gross starvation
        assert spread < 3000, f"possible starvation: spread too large ({spread}) cycles"

    sim.add_sync_process(proc)
    sim.run()

    print("OK: multicore burst stores complete; per-core events not lost; memory correct; no obvious starvation.")


if __name__ == "__main__":
    main()
