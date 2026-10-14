import importlib.util
from pathlib import Path
import pytest
_s=importlib.util.spec_from_file_location("s",Path(__file__).with_name("test_isa_zfh_add_sub.py"));_m=importlib.util.module_from_spec(_s);_s.loader.exec_module(_m);_run=_m._run
def lui(d,v):return(v&0xfffff000)|(d<<7)|55
def ai(d,a,i):return((i&4095)<<20)|(a<<15)|(d<<7)|19
def li(d,v):v&=0xffffffff;h=(v+2048)&0xfffff000;return[lui(d,h),ai(d,d,(v-h)&4095)]
def div(d,a,b,r):return(0b0001100<<25)|(b<<20)|(a<<15)|(r<<12)|(d<<7)|83
def csr(d,c,a,f=2):return(c<<20)|(a<<15)|(f<<12)|(d<<7)|115
@pytest.mark.parametrize("ext",["RV32I+GC+ZFINX","RV32I+GC+*+ZFINX"])
def test_zfinx_divide_thirds_all_rounding_modes_and_dynamic_frm(ext):
 p=li(1,0x3f800000)+li(2,0x40400000);regs=[]
 for d,f,r in zip(range(3,8),range(20,25),range(5)):
  p += [csr(0,1,0,1),div(d,1,2,r)]+[ai(0,0,0)]*4+[csr(f,1,0)];regs += [d,f]
 p += [csr(0,2,3,5),csr(0,1,0,1),div(8,1,2,7)]+[ai(0,0,0)]*4+[csr(25,1,0)];regs += [8,25]
 assert _run(ext,p,tuple(regs))==(0x3eaaaaab,1,0x3eaaaaaa,1,0x3eaaaaaa,1,0x3eaaaaab,1,0x3eaaaaab,1,0x3eaaaaab,1)
