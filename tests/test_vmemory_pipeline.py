"""Positive encoded pipeline closure for V memory issue and writeback."""

from amaranth.sim import Settle, Simulator, Tick

from rtl.vmemory_pipeline import VMemoryPipeline


LOAD_FP = 0x07


def encoding(vd, width=0):
    return (1 << 25) | (width << 12) | (vd << 7) | LOAD_FP


def test_vmemory_pipeline_encoded_issue_bus_writeback_and_illegal_trap():
    dut = VMemoryPipeline()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    memory = bytearray((index * 3 + 1) & 0xff for index in range(32))
    register = 0
    result = {"redirect": 0, "illegal": 0}

    def process():
        nonlocal register
        yield dut.insn.eq(encoding(1))
        yield dut.is_load.eq(1)
        yield dut.base.eq(1)
        yield dut.vl.eq(4)
        yield dut.vlmax.eq(16)
        yield dut.issue_valid.eq(1)
        yield Settle()
        result["redirect"] = yield dut.redirect
        yield Tick()
        yield dut.issue_valid.eq(0)

        pending = None
        seen_busy = False
        for _ in range(64):
            yield Settle()
            busy = yield dut.busy
            seen_busy |= bool(busy)
            valid = yield dut.dmem_valid
            address = yield dut.dmem_addr
            grant = valid and pending == address
            if valid and not grant:
                word = int.from_bytes(
                    memory[address & ~3:(address & ~3) + 4], "little")
                yield dut.dmem_rdata.eq(word)
                pending = address
            yield dut.dmem_grant.eq(grant)
            yield Settle()
            write_valid = yield dut.write_valid
            write_byte = yield dut.write_byte
            write_data = yield dut.write_data
            yield Tick()
            if grant:
                pending = None
            if write_valid:
                mask = 0xff << (write_byte * 8)
                register = (register & ~mask) | (write_data << (write_byte * 8))
                yield dut.vregs[1].eq(register)
            if seen_busy and not busy:
                break

        yield dut.insn.eq(encoding(2, width=1))
        yield dut.issue_valid.eq(1)
        yield Settle()
        result["illegal"] = yield dut.illegal
        yield Tick()

    sim.add_process(process)
    sim.run()
    assert result == {"redirect": 1, "illegal": 1}
    assert register == int.from_bytes(memory[1:5], "little")
