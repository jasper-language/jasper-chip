# tests/test_load_rb_trace.py
# 调试用：打印 program-driven lw->mv 的关键握手/数据，帮助定位 x1 未写回原因。

from amaranth import *
from amaranth.sim import Simulator, Tick

from tests.test_load_rb_program import TbProg


def main():
    dut = TbProg()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    c = dut.core
    mv = dut.mv

    def proc():
        last_cmd = 0
        last_rsp = 0
        for cyc in range(120):
            cmdv = (yield c.mv_cmd_valid)
            cmdr = (yield c.mv_cmd_ready)
            if cmdv and cmdr and not last_cmd:
                tag = (yield c.mv_cmd_tag)
                rd  = (yield c.mv_cmd_rd)
                rs1 = (yield c.mv_cmd_rs1)
                print(f"C{cyc}: MV_CMD fire tag=0x{tag:02x} rd={rd} rs1=0x{rs1:08x}")
                last_cmd = 1
            if not (cmdv and cmdr):
                last_cmd = 0

            rspv = (yield c.mv_rsp_valid)
            if rspv and not last_rsp:
                tag = (yield c.mv_rsp_tag)
                rd  = (yield c.mv_rsp_rd)
                data= (yield c.mv_rsp_data)
                print(f"C{cyc}: MV_RSP seen tag=0x{tag:02x} rd={rd} data=0x{data:08x}")
                last_rsp = 1
            if not rspv:
                last_rsp = 0

            yield Tick()

        # dump regs
        yield c.dbg_reg_addr.eq(1)
        yield Tick()
        x1 = (yield c.dbg_reg_rdata)
        yield c.dbg_reg_addr.eq(2)
        yield Tick()
        x2 = (yield c.dbg_reg_rdata)
        print(f"END: x1=0x{x1:08x} x2=0x{x2:08x}")

    sim.add_sync_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
