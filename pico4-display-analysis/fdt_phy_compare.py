#!/usr/bin/env python3
# 仅解析已知 FDT 偏移（dtbo 16 个 entry），提取各面板 fragment 的 phy/fps/clk 对照表。
import sys, struct
MAGIC=b'\xd0\x0d\xfe\xed'
def u32(d,o): return struct.unpack('>I', d[o:o+4])[0]
def parse(data, base, collect):
    if data[base:base+4]!=MAGIC: return
    total=u32(data,base+4); off_struct=u32(data,base+8); off_strings=u32(data,base+12); size_strings=u32(data,base+32)
    if size_strings==0: size_strings=total-off_strings
    strings=data[base+off_strings: base+off_strings+size_strings]
    def gs(o): return strings[o:].split(b'\x00')[0].decode('latin1','replace')
    pos=base+off_struct; end=base+total; depth=0; path=[]; frag=None; cur={}
    guard=0
    def flush():
        if frag and cur.get('phy'):
            collect.append((frag, dict(cur)))
    while pos+4<=end and guard<2000000:
        guard+=1
        tag=u32(data,pos)
        if tag==0x1:
            e=data.index(b'\x00',pos+4); nm=data[pos+4:e].decode('latin1','replace'); path.append(nm); pos=(e+1+3)&~3; depth+=1
            if nm.startswith('fragment@'):
                flush(); frag=nm; cur={}
        elif tag==0x2:
            depth-=1
            if path: path.pop()
            if depth<=0 and frag:
                flush(); frag=None; cur={}
        elif tag==0x3:
            plen,no=struct.unpack('>II', data[pos+4:pos+12]); pname=gs(no); pval=data[pos+12:pos+12+plen]; pos=(pos+12+plen+3)&~3
            if frag and pname=='qcom,mdss-dsi-panel-phy-timings' and len(pval)==14: cur['phy']=pval.hex()
            elif frag and pname=='qcom,mdss-dsi-panel-framerate' and len(pval)>=4: cur['fps']=str(u32(pval,0))
            elif frag and pname=='qcom,mdss-dsi-panel-clockrate' and len(pval)>=4: cur['clk']=str(u32(pval,0))
            elif frag and pname=='qcom,mdss-dsi-panel-name' and len(pval)<80: cur['name']=pval.decode('latin1','replace')
        elif tag==0x9:
            break
        else:
            pos+=4
    flush()
for path in sys.argv[1:]:
    data=open(path,'rb').read()
    collect=[]
    off=0; cnt=0
    while cnt<20:
        i=data.find(MAGIC,off)
        if i<0: break
        parse(data,i,collect); off=i+4; cnt+=1
    print("="*70); print("FILE:",path)
    for frag,info in collect:
        nm=info.get('name',''); fps=info.get('fps','?'); clk=info.get('clk','?'); phy=info.get('phy','')
        print("  %-14s fps=%-3s clk=%-10s %s" % (frag, fps, clk, nm))
        if phy: print("      PHY=%s" % phy)
