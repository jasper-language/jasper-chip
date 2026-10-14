# 架构总览（对齐当前实现）

> 这份文档描述 **仓库现在真正实现了什么**，不是愿景。
> 过去的“愿景文档”已经与代码演进脱节。
> 若只读一份资料：请读 **`MEMO.md`**（步骤式决策记录/契约说明，长期权威）。

---

## 0. 一句话

jasper-chip 在研究一种 RISC‑V 系统：把 GC 行为拆成 **三颗协作的 GC 芯片（Scan/Clean/Move）**，通过 **可背压的片间链路** 连接，并用 **epoch（轮次）一致性契约** 保证“在途延迟/背压/搬迁更新”下仍然正确。

---

## 1. 主要模块

### 1.1 CPU / SoC（上下文）
仓库里有研究型 CPU 流水线（`RV12Core`）和多核 SoC（`TopSoC`）。
GC 指令与（可选）屏障管线也在，但 **当前研究主线** 是：

- **三芯片 GC 子系统**
- **片间协议在真实互连行为（背压/延迟）下的正确性**

### 1.2 三芯片 GC 子系统
GC 被拆为三个 chip-top wrapper：

- **Scan 芯片**（`GCScanChipTop`）
  - 输入：写屏障风格事件（研究阶段用 card_id 等表示）
  - 输出：到 Clean 的 **card 记录流**
  - 关键点：per-core 去重 + epoch 生命周期

- **Clean 芯片**（`GCCleanChipTop`）
  - 输入：GC 命令（NEW/DROP/RELOC 等）与来自 Scan 的 card 流
  - 输出：
    - mark/scan 统计（研究模型）
    - **reloc 更新流**（old→new）到 Move（仅在 RELOC commit 时发出）
  - 关键点：背压下不丢关键更新（宁可 stall，也不能 silent drop）

- **Move 芯片**（`GCMoveChipTop`）
  - 输入：来自 Clean 的 reloc 更新（old→new）
  - 服务：forwarding table 查询（`MV_QUERY`），用于读屏障/PLD 类语义
  - 关键点：epoch 失效 + bounded chase（old→mid→new）

仓库提供一个参考互连系统：

- **`GC3ChipSystem`**
  - Scan → Clean：`card_link`（FIFO 链路模型）
  - Clean → Move：`reloc_link`（FIFO 链路模型）
  - 全局广播：`epoch_advance`（翻转 1bit epoch）

---

## 2. 片间链路（最关键的部分）

### 2.1 Scan → Clean：card 流
Scan 输出的每条 card 记录包含：
- `card_id`
- `core_id`
- `epoch`（在事件入队时捕获，即便延迟很久送达也不会变）

`GC3ChipSystem` 用可配置 FIFO 建模互连：
- `card_link_depth`
- `card_link_enable`（=0 表示停止投递/制造背压与在途延迟）

**正确性契约：stale card 必须丢弃**
- 如果一条 card 记录是在 epoch=E 产生的，它必须携带 E。
- 当 epoch 翻转后（E→E^1），旧 epoch 的 card 即便“迟到”，也不能污染新一轮 GC。
- Clean 的规则：
  - 若 `card_in_epoch != clean_epoch`：`ready=1` 接收并丢弃（不进入 marking 队列）
  - 丢弃计数：`dbg_card_stale_drop++`

### 2.2 Clean → Move：reloc 更新流
Clean 在 RELOC **成功提交（commit）** 时才产生 reloc 更新。
链路同样用 FIFO 建模：
- `reloc_link_depth`
- `reloc_link_enable`

每条更新包含：
- `old_handle`
- `new_handle`
- `epoch`（由 Clean 在捕获更新进入链路时打标）

**正确性契约：stale reloc update 不能“复活映射”**
- 旧 epoch 的 reloc 更新即便在新 epoch 才送达，也不能让新 epoch 的查询命中。
- 因此 epoch 必须随更新一起跨片传输；Move 写表时使用 **更新自带 epoch**（而不是 Move 当前 epoch）。

---

## 3. 背压原则：慢可以，错不行

两条链路都允许背压。系统的基本原则是：
- 背压时可以 **stall**
- 但不能 **silent drop** 正确性关键的信息

工程化体现：
- Clean 的 reloc 更新接口使用 `valid/ready`（不是 1-cycle 脉冲），确保不会丢更新。
- 链路 FIFO 占用可观测：
  - `dbg_card_link_level`
  - `dbg_reloc_link_level`

---

## 4. Epoch 语义

系统使用 1bit epoch（`epoch_advance` 翻转），作为 O(1) 的“轮次边界”。

- Scan：在 **入队时** 捕获 epoch，保证延迟投递仍携带原 epoch。
- Clean：对 epoch 不匹配的 card **接收并丢弃**。
- Clean：对 reloc 更新打 epoch tag。
- Move：表项带 `entry_epoch`，查询只命中 `entry_epoch == current_epoch`。

这样保证：
- 在途延迟/背压不会把旧轮次的信息带入新轮次
- epoch 翻转是 O(1) 的一致性边界（无需逐项清表）

---

## 5. 我应该跑哪些测试/工具？（最实用入口）

### 5.1 核心一致性契约
```bash
python -m tests.test_step58_reloc_epoch_tag_drop
python -m tests.test_step60_card_epoch_stale_drop
python -m tests.test_step62_dual_link_epoch_stale_protection
```

### 5.2 背压下“不 silent drop”
```bash
python -m tests.test_step63_card_link_level_saturates
python -m tests.test_step64_reloc_link_level_saturates
```

### 5.3 Fuzz + 互连深度收敛（autotune）
```bash
python -m tests.test_step65_randomized_dual_link_fuzz
python -m tools.step68_fuzz_matrix --seeds 0x1,0x2 --card-depths 1,2 --reloc-depths 1,2
python -m tools.step70_autotune
python -m tools.step71_apply_autotune
```

---

## 6. 代码入口（去哪找实现）

- `rtl/gc_chip_scan.py`, `rtl/gc_chip_clean.py`, `rtl/gc_chip_move.py`：三芯片 wrapper
- `rtl/gc_3chip_system.py`：参考互连与链路建模
- `tests/`：按 step 编号的契约测试
- `tools/`：matrix/pareto/autotune/report 等工具

---

## 7. 文档维护规则（避免再次漂移）

- **`MEMO.md` 是长期权威**：记录每一步新增契约与实现选择。
- docs 应该写三件事：
  1) 当前行为
  2) 当前契约
  3) 如何用测试/工具复现

若修改协议：请同步更新本文件，并在同一个 PR 里更新/新增对应的契约测试。
