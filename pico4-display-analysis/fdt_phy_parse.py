#!/usr/bin/env python3
# 鲁棒 DTBO/DTB 解析：扫描文件内所有 FDT 魔数(d00dfeed)逐个解析，
# 提取 qcom,mdss-dsi-panel-phy-timings（按节点）+ 含 120/sharp_493/ls026 的节点路径。
import sys, struct
from collections import defaultdict

MAGIC = b'\xd0\x0d\xfe\xed'

def parse_fdt(data, base):
    if data[base:base+4] != MAGIC:
        return None
    try:
        total = struct.unpack('>I', data[base+4:base+8])[0]
        # FDT header: off_dt_struct@+8, off_dt_strings@+12, size_dt_strings@+32
        off_struct = struct.unpack('>I', data[base+8:base+12])[0]
        off_strings = struct.unpack('>I', data[base+12:base+16])[0]
        size_strings = struct.unpack('>I', data[base+32:base+36])[0]
        if size_strings == 0:
            size_strings = total - off_strings  # vendor 未填 size，用末尾兜底
    except struct.error:
        return None
    s = base + off_struct
    end = base + (struct.unpack('>I', data[base+4:base+8])[0])
    strings = data[base+off_strings: base+off_strings+size_strings]
    def getstr(off):
        return strings[off:].split(b'\x00')[0].decode('latin1')
    pos = s
    path = []
    props = []
    kw_nodes = set()
    kw = ('120', 'sharp_493', 'ls026', 'phoenix', 'nt57900')
    while pos + 4 <= end:
        tag = struct.unpack('>I', data[pos:pos+4])[0]
        if tag == 0x1:
            pos += 4
            endn = data.index(b'\x00', pos)
            name = data[pos:endn].decode('latin1') or '/'
            path.append(name)
            p = '/'.join(path)
            if any(k.lower() in p.lower() for k in kw):
                kw_nodes.add(p)
            pos = (endn + 1 + 3) & ~3  # 对齐到 节点名null之后
        elif tag == 0x2:
            pos += 4
            if path: path.pop()
        elif tag == 0x3:
            if pos + 12 > end: break
            plen, nameoff = struct.unpack('>II', data[pos+4:pos+12])
            pos += 12
            pname = getstr(nameoff)
            pval = data[pos:pos+plen]
            if pname == 'qcom,mdss-dsi-panel-phy-timings' and len(pval) == 14:
                props.append(('/'.join(path), pval))
            # 抓刷新率/时序用于判断节点支持的模式
            if pname in ('qcom,mdss-dsi-panel-framerate', 'qcom,mdss-dsi-panel-clockrate',
                         'qcom,mdss-dsi-panel-width', 'qcom,mdss-dsi-panel-height'):
                pass
            pos = (pos + plen + 3) & ~3
        elif tag == 0x9:
            break
        else:
            pos += 4
    return props, kw_nodes

def main():
    for path in sys.argv[1:]:
        data = open(path, 'rb').read()
        print("="*72)
        print("FILE:", path, "size=%d" % len(data))
        print("-"*72)
        all_props = []
        all_kw = set()
        n_fdt = 0
        off = 0
        while True:
            i = data.find(MAGIC, off)
            if i < 0: break
            n_fdt += 1
            r = parse_fdt(data, i)
            if r:
                all_props += r[0]; all_kw |= r[1]
            off = i + 4
        print("FDT blocks found: %d" % n_fdt)
        d = defaultdict(list)
        for p, v in all_props:
            d[p].append(v.hex())
        print("== phy-timings by node (total %d entries) ==" % len(all_props))
        for p in sorted(d):
            print("  %s" % p)
            for v in d[p]:
                tag = ""
                if v == '0022080819230908090204001c0d': tag = "  [OLD 90Hz/993]"
                if v == '002e0b0b222f0c0b0c0306002612': tag = "  [SCALE blind 1325]"
                print("      %s%s" % (v, tag))
        print("-"*72)
        print("== keyword nodes (120/sharp_493/ls026/phoenix/nt57900) ==")
        for p in sorted(all_kw):
            print("  ", p)

if __name__ == '__main__':
    main()
