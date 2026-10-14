# -*- coding: utf-8 -*-
"""从 Amaranth RTL 生成 RTLIL +（可选）Verilog。

本脚本的目标：
1) 使用 amaranth.back.rtlil 把 TopSoC 转成 `TopSoC.il`
2) 调用 yosys 将 `TopSoC.il` 转为 `TopSoC.v`（便于后续用 Verilator/iverilog 等工具）

注意：
- 本脚本依赖 `amaranth` + `yosys`。
- 由于不同平台安装方式不同，这里不自动下载依赖。

运行：
    python sim/build_verilog.py

输出：
    sim/TopSoC.il
    sim/TopSoC.v
"""

import subprocess
from pathlib import Path

from amaranth.back import rtlil

from rtl.top_soc import TopSoC


def main():
    out_dir = Path(__file__).resolve().parent
    il_path = out_dir / "TopSoC.il"
    v_path  = out_dir / "TopSoC.v"

    # 可在此修改参数：核数、IMEM/DMEM 深度等
    top = TopSoC(ncores=4)

    # 1) 生成 RTLIL
    il = rtlil.convert(top, name="TopSoC", ports=[top.trap])
    il_path.write_text(il, encoding="utf-8")
    print(f"Wrote {il_path}")

    # 2) 调用 yosys 导出 Verilog
    #    这里使用非常保守的流程：proc/opt/techmap/opt
    script = "read_rtlil TopSoC.il; proc; opt; techmap; opt; write_verilog TopSoC.v"
    subprocess.check_call(["yosys", "-p", script], cwd=str(out_dir))
    print(f"Wrote {v_path}")


if __name__ == "__main__":
    main()
