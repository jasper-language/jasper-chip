import importlib.util
from pathlib import Path
import pytest

_s=importlib.util.spec_from_file_location("support",Path(__file__).with_name("test_isa_zfh_add_sub.py")); _m=importlib.util.module_from_spec(_s); _s.loader.exec_module(_m); _run=_m._run
def lui(d,v): return (v&0xfffff000)|(d<<7)|0x37
def addi(d,a,i): return ((i&0xfff)<<20)|(a<<15)|(d<<7)|0x13
def li(d,v): v&=0xffffffff; h=(v+0x800)&0xfffff000; return [lui(d,h),addi(d,d,(v-h)&0xfff)]
def sqrt(d,a,rm): return (0b0101100<<25)|(a<<15)|(rm<<12)|(d<<7)|0x53
def csr(d,c,a,f=2): return (c<<20)|(a<<15)|(f<<12)|(d<<7)|0x73
def clear(): return csr(0,1,0,1)
def flags(d): return csr(d,1,0)
def nops(): return [addi(0,0,0)]*4

@pytest.mark.parametrize("extensions",["RV32I+GC+ZFINX","RV32I+GC+*+ZFINX"])
def test_zfinx_sqrt_rounding_encodings_exceptions_and_dependency(extensions):
    p=li(1,0x40800000); regs=[]
    for d,f,rm in zip(range(3,8),range(20,25),range(5)):
        p += [clear(),sqrt(d,1,rm)]+nops()+[flags(f)]; regs += [d,f]
    p += li(8,0xbf800000)+[clear(),sqrt(9,8,0)]+nops()+[flags(25)]; regs += [9,25]
    p += li(10,0x7f800001)+[clear(),sqrt(11,10,0)]+nops()+[flags(26)]; regs += [11,26]
    p += li(12,0x40000000)+[clear(),sqrt(13,12,0)]+nops()+[flags(27)]; regs += [13,27]
    p += [sqrt(14,1,0),addi(15,14,1)]; regs += [14,15]
    assert _run(extensions,p,tuple(regs)) == (
        0x40000000,0,0x40000000,0,0x40000000,0,0x40000000,0,0x40000000,0,
        0x7fc00000,16,0x7fc00000,16,0x3fb504f3,1,0x40000000,0x40000001)
