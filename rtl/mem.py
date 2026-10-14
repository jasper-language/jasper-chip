# rtl/mem.py
from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out

class SimpleIMem(wiring.Component):
    """组合读 ROM（研究用）：字寻址，读为组合；便于与当前 core 的取指时序对齐。"""
    addr: In(32)     # byte address
    rdata: Out(32)

    def __init__(self, words=1024, init=None):
        super().__init__()
        self.words = words
        self.init  = init or [0]*words

    def elaborate(self, platform):
        m = Module()
        mem = Memory(width=32, depth=self.words, init=self.init)
        rp  = mem.read_port(domain="comb")
        m.submodules.rp = rp
        m.d.comb += [
            rp.addr.eq(self.addr[2:]),
            # 注意：domain="comb" 的读端口在 Amaranth 0.5 中没有可写的 en 信号，
            # 读始终有效；如果强行赋值会触发 "const cannot be assigned"。
            self.rdata.eq(rp.data),
        ]
        return m

class SimpleDMem(wiring.Component):
    """单端口 RAM（研究用）：读为组合，写在 req_valid&req_we 时发生。"""
    req_valid: In(1)
    req_we:    In(1)
    req_addr:  In(32)
    req_wdata: In(32)
    rsp_rdata: Out(32)

    def __init__(self, words=4096, init=None):
        super().__init__()
        self.words = words
        self.init  = init or [0]*words

    def elaborate(self, platform):
        m = Module()
        mem = Array(Signal(32, reset=val, name=f"mem{i}") for i, val in enumerate(self.init))

        word_addr = Signal(range(self.words))
        m.d.comb += word_addr.eq(self.req_addr[2:])
        m.d.comb += self.rsp_rdata.eq(mem[word_addr])

        with m.If(self.req_valid & self.req_we):
            m.d.sync += mem[word_addr].eq(self.req_wdata)
        return m
# rtl/mem.py 里替换 RRArbiter

from amaranth import *

from amaranth import *

class RRArbiter(Elaboratable):
    def __init__(self, n):
        self.n = n
        self.m_valid = Array(Signal(name=f"m{i}_valid") for i in range(n))
        self.m_we    = Array(Signal(name=f"m{i}_we")    for i in range(n))
        self.m_addr  = Array(Signal(32, name=f"m{i}_addr")  for i in range(n))
        self.m_wdata = Array(Signal(32, name=f"m{i}_wdata") for i in range(n))
        self.m_rdata = Array(Signal(32, name=f"m{i}_rdata") for i in range(n))
        self.m_grant = Array(Signal(name=f"m{i}_grant") for i in range(n))
        self.m_lock  = Array(Signal(name=f"m{i}_lock") for i in range(n))

        self.s_valid = Signal()
        self.s_we    = Signal()
        self.s_addr  = Signal(32)
        self.s_wdata = Signal(32)
        self.s_rdata = Signal(32)

    def elaborate(self, platform):
        m = Module()

        last = Signal(range(self.n), reset=0)
        grant = Signal(range(self.n))
        found = Signal()
        locked = Signal(reset=0)
        lock_owner = Signal(range(self.n), reset=0)

        # 用“纯组合表达式链”算 found/grant，避免 found 作为临时状态再被读取导致组合环
        sel_v = last
        found_v = Const(0)

        for k in range(self.n):
            idx = last + 1 + k
            idx = Mux(idx >= self.n, idx - self.n, idx)
            req = self.m_valid[idx]
            sel_v   = Mux((~found_v) & req, idx, sel_v)
            found_v = found_v | req

        m.d.comb += [
            grant.eq(Mux(locked, lock_owner, sel_v)),
            found.eq(Mux(locked, self.m_valid[lock_owner], found_v)),

            self.s_valid.eq(found),
            self.s_we.eq(self.m_we[grant]),
            self.s_addr.eq(self.m_addr[grant]),
            self.s_wdata.eq(self.m_wdata[grant]),
        ]

        # broadcast read data
        for i in range(self.n):
            m.d.comb += [
                self.m_rdata[i].eq(self.s_rdata),
                self.m_grant[i].eq(found & (grant == i)),
            ]

        # round-robin pointer update
        with m.If(locked):
            with m.If(~self.m_valid[lock_owner] | ~self.m_lock[lock_owner]):
                m.d.sync += [locked.eq(0), last.eq(lock_owner)]
        with m.Elif(found):
            m.d.sync += last.eq(grant)
            with m.If(self.m_lock[grant]):
                m.d.sync += [locked.eq(1), lock_owner.eq(grant)]

        return m
