import importlib.util
from pathlib import Path
import pytest
_s=importlib.util.spec_from_file_location("s",Path(__file__).with_name("test_isa_zfh_add_sub.py"));_m=importlib.util.module_from_spec(_s);_s.loader.exec_module(_m);_run=_m._run
def lui(d,v):return(v&0xfffff000)|(d<<7)|55
def ai(d,a,i):return((i&4095)<<20)|(a<<15)|(d<<7)|19
def li(d,v):v&=0xffffffff;h=(v+2048)&0xfffff000;return[lui(d,h),ai(d,d,(v-h)&4095)]
def sq(d,a,r):return(0b0101100<<25)|(a<<15)|(r<<12)|(d<<7)|83
def csr(d,c,a,f=2):return(c<<20)|(a<<15)|(f<<12)|(d<<7)|115
def clr():return csr(0,1,0,1)
def flg(d):return csr(d,1,0)
@pytest.mark.parametrize("ext",["RV32I+GC+ZFINX","RV32I+GC+*+ZFINX"])
def test_zfinx_sqrt_two_all_rounding_modes_and_dynamic_frm(ext):
 p=li(1,0x40000000);regs=[]
 for d,f,r in zip(range(3,8),range(20,25),range(5)):
  p += [clr(),sq(d,1,r)]+[ai(0,0,0)]*4+[flg(f)];regs += [d,f]
 p += [csr(0,2,3,5),clr(),sq(8,1,7)]+[ai(0,0,0)]*4+[flg(25)];regs += [8,25]
 assert _run(ext,p,tuple(regs)) == (0x3fb504f3,1,0x3fb504f3,1,0x3fb504f3,1,0x3fb504f4,1,0x3fb504f3,1,0x3fb504f4,1)
