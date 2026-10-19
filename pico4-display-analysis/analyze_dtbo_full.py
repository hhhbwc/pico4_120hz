#!/usr/bin/env python3
# 解析设备当前 dtbo（broken-table 的 120Hz 镜像），逐 FDT 提取面板关键属性，
# 判断：面板命令是 90 还是 120Hz、PHY 时序表是 993MHz 旧表还是 1325MHz 新表、pclk 多少。
import struct, sys

IMG = "dtbo-device-pulled.img"
def u32(b,o): return struct.unpack_from(">I",b,o)[0]
def u16(b,o): return struct.unpack_from(">H",b,o)[0]

with open(IMG,"rb") as f:
    b = f.read()

def align4(x): return (x+3)&~3

magic = u32(b,0)
assert magic == 0xD7B7AB1E, f"not DTBO table: {magic:#x}"
totalsize = u32(b,4); version=u32(b,8); entry_size=u32(b,12)
entry_count=u32(b,16); entries_off=u32(b,20)
print(f"DTBO table: totalsize={totalsize} version={version} entry_size={entry_size} entry_count={entry_count} entries_off={entries_off:#x}")

# 真实 FDT 魔数位置
FDT=b"\xd0\x0d\xfe\xed"
fdt_offsets=[]
s=0
while True:
    i=b.find(FDT,s)
    if i<0: break
    fdt_offsets.append(i); s=i+4
print(f"real FDT magic count: {len(fdt_offsets)}")

def parse_fdt(off):
    totalsize=u32(b,off+4)
    off_dt_struct=u32(b,off+8)
    off_dt_strings=u32(b,off+12)
    nodes={}
    stack=[]
    p=off_dt_struct
    guard=0
    while guard<100000:
        guard+=1
        tok=u32(b,p); p+=4
        if tok==0x9:  # END
            break
        elif tok==0x1: # BEGIN_NODE
            ne=b.index(b"\x00",p); name=b[p:ne].decode("latin1"); p=align4(ne+1)
            stack.append(name)
        elif tok==0x2: # END_NODE
            if stack: stack.pop()
        elif tok==0x3: # PROP
            plen=u32(b,p); p+=4; nameoff=u32(b,p); p+=4
            no=off_dt_strings+nameoff; ne=b.index(b"\x00",no); pname=b[no:ne].decode("latin1")
            pdata=b[p:p+plen]; p=align4(p+plen)
            path="/".join(n for n in stack if n) or "/"
            nodes.setdefault(path,{})[pname]=pdata
        elif tok==0x4: # NOP
            continue
        else:
            break
    return nodes

def hexs(x): return x.hex() if x else ""

INTEREST = ("qcom,mdss-dsi-panel-phy-timings","qcom,mdss-dsi-on-command",
            "qcom,mdss-dsi-panel-max-fps","qcom,mdss-dsi-framerate",
            "qcom,mdss-dsi-dfps-list","qcom,mdss-dsi-pclk",
            "qcom,mdss-dsi-panel-timings","qcom,mdss-dsi-panel-framerate")

# 旧 90Hz PHY 表（来自 v6 分析）：00 22 08 08 19 23 09 08 09 02 04 00 1c 0d
OLD_PHY = bytes.fromhex("0022080819230908090204001c0d")

for idx,off in enumerate(fdt_offsets):
    try:
        nodes=parse_fdt(off)
    except Exception as e:
        print(f"\n[{idx}] off={off:#x} PARSE ERR {e}")
        continue
    # 找含 phy-timings 的节点
    panel={}
    for path,props in nodes.items():
        if "qcom,mdss-dsi-panel-phy-timings" in props:
            panel=props; ppath=path; break
    if not panel:
        # 没面板节点，可能是 stub
        npanels=sum(1 for p,pr in nodes.items() if any(k.startswith("qcom,mdss-dsi") for k in pr))
        print(f"\n[{idx}] off={off:#x} no-panel-node (qcom,mdss-dsi nodes={npanels}) paths={list(nodes.keys())[:3]}")
        continue
    phy=panel.get("qcom,mdss-dsi-panel-phy-timings",b"")
    oncmd=panel.get("qcom,mdss-dsi-on-command",b"")
    pclk=panel.get("qcom,mdss-dsi-pclk",b"")
    pclkv=u32(pclk,0) if len(pclk)>=4 else None
    # 判断 B9 命令（90Hz b9 13 5f 02 64 ; 120Hz 不同）
    bi=oncmd.find(b"\xb9")
    b9ctx=oncmd[bi:bi+12].hex() if bi>=0 else "no-b9"
    # dfps
    dfps=panel.get("qcom,mdss-dsi-dfps-list",b"")
    # 把 dfps 当 u32 列表看
    dfps_u32=[u32(dfps,i) for i in range(0,len(dfps)-3,4)] if len(dfps)%4==0 and dfps else []
    maxfps=panel.get("qcom,mdss-dsi-panel-max-fps",b"")
    maxfpsv=u32(maxfps,0) if len(maxfps)>=4 else None
    fr=panel.get("qcom,mdss-dsi-framerate",b"")
    frv=u32(fr,0) if len(fr)>=4 else None
    phy_match = "==OLD90" if phy==OLD_PHY else ("len%d"%len(phy))
    print(f"\n[{idx}] off={off:#x} node={ppath}")
    print(f"   phy-timings={hexs(phy)} {phy_match}")
    print(f"   pclk={pclkv}  max-fps={maxfpsv} framerate={frv}")
    print(f"   b9-oncmd={b9ctx}")
    print(f"   dfps(u32)={dfps_u32[:12]}")
