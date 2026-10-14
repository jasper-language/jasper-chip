# Multi-Output Event Pipeline Experiment

## Objective

Determine whether distributing event pipeline results across N parallel
output ports can break the 1.0 evt/cyc throughput ceiling imposed by the
single-output merge in GCEventPipelineSeparated.

## Design

`MultiOutputEventPipeline(output_ports=N)` extends the 3-sub-pipeline
(Scan/Sweep/Move) architecture with N independent result ports:

- **N=1**: All results through one port (equivalent to Separated)
- **N=2**: Port 0 = Scan, Port 1 = Sweep+Move (round-robin)
- **N=3**: Port 0 = Scan, Port 1 = Sweep, Port 2 = Move
- **N=4**: Ports 0-2 as N=3, Port 3 = round-robin all types

Each port has its own valid/ready handshake. Downstream modules
(MetadataCache, ForwardingTable, BackendMerge) must also be multi-output
to consume results from all ports — otherwise, single-consumer limits apply.

## Results

| Outputs | Accept Rate | Response Rate | vs 1-out | Stall | Limiting Factor |
|---------|------------|---------------|----------|-------|-----------------|
| 1 | 1.000/cyc | 1.000/cyc | 1.0× | 0 | Single input |
| 2 | 1.000/cyc | 1.000/cyc | 1.0× | 0 | Single input |
| 3 | 1.000/cyc | 1.000/cyc | 1.0× | 0 | Single input |
| 4 | 1.000/cyc | 2.000/cyc | 2.0× | 0 | Single input |

## Key Finding

**Multi-output alone does NOT increase sustained throughput beyond 1.0 evt/cyc.**
The input port (event_valid/event_ready) is still a single-entry handshake.
Multi-output only helps drain results faster, but the pipeline cannot accept
events faster than 1/cycle regardless of output port count.

The 4-output case shows 2.000/cyc response rate — results drain from pipeline
buffers at 2× rate, but with only 1.0/cyc input, sustained throughput is 1.0/cyc.

## Conclusion

To break 1.0 evt/cyc, the architecture needs:

1. **Multi-input event pipeline** — accept N events/cycle from the frontend
2. **Multi-output result ports** — deliver N results/cycle to the backend
3. **Multi-consumer backend** — MetadataCache, ForwardingTable, BackendMerge
   must each be multi-input/multi-output

Multi-output alone is necessary but not sufficient. The frontend (WB FIFO,
RB injector, GC instruction decoder) must also send multiple events per cycle.

## Recommendation

- **Multi-output merge is not worth pursuing in isolation** — it addresses the
  output bottleneck but the input is the real constraint
- **Multi-input event pipeline** should be researched next if throughput >1.0
  is required
- **Multi-backend** may be more practical: each backend has its own event
  pipeline, metadata cache, forwarding table, and merge. Backend dispatch
  happens at the GC instruction level, bypassing the single-input limit.

## Files

- `rtl/gc_multi_output_pipeline.py` — MultiOutputEventPipeline implementation
- `tests/test_gc_multi_output.py` — Throughput scaling test
