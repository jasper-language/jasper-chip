from amaranth import *
from amaranth.sim import Simulator
from rtl.jasper_gc_accelerator_regs import AcceleratorRegs, ACCEL_VERSION_VALUE
from rtl.jasper_gc_accelerator_config import JasperGCAcceleratorConfig


def _cfg():
    return JasperGCAcceleratorConfig()


async def _write(ctx, dut, addr, data, wstrb=0xF):
    ctx.set(dut.bus_addr, addr)
    ctx.set(dut.bus_wdata, data)
    ctx.set(dut.bus_wstrb, wstrb)
    ctx.set(dut.bus_valid, 1)
    ctx.set(dut.bus_is_write, 1)
    await ctx.tick()
    ctx.set(dut.bus_valid, 0)


async def _read(ctx, dut, addr):
    ctx.set(dut.bus_addr, addr)
    ctx.set(dut.bus_valid, 1)
    ctx.set(dut.bus_is_write, 0)
    await ctx.tick()
    ctx.set(dut.bus_valid, 0)
    return ctx.get(dut.bus_rdata)


def test_elab():
    from amaranth.back import rtlil
    m = Module()
    m.submodules.dut = AcceleratorRegs(_cfg())
    rtlil.convert(m, ports=[])


def test_version_read():
    dut = AcceleratorRegs(_cfg())
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    async def proc(ctx):
        val = await _read(ctx, dut, 0x00)
        assert val == ACCEL_VERSION_VALUE
    sim.add_testbench(proc)
    sim.run()


def test_control_write_read():
    dut = AcceleratorRegs(_cfg())
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    async def proc(ctx):
        await _write(ctx, dut, 0x08, 0x7)
        val = await _read(ctx, dut, 0x08)
        assert val == 0x7
    sim.add_testbench(proc)
    sim.run()


def test_ro_write_ignored():
    dut = AcceleratorRegs(_cfg())
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    async def proc(ctx):
        await _write(ctx, dut, 0x00, 0xDEADBEEF)
        val = await _read(ctx, dut, 0x00)
        assert val == ACCEL_VERSION_VALUE
    sim.add_testbench(proc)
    sim.run()


def test_unmapped_read():
    dut = AcceleratorRegs(_cfg())
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    async def proc(ctx):
        val = await _read(ctx, dut, 0x100)
        assert val == 0
    sim.add_testbench(proc)
    sim.run()


def test_wstrb_partial():
    dut = AcceleratorRegs(_cfg())
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    async def proc(ctx):
        await _write(ctx, dut, 0x20, 0xFFFFFFFF)
        await _write(ctx, dut, 0x20, 0x12345678, wstrb=0b0100)
        val = await _read(ctx, dut, 0x20)
        assert val == 0xFF34FFFF
    sim.add_testbench(proc)
    sim.run()


def test_back_to_back_read():
    dut = AcceleratorRegs(_cfg())
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    async def proc(ctx):
        v0 = await _read(ctx, dut, 0x00)
        v1 = await _read(ctx, dut, 0x04)
        assert v0 == ACCEL_VERSION_VALUE
        assert v1 == 0
    sim.add_testbench(proc)
    sim.run()


def test_busy_status():
    dut = AcceleratorRegs(_cfg())
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    async def proc(ctx):
        ctx.set(dut.status_busy, 1)
        await ctx.tick()
        val = await _read(ctx, dut, 0x04)
        assert val & 0x1, f"busy bit not set: val=0x{val:08x}"
    sim.add_testbench(proc)
    sim.run()
