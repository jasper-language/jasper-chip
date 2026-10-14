# docs 导航

jasper-chip 的文档入口。

> 建议阅读顺序：先看 **MEMO.md**（权威、步骤式记录），再看架构总览与工具链。

---

## 1) 权威资料

- **`/MEMO.md`**：项目记忆/决策记录/契约列表（长期权威，包含 Step 0～Step72+ 的演进）。

---

## 2) 架构与协议

- **`architecture_overview.md`**：对齐当前实现的三芯片架构（Scan/Clean/Move）、两条片间链路（card_link/reloc_link）、背压与 epoch 一致性契约。

---

## 3) 常用入口

### 3.1 核心一致性契约（强烈建议先跑）

```bash
python -m tests.test_step58_reloc_epoch_tag_drop
python -m tests.test_step60_card_epoch_stale_drop
python -m tests.test_step62_dual_link_epoch_stale_protection
```

### 3.2 背压下“不 silent drop”

```bash
python -m tests.test_step63_card_link_level_saturates
python -m tests.test_step64_reloc_link_level_saturates
```

### 3.3 Fuzz / 矩阵报告 / autotune

```bash
python -m tests.test_step65_randomized_dual_link_fuzz
python -m tools.step68_fuzz_matrix --seeds 0x1,0x2 --card-depths 1,2 --reloc-depths 1,2
python -m tools.step70_autotune
python -m tools.step71_apply_autotune
```

---

## 4) 目录速查

- `rtl/`：Amaranth RTL（含三芯片 wrapper 与 `GC3ChipSystem`）
- `tests/`：按 step 编号的契约回归测试
- `tools/`：扫参/报告/matrix/pareto/autotune 等研究工具
- `reports/`：工具输出工件（CSV/MD/JSON 等）

---

## 5) 文档维护规则（避免漂移）

- **任何协议/语义改动必须同时更新文档与测试**。
- 优先用“契约型测试”锁住语义（stale drop / no silent drop / epoch / backpressure）。

