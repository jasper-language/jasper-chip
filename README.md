# jasper-chip

一个用 **Amaranth（Python HDL）** 编写的研究型 RISC‑V + GC 系统工程。

本项目不是“在 CPU 里写一个 GC 算法”；相反，我们把 GC 拆成可独立演化/综合的协处理器与**片间协议**，并用**可回归测试**把关键一致性契约钉死。

> 核心问题：
> **GC 能否从 CPU 中剥离，变成旁路/协处理器/多芯片系统，同时仍保持移动压缩与读屏障的一致性？**

---

## 当前“真实现状”（不是愿景）

### 1) RV12Core + TopSoC（研究型流水/SoC）
- 12 级流水线核心：`RV12Core`（IF1~IF4 / ID1~ID2 / IS / EX1~EX2 / MEM1~MEM2 / WB）。
- 多核 SoC：每核 IMEM；DMEM 通过 RR 仲裁共享。

### 2) 当前实现的 GC 指令集（CUSTOM0）
当前实现与 `MEMO.md` 保持一致：

- `NEW / DROP / CLONE / PIN / UNPIN / RELOC`

> 说明：仓库里历史上出现过“冻结 ISA=NEW/DROP/PLD/PST/SAFEPOINT/RB_CFG”的草稿文案。
> 那不是当前实现。现在所有可回归语义以 `MEMO.md` 为准。

### 3) 三协处理器与“三芯片”拆分（本项目当前主线）
- **Scan**：收集写屏障事件并输出 card 流（含去重、epoch 生命周期）。
- **Clean**：执行 GC 指令与最小 mark/sweep 模型；在 RELOC commit 时输出 reloc 更新流。
- **Move**：维护 forwarding table（old→new）；支持 epoch 失效与 bounded chase，供读屏障查询（`MV_QUERY`）。

仓库提供一个示例互连系统：
- `GC3ChipSystem`：Scan→Clean（`card_link` FIFO），Clean→Move（`reloc_link` FIFO），epoch 广播。

### 4) 片间协议：背压 + 在途延迟 + epoch 一致性
项目的“硬核点”是：两条跨片链路都用 FIFO 模拟真实互连（可背压/可延迟），并用 epoch 把跨轮次一致性钉死：
- stale card（旧 epoch 迟到）被 Clean 丢弃
- stale reloc update（旧 epoch 迟到）不能在新 epoch “复活映射”

---

## 快速开始

### 依赖
- Python 3.10+（建议）
- `amaranth`（以及其依赖：`pyvcd`, `jschon` 等）

无网环境可参考 `MEMO.md` 中关于离线 wheel 的记录与 `install_deps_offline.py`。

> 关于 `_rfc3986_shim/`：为防止离线环境缺 `rfc3986` 导致 `import amaranth` 失败，仓库自带一个
> **自研的极简 rfc3986 兼容 shim**。它**不是**上游 `python-rfc3986` 的 vendored 代码，也不附带上游许可证；
> 若环境中已安装官方 `rfc3986`，shim 会自动让位（优先使用官方包）。

### 跑一组最核心的回归（建议从这里开始）

```bash
# 3-chip 架构可 elaboration
python -m tests.test_step53_3chip_elaborate

# 关键一致性契约：epoch / stale drop / backpressure
python -m tests.test_step58_reloc_epoch_tag_drop
python -m tests.test_step60_card_epoch_stale_drop
python -m tests.test_step62_dual_link_epoch_stale_protection

# 链路“不会 silent drop”的契约
python -m tests.test_step63_card_link_level_saturates
python -m tests.test_step64_reloc_link_level_saturates
```

---

## 互连深度探索、fuzz 与 autotune（Steps 65+）

### 1) 随机化端到端 fuzz（可复现）
```bash
python -m tests.test_step65_randomized_dual_link_fuzz
```

或用 CLI 指定 seed：
```bash
python -m tools.step65_fuzz_run --seed 0xC0FFEE --cycles 500
```

### 2) 互连深度 × seed 矩阵报告
```bash
python -m tools.step68_fuzz_matrix --seeds 0x1,0x2 --card-depths 1,2 --reloc-depths 1,2
```
生成：
- `reports/step68_fuzz_matrix.csv`
- `reports/step68_fuzz_summary.csv`
- `reports/step68_fuzz_summary.md`

### 3) Pareto 收敛与一键 autotune
```bash
python -m tools.step70_autotune
```
输出推荐深度 JSON：`reports/step70_recommended_depths.json`

把推荐落地为可 import 的常量模块：
```bash
python -m tools.step71_apply_autotune
```
生成：`rtl/autotuned_link_depths.py`

并可在仿真里启用：
- `GC3ChipSystem(use_autotuned_defaults=True)`

---

## 文档导航

- `MEMO.md`：真实工程的“决策记录/演进日志/契约说明”（长期权威）。
- `docs/index.md`：docs 导航页（建议从这里找入口）。
- `docs/architecture_overview.md`：当前三芯片系统与片间协议（中文，且对齐实现）。

---

## 贡献方式（最重要的约定）

- **任何跨片语义改动都必须带测试。**
- 优先写“契约型测试”（stale drop / no silent drop / epoch / backpressure），而不是只靠波形观察。
- 若要改协议：先改文档，再改 RTL，再补测试（同一个 PR 里完成）。

---

## License

本项目基于 **Apache License 2.0** 发布，完整条款见仓库根目录的 [`LICENSE`](LICENSE)。
本项目定位为研究工程，欢迎在此基础上开展研究与工程实践。
