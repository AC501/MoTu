# -*- coding: utf-8 -*-
"""
analyze_v13_pgeom.py —— 逐点 pgeom 对齐 + v12 网络核实的「重新分析」(只出方案, 不改网络)
========================================================================================
针对用户质疑(旧法只做"整线互量最近距离", 把平行路/连接误判成整段缺, 过于草率):
新法用 v12 匹配结果里与"高德 mgeom 顶点"一一对应的 pgeom 逐点佐证, 并回到 v12 路网
核实参考段到底有没有路, 把每个候选区分成:
    whole_miss : 参考几何在 v12 上真有空白(真缺路段)      -> 建议补该参考段
    conn       : 参考被 v12 覆盖但结果线绕行(缺转向/连接) -> 建议补短连(绕行首尾之间)
    paral      : 参考被 v12 覆盖、绕行也小(多半平行路贴错)-> 暂不补/待复测
    artifact   : 首/尾掉头伪影                             -> 不补
每条候选打印: 弧长范围 / 逐点 d_i(pgeom 离参考)统计 / v12 覆盖统计 / A/B 落点
    (落点只查询打印: 20m 内现成节点 -> node; 否则最近边垂足 -> split, 不写入任何 shp)

输入: GD_FILE(高德 mgeom) + RES_FILE(v12 结果 mgeom/pgeom/spdist) + V12_NET(edges/nodes)
输出: v16_pgeom_report.txt(人读)  v16_plan_pgeom.json(机器读, 供人工决定补哪些)
用法: python analyze_v13_pgeom.py
"""
import json
import math
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = r"d:\Desktop\motu"
GD_FILE = os.path.join(BASE, "gdosm/cleaned_output_6/result_65tiao_stmatch.txt")
RES_FILE = os.path.join(BASE, "result_65tiao_onv15.txt")
V12_EDGES = os.path.join(BASE, "chengdu_road_network2_fixed_v15", "edges.shp")
V12_NODES = os.path.join(BASE, "chengdu_road_network2_fixed_v15", "nodes.shp")
IDS = [1, 5, 8, 10, 16, 24, 27, 35, 41, 45, 48, 55, 72, 74, 76, 77, 79, 80, 82, 84, 93, 94, 108, 110, 118, 119, 120, 122, 126, 127, 133, 141, 142, 148, 154, 169, 171, 172, 175, 176, 186, 201, 206, 208, 211, 219, 222, 230, 235, 237, 242, 243, 249, 250, 252, 255, 257, 259, 271, 272, 274, 291, 292, 298, 299]
RPT = os.path.join(BASE, "v16_pgeom_report.txt")
PLAN = os.path.join(BASE, "v16_plan_pgeom.json")
PATCH = os.path.join(BASE, "v16_patches.json")

# ---- 判定参数 ----
COV_TOL = 8.0        # 参考点离 v12 最近边 > 此值(m) = 该处 v12 无路(几何空白)
BLANK_MIN = 10.0     # [v16完善] 空白连续至少多长(m)才算"真缺段"
STEP_REF = 10.0      # 参考空白扫描采样步(m)
CHUNK_N = 60         # 每 N 个采样读一次 v12 边(控制单窗)
PAD = 0.0025         # 读边外扩(度)

DEV = 12.0           # 结果线采样点离参考线 > 此值(m) = 结果偏离
STEP_RES = 12.0      # 结果线采样步(m)
MERGE = 80.0         # 相邻偏离采样合并间隙(m)
TAIL = 40.0          # 首尾伪影过滤: 偏离区全在首/尾 TAIL 内且 < 150m 视为伪影
PK_CONN = 12.0       # [v16完善] 绕峰 >= 此值 且参考被覆盖 -> 判"连接/转向缺"(几十米小绕也补)
PK_PARAL = 8.0       # [v16完善] 绕峰 < 此值 -> 判"平行/小抖"(暂不补)
DEV_PG = 12.0        # pgeom 逐点切段: 参考顶点离其 v12 投影 >= 此值(m) 视为"该点没被贴住"
PG_MARGIN = 60.0     # pgeom 重切窗口 = mgeom 粗边界再外扩(m)

NODE_SNAP = 20.0     # 落点: 现成节点容差(m)
EDGE_SNAP = 50.0     # 落点: 最近边垂足容差(m)


def log(m):
    print(m, flush=True)


def hav(a, b):
    R = 6371000.0
    la, lb, lo, lc = map(math.radians, [a[1], b[1], a[0], b[0]])
    h = math.sin((lb - la) / 2) ** 2 + math.cos(la) * math.cos(lb) * math.sin((lc - lo) / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(h)))


def parse_wkt(s):
    s = s.strip()
    if "LINESTRING" not in s:
        return []
    inner = s[s.index("(") + 1:s.rindex(")")]
    pts = []
    for t in inner.split(","):
        tt = t.strip().split()
        if len(tt) == 2:
            pts.append((float(tt[0]), float(tt[1])))
    return pts


def read_gd(path):
    """高德参考: {tid: [(x,y)...]}"""
    out = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        head = f.readline().rstrip("\n").split(";")
        idc = head.index("id")
        gc = next(i for i, c in enumerate(head) if c.strip() == "mgeom")
        for line in f:
            p = line.rstrip("\n").split(";")
            if len(p) <= max(idc, gc):
                continue
            try:
                t = int(p[idc])
            except Exception:
                continue
            pts = parse_wkt(p[gc])
            if pts:
                out[t] = pts
    return out


def read_res(path):
    """v12 匹配结果: {tid: {"mgeom":[...], "pgeom":[...], "spdist":[..]}}"""
    out = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        head = f.readline().rstrip("\n").split(";")
        idc = head.index("id")
        ci = {c: i for i, c in enumerate(head)}
        for line in f:
            p = line.rstrip("\n").split(";")
            try:
                t = int(p[idc])
            except Exception:
                continue
            d = {}
            if "mgeom" in ci:
                d["mgeom"] = parse_wkt(p[ci["mgeom"]])
            if "pgeom" in ci:
                d["pgeom"] = parse_wkt(p[ci["pgeom"]])
            if "spdist" in ci:
                d["spdist"] = [float(x) for x in p[ci["spdist"]].split(",") if x]
            out[t] = d
    return out


def cum(pts):
    c = [0.0]
    for a, b in zip(pts, pts[1:]):
        c.append(c[-1] + hav(a, b))
    return c


def sample(pts, cc, step):
    o = [(0.0, pts[0])]
    n = int(cc[-1] // step)
    k = 1
    for i in range(len(pts) - 1):
        seg = cc[i + 1] - cc[i]
        while k <= n and k * step <= cc[i + 1] + 1e-9:
            t = (k * step - cc[i]) / seg if seg > 0 else 0.0
            t = max(0.0, min(1.0, t))
            o.append((k * step, (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t,
                                 pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t)))
            k += 1
    o.append((cc[-1], pts[-1]))
    return o


def d2seg(p, a, b):
    ax, ay = a[0] - p[0], a[1] - p[1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    tt = max(0.0, min(1.0, -(ax * dx + ay * dy) / L2)) if L2 else 0.0
    q = (a[0] + dx * tt, a[1] + dy * tt)
    return hav(p, q), q


def min_d(p, poly):
    bd = (1e18, None)
    for a, b in zip(poly, poly[1:]):
        d, q = d2seg(p, a, b)
        if d < bd[0]:
            bd = (d, q)
    return bd


def arc_at(ref, cr, s):
    if s <= 0:
        return ref[0]
    if s >= cr[-1]:
        return ref[-1]
    for i in range(len(ref) - 1):
        if cr[i] <= s <= cr[i + 1]:
            t = (s - cr[i]) / (cr[i + 1] - cr[i]) if cr[i + 1] > cr[i] else 0.0
            return (ref[i][0] + (ref[i + 1][0] - ref[i][0]) * t,
                    ref[i][1] + (ref[i + 1][1] - ref[i][1]) * t)
    return ref[0]


def arc_of(ref, cr, q):
    best = (1e18, 0.0)
    a = 0.0
    for j in range(len(ref) - 1):
        dd, _ = d2seg(q, ref[j], ref[j + 1])
        segl = hav(ref[j], ref[j + 1])
        if dd < best[0]:
            best = (dd, a + hav(ref[j], q))
        a += segl
    return best[1]


def ref_sub(ref, cr, a, b):
    lo, hi = (a, b) if a <= b else (b, a)
    sub = []
    for i, pt in enumerate(ref):
        if cr[i] >= lo - 1e-6 and cr[i] <= hi + 1e-6:
            sub.append(pt)
    if len(sub) < 2:
        sub = [arc_at(ref, cr, lo), arc_at(ref, cr, hi)]
    else:
        sub[0] = arc_at(ref, cr, lo)
        sub[-1] = arc_at(ref, cr, hi)
    return sub


def pgeom_ref_seg(ref, cr, pgeom, lo, hi, dev):
    """pgeom 顶点级重切: 在参考弧 [lo,hi] 窗口内, 对每个参考顶点算
    d_i = hav(参考顶点, 其 v12 pgeom 投影); 找 d_i>=dev 的最长连续顶点段,
    返回 (段首参考弧长, 段尾参考弧长, 顶点数); 找不到返回 None.
    因为 pgeom 与参考顶点一一对应, 切出的边界直接落在"参考顶点/弧长"上,
    无 mgeom 那种"采样再投影回参考"的二次误差。"""
    ids = [i for i in range(len(ref)) if i < len(pgeom) and lo - 1e-6 <= cr[i] <= hi + 1e-6]
    if not ids:
        return None
    best = None          # (跨度n, 首弧长, 尾弧长)
    cur_s = cur_e = None
    for i in ids:
        if hav(ref[i], pgeom[i]) >= dev:
            if cur_s is None:
                cur_s = cur_e = i
            else:
                cur_e = i
        else:
            if cur_s is not None:
                if best is None or (cur_e - cur_s) > best[0]:
                    best = (cur_e - cur_s, cr[cur_s], cr[cur_e])
                cur_s = cur_e = None
    if cur_s is not None:
        if best is None or (cur_e - cur_s) > best[0]:
            best = (cur_e - cur_s, cr[cur_s], cr[cur_e])
    if best is None:
        return None
    return best[1], best[2], best[0] + 1


def endpoint_pgeom(ref, cr, pgeom, s, direction):
    """返回离参考弧长 s 最近的那个参考顶点在 v12 上的 pgeom 投影坐标.
    pgeom 就是这个参考顶点被匹配到路网上的落点, 新增节点直接用它,
    保证补路段端点与 v12 实际贴住/投影位置一致(direction 仅兼容旧调用, 不使用)."""
    if not pgeom:
        return None
    idx = min(range(len(ref)), key=lambda i: abs(cr[i] - s))
    idx = max(0, min(idx, len(pgeom) - 1))
    return [round(pgeom[idx][0], 7), round(pgeom[idx][1], 7)]


# ---------------- v12 网络读取与测量 ----------------
def load_net_edges(bb):
    """读 bbox 内 v12 边 -> (shapely 线列表, 元数据列表[(fid,u,v)])"""
    import pyogrio
    from shapely.geometry import LineString
    df = pyogrio.read_dataframe(V12_EDGES, bbox=bb)
    lines, meta = [], []
    for i in range(len(df)):
        g = df.geometry.iloc[i]
        if g is None:
            continue
        gs = [g] if g.geom_type == "LineString" else list(g.geoms)
        for gg in gs:
            cs = list(gg.coords)
            if len(cs) >= 2:
                lines.append(gg)
                meta.append((int(df["fid"].iloc[i]), str(df["u"].iloc[i]), str(df["v"].iloc[i]),
                             str(df["oneway"].iloc[i]), str(df["reversed"].iloc[i])))
    return lines, meta


def dist_to_net(p, tree):
    """点到最近 v12 边距离(m). tree=None 或空 -> 大数"""
    from shapely.geometry import Point
    if tree is None:
        return 1e9
    try:
        i0 = tree.nearest(Point(p))
        ddeg = tree.geometries[i0].distance(Point(p))
        return ddeg * 111320.0 * math.cos(math.radians(p[1]))
    except Exception:
        return 1e9


def ref_blank_runs(ref):
    """参考折线相对 v12 的几何空白段(全程扫描, 分窗 STRtree)"""
    import pyogrio
    from shapely.strtree import STRtree
    cr = cum(ref)
    smp = sample(ref, cr, STEP_REF)
    dist = {}
    for b0 in range(0, len(smp), CHUNK_N):
        chunk = smp[b0:b0 + CHUNK_N]
        xs = [p[0] for _, p in chunk]
        ys = [p[1] for _, p in chunk]
        bb = (min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD)
        lines, _ = load_net_edges(bb)
        tree = STRtree(lines) if lines else None
        for s, p in chunk:
            dist[s] = dist_to_net(p, tree)
    runs = []
    prev = None
    for s, p in smp:
        d = dist.get(s, 1e9)
        if d >= COV_TOL:
            if prev and s - prev[1] <= STEP_REF * 3:
                prev[1] = s
                prev[2] = max(prev[2], d)
                prev[3] = p
            else:
                prev = [s, s, d, p]
                runs.append(prev)
    out = []
    for st, en, pk, p0 in runs:
        if en - st >= BLANK_MIN:
            sub = ref_sub(ref, cr, st, en)
            out.append({"st": st, "en": en, "len": en - st, "peak": pk,
                        "geom": sub,
                        "A": sub[0], "B": sub[-1]})
    return out


def anchor_on_net(pt):
    """落点查询(只读): 20m 内现成节点 -> ("node", osm, (x,y)); 否则最近边垂足 -> ("split", fid, q, d)"""
    import pyogrio
    from shapely.strtree import STRtree
    # 1) 节点
    bb = (pt[0] - 0.002, pt[1] - 0.002, pt[0] + 0.002, pt[1] + 0.002)
    try:
        dfn = pyogrio.read_dataframe(V12_NODES, read_geometry=False, bbox=bb,
                                     columns=["osmid", "x", "y"])
        best = (1e18, None, None)
        for i in range(len(dfn)):
            q = (float(dfn["x"].iloc[i]), float(dfn["y"].iloc[i]))
            d = hav(pt, q)
            if d < best[0]:
                best = (d, str(dfn["osmid"].iloc[i]), q)
        if best[1] is not None and best[0] <= NODE_SNAP:
            return ("node", best[1], best[2], best[0])
    except Exception:
        pass
    # 2) 最近边垂足
    bb = (pt[0] - 0.004, pt[1] - 0.004, pt[0] + 0.004, pt[1] + 0.004)
    try:
        df = pyogrio.read_dataframe(V12_EDGES, bbox=bb)
        best = (1e18, None, None, None)
        for i in range(len(df)):
            g = df.geometry.iloc[i]
            if g is None:
                continue
            cs = list(g.coords) if g.geom_type == "LineString" else list(g.geoms[0].coords)
            fid = int(df["fid"].iloc[i])
            u, v = str(df["u"].iloc[i]), str(df["v"].iloc[i])
            for a, b in zip(cs, cs[1:]):
                d, q = d2seg(pt, a, b)
                if d < best[0]:
                    best = (d, fid, (u, v), q)
        if best[1] is not None and best[0] <= EDGE_SNAP:
            return ("split", best[1], best[3], best[0])
    except Exception:
        pass
    return ("far", None, None, 1e18)


def cover_stats_on_ref(sub):
    """参考子段 sub 相对 v12 覆盖统计: (覆盖采样占比, 最大连续空白m, 空白段列表)"""
    import pyogrio
    from shapely.strtree import STRtree
    if len(sub) < 2:
        return 1.0, 0.0, []
    cr = cum(sub)
    smp = sample(sub, cr, STEP_REF)
    dist = {}
    for b0 in range(0, len(smp), CHUNK_N):
        chunk = smp[b0:b0 + CHUNK_N]
        xs = [p[0] for _, p in chunk]
        ys = [p[1] for _, p in chunk]
        bb = (min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD)
        lines, _ = load_net_edges(bb)
        tree = STRtree(lines) if lines else None
        for s, p in chunk:
            dist[s] = dist_to_net(p, tree)
    n_cov = sum(1 for s, _pp in smp if dist.get(s, 1e9) < COV_TOL)
    frac = n_cov / max(1, len(smp))
    # 最大连续空白
    runs, prev = [], None
    for s, p in smp:
        d = dist.get(s, 1e9)
        if d >= COV_TOL:
            if prev and s - prev[1] <= STEP_REF * 3:
                prev[1] = s
            else:
                prev = [s, s]
                runs.append(prev)
    mx = max((r[1] - r[0] for r in runs), default=0.0)
    return frac, mx, [(round(r[0], 1), round(r[1], 1)) for r in runs if r[1] - r[0] >= 5]


def oneway_conflicts(sub):
    """检测参考段 sub 下方 v15 边里的"单行道方向冲突":
    对 sub 每个采样点找最近边; 若该边 oneway=True 且"可通行方向"与参考行进方向相反,
    即参考要逆行 → 返回 [{'fid':..,'u':..,'v':..}] (去重)。
    可通行方向: 默认几何 cs[0]->cs[-1]; 若该边 reversed=True 则几何与 u->v 相反。"""
    import pyogrio
    from shapely.strtree import STRtree
    from shapely.geometry import Point
    if len(sub) < 2:
        return []
    cr = cum(sub)
    smp = sample(sub, cr, STEP_REF)
    conf = {}
    for b0 in range(0, len(smp), CHUNK_N):
        chunk = smp[b0:b0 + CHUNK_N]
        xs = [p[0] for _, p in chunk]
        ys = [p[1] for _, p in chunk]
        bb = (min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD)
        lines, meta = load_net_edges(bb)
        if not lines:
            continue
        tree = STRtree(lines)
        for s, p in chunk:
            try:
                i0 = tree.nearest(Point(p))
                g = tree.geometries[i0]
                fid, u, v, ow, rev = meta[i0]
            except Exception:
                continue
            if str(ow).strip().lower() != "true":     # 双向边, 无方向问题
                continue
            cs = list(g.coords)
            if len(cs) < 2:
                continue
            # 可通行方向(u->v)的矢量
            if str(rev).strip().lower() == "true":
                ex, ey = cs[0][0] - cs[-1][0], cs[0][1] - cs[-1][1]
            else:
                ex, ey = cs[-1][0] - cs[0][0], cs[-1][1] - cs[0][1]
            p2 = arc_at(sub, cr, min(s + STEP_REF, cr[-1]))
            dx, dy = p2[0] - p[0], p2[1] - p[1]
            if dx * ex + dy * ey < 0:                  # 参考逆行 -> 冲突
                conf[fid] = {"fid": int(fid), "u": str(u), "v": str(v)}
    return list(conf.values())


def build_patches_from_plan(plan):
    """按 v14 方法从 plan 挑可补候选, 去重后写 PATCH(repair_v15 可直接读).
       纳入: kind=='conn'/'miss'(L>=5m) 与 kind=='whole_miss'(peak>=18m)
       排除: conn?/paral/artifact(待核/伪影/平行)
       去重: 同 tid 且两端(A,A')(B,B') 均<=12m 视为同一处, 保留 len 大者
       附带: A_pgeom/B_pgeom(pgeom 锚)与显式 A_node/A_split(若 plan 给了)"""
    items = []
    for p in plan:
        k = p.get("kind")
        L = float(p.get("len_m", 0.0))
        pk = float(p.get("peak_m", 0.0))
        if k in ("conn", "miss"):
            if L < 3:
                continue
        elif k == "whole_miss":
            if pk < 10 and not p.get("oneway_fix"):
                continue
        elif k == "paral":
            if not p.get("oneway_fix"):
                continue
        else:
            continue
        it = {"tid": p["tid"], "name": p["name"], "kind": k,
              "A": p["A"], "B": p["B"], "len_m": L, "peak_m": pk,
              "geom": p.get("geom")}
        for f in ("A_pgeom", "B_pgeom", "A_node", "B_node", "A_split", "B_split", "oneway_fix"):
            if p.get(f):
                it[f] = p[f]
        items.append(it)
    kept = []
    for it in items:
        dup = None
        for k2 in kept:
            if k2["tid"] != it["tid"]:
                continue
            aa = hav(tuple(it["A"]), tuple(k2["A"])); bb = hav(tuple(it["B"]), tuple(k2["B"]))
            ab = hav(tuple(it["A"]), tuple(k2["B"])); ba = hav(tuple(it["B"]), tuple(k2["A"]))
            if (aa <= 12 and bb <= 12) or (ab <= 12 and ba <= 12):
                dup = k2
                break
        if dup is None:
            kept.append(it)
        elif it["len_m"] > dup["len_m"]:
            kept[kept.index(dup)] = it
    json.dump(kept, open(PATCH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return len(kept)


def main():
    if os.path.exists(RPT):
        os.remove(RPT)
    gd = read_gd(GD_FILE)
    rs = read_res(RES_FILE)
    rep = []
    plan = []

    for tid in IDS:
        if tid not in gd or tid not in rs:
            rep.append(f"!! id={tid} 缺参考或结果")
            continue
        ref = gd[tid]
        res = rs[tid]["mgeom"]
        pgeom = rs[tid].get("pgeom", [])
        cr, cc = cum(ref), cum(res)
        rep.append("\n" + "=" * 76)
        rep.append(f"===== id={tid}  参考(高德mgeom)={cr[-1]:.0f}m  结果(v12)={cc[-1]:.0f}m"
                   f"  比值={cc[-1]/cr[-1]:.2f}  参考顶点={len(ref)} pgeom顶点={len(pgeom)}")
        rep.append("=" * 76)
        log(f"[进度] id={tid}: 开始 (参考{cr[-1]:.0f}m) -- ①扫全程空白(可能要一会)")

        # ---------- ① 真缺: 参考几何在 v12 空白 ----------
        blk = ref_blank_runs(ref)
        log(f"[进度] id={tid}: ① 空白段 {len(blk)} 处")
        rep.append(f"\n[① 真缺候选] 参考线离 v12 网络> {COV_TOL:.0f}m 且长>= {BLANK_MIN:.0f}m 的空白段: {len(blk)} 处")
        for b in blk:
            a_an = anchor_on_net(b["A"])
            b_an = anchor_on_net(b["B"])
            # pgeom 锚: 空白段两端向 v12 贴住侧找端点参考顶点的 v12 投影点
            a_pg = endpoint_pgeom(ref, cr, pgeom, b["st"], -1) if pgeom else None
            b_pg = endpoint_pgeom(ref, cr, pgeom, b["en"], +1) if pgeom else None
            ow = oneway_conflicts(b["geom"])
            rep.append(f"   [空白!!] 参考弧 {b['st']:.0f}-{b['en']:.0f}m 长{b['len']:.0f}m 峰{b['peak']:.0f}m")
            rep.append(f"      A({b['A'][0]:.6f},{b['A'][1]:.6f}) 落点={a_an[0]}{a_an[1] if a_an[1] else ''} 距{a_an[3]:.1f}m")
            rep.append(f"      B({b['B'][0]:.6f},{b['B'][1]:.6f}) 落点={b_an[0]}{b_an[1] if b_an[1] else ''} 距{b_an[3]:.1f}m")
            plan.append({
                "tid": tid, "kind": "whole_miss", "name": f"{tid}-参考空白@弧{b['st']:.0f}-{b['en']:.0f}m",
                "ref_arc": [round(b["st"], 1), round(b["en"], 1)], "len_m": round(b["len"], 1),
                "peak_m": round(b["peak"], 1),
                "A": [round(b["A"][0], 7), round(b["A"][1], 7)],
                "B": [round(b["B"][0], 7), round(b["B"][1], 7)],
                "geom": [[round(x, 7), round(y, 7)] for x, y in b["geom"]],
                "A_anchor": {"kind": a_an[0], "id": a_an[1], "dist_m": round(a_an[3], 1)},
                "B_anchor": {"kind": b_an[0], "id": b_an[1], "dist_m": round(b_an[3], 1)},
                "A_pgeom": a_pg,
                "B_pgeom": b_pg,
                "oneway_fix": ow,
                "note": "参考几何在 v12 空白(真缺), 建议补此参考段",
            })

        # ---------- ② 结果绕行区 + pgeom 逐点佐证 ----------
        zones = []
        prev = None
        for s, p in sample(res, cc, STEP_RES):
            d, _ = min_d(p, ref)
            if d >= DEV:
                if prev and s - prev[1] <= MERGE:
                    prev[1] = s
                    prev[2] = max(prev[2], d)
                    prev[4] = p
                else:
                    prev = [s, s, d, p, p]
                    zones.append(prev)
        log(f"[进度] id={tid}: ② 绕行区 {len(zones)} 个 (逐区做覆盖核对)")
        rep.append(f"\n[② 结果绕行区] 结果线离参考>{DEV:.0f}m 的区间: {len(zones)} 个")
        for st, en, pk, ps, pe in zones:
            near_s = st < TAIL
            near_e = en > cc[-1] - TAIL
            artifact = (near_s or near_e) and (en - st) < 150
            # (a) mgeom 粗边界: 绕行区两端投影回参考(仅作搜索窗口)
            _, q0 = min_d(ps, ref)
            _, q1 = min_d(pe, ref)
            a0, a1 = arc_of(ref, cr, q0), arc_of(ref, cr, q1)
            # (b) pgeom 顶点级重切: 在粗窗口内找"参考顶点离其 v12 投影 >=DEV_PG"的最长连续段
            win_lo = max(0.0, a0 - PG_MARGIN)
            win_hi = min(cr[-1], a1 + PG_MARGIN)
            pseg = pgeom_ref_seg(ref, cr, pgeom, win_lo, win_hi, DEV_PG) if pgeom else None
            if pseg is not None:
                cut_a0, cut_a1, nv = pseg
                cut_src = f"pgeom({nv}顶点)"
            else:
                cut_a0, cut_a1, nv = a0, a1, 0
                cut_src = "mgeom"
            sub = ref_sub(ref, cr, cut_a0, cut_a1)
            L = sum(hav(x, y) for x, y in zip(sub, sub[1:]))
            # pgeom 锚: A/B 端向 v12 贴住侧找端点参考顶点的 v12 投影点(新增节点直接用它)
            a_pg = endpoint_pgeom(ref, cr, pgeom, cut_a0, -1) if (pgeom and pseg is not None) else None
            b_pg = endpoint_pgeom(ref, cr, pgeom, cut_a1, +1) if (pgeom and pseg is not None) else None
            ow = oneway_conflicts(sub)
            # pgeom 逐点佐证: 切段内参考顶点离其 v12 投影的距离
            di = []
            if pgeom:
                for i, v in enumerate(ref):
                    if i < len(pgeom) and cut_a0 - 1e-6 <= cr[i] <= cut_a1 + 1e-6:
                        di.append(hav(v, pgeom[i]))
            d_avg = (sum(di) / len(di)) if di else None
            d_max = max(di) if di else None
            # (c) v12 网络覆盖核对(最终判定真缺/平行/连接)
            frac, mxb, blank_runs = cover_stats_on_ref(sub)
            # (d) 分类
            if artifact:
                kind, why = "artifact", "首/尾伪影(停车/掉头)"
            elif mxb >= 15.0 or ((1 - frac) > 0.5 and L >= 15):
                kind, why = "miss", f"参考段内仍有空白(覆盖{frac * 100:.0f}% 最大空{mxb:.0f}m)"
            elif pk >= PK_CONN and L >= 5:
                kind, why = "conn", f"覆盖好但绕峰{pk:.0f}m(缺转向/连接, 补短连)"
            elif L >= 5 and pk >= PK_PARAL:
                kind, why = "conn?", f"覆盖好, 绕峰{pk:.0f}m 较小(疑似平行/短连, 待核)"
            else:
                kind, why = "paral", f"覆盖好, 绕峰仅{pk:.0f}m(小抖/平行, 不补)"
            rep.append(f"   [绕行] 结果弧{st:.0f}-{en:.0f}m 峰{pk:.0f}m -> 参考弧{cut_a0:.0f}-{cut_a1:.0f}m"
                       f" 长{L:.0f}m [{cut_src}; mgeom粗{a0:.0f}-{a1:.0f}m] -> {kind}: {why}")
            log(f"[进度] id={tid} 绕行区@结果弧{st:.0f}-{en:.0f}m -> {kind} ({why})")
            if di:
                rep.append(f"      pgeom逐点: 切段内{len(di)}个顶点离其v12投影 均{d_avg:.0f}m 最大{d_max:.0f}m"
                           f" (小=贴得上只是绕/贴平行; 大=真贴不上)")
            rep.append(f"      覆盖: 参考段{frac * 100:.0f}%离v12<{COV_TOL:.0f}m, 最大连续空{mxb:.0f}m"
                       f" {blank_runs if blank_runs else ''}")
            if kind in ("miss", "conn", "conn?"):
                A = [round(sub[0][0], 7), round(sub[0][1], 7)]
                B = [round(sub[-1][0], 7), round(sub[-1][1], 7)]
                plan.append({
                    "tid": tid, "kind": kind, "name": f"{tid}-{kind}@结果弧{st:.0f}-{en:.0f}m(参考{cut_a0:.0f}-{cut_a1:.0f}m)",
                    "res_arc": [round(st, 1), round(en, 1)],
                    "ref_arc": [round(cut_a0, 1), round(cut_a1, 1)],
                    "ref_arc_mgeom_window": [round(a0, 1), round(a1, 1)],
                    "cut_src": cut_src,
                    "len_m": round(L, 1), "peak_m": round(pk, 1),
                    "cover_frac": round(frac, 2), "max_blank_m": round(mxb, 1),
                    "pgeom_avg_m": round(d_avg, 1) if d_avg is not None else None,
                    "pgeom_max_m": round(d_max, 1) if d_max is not None else None,
                    "A": A, "B": B,
                    "A_pgeom": a_pg,
                    "B_pgeom": b_pg,
                    "oneway_fix": ow,
                    "geom": [[round(x, 7), round(y, 7)] for x, y in sub],
                    "note": why,
                })
    txt = "\n".join(rep) + "\n"
    with open(RPT, "w", encoding="utf-8") as f:
        f.write(txt)
    with open(PLAN, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    # 按 v14 规则从 plan 挑补丁 -> 生成 repair_v15 可直接读的 v16_patches.json
    n = build_patches_from_plan(plan)
    log(f"[patches] 已生成 {PATCH}: {n} 条 (纳入 conn/miss + whole_miss(峰>=18), 已去重; 排除 conn?/paral/artifact)")
    print(txt)
    print(f"\n方案 JSON({len(plan)} 条): {PLAN}")
    print(f"报告: {RPT}")


if __name__ == "__main__":
    main()
