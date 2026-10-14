# tests/test_gc_sweep_coproc_golden_model.py
# Step46 “实际测试效果”：为 GCSweepCoProc 建立随机黄金模型对拍，覆盖：
#   - 多核 enqueue/仲裁
#   - rsp slot 占用/释放（rsp_take）
#   - GC_NEW/CLONE/DROP/PIN/UNPIN/RELOC 语义
#   - RELOC 两步执行（pending free）
#
# 运行：
#   python -m tests.test_gc_sweep_coproc_golden_model

from __future__ import annotations
import random

from amaranth.sim import Simulator, Tick, Settle
from rtl.gc_sweep_coproc import GCSweepCoProc
from rtl.isa import GC_NEW, GC_DROP, GC_CLONE, GC_PIN, GC_UNPIN, GC_RELOC
from tools.gc_coproc_model import GCCoProcModel


def _rand_cmd(rng: random.Random, entries: int):
    op = rng.choice([GC_NEW, GC_DROP, GC_CLONE, GC_PIN, GC_UNPIN, GC_RELOC])
    rd = rng.randrange(1, 32)
    idx1 = rng.randrange(0, entries)  # include 0 to exercise traps
    idx2 = rng.randrange(0, entries)
    rs1 = idx1
    rs2 = idx2
    # Add some noise in upper bits to ensure RTL masks to low 8 bits.
    rs1 |= (rng.randrange(0, 1 << 8) << 8)
    rs2 |= (rng.randrange(0, 1 << 8) << 8)
    return op, rd, rs1, rs2


def run_one(seed: int, cycles: int = 400, ncores: int = 4, entries: int = 64, fifo_depth: int = 4):
    dut = GCSweepCoProc(ncores=ncores, entries=entries, fifo_depth=fifo_depth)
    model = GCCoProcModel(ncores=ncores, entries=entries, fifo_depth=fifo_depth)

    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def proc():
        rng = random.Random(seed)

        # init inputs
        for i in range(ncores):
            yield dut.cmd_enq_valid[i].eq(0)
            yield dut.cmd_op[i].eq(0)
            yield dut.cmd_rd[i].eq(0)
            yield dut.cmd_rs1[i].eq(0)
            yield dut.cmd_rs2[i].eq(0)
            yield dut.rsp_take[i].eq(0)

        # settle once
        yield Settle()

        for t in range(cycles):
            # ---- Drive takes (can be asserted even if no rsp)
            for i in range(ncores):
                # Take more aggressively if rsp pending, otherwise occasionally toggle.
                rv = (yield dut.rsp_valid[i])
                take = 1 if (rv and rng.random() < 0.35) else (1 if rng.random() < 0.02 else 0)
                yield dut.rsp_take[i].eq(take)

            # ---- Drive enqueues
            for i in range(ncores):
                do_enq = 1 if rng.random() < 0.45 else 0
                op, rd, rs1, rs2 = _rand_cmd(rng, entries)
                yield dut.cmd_enq_valid[i].eq(do_enq)
                yield dut.cmd_op[i].eq(op)
                yield dut.cmd_rd[i].eq(rd)
                yield dut.cmd_rs1[i].eq(rs1)
                yield dut.cmd_rs2[i].eq(rs2)

            # ---- Compare current (pre-tick) outputs
            yield Settle()

            dut_ready = []
            dut_rsp_valid = []
            dut_rsp_rd = []
            dut_rsp_data = []
            dut_trap = []
            dut_take = []
            dut_cmd_valid = []
            dut_cmd_op = []
            dut_cmd_rd = []
            dut_cmd_rs1 = []
            dut_cmd_rs2 = []

            for i in range(ncores):
                dut_ready.append((yield dut.cmd_enq_ready[i]))
                dut_rsp_valid.append((yield dut.rsp_valid[i]))
                dut_rsp_rd.append((yield dut.rsp_rd[i]))
                dut_rsp_data.append((yield dut.rsp_data[i]))
                dut_trap.append((yield dut.trap[i]))
                dut_take.append((yield dut.rsp_take[i]))

                dut_cmd_valid.append((yield dut.cmd_enq_valid[i]))
                dut_cmd_op.append((yield dut.cmd_op[i]))
                dut_cmd_rd.append((yield dut.cmd_rd[i]))
                dut_cmd_rs1.append((yield dut.cmd_rs1[i]))
                dut_cmd_rs2.append((yield dut.cmd_rs2[i]))

            
            def _dbg():
                parts = []
                parts.append(f"model: rr_ptr={model.rr_ptr} alloc_ptr={model.alloc_ptr} reloc_pending={int(model.reloc_pending)} reloc_src={model.reloc_src}")
                parts.append(f"model last: exec={model.last_exec} sel={model.last_sel} op={model.last_op} rd={model.last_rd} rs1={model.last_rs1 & 0xff} rs2={model.last_rs2 & 0xff} trap={model.last_trap}")
                parts.append("model fifo lens/head:")
                for j in range(ncores):
                    head = model.fifos[j][0] if model.fifos[j] else None
                    if head is None:
                        parts.append(f"  c{j}: len={len(model.fifos[j])}")
                    else:
                        parts.append(f"  c{j}: len={len(model.fifos[j])} head(op={head.op} rd={head.rd} rs1={head.rs1 & 0xff} rs2={head.rs2 & 0xff})")
                parts.append("model rsp slots:")
                for j in range(ncores):
                    parts.append(f"  c{j}: v={model.rsp_valid[j]} rd={model.rsp_rd[j]} data={model.rsp_data[j]}")
                parts.append("inputs (this cycle):")
                for j in range(ncores):
                    parts.append(f"  c{j}: v={dut_cmd_valid[j]} rdy={dut_ready[j]} op={dut_cmd_op[j]} rd={dut_cmd_rd[j]} rs1={dut_cmd_rs1[j]&0xff} rs2={dut_cmd_rs2[j]&0xff} take={dut_take[j]}")
                parts.append("dut outputs (this cycle):")
                for j in range(ncores):
                    parts.append(f"  c{j}: rsp_v={dut_rsp_valid[j]} rsp_rd={dut_rsp_rd[j]} rsp_data={dut_rsp_data[j]} trap={dut_trap[j]}")
                return "\n".join(parts)

# Ready should match model's view of FIFO fullness.
            for i in range(ncores):
                mr = model.cmd_ready(i)
                assert dut_ready[i] == mr, f"[seed={seed} t={t}] ready mismatch core{i}: dut={dut_ready[i]} model={mr}\n{_dbg()}"

            for i in range(ncores):
                assert dut_rsp_valid[i] == model.rsp_valid[i], f"[seed={seed} t={t}] rsp_valid mismatch core{i}: dut={dut_rsp_valid[i]} model={model.rsp_valid[i]}\n{_dbg()}"
                assert dut_rsp_rd[i] == model.rsp_rd[i], f"[seed={seed} t={t}] rsp_rd mismatch core{i}: dut={dut_rsp_rd[i]} model={model.rsp_rd[i]}\n{_dbg()}"
                assert dut_rsp_data[i] == model.rsp_data[i], f"[seed={seed} t={t}] rsp_data mismatch core{i}: dut={dut_rsp_data[i]} model={model.rsp_data[i]}\n{_dbg()}"
                assert dut_trap[i] == model.trap_out(i), f"[seed={seed} t={t}] trap mismatch core{i}: dut={dut_trap[i]} model={model.trap_out(i)}\n{_dbg()}"

            # ---- Advance one tick (RTL samples inputs at this edge)
            yield Tick()

            # ---- Advance model with the same sampled inputs/ready/take
            model.tick(
                cmd_valid=dut_cmd_valid,
                cmd_op=dut_cmd_op,
                cmd_rd=dut_cmd_rd,
                cmd_rs1=dut_cmd_rs1,
                cmd_rs2=dut_cmd_rs2,
                dut_ready=dut_ready,
                rsp_take=dut_take,
            )

        # One more settle/compare after final tick
        yield Settle()
        for i in range(ncores):
            assert (yield dut.rsp_valid[i]) == model.rsp_valid[i]
            assert (yield dut.trap[i]) == model.trap_out(i)

        print(f"OK: gccoproc golden match seed={seed}, cycles={cycles}")

    sim.add_sync_process(proc)
    sim.run()


def main():
    # A few fixed seeds for deterministic coverage.
    for seed in (20260102, 20260103, 20260104):
        run_one(seed=seed)

    print("OK: all gccoproc golden-model tests passed.")


if __name__ == "__main__":
    main()
