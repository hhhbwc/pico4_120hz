#!/usr/bin/env python3
import struct
IMG="dtbo-device-pulled.img"
def u32(b,o): return struct.unpack_from(">I",b,o)[0]
def align4(x): return (x+3)&~3
b=open(IMG,"rb").read()
FDT=b"\xd0\x0d\xfe\xed"
fdt_offsets=[]
s=0
while True:
    i=b.find(FDT,s)
    if i<0: break
    fdt_offsets.append(i); s=i+4

TARGETS=["qcom,mdss-dsi-panel-phy-timings","qcom,mdss-dsi-on-command",
         "qcom,mdss-dsi-panel-timings"]
OLD_PHY=bytes.fromhex("0022080819230908090204001c0d")

def extract(off):
    total=u32(b,off+4); so=u32(b,off+8); stro=u32(b,off+12)
    abs_stro=off+stro
    end=off+total
    local={}
    for t in TARGETS:
        tb=t.encode()
        i=b.find(tb, abs_stro, end)
        if i>=0: local[t]=i-abs_stro
    if not local: return {}
    res={}
    p=off+so; guard=0
    while guard<500000:
        guard+=1
        if p+4>len(b): break
        tok=u32(b,p); p+=4
        if tok==0x9: break
        elif tok==0x1:
            ne=b.index(b"\x00",p); p=align4(ne+1)
        elif tok==0x2: continue
        elif tok==0x3:
            pl=u32(b,p); p+=4; no=u32(b,p); p+=4
            data=b[p:p+pl]; p=align4(p+pl)
            for t,lo in local.items():
                if no==lo: res[t]=data
        elif tok==0x4: continue
        else: break
    return res

for idx,off in enumerate(fdt_offsets):
    try: r=extract(off)
    except Exception as e:
        print(f"[{idx}]@{off:#x} ERR {e}"); continue
    if not r: continue
    print(f"\n=== FDT[{idx}] @ {off:#x} ===")
    if "qcom,mdss-dsi-panel-phy-timings" in r:
        phy=r["qcom,mdss-dsi-panel-phy-timings"]
        tag="OLD90(993MHz) <-- QUALITY BUG" if phy==OLD_PHY else "DIFFERENT"
        print(f"  phy-timings({len(phy)}B)= {phy.hex()}  [{tag}]")
    if "qcom,mdss-dsi-on-command" in r:
        oc=r["qcom,mdss-dsi-on-command"]
        bi=oc.find(b"\xb9")
        # 打印所有 b9 上下文
        ctx=[]
        start=0
        while True:
            j=oc.find(b"\xb9",start)
            if j<0: break
            ctx.append(oc[j:j+10].hex()); start=j+1
        print(f"  on-command({len(oc)}B) B9-occurrences={ctx}")
    if "qcom,mdss-dsi-panel-timings" in r:
        pt=r["qcom,mdss-dsi-panel-timings"]
        # 12 x u32: hbp,hfp,hpw,vbp,vfp,vpw,hactive,vactive,...
        vals=[u32(pt,i) for i in range(0,min(len(pt),48),4)]
        print(f"  panel-timings({len(pt)}B)= {vals}")
