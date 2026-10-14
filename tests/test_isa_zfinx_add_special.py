import importlib.util
from pathlib import Path
import pytest
_s=importlib.util.spec_from_file_location("s",Path(__file__).with_name("test_isa_zfh_add_sub.py"));_m=importlib.util.module_from_spec(_s);_s.loader.exec_module(_m);_run=_m._run
def lui(d,v):return(v&0xfffff000)|(d<<7)|55
def ai(d,a,i):return((i&4095)<<20)|(a<<15)|(d<<7)|19
def li(d,v):v&=0xffffffff;h=(v+2048)&0xfffff000;return[lui(d,h),ai(d,d,(v-h)&4095)]
def add(d,a,b,r=0):return(b<<20)|(a<<15)|(r<<12)|(d<<7)|83
def csr(d,c,a,f=2):return(c<<20)|(a<<15)|(f<<12)|(d<<7)|115
@pytest.mark.parametrize("ext",["RV32I+GC+ZFINX","RV32I+GC+*+ZFINX"])
def test_zfinx_add_zero_sign_nan_infinity_and_invalid_flags(ext):
 vals=(0,0x80000000,0x7f800000,0xff800000,0x7fc12345,0x7f800001,0x3f800000);p=[]
 for r,v in enumerate(vals,1):p+=li(r,v)
 p += [csr(0,1,0,1),add(8,2,2),add(9,1,2),add(10,1,2,2),add(11,3,4),add(12,5,7),add(13,6,7)]+[ai(0,0,0)]*5+[csr(20,1,0)]
 assert _run(ext,p,(8,9,10,11,12,13,20))==(0x80000000,0,0x80000000,0x7fc00000,0x7fc00000,0x7fc00000,16)
