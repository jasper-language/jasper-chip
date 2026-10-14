# Jasper-GC Factory 5nm / 5.1GHz Synthesis Snapshot

This is a generic Yosys/Verilator snapshot, not PDK signoff STA.

## Tool Availability

- yosys: `/opt/homebrew/bin/yosys`
- verilator: `/opt/homebrew/bin/verilator`
- openroad/openlane/sta: `not found`
- 5nm liberty/SDC: `not found in repo`

## Synthesis Runs

|run|wires|wire_bits|ports|port_bits|cells|yosys_time_s|peak_mem_mb|rtlil_mb|verilog_mb|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|16t_domain_full|491668|1060066|11342|66834|503366|177.90|1257.47|99.7|8.1|
|32t_domain_stat|209730|1734796|22269|129730|121805|1016.55|1030.61|199.4|16.3|
|64t_factory_stat|326271|2888220|36103|245658|181413|2110.35|1859.22|371.9|26.3|

## 5nm / 5.1GHz Throughput Model

- Stable RTL point: `132 events/cycle * 5.1GHz = 673200 MEv/s`
- Aggressive ingress point: `256 events/cycle * 5.1GHz = 1305600 MEv/s`

|event_rate_per_core_cycle|cpu_demand_mev_s|stable_headroom|aggressive_headroom|
|---:|---:|---:|---:|
|0.05|65280|10.31x|20.00x|
|0.10|130560|5.16x|10.00x|
|0.20|261120|2.58x|5.00x|

## Timing Status

- Verilator lint passes for the generated 16t domain Verilog after suppressing generated-netlist width/priority warnings.
- Yosys `ltp -noff` on the flattened 16t synthesized domain reports a longest topological path length of `101` generic gates, rooted in accelerator compact-engine control (`accel.ce`).
- True 5.1GHz STA is blocked until a 5nm standard-cell liberty, wire RC assumptions, and SDC constraints are available.
- Ready-aware `HYBRID` dispatch is constrained out of large synthesis paths; large profiles use static `HASH_LSB` routing.
- Large ingress groups use a registered one-entry dispatch buffer/credit point; the 256c/64t smoke remains at `132 events/cycle` after this register cut.
