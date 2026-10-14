# RV12 多核 12 级流水线 + GC 指令集（研究工程）

这个工程用 **Amaranth（Python HDL）** 描述一个「多核 RV32 子集」的 **12 级流水线** CPU，并加入一组 **GC（垃圾回收）自定义指令**（CUSTOM0 opcode + funct3 选择）。

> 说明：本仓库定位为“研究骨架”。重点是流水线结构、GC 指令接口、多核仲裁与协处理器扩展接口。

## 目录
- `rtl/`：Amaranth RTL
- `sim/`：导出 RTLIL/Verilog 的脚本与（可选）仿真相关文件
- `tests/`：纯 Python 的轻量自检（不依赖 Amaranth）
- `MEMO.md`：项目“记忆/决策记录”，用来避免每次重复思考

## 当前已有的 GC 6 条指令（CUSTOM0）
位于 `rtl/isa.py`：

- `GC_NEW`：分配一个对象槽位（返回 handle/index 到 rd）
- `GC_DROP`：减少引用计数（可能触发释放）
- `GC_CLONE`：增加引用计数（返回原 handle 到 rd）
- `GC_PIN`：pin 住对象（禁止移动/释放）
- `GC_UNPIN`：解除 pin（如果 rc==0 可释放）
- `GC_RELOC`：把对象从 old 移到 new（两步写端口处理）

GC 协处理器：已拆为 3 个模块（接口骨架），位于 `rtl/`：
- `gc_scan_coproc.py`：写屏障事件收集/扫描（本阶段只做 FIFO 收集 + 背压）
- `gc_sweep_coproc.py`：清理/引用计数（当前仍承载原 6 条 GC 指令实现）
- `gc_mv_coproc.py`：移动/转发表（占位骨架，后续支撑读屏障）

> 兼容：保留旧文件 `rtl/gc_coproc.py`，但 TopSoC 已默认使用上述 3 模块。

## 阶段性目标
设计目标：
- 多核 12 级流水线 CPU
- 读屏障 / 写屏障
- GC 旁路 AU（ALU）
- 3 个 GC 协处理器：扫描（scan）、清理（sweep/cleanup）、移动（mv/relocate）

本仓库的后续演进计划已记录在 `MEMO.md`。

## 依赖与工具
### Python 依赖（用于生成/仿真）
- `amaranth`
- （可选）`amaranth-yosys` 或系统 `yosys`（用于从 RTLIL 输出 Verilog）

### 轻量自检（不依赖 Amaranth）
- 运行 `tests/test_isa.py` 可验证指令编码是否符合预期。

## 快速运行（本机）
1) 安装依赖
```bash
pip install amaranth
# 如果要用 sim/build_verilog.py 生成 TopSoC.il/TopSoC.v，还需要 yosys
```

2) 运行轻量自检
```bash
python -m tests.test_isa
```

3) 生成 RTLIL + 通过 yosys 导出 Verilog
```bash
python sim/build_verilog.py
```


## 无网环境（离线 wheel）怎么跑
在不能联网的环境（离线/隔离环境）里：

1) 把 wheel 放进 `third_party_wheels/`，至少需要：
- `amaranth-0.5.8-*.whl`
- `jschon-0.11.1-*.whl`
- `pyvcd-0.4.0-*.whl`

2) 然后运行离线安装脚本：
```bash
python install_deps_offline.py
```

> 备注：jschon 还依赖一个第三方包 rfc3986。为了避免无网环境里缺 wheel 导致安装失败，
> 本仓库在根目录自带了一个“极简 rfc3986 兼容 shim”（`_rfc3986_shim/`，**自研代码，非上游 vendored 代码**），
> 足够让 amaranth/jschon 正常 import；若环境中已安装官方 `rfc3986`，则优先使用官方包。

3) 运行 elaboration 测试（需要 amaranth）：
```bash
python -m tests.test_elaborate
```

## Step25：Sweep 去重表参数量化（生成表格）
可以用一个小脚本把 sweep 去重表（sets/ways/index_mode）的冲突/替换情况跑成表格：
```bash
python -m tools.sweep_param_sweep
```
输出：
- `reports/step25_sweep_table.csv`
- `reports/step25_sweep_table.md`

## Step26：批量扫参 + 多核 workload（更像真实系统）

本轮新增工具：`tools/sweep_param_sweep_step26.py`

- 默认（包含多核 workload，输出到 reports/）：
  - `python -m tools.sweep_param_sweep_step26`

- 自定义扫描范围：
  - `python -m tools.sweep_param_sweep_step26 --sets 2,4,8,16 --ways 1,2,4 --index 0,1`

- 只跑单核 workload（更快）：
  - `python -m tools.sweep_param_sweep_step26 --no-multicore`

输出文件：
- `reports/step26_sweep_table.csv`
- `reports/step26_sweep_table.md`

## Step27：Zipf 热点 workload + Top-N 汇总（更贴近真实写屏障压力）

本轮新增工具：`tools/sweep_param_sweep_step27.py`

特点：
- 新增 Zipf 分布 workload（单核/多核），更能代表真实的“热点 card”压力。
- Markdown 顶部自动生成 Top-N 推荐参数（按 replace 最小、dup 最大等排序）。

示例：
- 快速跑一个小表（适合在无网/低资源环境验证）：
  - `python -m tools.sweep_param_sweep_step27 --sets 2 --ways 1 --index 0 --topn 1 --zipf-single-events 48 --zipf-mc-events-per-core 12`

- 关闭 Zipf（只看构造 workload）：
  - `python -m tools.sweep_param_sweep_step27 --no-zipf`

输出文件：
- `reports/step27_sweep_table.csv`
- `reports/step27_sweep_table.md`

## Step28：跨 workload 全局 Top-K（综合评分，给出默认配置建议）

本轮新增工具：`tools/sweep_param_sweep_step28.py`

在 Step27 的“每 workload Top-N”基础上，Step28 增加一个“全局 Top-K”列表：
把所有 workload 的统计按权重汇总成综合 score（越小越好），用来挑选“默认参数”。

综合评分公式（可通过 CLI 调整权重）：

- `score = w_replace*Σreplace + w_miss*Σmiss - w_dup*Σdup - w_hit*Σhit`

示例：
- 跑一个非常小的组合并输出全局 Top-K：
  - `python -m tools.sweep_param_sweep_step28 --sets 2 --ways 1,2 --index 0,1 --topk 3 --no-zipf --no-multicore`

- 调大替换抖动惩罚（更保守）：
  - `python -m tools.sweep_param_sweep_step28 --w-replace 2.0 --w-miss 0.2 --w-dup 0.1 --w-hit 0.05`

输出文件：
- `reports/step28_sweep_table.csv`
- `reports/step28_sweep_table.md`

## Step29：跨 workload 全局 Top-K（按 workload 归一化 + 加权）

本轮新增工具：`tools/sweep_param_sweep_step29.py`

Step28 的全局 Top-K 是“直接求和”，事件数更大的 workload 会主导 score。
Step29 改为：先在每个 workload 内对 replace/miss/dup/hit 做 min-max 归一化，再按 workload 权重加权合成全局 score。

综合评分（每个 workload 内归一化后）：

- `score = Σ wl_weight * ( w_replace*replace_norm + w_miss*miss_norm - w_dup*dup_norm - w_hit*hit_norm )`

示例：
- 跑一个小表（关闭 zipf/multicore 保持极快）：
  - `python -m tools.sweep_param_sweep_step29 --sets 2 --ways 1,2 --index 0,1 --topk 3 --no-zipf --no-multicore`

- 调整 workload 权重（让 zipf_mc 更重要）：
  - `python -m tools.sweep_param_sweep_step29 --w-workload zipf_mc_s1p2=2.0,lowbit_conflict=1.0`

输出文件：
- `reports/step29_sweep_table.csv`
- `reports/step29_sweep_table.md`

## Step30：把推荐配置固化为默认参数 + baseline 回归

本轮新增：
- `rtl/gc_params.py`：SoC 默认 sweep 去重表参数（由 Step30 baseline 自动生成）。
- `reports/step30_baseline.json`：固定种子/固定规模的小扫参结果，用于回归。
- `tools/generate_step30_baseline.py`：生成 baseline，并回写 `rtl/gc_params.py`。

使用方式：
- 重新生成 baseline（并同步更新默认参数文件）：
  - `python -m tools.generate_step30_baseline`

- 跑 baseline 回归测试：
  - `python -m tests.test_step30_baseline`

说明：baseline 的 workload/事件数刻意选得很小，保证离线环境也能快速跑完。

## Step31：更贴近真实 mutator 的多核写屏障压力模型（纯 Python 快速评估）

本轮新增：`tools/step31_mutator_report.py`。

特点：
- 多核并发（round-robin 交织）
- Zipf 热点/长尾分布
- phase 热区迁移（模拟写热点随时间变化）
- scan：去重/epoch 生命周期 + 共享引擎（consume_every + batch_size）
- sweep：set-associative 去重表（含 xor-fold index）

生成报告：

```bash
python -m tools.step31_mutator_report --outdir reports --name step31_mutator
```

输出：
- `reports/step31_mutator.json`
- `reports/step31_mutator.md`

## Step32：Step31 趋势模型 baseline 回归

生成 baseline（固定种子/固定规模，供回归测试用）：

```bash
python -m tools.generate_step32_mutator_baseline
```

运行回归测试（检测趋势模型是否漂移）：

```bash
python -m tests.test_step32_mutator_baseline
```

输出：
- `reports/step32_mutator_baseline.json`
- `reports/step32_mutator_baseline.md`

说明：该工具是“研究用趋势模型”，不替代 RTL 级功能验证；默认 sweep 参数来自 `rtl/gc_params.py`（Step30 固化）。

---

## Step33：scan 默认参数推荐与固化（趋势模型）

目的：把 scan 的默认参数（cardset_size / fifo_depth / consume_every / batch_size）也固化下来，
避免每轮手调导致吞吐/背压指标漂移。

### 生成推荐与默认值

```bash
python -m tools.step33_scan_recommend --outdir reports --name step33_scan_reco --write-defaults
```

产物：
- `reports/step33_scan_reco.json` / `reports/step33_scan_reco.md`（Top-N 推荐表）
- `rtl/gc_scan_params.py`（Top-1 推荐写入，TopSoC 默认加载）
