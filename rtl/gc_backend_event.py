# rtl/gc_backend_event.py
# GCBackendEvent — unified event interface for all GC backend pipeline modules.
#
# Purpose:
#   Each GC backend module (EventPipeline, ForwardingTable, MetadataCache,
#   BackendMerge, HeapRegion, NumaCtrl) currently defines its own set of
#   input/output signals with overlapping but inconsistent semantics.
#   GCBackendEvent provides a single dataclass and Amaranth signal layout
#   that all modules share, solving core_id / merge domain alignment.
#
# Key design points:
#   - Every event carries core_id, event_id, epoch, sequence, merge_domain.
#   - merge_domain partitions events into independent ordering groups;
#     events in different domains can be processed in parallel.
#   - backend_id tracks which physical backend touched the event (debug).
#   - flush_epoch triggers epoch-based invalidation in ForwardingTable.
#
# Event types:
from amaranth import *

EVT_SCAN  = 0   # root scan event
EVT_SWEEP = 1   # sweep / free
EVT_MOVE  = 2   # object relocation
EVT_META  = 3   # metadata read / write
EVT_WB    = 4   # write barrier
EVT_RB    = 5   # read barrier

# ── Amaranth signal layout ─────────────────────────────────────
# Bit widths chosen to match existing module conventions
# (32-bit address/data, 8-bit epoch, etc.) while adding new fields
# for multi-backend / multi-domain alignment.

GC_BACKEND_EVENT_LAYOUT = [
    ("core_id",      8),   # which core issued this event
    ("event_id",    16),   # unique event sequence number (per-core)
    ("event_type",   3),   # supports up to 8 event types
    ("address",     32),   # 32-bit address of the object/pointer
    ("data",        32),   # 32-bit payload
    ("old_ptr",     32),   # old pointer value (for forwarding)
    ("new_ptr",     32),   # new pointer value (for forwarding)
    ("epoch",        8),   # GC epoch when event was issued
    ("sequence",     8),   # ordering sequence within epoch
    ("flush_epoch",  8),   # flush epoch (0 = no flush)
    ("merge_domain", 4),   # which merge domain this event belongs to
    ("backend_id",   4),   # which backend processed this event
    ("valid",        1),   # event valid qualifier
]


# ── Python dataclass ───────────────────────────────────────────
# A namedtuple-like dataclass for events flowing through the GC backend.
# Used for testbench stimulus/checking, cosimulation, and documentation.

from dataclasses import dataclass


@dataclass
class GCBackendEvent:
    core_id: int       # which core issued this event
    event_id: int      # unique event sequence number (per-core)
    event_type: int    # EVT_SCAN=0, EVT_SWEEP=1, EVT_MOVE=2, EVT_META=3, EVT_WB=4, EVT_RB=5

    address: int       # 32-bit address of the object/pointer
    data: int          # 32-bit payload
    old_ptr: int       # old pointer value (for forwarding)
    new_ptr: int       # new pointer value (for forwarding)

    epoch: int         # GC epoch when event was issued
    sequence: int      # ordering sequence within epoch
    flush_epoch: int   # flush epoch (0 = no flush)

    merge_domain: int  # which merge domain this event belongs to
    backend_id: int    # which backend processed this event

    def __post_init__(self):
        for field, (name, bits) in [(self.core_id, ("core_id", 8)),
                                     (self.event_id, ("event_id", 16)),
                                     (self.event_type, ("event_type", 3)),
                                     (self.address, ("address", 32)),
                                     (self.data, ("data", 32)),
                                     (self.old_ptr, ("old_ptr", 32)),
                                     (self.new_ptr, ("new_ptr", 32)),
                                     (self.epoch, ("epoch", 8)),
                                     (self.sequence, ("sequence", 8)),
                                     (self.flush_epoch, ("flush_epoch", 8)),
                                     (self.merge_domain, ("merge_domain", 4)),
                                     (self.backend_id, ("backend_id", 4))]:
            if field < 0 or field >= (1 << bits):
                raise ValueError(f"{name}={field} out of range [0, 2^{bits})")


# ── Helper: create a dict of Amaranth Signals from the layout ──

def make_gc_backend_event_signals():
    """Return dict of Signal() for each field in GC_BACKEND_EVENT_LAYOUT.

    Usage::

        ev = make_gc_backend_event_signals()
        m.d.comb += ev["address"].eq(0x1234)
        m.d.comb += some_valid.eq(ev["valid"])
    """
    return {name: Signal(width) for name, width in GC_BACKEND_EVENT_LAYOUT}


# ── GCBackendEventRecord: Amaranth Record wrapper ─────────────

class GCBackendEventRecord:
    """Convenience container: event signal dict + valid/ready handshake.

    Usage in module ``__init__``::

        self.input_event  = GCBackendEventRecord()
        self.output_event = GCBackendEventRecord()
    """
    def __init__(self):
        self.fields = make_gc_backend_event_signals()
        self.valid = Signal()
        self.ready = Signal()

    def __getitem__(self, key):
        """Allow dict-style access to fields: ev["address"]"""
        return self.fields[key]

    def __setitem__(self, key, value):
        self.fields[key] = value

    def wire_in(self, m, src):
        """Combinational connect from another GCBackendEventRecord."""
        for name in self.fields:
            m.d.comb += self.fields[name].eq(src.fields[name])
        m.d.comb += self.valid.eq(src.valid)
        m.d.comb += self.ready.eq(src.ready)

    def wire_out(self, m, dst):
        """Combinational connect to another GCBackendEventRecord."""
        for name in self.fields:
            m.d.comb += dst.fields[name].eq(self.fields[name])
        m.d.comb += dst.valid.eq(self.valid)
        m.d.comb += dst.ready.eq(self.ready)

    def passthrough(self, m, src, keep_fields=None):
        """Connect a subset of fields from src, leave others unchanged."""
        names = keep_fields or list(self.fields.keys())
        for name in names:
            if name in src.fields:
                m.d.comb += self.fields[name].eq(src.fields[name])


# ── Interface templates: per-module field subsets ──────────────

# EventPipeline:
#   Input:  core_id, event_id, event_type, address, data,
#           epoch, sequence, flush_epoch
#   Output: core_id, event_id, event_type, result_data,
#           epoch, sequence
#
# The EventPipeline classifies events by type, routes them through
# the appropriate sub-pipeline (scan/sweep/move/meta), then re-merges
# results.  The output retains core_id + event_id for correlation.
# flush_epoch triggers pipeline flush on the input side.

EVENT_PIPELINE_INPUT_FIELDS  = {"core_id", "event_id", "event_type",
                                "address", "data", "epoch", "sequence",
                                "flush_epoch"}
EVENT_PIPELINE_OUTPUT_FIELDS = {"core_id", "event_id", "event_type",
                                "data", "epoch", "sequence"}

# ForwardingTable:
#   Input:  core_id, event_id, old_ptr, new_ptr, epoch, flush_epoch
#   Output: core_id, event_id, old_ptr, new_ptr (possibly chased),
#           hit, epoch
#
# The ForwardingTable looks up old_ptr → new_ptr mappings.
# flush_epoch invalidates entries matching the given epoch.
# hit indicates whether the mapping was found (after chase).
# If miss, new_ptr on output equals old_ptr (passthrough).

FORWARDING_TABLE_INPUT_FIELDS  = {"core_id", "event_id", "old_ptr",
                                  "new_ptr", "epoch", "flush_epoch"}
FORWARDING_TABLE_OUTPUT_FIELDS = {"core_id", "event_id", "old_ptr",
                                  "new_ptr", "epoch"}

# MetadataCache:
#   Input:  core_id, event_id, address, epoch
#   Output: core_id, event_id, address, data, hit, epoch
#
# The MetadataCache reads/writes per-object metadata (mark bits, age, etc.)
# address selects the metadata word; data carries the result.
# hit indicates whether the access was served from cache (vs a fill miss).

METADATA_CACHE_INPUT_FIELDS  = {"core_id", "event_id", "address", "epoch"}
METADATA_CACHE_OUTPUT_FIELDS = {"core_id", "event_id", "address",
                                "data", "epoch"}

# BackendMerge:
#   Input (from N backends):
#     core_id, event_id, event_type, data, epoch, sequence,
#     merge_domain, backend_id
#   Output (merged):
#     core_id, event_id, event_type, data, epoch, sequence, merge_domain
#
# The merge unit collects results from multiple physical backends
# and emits a single ordered stream, using
#   (merge_domain, epoch, sequence)
# as the ordering key.

BACKEND_MERGE_INPUT_FIELDS  = {"core_id", "event_id", "event_type",
                               "data", "epoch", "sequence",
                               "merge_domain", "backend_id"}
BACKEND_MERGE_OUTPUT_FIELDS = {"core_id", "event_id", "event_type",
                               "data", "epoch", "sequence",
                               "merge_domain"}


# ── Merge domain alignment strategy ────────────────────────────
#
# Principle:
#   Events from different GC phases or different memory regions may be
#   processed in parallel.  The merge_domain field (set at event creation
#   time) partitions the event stream into independent ordering domains.
#
# Rules:
#   1. Each event carries a merge_domain field, set at creation by the
#      EventPipeline or NumaCtrl based on core_id / address hash / NUMA node.
#
#   2. Events belonging to different merge_domains are independent:
#      they can be dispatched to different backends and merged in any
#      order relative to each other.
#
#   3. Events within the same merge_domain must be merged in order.
#      The merge unit uses (merge_domain, epoch, sequence) as the
#      ordering tuple:
#
#        - merge_domain partitions the ordering space.
#        - epoch provides coarse ordering (events from older epochs
#          complete before newer epochs within the same domain).
#        - sequence provides fine-grained ordering within an epoch.
#
#   4. backend_id is a debug/observability field that records which
#      physical backend processed the event.  It has no ordering
#      semantics but is useful for performance counter collection
#      and functional verification.
#
# Example topology:
#
#   Core 0 ──┐
#   Core 1 ──┤                ┌──────────────┐
#   Core 2 ──┼── EventPipe ──▶│  Backend     │──▶ Merge ──▶ result
#   Core 3 ──┤                │  (banked     │
#            │                │   FT, MC, …) │
#            └────────────────│   domain=A   │
#                             └──────────────┘
#   merge_domain assignment: cores 0-1 → domain A
#                             cores 2-3 → domain B
#
#   Backend A processes domain A events; Backend B processes domain B.
#   The Merge unit interleaves results arbitrarily across domains but
#   preserves order within each domain.


# ── Migration path ─────────────────────────────────────────────
#
# Phase 1 — Add GCBackendEvent signals to each module
# ====================================================
# Every pipeline module (EventPipeline, ForwardingTable, MetadataCache,
# BackendMerge, HeapRegion, NumaCtrl) adds a new port:
#
#   self.backend_event = make_gc_backend_event_signals()
#
# with valid/ready handshake signals alongside it.  For modules that
# process only a subset of fields (see interface templates above),
# the unused fields are simply left at zero / don't-care.
#
# Phase 2 — Keep old interface signals for backward compat
# =========================================================
# Existing signals (event_valid, event_ready, event_addr, event_tag, …)
# remain in place.  A compatibility shim is added:
#
#   # Bridge old input  → backend_event (shim in the module's elaborate)
#   m.d.comb += [
#       ev["core_id"].eq(self.event_source),
#       ev["address"].eq(self.event_addr),
#       ev["valid"].eq(self.event_valid),
#       ...
#   ]
#
#   # Bridge backend_event → old output (shim in the caller's elaborate)
#   m.d.comb += [
#       self.result_valid.eq(ev["valid"]),
#       self.result_data.eq(ev["data"]),
#       ...
#   ]
#
# Phase 3 — Add bridge adapters
# ===============================
# Adapter modules (e.g. GCEventToBackendEvent, BackendEventToMergeEvent)
# translate between the old per-module signals and GCBackendEvent.
# These adapters live in separate files and are instantiated at the
# boundary of each module.  They allow gradual, per-module migration
# without touching the rest of the system.
#
# Phase 4 — Remove old signals
# =============================
# Once all modules and their callers are migrated to GCBackendEvent,
# delete the old per-module signal definitions.  The adapters are
# also removed at this point.  The system now uses a single,
# unified event interface everywhere.


# ── Example usage ──────────────────────────────────────────────
#
# Stimulus (testbench):
#
#   >>> ev = GCBackendEvent(
#   ...     core_id=0, event_id=42, event_type=EVT_SCAN,
#   ...     address=0x8000_1000, data=0, old_ptr=0, new_ptr=0,
#   ...     epoch=3, sequence=7, flush_epoch=0,
#   ...     merge_domain=0, backend_id=0,
#   ... )
#   >>> ev
#   GCBackendEvent(core_id=0, event_id=42, event_type=0, ...)
#
# RTL instantiation:
#
#   m = Module()
#   ev = make_gc_backend_event_signals()
#
#   # Drive input
#   m.d.comb += [
#       ev["core_id"].eq(0),
#       ev["event_id"].eq(core_counter),
#       ev["event_type"].eq(EVT_SCAN),
#       ev["address"].eq(scan_addr),
#       ev["valid"].eq(scan_valid),
#   ]
#
#   # Wire to module
#   m.submodules.pipe = pipe = GCEventPipelineStandard()
#   m.d.comb += [
#       pipe.event_valid.eq(ev["valid"]),
#       pipe.event_addr.eq(ev["address"]),
#       ...
#   ]
