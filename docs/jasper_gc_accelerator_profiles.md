# JasperGC Accelerator — Profiles

## accel_lite

| Attribute         | Value                        |
|-------------------|------------------------------|
| Status            | ARCHITECTURE                 |
| Tasks             | scan, sweep                  |
| Queue depth       | 4 commands                   |
| DMA width         | 64 bytes                     |
| Coherency         | IO-coherent (non-snooping)   |
| Adapter priority  | PCIe DMA (future)            |
| Adapter fallback  | None (chiplet optional)      |
| Module support    | CommandQueue, ScanEngine, SweepEngine, MemoryAccess, CompletionQueue |
| Compact           | Not supported                |
| Metadata rebuild  | Not supported (fallback)     |
| Region count      | 1 active region at a time    |
| Clock target      | 500 MHz (typical)            |
| Area estimate     | ~0.5 mm² (7nm)               |
| Use case          | Embedded, low-power, small heap |

**Notes:** accel_lite is the minimal viable accelerator. It handles the two most frequent cold-path operations (scan and sweep). Compaction and metadata rebuild are handled by Core software fallback. Designed as a PCIe-attached endpoint for systems where chiplet integration is not available.

---

## accel_standard

| Attribute         | Value                        |
|-------------------|------------------------------|
| Status            | ARCHITECTURE                 |
| Tasks             | scan, sweep, metadata rebuild|
| Queue depth       | 8 commands                   |
| DMA width         | 128 bytes                    |
| Coherency         | IO-coherent (non-snooping)   |
| Adapter priority  | CPU-package / chiplet        |
| Adapter fallback  | PCIe DMA (future)            |
| Module support    | CommandQueue, RegionScheduler, ScanEngine, SweepEngine, MetadataRebuildEngine, MemoryAccess, CompletionQueue |
| Compact           | Not supported                |
| Region count      | 2 active regions (pipelined) |
| Clock target      | 800 MHz                      |
| Area estimate     | ~1.2 mm² (7nm)               |
| Use case          | Mid-range server, standard JVM/Go workloads |

**Notes:** accel_standard is the target for initial RTL development. It adds metadata rebuild to the lite profile, enabling full cycle completion without software fallback for scan/sweep. The chiplet adapter provides low-latency access to coherent memory. RegionScheduler allows pipelining two regions for throughput.

---

## accel_server

| Attribute         | Value                        |
|-------------------|------------------------------|
| Status            | MAINLINE_STUDY               |
| Tasks             | scan, sweep, compact, metadata rebuild |
| Queue depth       | 16 commands                  |
| DMA width         | 256 bytes                    |
| Coherency         | Fully coherent (chiplet fabric) |
| Adapter priority  | CPU-package / chiplet        |
| Adapter fallback  | CXL.mem (future)             |
| Module support    | all 8 modules                |
| Compact           | Full support with relocation |
| Region count      | 4 active regions             |
| Clock target      | 1 GHz                        |
| Area estimate     | ~2.5 mm² (7nm)               |
| Use case          | Large server heap, concurrent compaction |

**Notes:** accel_server is the full-featured cold-path accelerator. It includes CompactEngine for live-object relocation and fully coherent memory access via the chiplet fabric. This profile is under MAINLINE_STUDY to validate area, timing, and power against server workloads. The CXL.mem adapter is a future option for disaggregated memory.

---

## accel_extreme

| Attribute         | Value                        |
|-------------------|------------------------------|
| Status            | RESEARCH/HOLD                |
| Tasks             | multi-region scan, sweep, compact, rebuild, HBM management |
| Queue depth       | 32 commands                  |
| DMA width         | 512 bytes                    |
| Coherency         | Fully coherent (chiplet fabric) |
| Adapter priority  | CPU-package / chiplet        |
| Adapter fallback  | CXL.mem (future)             |
| Module support    | all 8 modules + HBM controller interface |
| Compact           | Full support with parallel relocation |
| Region count      | 8 active regions             |
| HBM support       | Direct HBM channel access    |
| Clock target      | 1.2 GHz                      |
| Area estimate     | ~5.0 mm² (7nm)               |
| Use case          | Multi-terabyte heaps, tiered memory (DRAM+HBM) |

**Notes:** accel_extreme is a research concept for ultra-large heap configurations. It adds direct HBM channel access and supports up to 8 concurrent regions. The 512-byte DMA width matches HBM2e burst sizes. This profile is on HOLD pending market demand and HBM integration feasibility studies.
