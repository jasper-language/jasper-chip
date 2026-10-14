# Step53：三颗 GC 协处理芯片接口规格（Scan / Clean / Move）

## 1. 拆分目标

GC 子系统拆分为三颗独立可综合的协处理芯片：

- **Scan**：扫描（读为主），消费/去重写屏障产生的 dirty-card 事件，输出 remembered-set（card stream）。
- **Clean**：清理/回收（sweep + allocator），对象元数据的**唯一写者**，并且是 **GC_RELOC 的提交点**。
- **Move**：搬运/转发表（forwarding map），为读屏障查询提供 old→new；支持 epoch、latest-wins、链追踪、多路更新不丢。

CPU 侧把 GC 子系统当黑盒：CPU 不干预 GC 过程，只通过 GC 指令表达“引用语义变化”。

兼容说明：仓库当前 RTL 还保留 `GC_EPOCH`（研究/测试用）用于广播 `epoch_advance`。若坚持严格 6 指令，可将该指令视为特权/内部指令，或由 Clean 芯片内部计时器/阈值策略触发 `epoch_advance`。

## 2. CPU 可见 API（6 条 GC 指令）

| 指令 | 语义（抽象） | trap 条件（示例） |
|---|---|---|
| GC_NEW rd | 分配一个 handle/object-id（返回到 rd） | 无可用槽/资源不足 |
| GC_CLONE rd, rs1 | 引用计数 rc++（rd 可选返回 rs1 或 0） | rs1 未使用 |
| GC_DROP rs1 | rc--；若 rc 变为 0 且未 pinned，则释放 | 未使用 / pinned / rc==0 |
| GC_PIN rs1 | pin=1（禁止回收/搬运） | 未使用 |
| GC_UNPIN rs1 | pin=0 | 未使用 |
| GC_RELOC rs1(old), rs2(new) | 搬运提交点：若成功，产生 old→new 映射更新 | old 未使用 / pinned / 资源不足 |

> 关键约束：**old→new 映射只能在 GC_RELOC 成功提交时产生**（失败/trap 不得更新映射）。

## 3. 通用命令/响应协议（CPU↔协处理器）

每个协处理器对 CPU 暴露同一套 per-core 命令 FIFO + per-core 响应槽（与现实现一致）：

- 输入（每核 i）：
  - `cmd_enq_valid[i]` / `cmd_enq_ready[i]`
  - `cmd_tag[i]`（8-bit，本地递增即可）
  - `cmd_op[i]`（3-bit：具体 op 由协处理器内部解码）
  - `cmd_rd[i]`、`cmd_rs1[i]`、`cmd_rs2[i]`
- 输出（每核 i）：
  - `rsp_valid[i]` / `rsp_take[i]`
  - `rsp_tag[i]`、`rsp_rd[i]`、`rsp_data[i]`
  - `trap[i]`（1 拍脉冲或与 rsp 同步）

## 4. 三芯片端口定义（信号级）

### 4.1 Scan 芯片端口

- 写屏障事件输入（每核）：
  - `wb_valid[i]` / `wb_ready[i]`
  - `wb_addr[i]`、`wb_data[i]`（研究用）
- Epoch：
  - `epoch_advance`（输入，1 拍脉冲）
- Card stream 输出（单通道）：
  - `out_valid` / `out_ready`
  - `out_card_id`、`out_core_id`、`out_epoch`

### 4.2 Clean 芯片端口

- CPU 命令/响应：使用通用协议（主要承载 6 条 GC 指令）
- Card stream 输入（来自 Scan）：
  - `card_in_valid` / `card_in_ready`
  - `card_in_card_id`、`card_in_core_id`、`card_in_epoch`
- Epoch tick（可选，若仍保留 GC_EPOCH）：
  - `epoch_tick[i]`（输出，供 SoC OR 起来广播给 Scan/Move）
- Reloc commit sideband（输出，给 Move）：
  - `mv_upd_valid[i]`、`mv_upd_old[i]`、`mv_upd_new[i]`

### 4.3 Move 芯片端口

- CPU/微结构查询命令/响应：使用通用协议（典型为 MV_QUERY 微操作；不新增 ISA）
- Epoch：
  - `epoch_advance`（输入，1 拍脉冲；用于 epoch 翻转失效）
- Sideband 更新输入（来自 Clean）：
  - `upd_valid[i]`、`upd_old[i]`、`upd_new[i]`

## 5. 芯片间最小互连

- Scan → Clean：card stream（ready/valid，单通道）
- Clean → Move：reloc commit sideband（per-core 脉冲；Move 内部可缓冲/轮询 drain）
- Epoch 广播：`epoch_advance` 同时接入 Scan 与 Move

## 6. 现 RTL 对应关系

- Scan：`rtl/gc_scan_coproc.py`
- Clean：`rtl/gc_sweep_coproc.py`
- Move：`rtl/gc_mv_coproc.py`

Step53 新增的 chip-top wrapper（便于“按芯片”综合/接口冻结）位于：

- `rtl/gc_chip_scan.py`
- `rtl/gc_chip_clean.py`
- `rtl/gc_chip_move.py`
- 示例互连：`rtl/gc_3chip_system.py`

## 7. 验证/回归建议

### 7.1 单模块语义（已有）
- Clean（sweep）语义：用 Step45/46 的 golden-model 对拍钉死（DROP/RELOC/响应/trap）。
- Move（MV）语义：latest-wins、链追踪、multi-update 不丢、epoch 失效（Step48~52）。

### 7.2 3-chip 协议级契约（Step55，建议长期保留）
- `tests/test_step55_3chip_reloc_trap_no_mv_update.py`
  - **RELOC trap 不得更新映射**（提交点原则）。
- `tests/test_step55_3chip_epoch_invalidate_mv.py`
  - **epoch 广播必须失效映射**（跨周期隔离）。


## Step56: Clean→Move Reloc Stream（片间链路推荐形式）

- 推荐把 relocation 提交后的映射更新从 `per-core pulse` 形式升级为 **单条 ready/valid 流**：
  - `reloc_out_valid/ready/old/new/core_id`（Clean 输出）
  - `reloc_in_valid/ready/old/new/core_id`（Move 输入）
- 这样可以自然插入片间 FIFO/链路延迟，并用 backpressure 明确表达“链路拥塞”，避免静默丢更新。
- 仍保持原则：**只有 RELOC 成功提交（不 trap）才会产生更新**；链路只负责可靠传输。
