#!/usr/bin/env python3
# 稳健提取：在每个真实 FDT 中按属性名串偏移定位 PROP，提取面板关键属性原始字节。
import struct
IMG="dtbo-device-pulled.img"
def u32(b,o): return struct.unpack_from(">I",b,o)[0]
def align4(x): return (x+3)&~3
b=open(IMG,"rb").read()

# 真实 FDT 偏移（之前 find 得到）
FDT=b"\xd0\x0d\xfe\xed"
fdt_offsets=[]
s=0
while True:
    i=b.find(FDT,s)
    if i<0: break
    fdt_offsets.append(i); s=i+4

TARGETS=["qcom,mdss-dsi-panel-phy-timings","qcom,mdss-dsi-on-command",
         "qcom,mdss-dsi-panel-max-fps","qcom,mdss-dsi-framerate",
         "qcom,mdss-dsi-dfps-list","qcom,mdss-dsi-pclk",
         "qcom,mdss-dsi-panel-timings"]

# 每个目标名在文件中的绝对偏移（串块里）
name_abs={}
for t in TARGETS:
    tb=t.encode()
    i=b.find(tb)
    if i>=0: name_abs[t]=i
print("targets found in file:", {k:v for k,v in name_abs.items()})

OLD_PHY=bytes.fromhex("0022080819230908090204001c0d")

def extract(off):
    total=u32(b,off+4); so=u32(b,off+8); stro=u32(b,off+12)
    abs_stro=off+stro
    # 本 FDT 内各目标属性的 nameoff（相对串块）
    local={}
    for t in TARGETS:
        if t in name_abs:
            local[t]=name_abs[t]-abs_stro  # nameoff
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
                if no==lo:
                    res[t]=data
        elif tok==0x4: continue
        else:
            break
    return res

for idx,off in enumerate(fdt_offsets):
    try:
        r=extract(off)
    except Exception as e:
        print(f"[{idx}]@{off:#x} ERR {e}"); continue
    if not r: 
        continue
    print(f"\n=== FDT[{idx}] @ {off:#x} ===")
    if "qcom,mdss-dsi-panel-phy-timings" in r:
        phy=r["qcom,mdss-dsi-panel-phy-timings"]
        tag="OLD90(993MHz)!!" if phy==OLD_PHY else "DIFFERENT"
        print(f"  phy-timings({len(phy)}B)= {phy.hex()}  [{tag}]")
    if "qcom,mdss-dsi-on-command" in r:
        oc=r["qcom,mdss-dsi-on-command"]
        bi=oc.find(b"\xb9")
        print(f"  on-command({len(oc)}B) b9ctx={oc[bi:bi+16].hex() if bi>=0 else 'NO-B9'}")
    for k in ("qcom,mdss-dsi-pclk","qcom,mdss-dsi-panel-max-fps","qcom,mdss-dsi-framerate"):
        if k in r:
            v=r[k]
            print(f"  {k}={u32(v,0) if len(v)>=4 else v.hex()}")
    if "qcom,mdss-dsi-dfps-list" in r:
        d=r["qcom,mdss-dsi-dfps-list"]
        vals=[u32(d,i) for i in range(0,len(d)-3,4)] if len(d)%4==0 else []
        print(f"  dfps-list={vals[:16]}")
