# tests/test_scan_card_dedup.py
# Step18 “实际测试效果”：验证 card 去重（remembered set / card table 的核心优化）确实生效。
#
# 场景：同一个 card 内对多个 word 反复 store。
# 期望：
#   - 内存写入仍全部发生（不影响 store commit）
#   - scan 侧只把该 card 入队一次（uniq_enq=1），其余写入被去重丢弃（dup_drop=N-1）

from amaranth import *
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.gc_scan_coproc import GCScanCoProc
from rtl.isa import enc_i, enc_s, enc_jal, OP_IMM, STORE


def nop():
    return enc_i(OP_IMM, 0, 0b000, 0, 0)


class TbDedup(Elaboratable):
    def __init__(self, dedup_enable=True):
        # addi x1, x0, 1
        # sw x1, 0/4/8/12(x0)  -> 同一 card（card_shift=6 => 64B）
        # 注意：RV12Core 的 store-data 前递通路在某些紧邻场景下仍可能拿到旧值。
        # 这里插入足够 NOP，确保 x1 的写回已经完成，使测试聚焦于“scan card 去重”本身。
        pad = 20
        prog = [
            enc_i(OP_IMM, 1, 0b000, 0, 1),
        ] + [nop()] * pad + [
            enc_s(STORE, 0b010, 0, 1, 0),
            enc_s(STORE, 0b010, 0, 1, 4),
            enc_s(STORE, 0b010, 0, 1, 8),
            enc_s(STORE, 0b010, 0, 1, 12),
            enc_jal(0, 0),
        ] + [nop()] * (64 - (1 + pad + 5))

        self.core = RV12Core(core_id=0, wb_ptr_filter=0, wb_card_shift=6, wb_obj_shift=4)
        self.imem = SimpleIMem(words=64, init=prog)
        self.dmem = SimpleDMem(words=64, init=[0] * 64)
        # scan：consume_every=0 => 不消费（极端背压源），
        # 这样同一 card 的第 1 次入队后会一直保持 “pending”，后续写入才能命中并被去重丢弃。
        self.scan = GCScanCoProc(ncores=1, fifo_depth=4, consume_every=0, batch_size=1,
                                 dedup_enable=dedup_enable, cardset_size=4)

        # Debug mux: allow reading DMEM without poking core ports
        self.dbg_en = Signal(reset=0)
        self.dbg_addr = Signal(32, reset=0)

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

        # DMEM + grant (single master)
        m.d.comb += [
            c.dmem_grant.eq(1),
            dm.req_valid.eq(Mux(self.dbg_en, 0, c.dmem_valid)),
            dm.req_we.eq(Mux(self.dbg_en, 0, c.dmem_we)),
            dm.req_addr.eq(Mux(self.dbg_en, self.dbg_addr, c.dmem_addr)),
            dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
        ]

        # core -> scan
        m.d.comb += [
            sc.wb_valid[0].eq(c.wb_enq_valid),
            c.wb_enq_ready.eq(sc.wb_ready[0]),
            sc.wb_addr[0].eq(c.wb_addr),
            sc.wb_data[0].eq(c.wb_data),
        ]

        # core GC/MV 未用：全部 tie-off
        m.d.comb += [
            c.gc_enq_ready.eq(1),
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


def _run_one(dedup_enable: bool):
    dut = TbDedup(dedup_enable=dedup_enable)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    result = {}

    def proc():
        # 跑到 scan 接受 4 次输入即可（consume_every=0 时不会前向消费）。
        for cyc in range(400):
            yield Tick()
            in_cnt = (yield dut.scan.in_count[0])
            if in_cnt >= 4:
                # 读 DMEM 0/4/8/12 四个 word
                mem = {}
                for a in [0, 4, 8, 12]:
                    yield dut.dbg_en.eq(1)
                    yield dut.dbg_addr.eq(a)
                    yield Tick()
                    mem[a] = (yield dut.dmem.rsp_rdata)
                yield dut.dbg_en.eq(0)

                result['cycles'] = cyc
                result['in'] = in_cnt
                result['ev'] = (yield dut.scan.ev_count[0])
                result['uniq'] = (yield dut.scan.uniq_enq[0])
                result['dup'] = (yield dut.scan.dup_drop[0])
                result['mem'] = mem
                return
        raise AssertionError('timeout')

    sim.add_sync_process(proc)
    sim.run()
    return result


if __name__ == '__main__':
    off = _run_one(False)
    on  = _run_one(True)

    # 基本正确性：内存写入不受影响
    assert all(off['mem'][a] == 1 for a in [0, 4, 8, 12])
    assert all(on['mem'][a] == 1 for a in [0, 4, 8, 12])

    # 去重关闭：4 次都入队（consume_every=0 时 ev_count 可能为 0，因此不以 ev_count 判断）
    assert off['in'] >= 4
    assert off['uniq'] == 4 and off['dup'] == 0

    # 去重开启：只入队 1 次，其余 3 次被去重丢弃
    assert on['in'] >= 4
    assert on['uniq'] == 1 and on['dup'] == 3

    print(
        'OK: card dedup works: '
        f"dedup_off cycles={off['cycles']} uniq={off['uniq']} dup={off['dup']} ; "
        f"dedup_on cycles={on['cycles']} uniq={on['uniq']} dup={on['dup']}"
    )
