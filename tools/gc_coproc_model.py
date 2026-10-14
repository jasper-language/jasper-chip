# tools/gc_coproc_model.py
# Cycle-level golden model for rtl/gc_coproc.GCCoProc
#
# This model matches the RTL's *cycle semantics*:
#   - FIFO enqueue happens on the clock edge and is NOT visible to the same edge's arbitration.
#   - FIFO pop (r_en) also happens on the clock edge; arbitration uses pre-edge r_rdy.
#   - rsp_valid/trap are registered and become visible in the cycle after execution.
#   - reloc_pending blocks normal execution and performs its "free src" step on a clock edge.

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from rtl.isa import GC_NEW, GC_DROP, GC_CLONE, GC_PIN, GC_UNPIN, GC_RELOC


@dataclass
class Cmd:
    op: int
    rd: int
    rs1: int
    rs2: int


class GCCoProcModel:
    def __init__(self, ncores: int = 4, entries: int = 256, fifo_depth: int = 8):
        self.ncores = ncores
        self.entries = entries
        self.fifo_depth = fifo_depth

        # Tables
        self.rc = [0] * entries
        self.pin = [0] * entries
        self.used = [0] * entries

        # Engine state
        self.alloc_ptr = 1
        self.rr_ptr = 0
        self.reloc_pending = False
        self.reloc_src = 0

        # Per-core FIFO of commands (as seen *after* the most recent clock edge)
        self.fifos: List[List[Cmd]] = [[] for _ in range(ncores)]

        # Per-core response slot (registered)
        self.rsp_valid = [0] * ncores
        self.rsp_rd = [0] * ncores
        self.rsp_data = [0] * ncores

        # Trap pulse (registered for one cycle)
        self._trap_fire = 0
        self._trap_core = 0


        # Debug: last executed command (captured at clock edge)
        self.last_exec = 0
        self.last_sel = 0
        self.last_op = 0
        self.last_rd = 0
        self.last_rs1 = 0
        self.last_rs2 = 0
        self.last_trap = 0

    # -------- Combinational views (match RTL comb outputs) --------
    def cmd_ready(self, core: int) -> int:
        """Model of cmd_enq_ready (w_rdy). Computed from pre-edge FIFO fullness."""
        return 1 if len(self.fifos[core]) < self.fifo_depth else 0

    def trap_out(self, core: int) -> int:
        return 1 if (self._trap_fire and (self._trap_core == core)) else 0

    # -------- Tick update (match RTL sync updates) --------
    def tick(
        self,
        cmd_valid: List[int],
        cmd_op: List[int],
        cmd_rd: List[int],
        cmd_rs1: List[int],
        cmd_rs2: List[int],
        dut_ready: Optional[List[int]] = None,
        rsp_take: Optional[List[int]] = None,
    ) -> None:
        """
        Advance model by one clock edge.
        Inputs are sampled as they would be right before the clock edge.

        If dut_ready is provided, it is used for enqueue handshakes (to guarantee
        lockstep with the RTL FIFO implementation). Otherwise, model-ready is used.
        """
        if rsp_take is None:
            rsp_take = [0] * self.ncores
        if dut_ready is None:
            dut_ready = [self.cmd_ready(i) for i in range(self.ncores)]

        # Snapshot FIFO state as it is *before* this clock edge.
        pre_fifos = [q.copy() for q in self.fifos]

        self.last_exec = 0

        # ---- Compute arbitration based on pre-edge FIFO state (r_rdy)
        have = 0
        sel = self.rr_ptr
        for k in range(self.ncores):
            idx = (self.rr_ptr + k) % self.ncores
            if (len(pre_fifos[idx]) > 0) and (not have):
                sel = idx
                have = 1

        can_accept = 1 if (have and (self.rsp_valid[sel] == 0) and (not self.reloc_pending)) else 0
        exec_cmd = pre_fifos[sel][0] if can_accept else None  # head element, sampled pre-edge

        # ---- Default trap clear every cycle, overridden if raise_trap happens this tick.
        self._trap_fire = 0

        # ---- Response clear on take (appears before execute block in RTL source)
        for i in range(self.ncores):
            if rsp_take[i]:
                self.rsp_valid[i] = 0

        # ---- Apply RELOC step2 on this clock edge if pending (blocks normal execution)
        if self.reloc_pending:
            src = self.reloc_src & 0xFF
            if 0 <= src < self.entries:
                self.used[src] = 0
                self.rc[src] = 0
                self.pin[src] = 0
            self.reloc_pending = False
            # Even though execution is blocked, enqueues still happen at this edge.
            # (handled below)
            exec_cmd = None
            can_accept = 0

        # ---- Apply FIFO pop for execution (r_en sampled at this edge)
        if can_accept and exec_cmd is not None:
            # Pop head of selected FIFO
            if self.fifos[sel]:
                self.fifos[sel].pop(0)

        # ---- Apply FIFO enqueues (writes) at this edge
        for i in range(self.ncores):
            if cmd_valid[i] and dut_ready[i]:
                if len(self.fifos[i]) < self.fifo_depth:
                    self.fifos[i].append(Cmd(cmd_op[i], cmd_rd[i], cmd_rs1[i], cmd_rs2[i]))

        # ---- Execute command (state/response updates) at this edge
        if not (can_accept and exec_cmd is not None):
            return

        # rr_ptr advances regardless of op result (as RTL does)
        self.rr_ptr = (sel + 1) % self.ncores

        # Default response every execute
        self.rsp_valid[sel] = 1
        self.rsp_rd[sel] = exec_cmd.rd & 0x1F
        self.rsp_data[sel] = 0

        # Record last-exec info for debugging
        self.last_exec = 1
        self.last_sel = sel
        self.last_op = exec_cmd.op & 0x7
        self.last_rd = exec_cmd.rd & 0x1F
        self.last_rs1 = exec_cmd.rs1 & 0xFFFFFFFF
        self.last_rs2 = exec_cmd.rs2 & 0xFFFFFFFF
        self.last_trap = 0

        def raise_trap():
            self._trap_fire = 1
            self._trap_core = sel
            self.last_trap = 1

        op = exec_cmd.op & 0x7
        rs1 = exec_cmd.rs1 & 0xFFFFFFFF
        rs2 = exec_cmd.rs2 & 0xFFFFFFFF
        idx1 = rs1 & 0xFF
        idx2 = rs2 & 0xFF

        if op == GC_NEW:
            ap = self.alloc_ptr
            if self.used[ap] == 0:
                self.used[ap] = 1
                self.rc[ap] = 1
                self.pin[ap] = 0
                self.rsp_data[sel] = ap
                self.alloc_ptr = 1 if ap == (self.entries - 1) else (ap + 1)
            else:
                raise_trap()

        elif op == GC_CLONE:
            if self.used[idx1]:
                self.rc[idx1] = (self.rc[idx1] + 1) & 0xFFFF
                self.rsp_data[sel] = rs1
            else:
                raise_trap()

        elif op == GC_DROP:
            if self.used[idx1]:
                if self.pin[idx1]:
                    raise_trap()
                elif self.rc[idx1] == 0:
                    raise_trap()
                else:
                    self.rc[idx1] -= 1
                    if self.rc[idx1] == 0:
                        self.used[idx1] = 0
            else:
                raise_trap()

        elif op == GC_PIN:
            if self.used[idx1]:
                self.pin[idx1] = 1
            else:
                raise_trap()

        elif op == GC_UNPIN:
            if self.used[idx1]:
                self.pin[idx1] = 0
                if self.rc[idx1] == 0:
                    self.used[idx1] = 0
            else:
                raise_trap()

        elif op == GC_RELOC:
            if self.used[idx1] and (self.pin[idx1] == 0) and (self.used[idx2] == 0):
                self.used[idx2] = 1
                self.rc[idx2] = self.rc[idx1] & 0xFFFF
                self.pin[idx2] = self.pin[idx1] & 0x1
                self.reloc_pending = True
                self.reloc_src = idx1
            else:
                raise_trap()

        else:
            raise_trap()
