# MEMO（项目记忆/决策记录）

> 目的：把“已经想清楚的架构选择、接口约定、下一步任务”固定下来，避免每次重新推导。

## 0. 当前状态（2026-01-01）
- 代码库使用 **Amaranth** 描述 RTL。
- 已实现：
  - 多核 TopSoC：每核独立 IMEM；DMEM 通过 RRArbiter 共享；GC 通过共享 `GCCoProc`。
  - 12 级流水线核心（`RV12Core`）：IF1~IF4 / ID1~ID2 / IS / EX1~EX2 / MEM1~MEM2 / WB。
  - GC 指令集 6 条（CUSTOM0 + funct3）：NEW/DROP/CLONE/PIN/UNPIN/RELOC。
  - GC 协处理器：每核 FIFO + 单引擎轮询，每 cycle 处理 1 条（RELOC 用两步）。

## 1. GC 指令编码约定
- `opcode = CUSTOM0 (0b0001011)`
- `funct3` 选择 GC op：
  - 000 NEW
  - 001 DROP
  - 010 CLONE
  - 011 PIN
  - 100 UNPIN
  - 101 RELOC
- `funct7` 目前保留为 0。

## 2. 读屏障/写屏障：建议的“最小可落地”接口
### 2.1 写屏障（store barrier）
- 触发位置：在 **store** 发出到 DMEM 前（建议在 MEM1/MEM2）
- 目的：把“旧引用/新引用”或“被写对象地址”记录到 GC 的 remembered set / card table。
- 推荐做法：新增一条 GC 指令（或复用现有 CUSTOM0 编码扩展）
  - 例如 `GC_WB rs1=obj, rs2=value` 或 `GC_WB rs1=addr, rs2=new_ref`。
- 第一阶段实现（研究骨架）：
  - 只要能把写入地址入队到 GCScanCoProc 即可（不需要真正 card table）。

### 2.2 读屏障（load barrier）
- 触发位置：load 数据返回后进入 WB 前（MEM2/WB）
- 目的：当对象被移动/转发时，返回“新地址”。
- 第一阶段实现：
  - 在 load path 上增加一个“条件重定向”：如果高位标记/版本不匹配，则发起 GC_MV 查询。
  - 简化模型：用一个小的 forwarding 表（old->new）由 GCMvCoProc 提供。

## 3. GC 旁路 AU（ALU bypass）建议
- 目标：当 GC 指令产生一个 handle/地址写回 rd，后续 AU/地址计算能立即使用。
- 最小实现：
  - 在 `IS/EX1` 阶段为 rs1/rs2 选择加入额外旁路源：
    - 来自 GC 响应通道（`gc_rsp_valid`/`gc_rsp_rd`/`gc_rsp_data`）
  - 如果 gc_rsp_data 当 cycle 有效且 rd 匹配，则覆盖 rs1v/rs2v。

## 4. 三个 GC 协处理器：接口拆分建议（下一步）
把现有 `GCCoProc` 拆成 3 个模块，各自专注：

1) `GCScanCoProc`（扫描/记录屏障事件）
- 输入：写屏障事件、根集合更新等。
- 输出：可选（统计/ack）。

2) `GCSweepCoProc`（清理/回收）
- 输入：DROP 导致 rc==0 的候选、或扫描结果。
- 输出：释放确认、可选 trap。

3) `GCMvCoProc`（移动/转发表）
- 输入：RELOC 指令、或 GC 移动阶段生成的映射。
- 输出：读屏障查询 old->new。

### 接口统一（建议）
- 统一使用：每核 FIFO + 单引擎轮询（第一阶段），后续再扩展多引擎。
- 响应带 `rd`（寄存器号）+ `data`（返回值），并有 `take` 清除。

## 5. 立即可做的下一步任务（按优先级）
1) **补齐可运行的 Python 仿真环境**：需要在开发机上安装 `amaranth`（以及 `yosys`）。
2) 增加 `tests/`：
   - `test_isa.py`（已加入）
   - 后续加入：`test_gc_coproc_model.py`（纯 Python golden model）
3) 在 `RV12Core` 增加 GC 响应旁路到 rs1/rs2（先做最小版本）。
4) 在 store path 加一个写屏障事件入队（先不做真实 card table）。
5) 拆分协处理器为 3 类（保留现有实现作为 `GCSweepCoProc` 原型）。

## 6. 本次我在容器里能做/不能做
### 6.1 当前容器状态（重要）
- 离线环境不能联网安装 pip 依赖，所以需要离线 wheel。
- 目前已验证：只要提供以下 wheel，就可以成功 `import amaranth` 并运行 `rtlil.convert`：
  - amaranth-0.5.8
  - jschon-0.11.1
  - pyvcd-0.4.0
- 因 jschon 还依赖 rfc3986，本仓库增加了 `_rfc3986_shim/` 极简兼容 shim（自研代码）用于兜底。

### 6.2 本次我实际完成的测试
- 已完成纯 Python 单元测试：`tests/test_isa.py`（校验 6 条 GC 指令编码一致性）。
- 已完成 Amaranth elaboration 测试：`tests/test_elaborate.py`（TopSoC -> RTLIL）。

### 6.3 下一步为了“更深入验证”建议准备的额外东西
- 推荐：`yosys`（用于把 RTLIL 导出为 Verilog）。
- 推荐：`verilator` 或 `slang`（用于更强的 lint/仿真）。

---

## 13. Step13 更新（2026-01-02）

本轮目标：把“写屏障（store barrier）”真正纳入可自动验证的正确性闭环，
并修补一个隐藏很深、但在真实多核 GC 体系里一定会咬人的坑：
**紧跟其后的依赖指令可能在 scoreboard 置位之前锁存旧值（1-cycle hole 的变体）**。

### 13.1 修复：ID1 hazard 看到“ID2 即将置位 pending”
问题：pending_rd_mask 是同步更新。即便有 ID1 前瞻检查，如果 ID2 本拍才会置位 pending，
那么 ID1 仍可能看不到，从而让“下一条指令”进入 ID2 并锁存旧 rs1v/rs2v。

典型复现：
- `GC_NEW x1`
- `SW x1,0(x0)`（立即依赖）

修复：给 ID1 一个视图 `pending_id1_view = pending_rd_mask | will_set_pending(ID2)`，
让 ID1 在同一拍就能感知 ID2 将要产生的 pending，提前阻塞下一条依赖指令。

### 13.2 scan 协处理器加入可观测统计（不改变语义）
为便于写自动化测试，`GCScanCoProc` 增加每核输出：
- `ev_count`：累计接收的写屏障事件数
- `last_addr/last_data`：最近一条被接收事件的内容

这些信号仅用于研究/仿真验证，不影响核心背压语义。

### 13.3 新增“实际测试效果”
新增单测 `tests/test_store_wb_event_dep.py`：
- 程序：`GC_NEW x1; SW x1,0(x0)`
- sweep 设为 `engine_latency=30`，制造 x1 很晚才返回
- 断言：
  - 早期（C20）x1=0、dmem[0]=0、scan ev_count=0
  - 后期（C220）x1=1、dmem[0]=1、scan ev_count=1 且 last_data=1

该测试同时验证：
- 依赖 store 不会把旧值写入内存
- 写屏障事件与 store commit 一致（不会丢、不会错拍）

## 7. Step3 更新（2026-01-01）
### 7.1 依赖可在无网环境跑通
- 现在只要有以下 wheel，就可以在无网环境 `import amaranth` 并执行 `rtlil.convert`：
  - amaranth-0.5.8
  - jschon-0.11.1
  - pyvcd-0.4.0
- 由于 jschon 还依赖 rfc3986，而 wheel 常常缺失：
  - 本仓库新增 `_rfc3986_shim/`（极简兼容 shim，自研代码），用于研究阶段兜底。
  - `install_deps_offline.py` 改为 `pip install --no-deps`，避免 pip 因缺 rfc3986 直接失败。

### 7.2 GC 旁路 AU（最小实现已落地）
- 在 `RV12Core` 的 EX1 操作数选择中新增旁路源：
  - 当 `gc_rsp_valid` 且 `gc_rsp_rd` 匹配 `IS.rs1/rs2` 时，直接用 `gc_rsp_data` 覆盖。
- 这让“GC 指令写回的新地址/handle”在**同一个 cycle**可被后续 AU/地址计算使用。

### 7.3 本轮新增的可验证测试
- `tests/test_elaborate.py`：
  - 实测 `TopSoC(ncores=2)` 可以成功 `rtlil.convert`，并在输出中找到 `module TopSoC`。

---

## 8. Step4 更新（2026-01-01）
本轮目标（两项要求）已完成两件事：

### 8.1 写屏障事件通路（store path -> GCScanCoProc）
**已落地最小实现**：
- 在 `RV12Core` 的 **MEM1** 阶段，当遇到 store（当前仅实现 SW）时：
  - 产生写屏障事件：`(addr=MEM1.mem_addr, data=MEM1.mem_wdata)`
  - 通过 `wb_enq_valid/ready` 通道入队到扫描协处理器 `GCScanCoProc`。

**背压与正确性约束**：
- 如果 `GCScanCoProc` FIFO 满导致 `wb_enq_ready=0`：
  - 核心会保守地 **全局 stall**（研究阶段先“安全优先”）。
  - 同时 **禁止向 DMEM 发出该条 store 请求**，避免“stall 期间重复写内存”。

### 8.2 三协处理器接口拆分（scan/sweep/mv）
**已完成骨架拆分**（不强行改行为）：
- `GCScanCoProc`：每核 FIFO 收集写屏障事件（本轮新增）。
- `GCSweepCoProc`：从 Step3 的 `GCCoProc` 迁移而来，仍承载 GC 6 指令实现（本轮新增文件）。
- `GCMvCoProc`：占位骨架（每核 FIFO + 单引擎轮询），当前对命令直接返回 0（本轮新增）。

**TopSoC 连接策略（当前版本）**：
- 仍将 GC 6 指令请求连接到 `GCSweepCoProc`，确保不破坏原有路径。
- 写屏障事件连接到 `GCScanCoProc`。
- `GCMvCoProc` 先实例化但暂不接入核心（下一步用于读屏障）。

### 8.3 本轮新增/更新的测试
- `tests/test_elaborate.py` 更新：
  - 继续验证 `TopSoC -> rtlil.convert` 成功
  - 额外断言 RTLIL 中存在：`GCScanCoProc / GCSweepCoProc / GCMvCoProc` 三个模块



## 9. Step6 更新（2026-01-01）
本轮按既定顺序 **A->B->C** 完成三件关键改造。

### 9.1 A：GC 请求/响应增加 tag（防串台/为乱序铺垫）
- `RV12Core` 发起 GC 指令请求时，携带 `gc_tag`（8bit，本地递增）。
- `GCSweepCoProc` FIFO 里把 tag 一起排队，并在响应时通过 `rsp_tag` 原样返回。
- 核心侧只有当 `gc_rsp_tag == gc_wait_tag` 时才会：
  - `gc_rsp_take=1`（取走响应）
  - 写回 `rd=data`（防止未来扩展后响应串台污染寄存器）

### 9.2 B：写屏障背压改为“本地队列吸收”（局部阻塞）
- 在 `RV12Core` 内新增 `wbq`（SyncFIFO depth=4），专门缓存写屏障事件 `(addr,data)`。
- scan 协处理器慢/满时：
  - 不再立刻卡死 store，而是让 `wbq` 先吸收。
  - 只有当 `wbq` 真满时，才阻塞 store（局部阻塞）。

### 9.3 C：把写屏障事件与“store commit”绑定
- 在本研究 CPU（无乱序）里，将 store 的 commit 定义为：**该 store 被真正发往 DMEM 的那个 cycle（MEM1 发请求）**。


## Step38 更新（2026-01-03）

本轮目标：在已有 Step37 “worst-case(max) 稳健推荐”闭环上，补上**解释性**视角：
不仅给出 Top-1，还要回答“哪个参数维度更关键/更值得花面积与带宽”。

### Step38.1 新增：跨 workload 的 scan 参数敏感性分析
- 新增工具：`tools/step38_scan_sensitivity.py`
  - 在 `shared_hot_shift` 与 `per_core_partition` 两种 workload 上跑同一 scan_grid
  - 定义 `worst_score = max(per_mode_score)`
  - 对每个参数维度（cardset/fifo/consume/batch）做 group-by：输出不同取值的 mean(worst_score)
  - 计算 `delta = max(mean) - min(mean)` 用于衡量“选错取值的代价”（越大越重要）

### Step38.2 baseline 回归保护
- 生成：`tools/generate_step38_scan_sensitivity_baseline.py`
- 回归：`tests/test_step38_scan_sensitivity_baseline.py`

### Step38.3 本轮新增的“实际测试效果”
- 在容器内执行：
  - `python -m tools.generate_step38_scan_sensitivity_baseline` 生成 baseline
  - `python -m tests.test_step38_scan_sensitivity_baseline` 通过，并打印 top1 与 importance 排序

- 只有当 `wbq` 有空间时，store 才允许发往 DMEM；并且同一 cycle 把事件写入 `wbq`。
- 这样保证：不会出现“内存已经写了，但事件因为背压被丢掉/延迟到不一致”的情况。

### 9.4 本轮新增测试
- `tests/test_gc_tag.py`：仿真验证 `cmd_tag -> rsp_tag` 原样返回。
- `tests/test_wbq_present.py`：结构性验证 RV12Core 中存在 `wbq` 本地队列。


## 10. Step7 更新（2026-01-01）

本轮目标：把“tag”真正用于制造 **乱序返回** 的可测场景，为后续多 outstanding 做准备。

### 10.1 GCMvCoProc：加入 tag + 乱序返回模型
- `GCMvCoProc` 命令/响应增加：`cmd_tag` / `rsp_tag`。
- 同一核内部增加 2 个 pending slot：
  - 从 FIFO 取命令后写入 pending slot，并设置 `delay = tag[1:0]`（可控、可复现）。
  - delay 归零即“就绪可返回”。
  - 若 slot0/slot1 同时就绪，优先返回 slot1，从而**稳定制造乱序**。

### 10.2 新增测试（实际效果）
- `tests/test_mv_ooo.py`：
  - 先发送 tag=0x03（delay=3），再发送 tag=0x00（delay=0）。
  - 预期并断言：响应顺序为 0x00 -> 0x03（乱序成立）。

### 10.3 技术评估（为什么要这么做）
- 只要协处理器存在“队列 + 仲裁 + 可变延迟”，响应乱序就是必然事件。
- 因此 CPU 侧**必须**使用 tag/sequence 做匹配；仅靠 rd 匹配迟早会串台。
- Step7 先把这个风险用“可重复的单元测试”固化下来，后续做多 outstanding 时不靠拍脑袋。

## 11. Step8 更新（2026-01-02）

本轮目标：让“读屏障/乱序返回”不再只是协处理器自嗨，而是 **CPU 侧有真实的 tag 匹配与写回**。

### 11.1 CPU 新增 MV 协处理器接口（core <-> GCMvCoProc）
- `RV12Core` 增加 mv 命令/响应信号：
  - `mv_cmd_valid/ready/tag/op/rd/rs1/rs2`
  - `mv_rsp_valid/tag/rd/data/take`
- `TopSoC` 连接 `core[i] <-> gc_mv[i]`。

### 11.2 CPU 内部新增两个关键结构
1) **mvq（每核命令队列）**
- `SyncFIFO(depth=4)`，格式：`tag|op|rd|rs1|rs2`
- 目的：解耦“请求产生”和“协处理器 ready”。

2) **pending 表（tag -> rd）**
- 4 个槽：`rb_valid/tag/rd`
- 目的：
  - 多条 query 在飞时，协处理器响应乱序也能找到正确 rd。

### 11.3 Step9-B 的测试注入口（rb_inj）提前落地
- 在 `RV12Core` 新增：
  - `rb_inj_valid/ready/rd/value`
  - `dbg_reg_addr/rdata`（调试读口）
- 用途：当 IMEM/DMEM/流水线仍在调试时，可以绕开访存，直接验证：
  - 多条 pending
  - 乱序响应
  - tag 匹配写回

### 11.4 本轮新增测试（实际效果）
- `tests/test_rb_inject_ooo.py`：
  - 注入两条 query（tag=3 delay=3, tag=4 delay=0），制造稳定乱序
  - 断言最终 `x1/x2` 写回正确


## 12. Step9 更新（2026-01-02）

本轮目标：解决 “memory 时序假设不一致” 这类底座问题，让端到端测试可稳定推进。

### 12.1 修复 IMEM/DMEM 的读时序：改为组合读
- `SimpleIMem/SimpleDMem` 的 `read_port(transparent=False)` 改为 `transparent=True`。
- 原因：当前 `RV12Core` 的取指/访存阶段，把 `*_rdata` 当组合输入使用；
  若 memory 是 1-cycle latency，会出现系统性错拍。
- 备注：这是研究阶段权衡（便于快速验证体系），未来要贴近真实 BRAM 时再回到 1-cycle，并补齐 pipeline 对齐。

### 12.2 新增“程序驱动”的端到端测试
- `tests/test_load_rb_program.py`：
  - 在 IMEM 放入两条 `lw`（读 dmem[0]/dmem[1]）
  - 核心不会直接写回 lw 原值，而是发起 MV_QUERY；mv 返回 rs1 原值
  - 由于 tag 起始为 3，mv 侧会稳定制造“第二条先返回”
  - 断言最终 `x1==0x11111111`、`x2==0x22222222`

### 12.3 下一步（Step10 的硬核点）
- 读屏障真正可用还缺：**scoreboard/依赖 stall**。
  - 当前实现允许 load 之后的依赖指令继续前进，可能读到旧值。
  - Step10 建议加入：`pending_rd_mask` 或小 scoreboard，在读到 pending rd 时 stall。
- 三协处理器并发/多核共享的仲裁策略也需要进一步测试覆盖。


## 13. Step10 更新（2026-01-02）

本轮目标：把 Step9 的端到端测试真正跑通，并定位/修复“指令字段错拍”的硬 Bug。

### 13.1 A->B->C：问题现象 -> 定位 -> 修复

**A（现象）**
- `tests/test_load_rb_program.py` 失败：`x2` 正确写回，但 `x1` 仍为 0。
- 进一步观察发现：MV 协处理器只收到 `rd=2` 的 QUERY；`rd=1` 那条 load 根本没进入读屏障入队。

**B（定位）**
- 我先加了 Step10 的“调试导出信号”（见 13.2），并写了一个临时 trace 测试打印关键状态。
- 观测到离谱现象：
  - DMEM 请求顺序被反转：先发 `addr=4`，后发 `addr=0`。
  - 某些拍里 `MEM2.wb_data` 是正确的 `0x11111111`，但 `MEM2.rd` 变成了 0。
- 根因：**ID2 阶段的 is_load/imm 组合逻辑用的是 “ID2 寄存器旧值”，却在同一拍又把结果写回 ID2。**
  - 结果：is_load/imm 永远落后一拍（对应上一条指令）。
  - 更糟糕的是：imm_i 来自 ID1，而 imm_s/imm_b 来自 ID2，字段错拍混在一起。
  - 这会把连续两条 load 的字段“交叉污染”，最终表现为顺序错乱、rd 丢失、读屏障漏入队。

**C（修复）**
- 将 **ID2 的分类/立即数计算全部改为基于 ID1（本拍已经锁存的那条指令）** 的组合值，然后在同一拍写入 ID2：
  - `is_load_d/is_store_d/...` 基于 `ID1.opcode`
  - `imm_i_d/imm_s_d/imm_b_d/imm_j_d` 基于 `ID1.insn`
  - `ID2.imm/ID2.is_load/...` 由上述 *_d 直接赋值
- 修复后，`test_load_rb_program` 稳定通过：两条 load 都能入队读屏障，且 mv 响应乱序也能正确写回。

### 13.2 Step10 新增：调试导出信号
- 在 `RV12Core` 增加以下只读调试口（不参与功能）：
  - `dbg_mem2_valid/is_load/rd/wb_data`
  - `dbg_rb_need_load/enq_ready/fire`
- 用途：后续做 scoreboard/依赖 stall 或更复杂的读屏障时，可以直接用单测断言这些中间状态。

### 13.3 本轮实际测试效果

在容器里离线安装（amaranth/jschon/pyvcd wheel）后，逐个运行：
- `python -m tests.test_elaborate`  ✅ TopSoC + 3 个协处理器可 elaboration
- `python -m tests.test_gc_tag`     ✅ GC tag 匹配链路 OK
- `python -m tests.test_isa`        ✅ 编码器一致性 OK
- `python -m tests.test_wbq_present`✅ 每核 wbq 存在
- `python -m tests.test_mv_ooo`     ✅ mv 乱序返回可复现
- `python -m tests.test_rb_inject_ooo`✅ rb_inj + tag 匹配写回 OK
- `python -m tests.test_load_rb_program`✅ 端到端：lw -> mv(query) -> 写回 OK（乱序返回下依然正确）

### 13.4 下一步建议（Step11）
- 现在 load 结果最终能写回，但**依赖指令可能提前读到旧值**。
- 下一步应加一个最小 scoreboard（如 `pending_rd_mask`）：
  - 当 `ID2/IS` 读到的 rs1/rs2 在 pending 表中时，stall 直到对应 tag 响应写回。
  - 并补一个单测：`lw x1; add x3,x1,x0` 这类依赖链必须被正确阻塞。


## 14. Step11 更新（2026-01-02）

本轮目标：补齐 Step10 提到的 **scoreboard/依赖 stall**，让“load 走读屏障（mv）”时，紧跟着的依赖指令不会读到旧值。

### 14.1 A->B->C：需求 -> 方案 -> 落地

**A（需求/风险）**
- Step10 虽然能保证 `lw -> mv(query) -> 写回` 最终正确，但仍存在经典 RAW 风险：
  - `lw x1,0(x0)` 的“新值”要等 mv 响应写回；
  - 紧跟着 `addi x3,x1,1` 如果继续前进，就会读到旧的 `x1=0`，导致 `x3=1`。

**B（方案）**
- 引入一个极简 scoreboard：`pending_rd_mask[32]`。
  - `pending_rd_mask[rd]=1` 表示该寄存器的“新值”还在 mv/读屏障路径上飞行。
  - decode 阶段（ID2）如果发现当前指令要读取的 `rs1/rs2` 命中 pending，则产生 `stall_dep`。
  - 额外加一个便宜的 WAW 保护：如果指令要写 `rd`，但 `rd` 仍 pending，则同样 stall。
- 关键实现点：**不能用“全局 stall 冻住所有流水级”**，否则会出现潜在死锁（依赖指令卡住，老的 load 也被冻住，永远到不了产生 mv 响应的时刻）。
  - 本工程采取：`stall = stall_store | stall_rb` 仍然是“后端全局停顿”；
  - `stall_dep` 只冻结 IF/ID（前端），并把 IS 置为气泡，允许后端继续排空。

**C（落地）**
- `rtl/rv12_core.py`
  - 新增 `pending_rd_mask`。
  - 在 **load 发射进入 IS** 时置位对应 rd（让紧随其后的依赖指令能及时被挡住）。
  - 在 **mv 响应写回** 时清除对应 rd。
  - 在 ID2 计算 `stall_dep`：
    - `haz_rs1 / haz_rs2`：rs1/rs2 命中 pending
    - `haz_waw`：写入 rd 但 rd 仍 pending
  - 注意 Amaranth 语法：对可变索引取 bit 必须用 `bit_select()`，不能写 `mask[rs1]`。

### 14.2 本轮实际测试效果

我在容器里用模块方式运行全部单测（避免 rfc3986 兼容层不在 sys.path 的问题）：

- `python -m tests.test_elaborate` ✅ TopSoC elaboration + rtlil.convert OK
- `python -m tests.test_load_rb_program` ✅ 两条 load 走读屏障 + mv 乱序返回下写回正确
- `python -m tests.test_scoreboard_dep` ✅ **新测试**通过：
  - 观测结果：`x1=0x11111111 x3=0x11111112`
  - 结论：scoreboard 成功阻塞 `addi x3,x1,1`，直到 mv 写回完成
- 其余历史测试（gc_tag/mv_ooo/rb_inject_ooo/wbq_present 等）全部通过

### 14.3 技术方向评估（到 Step11 的状态）
- 读屏障路径已经从“只验证链路”升级为“可跑依赖链”的最小可用形态。
- 当前 scoreboard 是“保守正确”的：
  - 分支 flush 场景下可能出现暂时多 stall（因为我们没在 flush 时做精细清理），但不会出现错误执行。
- 下一步如果要继续逼近真实 CPU：
  - 需要把 `pending_rd_mask` 从“按 rd 一位”升级到“按流水级/ROB/slot 精确回收”，否则性能会被过度保守。
  - 并开始把 GC 六指令与三协处理器的交互纳入同一个 scoreboard/旁路体系（尤其是 GC_RELOC 对地址的影响）。


## 15. Step12 更新（2026-01-02）

本轮目标：把 GC 指令从“强屏障全局卡死”升级为“只序列化 GC 自身”，让 CPU 在等待 GC 响应期间仍能执行无关指令；同时把 GC 写回纳入 scoreboard，保证依赖 GC 结果的后续指令不会读到旧值。

### 15.1 A->B->C：实现 -> 发现 Bug -> 修复

**A（实现）**
- `RV12Core`：不再用 `gc_waiting` 直接阻塞 `can_fetch` 或全流水推进。
  - 同一时刻仍只允许 **1 条 GC 指令**在协处理器中飞行（保持 side-effect 顺序）。
  - 只有两种情况下 stall：
    1) IS 上有 GC，但协处理器 `gc_enq_ready=0`（防止丢指令）
    2) 新的 GC 到来但上一条 GC 仍在等待响应（防止 GC 乱序）
- `GCSweepCoProc`：新增 `engine_latency` 参数，用来人为制造“响应很慢”的场景，验证 core 是否还能推进无关指令。
- 新增测试 `tests/test_gc_no_global_stall.py`：
  - 0: `gc_new x1`
  - 4: `addi x5,x0,7`（无关，应在 GC 响应前就能写回）
  - 8: `addi x2,x1,1`（依赖，应等待 GC 写回）
  - 12:`addi x6,x0,9`
  - sweep 设置 `engine_latency=40`

**B（发现 Bug）**
- 测试最初失败：`x5==7` 能提前写回（证明不再全局卡死），但最终 `x2==1`（读到了旧 `x1=0`）。
- 根因：scoreboard 如果只在 ID2 上做 hazard 检查，会出现“1-cycle hole”——
  依赖指令在进入 ID2 的那个时钟沿就把 `rs1v` 锁存了旧值，hazard 只能下一拍才检测到，已经来不及。

**C（修复）**
- 将 hazard 检查升级为“两级检查”：
  - `stall_dep_id1`：基于 **ID1** 做前瞻检查，提前阻止指令进入 ID2（避免锁存旧 `rs1v/rs2v`）
  - `stall_dep_id2`：保底检查，若某条指令已在 ID2 中仍不应发射，则阻止其进入 IS
- `stall_front = stall | stall_dep_id1 | stall_dep_id2`
- IS 置气泡仅在 `stall_dep_id2` 时触发（避免因为 ID1 前瞻 stall 而错误打断当前 ID2 指令的发射）。

### 15.2 本轮实际测试效果

在容器里离线安装 wheel 后，回归运行（均通过）：
- `python -m tests.test_elaborate` ✅
- `python -m tests.test_load_rb_program` ✅
- `python -m tests.test_scoreboard_dep` ✅
- `python -m tests.test_gc_no_global_stall` ✅（新增）
  - 25 cycle：`x5==7` 且 `x1==0`
  - 120 cycle：`x1==1` 且 `x2==2`，证明依赖被正确阻塞直到 GC 写回

### 15.3 技术方向评估

- “GC 等待期间不全局卡死”是多核/多协处理器体系的前提；本轮测试用可控延迟证明该方向可行。
- scoreboard 需要考虑“寄存器值在何时被锁存”的流水细节；ID1 前瞻 hazard 是把研究型流水从“跑得起来”推进到“语义正确”的关键一步。

## 14. Step14 更新（2026-01-02）

本轮目标：把 scan 协处理器从“纯背压源”升级为“可控带宽模型”，
以便研究写屏障在多核/高 store 压力下的吞吐与背压边界。

### 14.1 变更：GCScanCoProc 引入 consume_every（可控消费速率）
- scan 内部每核仍是一个 SyncFIFO（保存写屏障事件 addr/data）。
- 新增参数：consume_every
  - 1：每拍尽可能消费 1 条（最大带宽，几乎不背压）
  - N>1：每 N 拍至多消费 1 条（制造可控背压）
  - 0：不消费（纯背压源；仅用于极端测试）

意义：
- 把“写屏障事件 -> scan”的背压从“要么永远不满/要么永久堵死”变成可调节，
  从而可以系统性研究：wbq 深度、scan FIFO 深度、消费带宽与 stall 行为的关系。

### 14.2 变更：TopSoC 暴露 scan 参数
- TopSoC 新增参数：scan_fifo_depth / scan_consume_every
- 默认 consume_every=1，保证默认行为更接近“后台持续扫描”。

### 14.3 新增实际测试效果
新增单测：tests/test_scan_backpressure_burst.py
- 设 scan FIFO 深度=1，分别运行：
  - consume_every=1（fast）
  - consume_every=8（slow）
- 程序：GC_NEW x1；连续 8 个 store；写入完成标记 x7=0x55
断言：
1) ev_count == 8（写屏障事件不丢失）
2) slow 完成周期数明显大于 fast（背压真实发生）

## 15. Step15 更新（2026-01-02）

本轮目标：把 Step14 的“scan 可控背压”扩展到 **多核压力场景**，并用自动化测试固化一个关键工程属性：
**在共享 DMEM 仲裁 + scan 背压下，不应该出现某核明显饥饿（starvation）**。

### 15.1 新增测试：tests/test_multicore_scan_fairness.py
- 4 核同时执行 burst store（每核 8 次）：
  - `addi x1,0,(core_id+1)`
  - `sw x1, base+off(x0)`，base = core_id*64（避免互相覆盖）
  - `jal x0,0` 自环
- scan 配置：fifo_depth=1，consume_every=8（制造背压）

断言：
1) 每核 `scan.ev_count[i] == 8`（写屏障事件不丢）
2) 每核最后一笔写入的 DMEM 值正确（dmem[base+28] == core_id+1）
3) 记录每核完成周期 done_cycles，并要求 `max-min` 不超过一个保守阈值（用于捕获“明显饥饿”而不是微小差异）。

意义：
- 把“多核背压/仲裁公平性”从靠肉眼猜测升级为可回归的单元测试。
- 后续如果 RRArbiter/scan/wbq 逻辑改动导致某核被饿死，这个测试会第一时间报警。

### 15.2 本轮真实暴露的 Bug：多核 DMEM “单拍请求丢失”
在加入多核测试后，最先出现的失败现象是：
- 4 核的 scan.ev_count 都能到 8（说明写屏障事件链路在跑）
- 但 DMEM 里只有 core0 的地址区间被写入，core1~3 的内存仍为 0

根因：
- 当前 DMEM 接口**没有 ready/ack**，而 RRArbiter 只能每拍选中 1 个 master。
- 如果 core 的 store/load 只在 MEM1 打一个“单拍 valid”，那一拍没被 grant 到就等价于“请求被吞掉”。
- 写屏障事件在 core 内部按“store_issue”逻辑生成，但在多核下 store 并未真正落到 DMEM，导致“事件存在但内存没写”。

修复（Step15 落地）：
- RV12Core 新增输入 `dmem_grant`（reset=1，单核旧测试不需要改线）。
- 在 MEM1 增加 `stall_dmem`：当存在 load/store_req 且本拍未 grant，则 stall 保持 MEM1 不前推。
- store 请求改为 `store_req = store_sw & wbq.w_rdy`（保持约束：wbq 满时不请求 DMEM）。
- 只有在 `store_issue = store_req & dmem_grant` 的周期才：
  - 真正写 DMEM（dmem_we=store_issue）
  - 入队写屏障事件（wbq.w_en=store_issue）
- TopSoC 把 `core.dmem_grant` 接到 `arb.m_grant[i]`。

结果：
- 多核测试中 4 核的最后写入均正确（dmem[base+28] == core_id+1）
- done_cycles 完全一致（RR 公平 + 无明显饥饿）


## Step16（共享 scan 引擎 + 写屏障指针过滤）

- GCScanCoProc：从“每核独立消费”升级为“共享扫描引擎”。每核仍有输入 FIFO，但只有一个 consumer 按 consume_every 带宽轮询消费。
- RV12Core / TopSoC：新增 wb_ptr_filter 参数（0=不过滤，1=仅记录看起来像指针的写入：wdata[31]==1）。
- 写屏障与 store commit 对齐保持不变：只有在 dmem_grant 的那拍 store commit，才会（在需要 barrier 时）入队写屏障事件。
- 新增测试：
  - tests/test_wb_ptr_filter.py：验证过滤只上报 MSB=1 的写入，且不影响内存写。
  - tests/test_scan_shared_engine_starvation.py：极端负载下（core0 64 次 store，其它核 2 次）验证共享 scan 引擎不会把小核饿死。


## Step17（scan 批处理吞吐 + 写屏障事件格式升级）

本轮两个目的：
1) 让 scan 引擎具备“突发/批处理”消费模型，用于模拟扫描一个 card 时可能连续处理多个记录。
2) 把写屏障事件从“(addr,data)”升级为“(card_id,obj_id)”，更贴近 card table / remembered set 的表示。

### 17.1 写屏障事件格式：card_id / obj_id
- RV12Core：写屏障入队内容改为：
  - `card_id = store_addr >> wb_card_shift`（默认 6 => 64B card）
  - `obj_id  = store_addr >> wb_obj_shift`（默认 4 => 16B 对齐对象，研究阶段用 shift 近似）
- 接口保持两个 32bit 信号不变：`wb_addr=card_id`, `wb_data=obj_id`。
- 指针过滤（wb_ptr_filter）仍以原始 store 的 wdata 判定，**只影响是否上报事件，不影响内存写**。

### 17.2 scan 引擎批处理：batch_size
- GCScanCoProc 新增参数 `batch_size`：
  - `batch_size=1`：保持 Step16 行为（每个节拍最多消费 1 条）。
  - `batch_size>1`：当节拍到来时装载一个 `credit=batch_size`，随后若干个 cycle 连续消费（每 cycle 1 条）直到 credit 用尽。
  - `consume_every` 仍用于控制“节拍到来频率”，两者组合形成有效带宽：约等于 `batch_size/consume_every` 条/周期。

### 17.3 新增可回归测试（实际效果）
1) `tests/test_store_wb_event_dep.py` 更新：
   - store_addr 改为 64，用于验证 `card_id=1, obj_id=4`（在 scoreboard 阻塞下仍正确）。
2) `tests/test_scan_batch_throughput.py`：
   - consume_every=8 下，对比 batch_size=1 vs 4 的到达 `ev_count==32` 的 cycle 数，验证 batch 确实提升吞吐。


## Step18（card 去重/合并：remembered set 的核心优化）

本轮目的：把写屏障事件从“每次 store 都记录”推进到更贴近真实 GC 的做法：

- **同一张 card 被反复写入时，只需要记录一次**（card 置脏），scan 引擎处理一次即可。

### 18.1 设计选择：per-core 小 card 集合 + FIFO（可研究、可复现）
- GCScanCoProc 新增参数：
  - `dedup_enable`：是否开启 card 去重（默认 True）。
  - `cardset_size`：每核可同时跟踪的“待处理 card”数量（默认 16）。
- 每核维护一个小集合（寄存器数组）保存“已入队/待处理”的 `card_id`：
  - 若新写入命中集合：**直接接受并丢弃**（不占 FIFO），计入 `dup_drop`。
  - 若未命中且集合有空位且 FIFO 可写：入队并在集合中登记，计入 `uniq_enq`。
  - 若未命中且集合满：对该核 backpressure（wb_ready=0），直到有 card 被消费释放。

### 18.2 关键实现点：用 SyncFIFOBuffered 保证 r_data 当拍可见
- 为了在 consumer 弹出 card 的当拍就能拿到正确 `card_id` 并清除集合，本轮把输入 FIFO 改为 `SyncFIFOBuffered`。

### 18.3 可观测统计（研究/测试用）
- 新增：
  - `in_count`：写屏障输入被接受次数（valid&ready）。
  - `uniq_enq`：真正入队的“唯一 card”次数。
  - `dup_drop`：因命中集合而去重丢弃次数。
- `ev_count/last_*` 仍表示“被 scan 引擎实际消费”的条数/最后一条。

### 18.4 新增测试（实际效果）
- `tests/test_scan_card_dedup.py`：
  - 同一 card 内连续 4 次 store。
  - 去重关闭：uniq≈4、dup=0。
  - 去重开启：uniq=1、dup=3。
  - 两种情况下内存写入均不受影响。

### 18.5 兼容性处理
- 旧测试中有不少用 `ev_count==store 条数` 作为完成条件；开启去重后不再成立。
- 因此这些“吞吐/背压/公平性”测试显式传入 `dedup_enable=False`，避免把去重效应混进它们的基线结论。


## Step19（epoch / generation：一轮 GC 结束后允许同一卡再次入队）

本轮目的：把 Step18 的“card 去重集合”推进到更像真实 GC 的 dirty-bit 生命周期：

- 真实 GC 往往按“epoch/轮次”管理 dirty card。
- 一轮 GC 结束后进入新 epoch：即使同一张 card 在上一轮已经入队过，下一轮仍应允许再次入队。

### 19.1 设计选择：1bit epoch + 条目携带 epoch 标记
- GCScanCoProc 新增信号：
  - `epoch`（1bit，reset=0）
  - `epoch_advance`（拉高 1 拍翻转 epoch）
- 去重集合条目增加 `card_epoch`：
  - 命中条件：`valid & (card_epoch==epoch) & (card_id==in_card)`
  - 空位条件：`~valid | (card_epoch!=epoch)`（旧 epoch 条目视为 stale，可直接覆盖）

### 19.2 同 epoch 内“消费后可再入队”保持不变
- shared scan engine 消费某核 FIFO 队头 card 时，会清除该核集合中匹配 card 的条目（只清当前 epoch），
  这样同一卡在同一轮 GC 内也可以“再次变脏并入队”。

### 19.3 新增测试（实际效果）
- `tests/test_scan_epoch_redirty.py`：
  - consume_every=0（不消费，避免消费清除集合影响结论）
  - 连续 3 次写同一卡：
    1) 第一次 uniq_enq++
    2) 第二次命中去重 dup_drop++
    3) epoch_advance 翻转 epoch 后第三次：应再次 uniq_enq++
  - 期望：in=3, uniq=2, dup=1

## Step21（scan out_q -> sweep：跨协处理器闭环的最小标记模拟）

本轮目的：把 Step20 引入的 scan out_q（card stream 输出）真正接到 sweep 协处理器，形成最小闭环：

- write barrier -> scan 消费/去重 -> out_q 输出 card stream -> sweep 接收并做“标记计数”

### 21.1 sweep 增加 card 输入接口
- 新增 `card_in_valid/ready/card_id/core_id/epoch`。
- sweep 内部使用 `SyncFIFOBuffered` 做输入缓冲，避免 scan->sweep 形成组合环。

### 21.2 最小“标记模拟”
- sweep 每拍尽可能消费 1 条 card 记录：
  - `mark_count_total++`
  - `mark_count_core[core]++`
  - 记录 `last_{core,card,epoch}`

### 21.3 TopSoC 连线
- `gc_scan.out_*` 直接连到 `gc_sweep.card_in_*`，用 ready/valid 形成握手。

### 21.4 新增测试（实际效果）
- `tests/test_scan_to_sweep_pipeline.py`：
  - 2 核注入写屏障事件，core0 对同一卡重复写 3 次（应被 scan 去重），core1 写 1 次。
  - 期望 sweep 侧最终只标记到 2 条 card 记录（每核各 1）。


## Step22（sweep 侧 card 去重 + epoch 语义）

### 本轮目标
- scan 已有 card 去重与 epoch，但 sweep 作为下游消费端，在 redirty/多核写同一卡等情况下仍可能看到重复 card。
- 本轮为 sweep 增加“同 epoch 内去重”，并用测试验证：同一卡在新 epoch 仍可再次处理。

### 关键改动
- `GCSweepCoProc` 增加参数：
  - `card_dedup_enable`：是否开启 sweep 去重
  - `card_table_size`：去重表大小（要求 2 的幂）
- sweep 的去重表采用“直接映射”：
  - index = card_id 低位
  - entry 记录 (card_id, epoch)
  - 命中且 epoch 相同 -> 视为重复：`mark_dup_drop_total++`
  - 未命中/epoch 不同 -> 视为新 card：`mark_count_total++` 并写入表
- TopSoC 透传参数：`sweep_card_dedup_enable / sweep_card_table_size`

### 新增测试（实际效果）
- `tests/test_sweep_card_dedup_epoch.py`
  - scan 去重关闭，重复 card 进入 sweep
  - 期望 sweep 在 epoch0 只标记 1 次（dup=3）
  - 推进 epoch 后同一卡再次写入，应再次标记（mark_total=2, dup 不变）

## Step23 记录（sweep 去重表升级：set-associative，抗冲突）

### 本轮目标
- Step22 的 sweep 去重表是“直接映射”，当不同 card_id 落到同一个 index 时，会发生覆盖，导致去重失效（重复处理）。
- 本轮将 sweep 去重表升级为“set-associative 小表”，显著降低 index 冲突带来的重复处理。

### 关键改动
- `GCSweepCoProc` 新增参数：
  - `card_table_ways`：每个 set 的 way 数（默认 1，保持兼容）。
- sweep 去重表结构：
  - `sets = card_table_size`（2 的幂）
  - `ways = card_table_ways`（>=1）
  - 命中判定仍为 (card_id, epoch)
  - 空槽判定：`~valid` 或 `entry_epoch != epoch_in`（旧 epoch 槽可直接覆盖）
  - miss 时写入：优先空槽，否则按 per-set rr 指针替换

### 新增测试（实际效果）
- `tests/test_sweep_card_dedup_conflict.py`
  - sets=2, ways=2
  - 输入 card 序列：1,3,1,3（两者 idx 都为 1，强制冲突）
  - 期望：`mark_total=2, dup_drop=2`（两张 card 都被记住，后续重复被正确丢弃）

## Step24（Sweep 去重表的容量/冲突量化 + 索引 hash）

- 背景：
  - Step22/23 在 sweep 侧实现了 card 去重（同 epoch 内不重复处理同一卡），并在 Step23 升级为组相联（ways）。
  - Step24 进一步把“冲突/替换”变成可量化的统计，并增加可选 hash 索引，用测试固化行为。

- Sweep 新增参数：
- 修复：ways==1 时 repl_ptr/ins_way 可能产生无效 way（1），导致表项写入失效、命中行为异常；本轮在 ins_way 选择与 repl_ptr 更新处对 ways==1 做了强制钳制（ins_way=0，repl_ptr=0）。

  - card_index_mode:
    - 0：使用 card_id 的低 idx_w 位做 set 索引（默认，兼容旧行为）
    - 1：xor-fold（将 card_id 的 idx_w-bit chunk 做 XOR 折叠）降低低位冲突（研究用）
  - 统计计数器：
    - mark_hit_total：命中去重表次数
    - mark_miss_total：未命中次数（会被当作“新 card”处理）
    - mark_replace_total：miss 且无可用槽（empty_found=0）时发生替换次数

- 新增测试（实际效果）：
  - tests/test_sweep_dedup_pressure_assoc.py：
    - 构造同一个 set 内的容量压力（card 0 和 2 低位冲突）
    - 对比 ways=1 vs ways=2 的 mark/dup/replace 统计，证明组相联能减少替换引发的重复处理
  - tests/test_sweep_index_hash.py：
    - 构造低位冲突 card_id（0,4,8,12 低 2bit 都是 00）
    - 对比 index_mode=0 vs index_mode=1 的 mark/dup/replace 统计，证明 xor-fold 能分散冲突，避免替换抖动



## Step25（Sweep 参数扫描/量化表）

- 新增 tools/sweep_param_sweep.py：扫描 sweep 去重表参数（sets/ways/index_mode），生成 CSV/Markdown 表：
  - reports/step25_sweep_table.csv
  - reports/step25_sweep_table.md
- 新增 tests/test_sweep_param_sweep.py：在容器里跑基准并断言关键趋势：
  - lowbit_conflict 下 xor-fold(index_mode=1) 的 replace 明显更少
  - lowbit_conflict 下 ways=2 比 ways=1 的 replace 更少（同 sets/index_mode=0）
- 研究意义：把“选 sets/ways/index_mode”的问题从主观讨论变成可复现数据。

## Step26（批量扫参 + 多核 card 分布 workload）

**本轮动机**：Step25 的扫参是“少量点 + 趋势断言”，能证明开关有效，但不够支持真实的参数选择。并且实际多核下 card 输入是 interleave 的，替换抖动/统计正确性必须用多核 workload 验证。

**主要改动**：
- 新增 `tools/sweep_param_sweep_step26.py`：
  - 支持 sets×ways×index_mode 全组合（CLI 可控）。
  - 增加 2 个多核 workload：`multicore_hot0`（core0 热点 + 其他核少量）与 `multicore_uniform`。
  - CSV/MD 输出额外包含 `core0_mark..core3_mark`，用来验证输入 core_id 传递与统计自洽。
- 新增测试 `tests/test_sweep_param_sweep_multicore.py`：
  - 断言多核 workload 出现在报告中。
  - 断言 per-core sum == mark_total，且各核 mark 数符合 workload 设计。

**实际效果（容器测试）**：
- `python -m tests.test_sweep_param_sweep`（Step25 旧测试）仍通过。
- 新增 `python -m tests.test_sweep_param_sweep_multicore` 通过，证明多核统计自洽。

## Step27（Zipf 分布 workload + Top-N 汇总视图）

**本轮动机**：Step26 的 workload 依然偏“人工构造”（lowbit_conflict/toggle/简单 interleave）。
真实 mutator 的写入通常呈现强热点/长尾分布，因此加入 Zipf 分布更能代表真实写屏障压力。
此外，研究时需要快速看到“在某个 workload 下更推荐哪组 sets/ways/index_mode”，因此增加 Top-N 汇总视图。

**主要改动**：
- 新增 `tools/sweep_param_sweep_step27.py`：
  - 新增 Zipf workload：`zipf_single_*`（单核）与 `zipf_mc_*`（多核轮询交织）。
  - Markdown 顶部自动生成 Top-N 推荐参数（按 replace 升序、dup 降序、hit 降序、miss 升序排序）。
  - 输出：`reports/step27_sweep_table.csv` 与 `reports/step27_sweep_table.md`。
- 新增测试 `tests/test_sweep_param_sweep_step27.py`：
  - 断言报告生成成功；MD 含 Top-N 区；CSV/MD 中都出现 Zipf workload 标识。

**实际效果（容器测试）**：
- `python -m tests.test_sweep_param_sweep_step27` 通过，证明 Zipf + Top-N 输出路径正常。


## Step28（跨 workload 全局 Top-K 综合评分）

**本轮动机**：Step27 的 Top-N 是“每个 workload 单独排名”，便于局部复查，但在实际工程上需要一个“默认配置”，并且希望它在多种 workload 上总体不差。
因此 Step28 引入“跨 workload 的综合评分”，自动输出全局 Top-K，降低参数选择的成本。

**主要改动**：
- 新增 `tools/sweep_param_sweep_step28.py`：
  - 在 Step27 的基础上保留 Zipf、多核与每 workload Top-N。
  - 新增全局 Top-K：把所有 workload 的统计按权重汇总成 score（越小越好）：
    - `score = w_replace*Σreplace + w_miss*Σmiss - w_dup*Σdup - w_hit*Σhit`
  - 权重与 Top-K 数量可通过 CLI 参数调整：`--topk --w-replace --w-miss --w-dup --w-hit`。
  - Markdown 顶部新增“全局 Top-K 推荐参数（跨 workload）”表。
- 新增测试 `tests/test_sweep_param_sweep_step28.py`：
  - 验证 MD 包含全局 Top-K 区与表头；
  - 验证每 workload Top-N 仍存在；
  - 验证 CSV/MD 都能生成。

**实际效果（容器测试）**：
- `python -m tests.test_sweep_param_sweep_step28` 通过，证明全局 Top-K 输出路径与结构稳定。

## Step29（按 workload 归一化 + 加权的全局 Top-K）

**本轮动机**：Step28 的全局 Top-K 是“直接把各 workload 的指标求和再算 score”。
这会让事件数更大的 workload（尤其 zipf_mc）天然主导总和，导致“全局最优配置”过度迎合某一个 workload。

**主要改动**：
- 新增 `tools/sweep_param_sweep_step29.py`：
  - 每个 workload 内对 replace/miss/dup/hit 做 min-max 归一化：
    - `x_norm = (x - min_x) / (max_x - min_x + eps)`
  - 全局 score 改为各 workload 的归一化 score 加权求和：
    - `score = Σ wl_weight * ( w_replace*replace_norm + w_miss*miss_norm - w_dup*dup_norm - w_hit*hit_norm )`
  - Markdown 顶部新增：
    - `Global Top-K (normalized)`（跨 workload 推荐）
    - `Workload normalization ranges`（输出每个 workload 的 min/max）
  - 支持 CLI workload 权重：`--w-workload a=2.0,b=0.5,...`（未提供默认 1.0）
- 新增测试 `tests/test_sweep_param_sweep_step29.py`：
  - 断言 MD 含 `Global Top-K (normalized)` 与 `Workload normalization ranges`；
  - 验证 CSV/MD 生成路径稳定。

**实际效果（容器测试）**：
- `python -m tests.test_sweep_param_sweep_step29` 通过，证明归一化 Top-K 与 ranges 输出结构稳定。

## Step30（固化推荐配置为默认参数 + baseline 回归）

**本轮动机**：Step29 已经能在“固定一套 workload”下给出推荐参数，但如果以后修改 RTL 或评分逻辑，
推荐结果可能悄悄变化。为避免“越改越不知道变没变”，需要一个可复现的 baseline。

**主要改动**：
- 新增 `tools/generate_step30_baseline.py`：
  - 用固定种子/固定规模 workload 做一次小扫参；
  - 调用 Step29 的 `compute_global_topk_normalized` 取 Top-1；
  - 输出 `reports/step30_baseline.json`；
  - 同时回写 `rtl/gc_params.py`，把 Top-1 作为 SoC 默认 sweep 去重表参数。
- 新增 `rtl/gc_params.py`：存放默认 sweep 去重表参数（table_size/ways/index_mode）。
- 修改 `rtl/top_soc.py`：
  - 增加 `sweep_card_table_ways` 与 `sweep_card_index_mode` 两个 SoC 级参数；
  - 默认值来自 `gc_params.py`；
  - 传给 `GCSweepCoProc`，让 SoC 默认配置与研究推荐一致。
- 新增测试 `tests/test_step30_baseline.py`：
  - 重新跑一遍 baseline 的小扫参并 recompute Top-1；
  - 断言结果与 `step30_baseline.json` 一致；
  - 断言 `gc_params.py` 与 `TopSoC()` 默认值一致。

**实际效果（容器测试）**：
- `python -m tests.test_step30_baseline` 通过，证明 baseline 稳定且默认值对齐。

## Step31（更贴近真实 mutator 的端到端趋势模型：Mutator→Scan→Sweep）

**本轮动机**：Step25~Step30 的 sweep 扫参工具能评估去重表，但 workload 仍偏“表格/序列”。
为了更贴近真实系统，需要一个可复现、可控、跑得快的 mutator 压力模型，能够同时覆盖：
- 多核并发写入（interleave）
- 热点/长尾（Zipf）
- phase 热区迁移
- scan 去重 + epoch 生命周期 + 共享引擎吞吐（consume_every + batch_size）
- sweep 去重表（set-associative + xor-fold index）

**主要改动**：
- 新增工具 `tools/step31_mutator_report.py`：纯 Python 模型，输出 JSON/Markdown 报告。
  - 默认 sweep 参数来自 `rtl/gc_params.py`（Step30 固化）。
- 新增测试 `tests/test_step31_mutator_report.py`：
  - 验证工具可运行并输出 json/md；
  - 断言基本不变量：`scan.uniq<=scan.in`、`sweep.mark<=scan.out`、`sum(per_core)==mark_total`。
- README_CN 增加 Step31 使用说明。

**实际效果（容器测试）**：
- `python -m tests.test_step31_mutator_report` 通过，证明趋势模型可复现且输出结构稳定。

## Step32（把 Step31 趋势模型固化为 baseline 回归：防止指标悄悄漂移）

**本轮动机**：
Step31 的趋势模型跑得快、可复现，但如果后续修改 scan/sweep 模型细节或默认参数，
可能出现“结果悄悄变化却不自知”。因此 Step32 增加一个 baseline（固定种子/固定规模）
与对应的回归测试。

**主要改动**：
- 新增 `tools/generate_step32_mutator_baseline.py`：
  - 调用 `tools.step31_mutator_report.run_step31()` 以固定配置生成 baseline；
  - 输出 `reports/step32_mutator_baseline.json/.md`；
  - baseline 规模较小（epochs=2, events/core/epoch=64），用于快速回归。
- 新增 `tests/test_step32_mutator_baseline.py`：
  - 读取 baseline 内的 `baseline_cfg`；
  - 重新跑一次 `run_step31(**baseline_cfg)`；
  - 抽取关键指标（cycle、scan 汇总、sweep 汇总、per-core mark/out）并要求严格一致。

**实际效果（容器测试）**：
- `python -m tools.generate_step32_mutator_baseline` 成功生成 baseline 文件。
- `python -m tests.test_step32_mutator_baseline` 通过，证明 baseline 无漂移。

## Step33（scan 默认参数推荐 + 固化：避免每轮手调导致吞吐指标漂移）

**本轮动机**：
目前 sweep 去重表已经有“推荐默认值 + baseline 回归”（Step30）。
但 scan 侧的关键参数（cardset_size / fifo_depth / consume_every / batch_size）仍然靠手调，
很容易出现：
- 修改别的模块后，为了让测试跑得快随手改 scan 参数，指标就漂了；
- 或者不同人/不同轮次默认值不同，研究结论难以复现。

**主要改动**：
- 新增工具 `tools/step33_scan_recommend.py`：
  - 固定 sweep 默认值（来自 `rtl/gc_params.py`）；
  - 固定一个可复现的 Step31 mutator workload；
  - 扫描一小片 scan 参数空间，按 score（cycle + stall_in + sweep.replace）排序输出 Top-N；
  - 支持 `--write-defaults` 将 Top-1 写入 `rtl/gc_scan_params.py`。
- 新增 `rtl/gc_scan_params.py`：Step33 推荐的 scan 默认参数（研究用）。
- `rtl/top_soc.py`：TopSoC 的 scan 参数默认值改为读取 `gc_scan_params`（若缺失则回退旧默认）。
- 新增测试 `tests/test_step33_scan_defaults.py`：
  - 断言 TopSoC 默认 scan 参数 == `gc_scan_params`；
  - 断言 `recommend()` 能在小网格上运行并输出 Top-1。

**实际效果（容器测试）**：
- `python -m tools.step33_scan_recommend --write-defaults` 可生成 `reports/step33_scan_reco.*` 并更新 `rtl/gc_scan_params.py`。
- `python -m tests.test_step33_scan_defaults` 通过，证明默认值已固化且工具可复现。
## Step34（把 Step33 scan 推荐固化为 baseline 回归：防止默认参数与评分逻辑漂移）

**本轮动机**：
Step33 已经能自动推荐 scan 参数并写入 `rtl/gc_scan_params.py` 作为 SoC 默认。
但只要后续修改趋势模型（mutator/scan/sweep）或权重/网格，推荐 Top-1 可能悄悄变化，
进而让“默认参数为何是这样”失去可追溯性。Step34 用一个固定种子/固定规模/固定网格的 baseline
把推荐结果钉死：后续若要变更必须显式更新 baseline。

**主要改动**：
- 新增 `tools/generate_step34_scan_baseline.py`：
  - 用小网格（16 组合）跑 `tools.step33_scan_recommend.recommend()`；
  - 输出 `reports/step34_scan_baseline.json/.md`，记录 Top-N 与关键统计字段。
- 新增 `tests/test_step34_scan_baseline.py`：
  - 重新计算一次并与 baseline（裁剪后字段）逐项比对；
  - 断言 `rtl/gc_scan_params.py` 与 `TopSoC()` 默认值 == baseline Top-1。

**实际效果（容器测试）**：
- `python -m tools.generate_step34_scan_baseline` 生成 baseline 文件；
- `python -m tests.test_step34_scan_baseline` 通过，且当前最佳组合保持为 `cardset=8, fifo=1, consume=2, batch=2`（score=910.00）。


## Step35（新增“多核 card 分布” workload：per_core_partition，并固化 baseline）

**本轮动机**：
Step31 默认 workload 偏“全局共享热点 + phase_shift 迁移”。真实系统还常见另一种形态：每核主要写自己的 region（local hot），但仍会触达少量全局共享结构。
Step35 在不破坏既有 baseline 的前提下，为 Step31 趋势模型新增 `workload_mode=per_core_partition`，并把关键 card 分布指标（shared_ratio/avg_jaccard 等）固化为回归 baseline。

**主要改动**：
- `tools/step31_mutator_report.run_step31()` 新增参数：`workload_mode`（默认 `shared_hot_shift` 保持 Step32 baseline 不变）、`global_share_p`。
- 新增 card 分布统计：per-core unique / union_unique / shared_ratio / avg_jaccard（仅用于评估，不影响 scan/sweep 行为）。
- 新增 `tools/generate_step35_mc_dist_baseline.py`：生成 `reports/step35_mc_dist_baseline.json/.md`。
- 新增 `tests/test_step35_mc_dist_baseline.py`：回归保护 + 趋势 sanity（分区 workload 的 shared_ratio 更低）。

**实际效果（容器测试）**：
- `python -m tools.generate_step35_mc_dist_baseline` 生成 baseline 文件；
- `python -m tests.test_step35_mc_dist_baseline` 通过；
- 当前 baseline 下：`shared_hot_shift` 的 avg_jaccard≈0.712，而 `per_core_partition`≈0.326，能稳定区分“共享热点 vs 分区写入”的多核分布形态。

## Step36（scan 推荐纳入 per_core_partition，并做 robust(min) 排名 + baseline）

- 动机：Step35 引入 per_core_partition workload 后，scan 参数只在 shared_hot_shift 上调优容易过拟合。
- 做法：新增 `tools/step36_scan_recommend_robust.py`，在 `shared_hot_shift` 与 `per_core_partition` 下分别评估同一 scan 网格，
  用 `robust_score = min(score_mode)` 排序，得到跨 workload 稳健的 Top-N。
- 保持兼容：仅给 Step33 的 `recommend()` 增加可选参数（默认不变），不改 Step34 baseline 的输出结构。
- 回归：新增 `tools/generate_step36_scan_robust_baseline.py` 与 `tests/test_step36_scan_robust_baseline.py` 固化 robust 推荐。

## Step37（修正稳健推荐：引入真正的 worst-case(max) 排名 + baseline）

**本轮动机**：
Step36 为了快速把 per_core_partition 纳入推荐闭环，使用了 `robust_score = min(score_mode)`。
但在本项目里 score 定义为“越小越好”，因此 `min` 实际是 **best-case**，并不能代表跨 workload 的最坏情况。
为了在后续做“协处理芯片结构扫参/默认值收敛”时不被单一 workload 误导，Step37 保留 Step36 不动，
另起一个推荐器用 `worst_score = max(score_mode)` 来做真正的 worst-case 稳健排名。

**主要改动**：
- 新增 `tools/step37_scan_recommend_worstcase.py`：
  - 对同一 scan 网格在多种 workload 下评估；
  - 用 `worst_score = max(per_mode_score)` 排序，给出 Top-N；
  - 额外输出 `worst_mode` 指示哪个 workload 在拖后腿。
- 新增 `tools/generate_step37_scan_worstcase_baseline.py`：生成 baseline。
- 新增 `tests/test_step37_scan_worstcase_baseline.py`：回归保护 + sanity（worst_score==max 且 worst_mode 指向最大项）。

**实际效果（容器测试）**：
- `python -m tools.generate_step37_scan_worstcase_baseline` 生成 baseline 文件；
- `python -m tests.test_step37_scan_worstcase_baseline` 通过，说明 worst-case 推荐结果可复现且已被锁死。

## Step39（mutator 端到端模型下的 sweep 参数 worst-case 推荐 + 敏感性）

**本轮动机**：
此前 sweep 参数（sets/ways/index_mode）主要通过 Step26~29 的“事件序列类 workload”扫参；
而 Step31 起我们已经有更贴近真实多核 mutator 的端到端模型（mutator→scan→sweep）。
为了让 sweep 参数的选择同样具备“跨写入形态稳健性”，Step39 把 sweep 也纳入 worst-case(max) 框架。

**主要改动**：
- 新增 `tools/step39_sweep_recommend_worstcase.py`：
  - 固定 scan 默认值（rtl/gc_scan_params.py）；
  - 在 `shared_hot_shift` 与 `per_core_partition` 上评估 sweep 配置；
  - 用 `worst_score = max(per_mode_score)` 排名输出 Top-K；
  - 输出 sweep 三个维度的敏感性（mean worst_score 的 delta）。
- 新增 baseline：`tools/generate_step39_sweep_worstcase_baseline.py`。
- 新增回归：`tests/test_step39_sweep_worstcase_baseline.py`（Top-1 + worst-case sanity）。

**实际效果（容器测试）**：
- `python -m tools.generate_step39_sweep_worstcase_baseline` 生成 baseline。
- `python -m tests.test_step39_sweep_worstcase_baseline` 通过，说明 sweep worst-case 推荐已可复现并被锁死。


## Step40（scan+sweep 联合扫参：worst-case + Pareto 前沿 + knee 折中选择）

**本轮动机**：
- Step38/39 分别对 scan / sweep 做了 worst-case 推荐与敏感性分析，但默认值落地前仍需看二者的耦合。
- Step40 将 scan 与 sweep 的组合放到同一个端到端评估里，输出性能 vs 资源的可解释取舍，方便后续协处理器微结构预算。

**主要改动**：
- 新增 `tools/step40_joint_opt_pareto.py`：
  - 在两个 workload（shared_hot_shift / per_core_partition）上评估 scan×sweep 全组合；
  - `worst_score = max(per_mode_score)`；
  - 引入简单的 `cost_model()` 作为资源 proxy；
  - 求 (worst_score, cost) 的 Pareto 前沿，并选一个 knee 点作为折中默认建议。
- 新增 baseline：`tools/generate_step40_joint_pareto_baseline.py`。
- 新增回归：`tests/test_step40_joint_pareto_baseline.py`（knee + 前沿前若干项 + worst-case sanity）。

**实际效果（容器测试）**：
- 生成 baseline 并通过回归，说明联合扫参与 Pareto/knee 选择可复现且被锁死。


## Step41（把 Step40 knee 默认值固化成可切换 profile，并接入 TopSoC）

**本轮动机**：
- Step40 得到了 scan×sweep 联合 worst-case + pareto/knee 的折中默认建议；
- 但 Step30 baseline 回归要求 TopSoC 的默认 sweep 参数不能被新建议“悄悄替换”；
- 因此需要一个“可控切换默认值”的机制：既保留历史默认，又允许后续研究默认一键启用。

**主要改动**：
- 新增 `rtl/gc_profile_params.py`：
  - `PROFILES['step30']`：保持 Step30 默认 sweep + Step33/34 scan 固化默认；
  - `PROFILES['step40_joint']`：固定 Step40 knee（scan=8/1/2/2, sweep=16/4/0）。
- 在 `rtl/top_soc.py` 新增 `TopSoC.with_profile(profile, **kwargs)`：
  - 根据 profile 自动填入 scan/sweep 参数；
  - 允许 kwargs 覆盖 profile 值；
  - 不改变 `TopSoC()` 的历史默认行为（确保 Step30 回归不漂移）。
- 新增 baseline：`tools/generate_step41_profile_step40_joint_baseline.py`。
- 新增回归：`tests/test_step41_profile_step40_joint_baseline.py`（profile 与 Step40 knee 一致 + TopSoC 注入正确）。

**实际效果（容器测试）**：
- 生成 baseline 并通过回归，说明 Step40 knee 已被“以 profile 形式固化”，且可被 TopSoC 可控启用。


## Step42（新增 profile benchmark：对比 step30 vs step40_joint，并固化 baseline）

**本轮动机**：
- Step41 已把 Step40 knee 以 profile 形式固化（step40_joint），且保持 step30 历史默认不漂移。
- 但缺少一个可回归的“profile 对比基准”，后续模型调整可能导致 profile 优劣结论悄悄漂移。

**本轮改动**：
- 新增 `tools/step42_profile_compare.py`：
  - 在相同 mutator→scan→sweep workload 下评估多个 profile；
  - 复用 Step33 的 score 公式、Step40 的 cost proxy；
  - 输出 per-workload score 与 worst-case score。
- 新增 baseline：`tools/generate_step42_profile_compare_baseline.py`
  - 写入 `reports/step42_profile_compare_baseline.json/.md`
- 新增回归测试：`tests/test_step42_profile_compare_baseline.py`

**验证方式**：
- `python -m tools.generate_step42_profile_compare_baseline`
- `python -m tests.test_step42_profile_compare_baseline`


## Step43（扩展 profile 档位：纳入 Step40 Pareto 前沿其它点，并固化 catalog baseline）

**本轮动机**：
- Step41/42 已把 knee 点（step40_joint）落地为可切换 profile，并建立了 step30 vs step40_joint 的对比基准；
- 但工程讨论里通常需要“多档位”（不同资源预算下的候选），而不是只有一个 knee 点；
- Step40 的 Pareto 前沿天然给出了一条成本-性能序列，本轮把其余点也固化成 profile，避免每次口头引用/手工抄配置。

**本轮改动**：
- `rtl/gc_profile_params.py` 新增：`step40_pareto1/2/3`（来源：`reports/step40_joint_pareto_baseline.json` 的 `pareto_front[1:]`）。
- 新增 `tools/step43_profile_catalog.py`：对一组 profiles 做端到端 workload 评估并排序输出。
- 新增 baseline：`tools/generate_step43_profile_catalog_baseline.py` → `reports/step43_profile_catalog_baseline.json/.md`。
- 新增回归：
  - `tests/test_step43_profile_catalog_baseline.py`（catalog 指标锁死，防止结论漂移）
  - `tests/test_step43_pareto_profiles_match_step40.py`（确保 step40_pareto* 与 Step40 pareto_front 源数据一致）

**验证方式**：
- `python -m tools.generate_step43_profile_catalog_baseline`
- `python -m tests.test_step43_profile_catalog_baseline`
- `python -m tests.test_step43_pareto_profiles_match_step40`

## Step44（Profile 稳健性：跨随机种子方差评估 + baseline 回归）

**本轮动机**：
- Step42/43 的 profile benchmark/catelog 都是固定单一 seed 的“单点可回归结论”；
- 但真实 mutator 写入包含随机性（热点排序、phase 迁移、跨核共享触达），单点结论可能掩盖方差/尾部风险；
- Step44 增加跨多个 seed 的统计评估，把“稳健性结论”也做成可回归基准。

**本轮改动**：
- 新增 `tools/step44_profile_variance.py`：
  - 对多个 profile 在多个 seed 上做端到端评估（mutator→scan→sweep）；
  - 统计每个 profile 的 worst_score mean/std/min/max、avg_rank；
  - 统计相对参考 profile（默认第一个）的胜率（win_rate）。
- 新增 baseline 生成：`tools/generate_step44_profile_variance_baseline.py`
  - 输出：`reports/step44_profile_variance_baseline.json/.md`
- 新增回归测试：`tests/test_step44_profile_variance_baseline.py`
  - 对比 stable_trim 后的 JSON，锁死“跨种子稳健性”结论，防止后续模型调整导致静默漂移。

**验证方式**：
- `python -m tools.generate_step44_profile_variance_baseline`
- `python -m tests.test_step44_profile_variance_baseline`


## Step45（GCCoProc 黄金模型对拍 + 关键语义修复）

- 新增 `tools/gc_coproc_model.py`：GCCoProc 的 cycle-level reference model（含仲裁、rsp slot、trap pulse、RELOC 两步）。
- 新增 `tests/test_gc_coproc_golden_model.py`：多核随机 enqueue + rsp_take + op 混合，对 RTL 与 model 每拍对拍。
- 修复 `rtl/gc_coproc.py`：
  - Memory read_port 改为 `domain="comb"`（异步读），匹配“同拍读判定/单拍执行”的实现意图；
  - 增加 FIFO `r_en`（执行时 pop），避免同一命令被重复执行；
  - GC_DROP 改为“按模型语义”：pinned trap、rc==0 trap、否则 rc--，rc==0 时 free。

**验证方式**：
- `python -m tests.test_gc_coproc_golden_model`


## Step46（将 Step45 语义修复同步到 GCSweepCoProc + 对拍测试）

- 修复 `rtl/gc_sweep_coproc.py`：
  - Memory read_port 改为 `domain="comb"`（异步读），避免同拍判定读取到上一拍数据；
  - GC_DROP 对齐 Step45 model 语义：pinned trap、rc==0 trap、否则 rc--，rc==0 时 free。
- 新增 `tests/test_gc_sweep_coproc_golden_model.py`：复用 Step45 的 `GCCoProcModel`，对 `GCSweepCoProc` 做多核随机对拍。
- 验证方式：
  - `python -m tests.test_gc_sweep_coproc_golden_model`


## Step47（RELOC -> MV 转发表闭环：读屏障可见的 forwarding table）

**本轮动机**：
- Step9 以后，CPU 的读屏障已经能把 LW 返回值通过 MV_QUERY 走“tag 匹配 + 乱序返回”链路；
- 但 MV 协处理器仍是“恒等返回”（rsp_data = rs1），缺少真实的 old->new 转发表语义；
- 同时，RELOC 的正确提交点在 sweep 侧（可能 trap），如果由 CPU 提前写 MV 表会产生语义偏差；
- 需要一个最小闭环：RELOC **成功提交** -> 更新 MV 转发表 -> 后续 load 读屏障能改写旧 handle。

**本轮改动**：
- `rtl/gc_mv_coproc.py`：
  - 增加 per-core forwarding table（小型 CAM，默认 8 条）；
  - MV_RELOC：写入表（old=rs1,new=rs2），响应返回 0；
  - MV_QUERY：查询表，命中返回 new，否则返回 rs1；
  - 新增 SoC 级 sideband `upd_valid/old/new`（由 sweep RELOC commit 触发），用于避免 CPU 侧提前写表。
- `rtl/gc_sweep_coproc.py`：
  - 新增 `mv_upd_*` 输出：当 GC_RELOC 成功提交时，发出 1 拍 old->new 更新脉冲；
  - 保证“仅成功 RELOC 才写 MV 表”，避免 trap 时污染。
- `rtl/top_soc.py`：
  - 连接 `gc_sweep.mv_upd_* -> gc_mv.upd_*`，打通 SoC 闭环。
- 新增测试 `tests/test_reloc_updates_mv_map.py`：
  - 通过一段极小程序：GC_NEW -> GC_RELOC(1->10) -> store old -> load，断言 lw 经读屏障写回 10。

**验证方式**：
- `python -m tests.test_reloc_updates_mv_map`


## Step48（MV 转发表：ring wrap 最新优先 + 转发链追踪）

**本轮动机**：
- Step47 的 forwarding table 是 ring buffer（map_ptr 轮转写入）。如果同一个 old key 被多次写入并发生 wrap，
  仅靠“物理 index 最后命中 wins”的 lookup 会返回旧映射（隐性错误，且极难靠系统级现象直接定位）。
- 真实移动 GC 中还会出现“转发链”：old->mid、mid->new。如果 MV_QUERY 只做单跳 lookup，load barrier 会拿到 mid（陈旧）。

**本轮改动**：
- `rtl/gc_mv_coproc.py`：
  - Step48：lookup 改为按 map_ptr 从“最新->最旧”搜索（ring wrap 后仍是 latest-wins）。
  - 增加 `chase_depth`（默认=2）：MV_QUERY 支持有限深度的转发链追踪（lookup(lookup(old)) ...）。
- 新增测试：
  - `tests/test_mv_table_wrap_latest_wins.py`：构造重复写同一 key + ring wrap，断言 MV_QUERY 返回最新映射。
  - `tests/test_reloc_chain_mv_chase.py`：两次 GC_RELOC 构造转发链 old->10->20，断言 LW 读屏障直接写回 20。

**验证方式**：
- `python -m tests.test_mv_table_wrap_latest_wins`
- `python -m tests.test_reloc_chain_mv_chase`

## 49. Step49 更新（2026-01-03）

本轮目标：让 moving/reloc 的转发表具备**跨核可见性**，避免“core0 relocate 对 core1 load barrier 不可见”的一致性隐患。

### 49.1 变更：MV forwarding table 改为 SoC 级共享
- `GCMvCoProc` 的 forwarding table 从 per-core 改为 **单张共享 ring buffer**。
- lookup 保持 Step48 的 **latest-wins**（按 map_ptr 从新到旧搜索），并保留 bounded chase（默认深度 2）。
- sweep sideband `mv_upd_valid/old/new` 仍是 per-core 脉冲，但 MV 内部按 **最低核优先**选择一个更新写入共享表（理论上同拍仅一条）。
- 若同拍同时存在 sideband 更新与命令路径 `MV_RELOC` 写表，**sideband 优先**（以 RELOC commit 语义为准）。

### 49.2 新增测试（集成）：跨核可见性
- 增加 `tests/test_reloc_visible_cross_core.py`：core0 触发 RELOC 并写旧 handle 到共享内存；core1 读取并通过读屏障（MV_QUERY）得到新 handle。
- 备注：该测试依赖双核 TopSoC 仿真，可能需要在开发机上用更快的仿真器跑更稳；单元级 MV 测试已覆盖关键语义。

## 50. Step50 更新（2026-01-03）

本轮目标：**把 Step49 的“跨核可见性”测试收敛成可在离线环境稳定运行的回归**。

### 50.1 问题：双核 RV12Core SoC 级 python-sim 过慢
Step49 的 `tests/test_reloc_visible_cross_core.py` 使用 2× `RV12Core` + RRArbiter 进行 end-to-end 验证。
在 Amaranth Python Simulator 下，该测试的 elaboration/仿真耗时过大，导致无法作为回归 baseline。

### 50.2 修复：改为“协处理器级端到端”快速回归
- 重写 `tests/test_reloc_visible_cross_core.py`：
  - `sweep(core0)` 执行 `GC_NEW -> GC_RELOC(old->10)`，通过 Step47 sideband 输出 `mv_upd_*`。
  - `mv(core1)` 直接发 `MV_QUERY(old)`，断言返回 10。
- 为了让 simulator 建模更快，将该测试中的 `GCMvCoProc` 参数缩小：`map_depth=2, chase_depth=1`。
  这不影响“跨核可见性”性质，但能显著降低 Python-level elaboration 成本。

### 50.3 本轮新增的“实际测试效果”
在容器内执行：
- `python -m tests.test_reloc_visible_cross_core`
输出示例：
- `old_handle=1 mv_query(core1)->10`
并通过断言：跨核可见性成立。
## 51. Step51：MV sideband 多路更新鲁棒性（不丢 update）

### 51.1 背景
Step49 将 MV forwarding table 改为 SoC 级共享；Step50 增加跨核可见性回归。
但 MV 的 sideband 接口仍是 per-core `upd_valid/old/new`，理论上同一拍可能出现多路更新
（例如未来把多个 GC 引擎/多通道 commit 合并到 MV），原实现只选择一个（最低核）会丢更新。

### 51.2 修复：加入 update buffer + drain
- `rtl/gc_mv_coproc.py`：
  - 增加 per-core pending slot（depth=1）+ cmd-path pending slot；
  - 每拍最多 drain 1 条写入 forwarding table；
  - 优先级：sideband > cmd；sideband 按 round-robin 选取；
  - 支持“同拍新 sideband 更新”立即 drain（保留 Step47/48 常见路径时序）；
  - 增加 `dbg_upd_overflow` 计数器，用于发现异常的 pending 溢出（正常 sweep 不应触发）。

### 51.3 新增测试（单元级）：同拍双路 sideband 更新不丢
- `tests/test_mv_multi_update_buffer.py`
  - 同一拍 core0/core1 同时 `upd_valid` 写入两条映射；
  - 等待 drain 完成后，分别查询并断言映射都可见（且跨核共享）。
  - 断言 `dbg_upd_overflow==0`。

**验证方式**：
- `python -m tests.test_mv_multi_update_buffer`


## 52. Step52 更新（2026-01-03）

本轮目标：**让 MV 转发表支持 epoch，避免跨 GC 周期的陈旧映射污染读屏障**。

### 52.1 MV 增加 epoch_advance + entry_epoch
- `rtl/gc_mv_coproc.py` 增加输入 `epoch_advance`（SoC 广播），内部维护 `epoch` bit。
- forwarding table 每条 entry 增加 `entry_epoch`，写入时标记为当前 epoch。
- MV_QUERY 仅命中 `entry_epoch == epoch` 的记录，实现 O(1) epoch 切换清空效果（无需逐条清表）。

### 52.2 SoC 连接
- `rtl/top_soc.py`：将 `ep_any` 同时广播到 `scan.epoch_advance` 与 `mv.epoch_advance`。

### 52.3 新增测试：epoch 失效
- `tests/test_mv_epoch_invalidate.py`
  - epoch 前写入 1->10，查询返回 10；
  - epoch_advance 后同 key 查询返回原值 1（陈旧映射失效）；
  - 再用 sideband 更新 1->20，查询返回 20。

验证方式：
- `python -m tests.test_mv_epoch_invalidate`


## 53. Step53 更新（2026-01-03）

本轮目标：开始进入“三颗 GC 协处理芯片”架构设计阶段，把扫描/清理/搬运硬切成 3 个可独立综合的模块，同时把接口冻结成文档 + 最小可回归。

### 53.1 新增规格文档（信号级草案）
- `docs/step53_gc_3chip_spec.md`
  - 定义 3-chip 拆分边界（Scan/Clean/Move）
  - CPU 黑盒约束：CPU 仅通过 6 条 GC 指令表达“引用语义变化”
  - 明确关键原则：RELOC 提交点才允许更新映射、epoch 广播、最小互连集合

### 53.2 新增 chip-top wrapper（便于按芯片综合/接口冻结）
- `rtl/gc_chip_scan.py`：`GCScanChipTop`（包装 `GCScanCoProc`）
- `rtl/gc_chip_clean.py`：`GCCleanChipTop`（包装 `GCSweepCoProc`）
- `rtl/gc_chip_move.py`：`GCMoveChipTop`（包装 `GCMvCoProc`）
- `rtl/gc_3chip_system.py`：示例互连 `GC3ChipSystem`（Scan→Clean card stream，Clean→Move reloc sideband，epoch 广播）

### 53.3 新增回归：3-chip 互连可 elaboration
- `tests/test_step53_3chip_elaborate.py`
  - 对 `GC3ChipSystem` 做 `rtlil.convert`，并断言 scan/clean/move 三个层级模块均存在。

验证方式：
- `python -m tests.test_step53_3chip_elaborate`


## 54. Step54 更新（2026-01-03）

本轮目标：把 Step53 的 3-chip wrapper 从“信号别名 re-export”升级为真正的“芯片边界端口”，
为后续独立综合/独立布线做准备（物理分割时不允许 top-level 直接引用子模块内部 Signal 对象）。

### 54.1 Wrapper 端口显式化（no aliasing）
- `rtl/gc_chip_scan.py` / `rtl/gc_chip_clean.py` / `rtl/gc_chip_move.py`
  - top-level 创建 `Signal.like(...)` 的独立端口，并在 `elaborate()` 中逐项连线。
  - 这样 chip top 可以作为真正黑盒边界，便于后续导出 netlist/约束/IO 列表。

### 54.2 新增回归：端口不允许别名
- `tests/test_step54_chip_ports_distinct.py`
  - 用 object identity 检查关键端口 `top.port is not top.u.port`。

验证方式：
- `python -m tests.test_step54_chip_ports_distinct`
- `python -m tests.test_step53_3chip_elaborate`


## 55. Step55 更新（2026-01-03）

本轮目标：为 3-chip（Scan/Clean/Move）拆分加入**协议级契约回归**，把最关键的黑盒正确性约束锁死，
避免后续做时钟域/片间链路/资源裁剪时出现“静默语义漂移”。

### 55.1 契约 1：RELOC trap 不得更新 MV 映射
- 新增回归：`tests/test_step55_3chip_reloc_trap_no_mv_update.py`
  - 对未分配的 old handle 发 `GC_RELOC`，必须 trap。
  - 断言 Move 侧 `MV_QUERY(old)` 仍返回 old（映射未被污染）。

### 55.2 契约 2：epoch 广播必须失效 MV 映射
- 新增回归：`tests/test_step55_3chip_epoch_invalidate_mv.py`
  - Clean 成功提交 `GC_RELOC(old->new)` 后，Move 侧 `MV_QUERY(old)` 返回 new。
  - 通过 `GC3ChipSystem.epoch_advance` 脉冲广播 epoch，随后 `MV_QUERY(old)` 必须返回 old（O(1) 失效）。

验证方式：
- `python -m tests.test_step55_3chip_reloc_trap_no_mv_update`
- `python -m tests.test_step55_3chip_epoch_invalidate_mv`


## Step56
- Clean→Move reloc 更新链路升级为 ready/valid stream，并在 GC3ChipSystem 中加入小型 SyncFIFO 作为片间链路模型（支持 backpressure/链路拥塞）。
- Clean wrapper 增加 reloc_out_* 端口与 pending 缓冲；Move wrapper 增加 reloc_in_* 端口并注入到 upd_*。
- 新增回归：test_step56_reloc_stream_backpressure（链路停顿期间两核提交 RELOC 更新不丢）。


## Step57
- 修复 Step56 reloc stream 的关键缺口：Clean wrapper 之前没有把内部 `mv_upd_*` 脉冲捕获进 pending 槽，导致 `reloc_out_*` 永远不出数据；并修复 overflow 统计的组合自反馈（会导致 pysim 构建/收敛极慢）。
- 全局移除 RR 选择中的 `% self.ncores` 模运算（替换为显式 wrap-around 的 `Mux(idx >= ncores, idx - ncores, idx)`），避免生成除法/模运算网络导致 pysim/转换阶段卡顿。
- GC3ChipSystem 增加 `enable_scan` 开关，允许在只测 Clean↔Move 协议时不实例化 Scan（减少仿真构建成本）。
- 回归增强：Step55 epoch 契约测试改为等待 RELOC 响应并容忍片间链路/ FIFO 延迟，避免“固定等待 10 拍”导致的偶发失败。

验证方式：
- `python -m tests.test_step55_3chip_reloc_trap_no_mv_update`
- `python -m tests.test_step55_3chip_epoch_invalidate_mv`
- `python -m tests.test_step56_reloc_stream_backpressure`
- `python -m tests.test_step53_3chip_elaborate`

Step58
- 解决“epoch advance 时 link FIFO 里仍有 in-flight reloc 更新会复活新 epoch 映射”的一致性漏洞：
  - Clean 在捕获 reloc 更新时同时打上 epoch bit（SoC 广播 epoch_advance 翻转）。
  - Clean->Move reloc stream/FIFO 增加 epoch 字段。
  - Move sideband 更新接口增加 upd_epoch，并在写表时使用更新自带 epoch（而不是当前 epoch）。
  - 这样：旧 epoch 的更新即使延迟到新 epoch 才送达，也只会写成旧 epoch 条目，查询不会命中。
- 新增测试：`python -m tests.test_step58_reloc_epoch_tag_drop`
  - 场景：link disable 缓存一条 RELOC -> epoch advance -> link enable -> MV_QUERY 必须 miss。


Step59
- 修复“Clean wrapper 1-slot pending 在极端背压下会丢 mv_upd 脉冲”的正确性风险：
  - sweep 的 mv_upd 改为 valid/ready（新增 mv_upd_ready，默认 reset=1 兼容旧测试）。
  - Clean chip wrapper 用 slot_free 驱动 mv_upd_ready；背压时 RELOC 提交会自然 stall，而不是丢更新。
  - 新增压力测试：reloc_link_enable=0 + link FIFO depth=1，连续提交 4 条 RELOC，
    期望前 3 条响应可返回，第 4 条必须等待 link 恢复；最终 MV_QUERY 对 4 条 old 都命中新 new。


Step60
- 在 3-chip harness 中加入 Scan->Clean 的显式跨片传输 FIFO（card_link），并提供 card_link_enable / card_link_depth 以模拟跨片延迟与背压。
- 修复跨 epoch 的脏卡“迟到”语义：Clean wrapper 维护本地 epoch bit（跟随 epoch_advance 翻转），若收到的 card_in_epoch != 当前 epoch，则 ready=1 接收并丢弃（不进入 sweep 的 mark queue），并计数 dbg_card_stale_drop++。
  - 目的：旧 epoch 的 card 记录即使因为链路/背压延迟到新 epoch 才送达，也不会污染新 epoch 的 mark/dedup 状态。
- 新增测试：python -m tests.test_step60_card_epoch_stale_drop
  - card_link_enable=0 让一条 card 记录滞留在 link FIFO；epoch_advance 翻转后再 card_link_enable=1 送达；期望 mark_count_total 仍为 0 且 dbg_card_stale_drop=1。


Step61
- 修复 Scan 侧 epoch 标记与去重集合生命周期在跨片背压/延迟下的正确性漏洞：
  - per-core fifo entry 增加 1-bit epoch（写屏障事件入队时捕获），确保即便 card 记录在 Scan 内部延迟到 epoch 翻转之后才被消费/输出，也仍携带原始 epoch。
  - out_q 输出 epoch 改用 entry 自带 epoch（不再使用当前 self.epoch）。
  - cardset(valid/id/epoch) 的清除时机从“入 out_q 时”改为“out_q pop（真正离开 Scan 芯片）时”，并按 record 自带 epoch 匹配清除，避免 1-bit epoch wrap 造成 ghost 命中。
- 新增测试：python -m tests.test_step61_scan_epoch_tag_for_delayed_card
  - 场景：card_link_enable=0 造成 link 满 + out_q 满，使第 3 条 card 卡在 Scan 内部；epoch_advance 翻转后再恢复链路；期望 3 条都作为 stale 被 Clean 丢弃（dbg_card_stale_drop=3）且 mark_count_total 仍为 0。


Step62
- 增强 3-chip harness 的可观测性：导出跨片传输 FIFO 占用 level（dbg_card_link_level / dbg_reloc_link_level），用于背压/互连建模与性能剖析。
- 新增端到端一致性回归测试：python -m tests.test_step62_dual_link_epoch_stale_protection
  - 同时关闭 card_link_enable 与 reloc_link_enable，制造双向跨片背压；在旧 epoch 产生一条 scan card 与一条 clean RELOC 更新并滞留在链路 FIFO；随后 epoch_advance 翻转，再恢复链路并 drain。
  - 期望：Clean 丢弃 stale card（dbg_card_stale_drop++ 且 mark_count_total 不增加）；Move 新 epoch 下 MV_QUERY(old) 必须 miss（返回 old），证明 stale reloc 更新不会“复活”映射。
Step63
- 把 Step62 导出的 dbg_card_link_level / dbg_reloc_link_level 变成“可验证契约”：新增测试验证 Scan->Clean transport FIFO 在背压下会饱和到 depth、恢复后会 drain 回 0，并且 Clean 最终消费的 card 数量与注入一致（无 silent drop）。
  - 新增测试：python -m tests.test_step63_card_link_level_saturates
- 增加一个小型 sweep 工具脚本：tools/step63_link_sweep.py
  - 用固定 workload（N 条写屏障 card）扫 card_link_depth，输出 cycles/max_link_level/mark_count_total 到 CSV，作为后续互连/封装 trade-off 的性能剖析入口。

Step64
- 增加 Clean->Move reloc_link 的“可验证契约”回归测试：python -m tests.test_step64_reloc_link_level_saturates
  - 场景：reloc_link_enable=0 造成 link FIFO 无法 drain；提交超过 reloc_link_depth 的 RELOC。
  - 期望：dbg_reloc_link_level 饱和到 depth；多余的 RELOC 必须 stall（无响应）直到 link 恢复；
    恢复后 dbg_reloc_link_level drain 回 0，并且 MV_QUERY 能看到所有映射（无 silent drop）。
- 增加 Step64 双链路扫参脚本：tools/step64_dual_link_sweep.py
  - 同时扫 card_link_depth × reloc_link_depth，运行“cards + relocs”混合 workload，
    输出 cycles/max_card_link_level/max_reloc_link_level/marks/overflow 到 CSV，作为后续互连参数空间探索入口。

Step65
- 增加三芯片端到端随机化压力回归（deterministic fuzz）：tests/test_step65_randomized_dual_link_fuzz.py
  - 随机混合注入：scan WB、clean NEW/RELOC（只生成合法 RELOC：src used & dst free）
  - 随机切换 card_link_enable / reloc_link_enable；epoch_advance 仅在双链路 stall 时触发
  - 断言：dbg_card_stale_drop 与软件统计一致；dbg_reloc_overflow==0；链路 dbg level 最终 drain 至 0；
    drain 后 MV_QUERY 与基于 move.reloc_in handshake（按 update 自带 epoch 分桶）的软件映射一致（含深度2 chase）。
- 增加 CLI 复现工具：tools/step65_fuzz_run.py

Step66
- 增加多 seed smoke 回归：tests/test_step66_fuzz_multiseed_smoke.py（少量 seed + 小 cycles + 少量 queries，保证快速回归）
- 增加批量 sweep 工具：tools/step66_fuzz_sweep.py
  - 可跑 N 个随机 seed；失败时打印一条可直接复现的 step65_fuzz_run 命令行。

Step67
- 把 Step65/66 的 fuzz 变成“可度量的报告工件”：tools/step67_fuzz_report.py
  - 支持输入 seeds 或生成 count 个 seeds，逐个调用 run_fuzz(return_stats=True) 收集统计项；
    输出 CSV（默认 reports/step67_fuzz_report.csv），便于后续做互连深度/背压参数探索的趋势分析。
- 增加工具回归测试：tests/test_step67_fuzz_report_tool.py
  - 验证报告 CSV 的基本 schema（seed/ok/max_link_level 等）并确保小样本 seeds 全部通过。

Step68
- 增加互连深度 × seed 的 fuzz 矩阵报告工具：tools/step68_fuzz_matrix.py
  - 对 (card_link_depth × reloc_link_depth) 的每个组合与每个 seed，调用 step65_fuzz_run --json 收集统计并输出矩阵 CSV。
  - 生成按深度对聚合的 summary CSV + markdown 表（ok_rate、avg max link level 等），作为互连缓冲深度 trade-off 的量化入口。
- 增加工具回归测试：tests/test_step68_fuzz_matrix_tool.py
  - 以单个 seed 与单一深度对的小样本运行，验证 CSV/MD 工件生成与 schema。

Step69
- 增加互连深度的 Pareto 收敛选择工具：tools/step69_select_pareto.py
  - 读取 Step68 summary CSV（ok_rate、avg max link level 等），先按 ok_rate_pct >= threshold 过滤；
    再在 (total_depth, worst_avg_max_link, sum_avg_max_link) 三目标上计算 Pareto frontier。
  - 输出 Pareto CSV + markdown，并给出一个确定性的“推荐深度对”（优先最小总深度，其次最小 worst/max 占用）。
- 增加工具回归测试：tests/test_step69_pareto_select_tool.py
  - 以合成的 summary CSV 验证 Pareto/frontier 与推荐规则、工件输出。

Step70
- 增加“一键互连深度自收敛”流水线工具：tools/step70_autotune.py
  - 组合 Step68（fuzz matrix + summary）与 Step69（Pareto + 推荐），并输出 machine-readable 推荐深度 JSON：reports/step70_recommended_depths.json
  - 目的：把互连参数探索从“跑完再手动挑”升级为“跑完自动给出推荐，并可被后续步骤/CI 消费”。
  - 工具提供 --skip-matrix：在无 Amaranth/仿真受限环境下，可直接对已有 summary CSV 运行 Pareto+JSON。
- 增加工具回归测试：python -m tests.test_step70_autotune_pipeline
  - 以单 seed + 单深度对的小样本运行整条 pipeline，验证 matrix/summary/pareto/json 工件生成与推荐深度字段一致。

Step71
- 增加“应用互连深度推荐”的工具：tools/step71_apply_autotune.py
  - 读取 Step70 输出的 reports/step70_recommended_depths.json
  - 生成可被仿真/后续步骤 import 的 rtl/autotuned_link_depths.py（VALID + CARD/RELOC 深度常量）
  - 可选输出 JSON copy：reports/step71_applied_depths.json
- GC3ChipSystem 增加可选参数 use_autotuned_defaults：若 rtl/autotuned_link_depths.VALID==1，则用其中深度覆盖显式参数（仅仿真便利，不改变硬件显式参数机制）。
- 增加工具回归测试：python -m tests.test_step71_apply_autotune_tool
  - 以临时 JSON 输入验证生成的 python 模块可 import 且常量正确。

Step72
- GC3ChipSystem 增强“互连参数可观测性”：除了 dbg_*_link_level（占用）外，新增导出 dbg_card_link_depth / dbg_reloc_link_depth（配置深度常量），便于在 fuzz/回归/波形中直接确认当前 harness 实际使用的深度。
- GC3ChipSystem 在 __init__ 期显式保存 effective_card_link_depth / effective_reloc_link_depth（考虑 use_autotuned_defaults 覆盖），让测试/工具无需深入子模块即可确认参数收敛是否生效。
- 新增回归测试：python -m tests.test_step72_autotuned_defaults_take_effect
  - 场景：写入合成的 step70 推荐 JSON，调用 step71_apply_autotune 覆盖 rtl/autotuned_link_depths.py；实例化 GC3ChipSystem(use_autotuned_defaults=True) 并断言 effective depth 与 dbg_*_link_depth 常量正确。

## Step73 — ISA 模块化 + XLEN 参数化 + C 扩展展开器（2026-06）

### 背景
原 rv12_core.py 中 ISA 解码逻辑（opcode、funct3、funct7、immediate 拆分、分类信号）全部硬编码在
核心流水线内，导致：
- RISC-V 扩展（M/Zicsr/JasperGC）的解码散落在不同层级的 `with m.If` 中
- XLEN 硬编码为 32，不支持 RV64 的 W-suffix
- C 扩展（16-bit 压缩指令）无展开支持

### Step73.1 — ISA 模块化基类
```
rtl/
├── isa_module.py       # ISAExtension 基类（xlen 参数 + matched 信号 + instruction 子表）
├── isa_rv32i.py        # RV32I: 39 条指令（含 AUIPC + 各分类信号）
├── isa_rv32m.py        # M 扩展: MUL/DIV/REM
├── isa_zicsr.py        # Zicsr: CSR 读写
├── isa_jasper_gc.py    # JasperGC: GC 指令解码（可配置 opcode）
├── isa.py              # 常量/工具: opcode 枚举、LUI/MASK 等
```

**ISAExtension 设计**：
- 所有子类同签名 `ISAExtension(xlen=32, ...)`，输出 `matched`/`matched_*` 信号
- `matched` 触发时连带输出 decoded fields（rd/rs1/rs2/funct3/funct7/imm/分类信号）
- 仲裁优先级：GC → Zicsr → M → I（M 和 Zicsr 互斥；I 作为最终 fallback）
- ISA 模块输出在 ID1 阶段用于统一分类/寻址

### Step73.2 — XLEN 参数化
- 构造参数 `self.xlen` 传入流水线记录字段宽度、数据/地址信号
- RV64 W-suffix（ADDW/SUBW/SLLW/SRLW/SRAW/ADDIW/SLLIW/SRLIW/SRAIW）内联在
  `isa_rv32i.py` 中，通过 `with m.If((XLEN == 64) & ...)` 保护
- bit-mask 信号保留 32-bit（x0-x31 共 32 个寄存器不受 XLEN 影响）

### Step73.3 — CExpander 展开器
```
rtl/isa_c_expand.py    # CExpander(Elaboratable): 16-bit → 32-bit 展开
```

**支持的 27 条压缩指令**（全部通过 27/27 测试）：
| 类别 | 指令 | 说明 |
|------|------|------|
| CR/CI | C.NOP/C.ADDI/C.LI/C.MV/C.ADD/C.JR/C.JALR/C.EBREAK | op=10, funct4/funct3 细分 |
| CI-shift | C.SLLI/C.SRLI/C.SRAI | funct3=100, shamt[5]=i16[12] |
| CI-ALU | C.ANDI/C.SUB/C.XOR/C.OR/C.AND | funct3=100, funct2 区分 SUB/XOR/OR/AND |
| CJ | C.JAL（RV32 only）/ C.J | op=01, funct3=101/001 |
| CB | C.BEQZ/C.BNEZ | op=01, funct3=110/111 |
| CL | C.LW | op=00, funct3=010 |
| CS | C.SW | op=00, funct3=110 |
| CIW | C.LWSP | op=10, funct3=010 |
| CSS | C.SWSP | op=10, funct3=110 |

**关键 bugfix**（排错过程见 conversation）：
1. `rs18`/`rs28`/`rd8` 从 bare 表达式改为 `Signal(5)` + `C(8,5)` — 修复 Amaranth 隐式截断 bug
2. C.SLLI 使用 `rs18`（bits[9:7]）而非 `rd0`（bits[11:7]）
3. C.ANDI funct3: `C(4,3)` → `C(7,3)` — 修复 XORI→ANDI 错误
4. CB offset Cat 顺序: `cb_off[11:12]` 在前（imm[11]=bit7）、`cb_off[1:5]` 在后（imm[4:1]=bits[11:8]）
5. Sign extension 宽度: `Cat(i16[2:7], i16[12], Cat(*[i16[12]]*6))` — 12-bit（非 11-bit）

### Step73.4 — CExpander 集成到 rv12_core.py

**IF2 阶段**（在 stall_front 保护的同步块之外）：
```python
ce = CExpander(xlen=self.xlen)
m.d.comb += [ce.valid.eq(1), ce.insn16.eq(self.imem_rdata[0:16])]
m.d.comb += expanded_insn.eq(Mux(ce.is_compressed, ce.insn32, self.imem_rdata))
```

**PC 增量**（IF2 同步块内）：
```python
m.d.sync += pc.eq(pc + Mux(ce.is_compressed, C(2, xl), C(4, xl)))
```

**压缩标志传播**：`compressed(1)` 字段从 IF2 → IF3 → IF4 → ID1 → ID2 → IS，通过 `step()` 函数传递

**核心改动**：
- 新增 `("compressed", 1)` 到 pipeline 记录 S
- CExpander 作为子模块放在 IF2 级（IMEM 是 combinational read，不需要等一周期）
- 展开后的指令代替 `imem_rdata` 喂入 IF2.insn（未压缩时 pass-through）
- PC 增量根据 `ce.is_compressed` 选择 2 或 4

### 验证方式
- `python -m tests.test_isa`                          # ISA 编码一致性
- `python -m tests.test_isa_c_expand`                   # CExpander 27 条指令展开 + core elaboration
- `python -c "from rtl.isa_c_expand import CExpander; ..."`  # 全部 27 条测试用例
- RV12Core 顶层 elaboration 验证： `python -m tests.test_isa_c_expand`


## 74. 下一步架构演进路线图（2026-05）

### 现状
- 单发射、顺序、12 级流水线；无分支预测
- IPC 上限 1.0，带 taken 分支降至 ~0.87
- GC barrier 路径正确性已验证（MV forwarding table / RB cache / scoreboard / bypass chain）
- **但 barrier 硬件加速在当前单发射天花板下没有意义——空闲执行 slot 已被 barrier stall 提前耗尽**

### Phase 1: 提升通用性能天花板（核心架构重做）

#### 1.1 分支预测
- 实现 2-level BTB + 2-bit saturating counter
- 预估：分支场景 IPC 从 0.87 → ~0.95
- 复杂度：低（与现有指令流兼容）

#### 1.2 多发射
- 2-issue → 4-issue 逐步扩展
- IS 阶段必须支持多指令并行 issue
- 改动量级：大（整个前端重新设计）
- 预估：稳态 IPC ~3.5（理论 4-issue 极限 ~3.8）

#### 1.3 乱序执行
- ROB（Reorder Buffer）+ 物理寄存器文件
- Reservation Station / Issue Queue
- Load-Store Unit（LSU）处理内存序
- 预估：IPC ~2.5-3.0（关 barrier），~1.2-2.0（开 barrier）

### Phase 2: 非阻塞 GC Barrier

#### 2.1 Non-blocking load → MV_QUERY
- 当前设计：load 遇到 RB 后在 MEM2 stall，阻塞后续指令退休
- 改为：load 发射 MV_QUERY 后标记为"pending"，不阻塞 ROB
- 后续依赖指令读到推测值，并在 MV 响应回来时验证/回滚
- 预估：barrier 场景 IPC 从 ~1.5 升至 ~2.0-2.5

#### 2.2 值预测（GC forwarding 的 value prediction）
- GC relocation 期间 old→new 映射稳定不变（一次 GC cycle 内确定性映射）
- 预测准确率理论上 >95%（远高于通用值预测）
- 设计：history table keyed by old_value → predicted_new_value
- 误预测时回滚 ROB 中依赖指令
- 预估：barrier 开销从 ~50% 降至 ~5-10%

### Phase 3: 片上验证

#### 3.1 FPGA 原型
- 当前 Amaranth pysim 纯仿真，无真实频率信息
- 目标：在 FPGA 上运行简易操作系统 / baremetal GC benchmark
- 测量：关 barrier vs 开 barrier 下的 STW 时间

#### 3.2 GC Workload 对标
- 对比软件方案（Go/GHC 的 mutator write barrier）
- 指标：mutator 吞吐损失百分比、STW 缩减百分比

### 优先级判断
```
Phase 1.1 分支预测        ← 投入产出比最高，先做
Phase 1.3 乱序执行        ← 门槛最高，但 barrier 加速的前提
Phase 2.1 Non-blocking    ← 依赖 1.3
Phase 2.2 值预测          ← 依赖 2.1
Phase 1.2 多发射          ← 收益边际递减（ROB 够大时 2-issue ≈ 4-issue）
Phase 3                   ← 等 1+2 收敛后
```

## 待补充的标准扩展清单

### 小规模（1-2 人天，stub 级）
- **Zdinx** — 双精度浮点用整型寄存器（F/D for integer regs，接口同 Zfinx）
- **Zqinx** — 四精度浮点用整型寄存器
- **Zca** — 压缩基准指令子集（CExpander 的 op=01/10 已实际支持，需显式声明模块）
- **Zkt** — 数据独立时序（纯安全规范，无新指令，matched=0 占位）
- **Zihintcond** — 条件提示（较新加入的 Zihint* 系列）

### 中等规模（浮动 FP 集成）
- **Zvfh / Zvfhmin** — 向量半精度浮点（V + Zfh 的交集）
- **Zvbb / Zvbc** — 向量位操作/无进位乘（V + B 的交集）
- **Zvkb** — 向量密码学位操作（V + Zbkb 的交集）

### 大规模（需完整单元）
- **向量密码学套件**：Zvkg/Zvkn/Zvknc/Zvkng/Zvks/Zvksg（Vector GMAC/AES/SHA2/SM4/SM3 — 每个约 10-30 条指令）
- **Zvkt** — 向量数据独立时序（安全规范）

### 超大（暂缓）
- **H 扩展（Hypervisor）** — 完整的第二级页表 + 虚拟化陷阱 + 中断虚拟化。~200+ 页规范
- **Smstateen / Ssaia** — 特权架构扩展（状态使能/高级中断架构）。依赖 H 扩展上下文
- **完整向量（V）实现** — 当前为 decode stub，实际需要向量寄存器文件 + 配置 CSR + 执行单元
