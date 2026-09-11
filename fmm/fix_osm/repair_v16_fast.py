# -*- coding: utf-8 -*-
"""
输入:
    BASE_NET  : 基网目录(默认 chengdu_road_network2_fixed_v15, 只读)
    PATCH_FILE: 补丁清单 JSON(默认 v16_patches.json)
                每条补丁字段:
                  tid   轨迹id; name 名称(仅日志)
                  A,B   补路段两端(参考线上坐标 [x,y])
                  geom  可空; 新路几何点列(默认 A-B 直线); 首尾会用锚点坐标替换
                  A_node/B_node 可空; 若端点正好有现成节点, 填其 osmid(str)
                  A_split/B_split 可空; 显式打断: {"fids":[正反向fid...], "point":[x,y]}
                  A_pgeom/B_pgeom 可空(推荐); = 端点参考顶点在 v15 上的投影点坐标,
    
    OUT_NET   : chengdu_road_network2_fixed_v16/  (全新目录)
    LOG       : add_v16_log.txt
    ①打断插点: 把要接入的边在锚点处打断成两段, 插入新节点
    ②加双向边: 沿参考几何新增 A<->B 两条(oneway=False, reversed False/True)
    ③nodes 追加新节点; ④自检(残留/计数/节点存在)
"""
import json
import math
import os
import shutil
import sys

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely.geometry import LineString, Point

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = r"d:\Desktop\motu"
BASE_NET = os.path.join(BASE, "chengdu_road_network2_fixed_v15")
OUT_NET = os.path.join(BASE, "chengdu_road_network2_fixed_v16")
PATCH_FILE = os.path.join(BASE, "v16_patches.json")
LOG = os.path.join(BASE, "add_v16_log.txt")
ENCODING = "UTF-8"
NODE_SNAP = 20.0    # 端点附近多近算"现成节点"(m)
EDGE_SNAP = 50.0    # 端点附近多近可打断最近边(m)
EDGE_NODE_END = 3.0  # 投影离边端点小于此值 -> 直接用该端点节点, 不打断(m)


def log(m):
    print(m, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(m + "\n")


def hav(a, b):
    R = 6371000.0
    la, lb, lo, lc = map(math.radians, [a[1], b[1], a[0], b[0]])
    h = math.sin((lb - la) / 2) ** 2 + math.cos(la) * math.cos(lb) * math.sin((lc - lo) / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(h)))


def line_len(cs):
    return sum(hav(a, b) for a, b in zip(cs, cs[1:]))


def d2seg(p, a, b):
    ax, ay = a[0] - p[0], a[1] - p[1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    tt = max(0.0, min(1.0, -(ax * dx + ay * dy) / L2)) if L2 else 0.0
    q = (a[0] + dx * tt, a[1] + dy * tt)
    return hav(p, q), q


def coords_of(g):
    if g is None:
        return []
    return list(g.coords) if g.geom_type == "LineString" else list(g.geoms[0].coords)


# ---------------- 读补丁清单 ----------------
def load_patches():
    with open(PATCH_FILE, encoding="utf-8") as f:
        data = json.load(f)
    # 统一: 允许顶层 {patches:[...]} 或直接数组
    if isinstance(data, dict):
        data = data.get("patches", [])
    if not data:
        log("!! 补丁清单为空, 退出")
        sys.exit(1)
    return data


def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    log(f"输入基网: {BASE_NET}")
    log(f"补丁清单: {PATCH_FILE}")
    log(f"输出新网: {OUT_NET}")

    # ---------- 0. 复制整网 ----------
    if os.path.exists(OUT_NET):
        shutil.rmtree(OUT_NET)
    shutil.copytree(BASE_NET, OUT_NET)
    ED = os.path.join(OUT_NET, "edges.shp")
    ND = os.path.join(OUT_NET, "nodes.shp")
    NDSRC = os.path.join(BASE_NET, "nodes.shp")
    EDSRC = os.path.join(BASE_NET, "edges.shp")

    # ---------- 1. 读全表 ----------
    log("读 edges/nodes 全表(pyogrio) ...")
    gdf = gpd.read_file(ED, engine="pyogrio", encoding=ENCODING)
    attr = [c for c in gdf.columns if c != "geometry"]
    maxfid = int(gdf["fid"].max())
    maxosm = int(pyogrio.read_dataframe(ND, read_geometry=False,
                                        sql="SELECT MAX(osmid) AS m FROM nodes")["m"].iloc[0])
    log(f"edges={len(gdf)} maxfid={maxfid}; nodes maxosmid={maxosm}")
    fidmap = {int(gdf.at[i, "fid"]): i for i in range(len(gdf))}
    uv_fid = {(str(gdf.at[i, "u"]), str(gdf.at[i, "v"])): int(gdf.at[i, "fid"]) for i in range(len(gdf))}
    # 线几何缓存(仅涉及打断的边)
    line_of = {}

    def line_of_fid(fid):
        if fid not in line_of:
            i = fidmap[fid]
            line_of[fid] = coords_of(gdf.geometry.iloc[i])
        return line_of[fid]

    # [fast] 预读 nodes 坐标一次(替代逐条 SQL), 大幅提速
    _nd = pyogrio.read_dataframe(NDSRC, read_geometry=False, columns=["osmid", "x", "y"])
    NODE_XY = {str(_nd["osmid"].iloc[i]): (float(_nd["x"].iloc[i]), float(_nd["y"].iloc[i]))
               for i in range(len(_nd))}
    log(f"[fast] 预读 nodes {len(NODE_XY)} 个")

    def node_xy(osm):
        return NODE_XY.get(str(osm))

    def nearest_node(p):
        x0, y0 = p[0] - 0.002, p[1] - 0.002
        dfn = pyogrio.read_dataframe(NDSRC, read_geometry=False, bbox=(x0, y0, p[0] + 0.002, p[1] + 0.002),
                                     columns=["osmid", "x", "y"])
        best, bo = 1e18, None
        for i in range(len(dfn)):
            q = (float(dfn["x"].iloc[i]), float(dfn["y"].iloc[i]))
            d = hav(p, q)
            if d < best:
                best, bo = d, str(dfn["osmid"].iloc[i])
        return bo, best

    def nearest_edge_proj(p):
        """返回 (fid, 投影点, 距端最近节点osm或None, 距端最近节点距离m)"""
        x0, y0 = p[0] - 0.004, p[1] - 0.004
        x1, y1 = p[0] + 0.004, p[1] + 0.004
        dfe = pyogrio.read_dataframe(EDSRC, bbox=(x0, y0, x1, y1))
        best = (1e18, None, None, None, None)
        for i in range(len(dfe)):
            g = dfe.geometry.iloc[i]
            cs = coords_of(g)
            if len(cs) < 2:
                continue
            fid = int(dfe["fid"].iloc[i])
            u = str(dfe["u"].iloc[i])
            v = str(dfe["v"].iloc[i])
            for a, b in zip(cs, cs[1:]):
                d, q = d2seg(p, a, b)
                if d < best[0]:
                    best = (d, fid, q, u, v)
        return best

    # ---------- 2. 解析每条补丁的锚点 ----------
    # 每条补丁记录: A/B -> ("node", osm) 或 ("split", fids, point)
    # split 登记表: (pairkey, point) -> 新节点 osm; 同一物理点合并
    splits = {}      # (frozenset(fids), point_rounded) -> osm
    patches = load_patches()
    # [v16] 单行道方向冲突修复: 补丁 oneway_fix 列出的 (u,v) 边需改为双向
    ow_fix = set()
    for pj in patches:
        for it in (pj.get("oneway_fix") or []):
            try:
                ow_fix.add((str(it["u"]), str(it["v"])))
            except Exception:
                pass
    if ow_fix:
        log(f"[oneway修复] 待改双向的单向边: {len(ow_fix)} 条")
    resolved = []    # 与 patches 平行: (a_spec,b_spec,a_xy,b_xy)
    next_osm = maxosm + 1

    def register_split(fids, point):
        key = (frozenset(int(f) for f in fids),
               (round(point[0], 6), round(point[1], 6)))
        if key not in splits:
            splits[key] = {"fids": sorted(int(f) for f in fids), "point": point, "osm": None}
        return splits[key]

    for pj in patches:
        def resolve(side):
            sp = pj.get(side + "_node")
            if sp is not None:  # 显式现成节点
                xy = node_xy(sp)
                if xy is None:
                    log(f"!! {pj['name']} {side}_node={sp} 不存在")
                    sys.exit(1)
                return ("node", str(sp), xy)
            sp = pj.get(side + "_split")
            if sp is not None:  # 显式打断
                pt = tuple(sp["point"])
                fids = [int(f) for f in sp["fids"]]
                for f in fids:
                    if f not in fidmap:
                        log(f"!! {pj['name']} {side}_split fid={f} 不存在")
                        sys.exit(1)
                return ("split", fids, pt)
            # pgeom 锚: 新增节点 = 端点参考顶点在 v12 上的投影点 pgeom.
            # 直接打断"pgeom 所在的那条 v12 边", 新节点就落在 pgeom 上
            # (不再拿参考坐标/20m 节点盲猜), 保证端点接到 v12 真实贴住处
            pg = pj.get(side + "_pgeom")
            if pg is not None:
                xy = tuple(pg)
                d, fid, q, u, v = nearest_edge_proj(xy)
                if d > EDGE_SNAP or fid is None:
                    log(f"!! {pj['name']} {side}_pgeom 附近无网络(最近{d:.0f}m), 回退自动吸附")
                else:
                    for node, ndist in ((u, hav(q, node_xy(u)) if node_xy(u) else 1e18),
                                        (v, hav(q, node_xy(v)) if node_xy(v) else 1e18)):
                        if ndist <= EDGE_NODE_END:
                            log(f"  {pj['name']} {side} pgeom=({xy[0]:.6f},{xy[1]:.6f}) -> 恰在边端点节点 {node}")
                            return ("node", node, node_xy(node))
                    rf = uv_fid.get((v, u))
                    fids = [fid] + ([rf] if rf is not None else [])
                    log(f"  {pj['name']} {side} pgeom=({xy[0]:.6f},{xy[1]:.6f}) -> 打断 fid {fid} (距{d:.1f}m), 新节点=pgeom")
                    return ("split", fids, q)
            # 自动: 现成节点 -> 最近边打断
            xy = tuple(pj[side])
            osm, d = nearest_node(xy)
            if osm is not None and d <= NODE_SNAP:
                return ("node", osm, node_xy(osm))
            d, fid, q, u, v = nearest_edge_proj(xy)
            if d > EDGE_SNAP or fid is None:
                log(f"!! {pj['name']} {side} 附近无网络(最近{d:.0f}m), 跳过该补丁")
                return None
            # 若投影极靠近端点节点 -> 直接用节点
            for node, ndist in ((u, hav(q, node_xy(u)) if node_xy(u) else 1e18),
                                (v, hav(q, node_xy(v)) if node_xy(v) else 1e18)):
                if ndist <= EDGE_NODE_END:
                    return ("node", node, node_xy(node))
            rf = uv_fid.get((v, u))
            fids = [fid] + ([rf] if rf is not None else [])
            return ("split", fids, q)
        a = resolve("A")
        b = resolve("B")
        if a is None or b is None:
            resolved.append(None)
            continue
        # 收集 split 登记(不立刻分配 osm)
        def note(spec):
            if spec[0] == "split":
                register_split(spec[1], spec[2])
        note(a)
        note(b)
        resolved.append((a, b))

    # 给每个 split 分配 osm + 准备打断产物
    split_out = []   # dict: osm, fids, point
    for key, s in splits.items():
        s["osm"] = str(next_osm)
        next_osm += 1
        log(f"  [split@{s['point'][0]:.6f},{s['point'][1]:.6f}] fids={s['fids']} -> 新节点 osmid={s['osm']}")
        split_out.append(s)

    # 打断需要知道锚点坐标(现成节点坐标或 split point)
    def spec_xy(spec):
        return spec[2] if spec[0] == "node" else tuple(spec[2])

    # ---------- 3. 执行打断(SPLIT) ----------
    # 被删fid -> 新分段列表(records+geoms); 每个 split 处理其全部 fids
    cut_fids = set()
    new_rows, new_geoms = [], []
    next_fid = maxfid + 1
    for s in split_out:
        P = tuple(s["point"])
        for fid in s["fids"]:
            i = fidmap[fid]
            row = gdf.iloc[i]
            cs = list(line_of_fid(fid))
            if len(cs) < 2:
                continue
            # 找 P 所在段(投影法)
            j = 0
            bd = 1e18
            for k in range(len(cs) - 1):
                d, _ = d2seg(P, cs[k], cs[k + 1])
                if d < bd:
                    bd, j = d, k
            sA = list(cs[:j + 1]) + [P]
            sB = [P] + list(cs[j + 1:])
            u, v = str(row["u"]), str(row["v"])
            cut_fids.add(fid)
            for su, sv, scs in [(u, s["osm"], sA), (s["osm"], v, sB)]:
                if hav(scs[0], scs[1]) < 0.5:
                    continue
                rec = {c: row[c] for c in attr}
                rec["u"], rec["v"] = su, sv
                rec["fid"] = next_fid
                rec["length"] = line_len(scs)
                if (str(row["u"]), str(row["v"])) in ow_fix:
                    rec["oneway"] = "False"      # [v16] 单向冲突边改双向
                next_fid += 1
                new_rows.append(rec)
                new_geoms.append(LineString(scs))
            log(f"    fid={fid}({u}->{v}) 于({P[0]:.6f},{P[1]:.6f}) -> 2 段")

    # ---------- 4. 新增双向边(JOIN) ----------
    def tmpl_near(xy, near_osm=None):
        x0, y0 = xy[0] - 0.004, xy[1] - 0.004
        x1, y1 = xy[0] + 0.004, xy[1] + 0.004
        dfe = pyogrio.read_dataframe(EDSRC, bbox=(x0, y0, x1, y1))
        for i in range(len(dfe)):
            u, v = str(dfe["u"].iloc[i]), str(dfe["v"].iloc[i])
            if near_osm is not None and (u == near_osm or v == near_osm) \
                    and str(dfe["reversed"].iloc[i]) == "False":
                return {c: dfe[c].iloc[i] for c in attr}
        for i in range(len(dfe)):
            if str(dfe["reversed"].iloc[i]) == "False":
                return {c: dfe[c].iloc[i] for c in attr}
        return None

    join_osm = []
    done_pairs = set()   # 已补过的节点对(防同一处重复补)
    for k, pj in enumerate(patches):
        if resolved[k] is None:
            continue
        a, b = resolved[k]
        # u/v osmid
        uo = a[1] if a[0] == "node" else next((s["osm"] for s in split_out
                                               if frozenset(s["fids"]) == frozenset(a[1])
                                               and hav(s["point"], a[2]) < 1.0), None)
        vo = b[1] if b[0] == "node" else next((s["osm"] for s in split_out
                                               if frozenset(s["fids"]) == frozenset(b[1])
                                               and hav(s["point"], b[2]) < 1.0), None)
        if uo is None or vo is None:
            log(f"!! {pj['name']} 端点解析失败, 跳过")
            continue
        if uo == vo:
            log(f"!! {pj['name']} 两端同节点, 跳过")
            continue
        # [v16完善] ①同一对节点只补一次(防两条补丁落在同一处) ②基网已直连则不补
        pair = frozenset((uo, vo))
        if pair in done_pairs:
            log(f"  [跳过-重复] {pj['name']} 与已补补丁同一对节点 {uo}<->{vo}")
            continue
        if uv_fid.get((uo, vo)) is not None or uv_fid.get((vo, uo)) is not None:
            log(f"  [跳过-已连通] {pj['name']} 基网已存在 {uo}<->{vo} 直连边, 无需补")
            continue
        axy = spec_xy(a)
        bxy = spec_xy(b)
        geom_pts = pj.get("geom")
        if geom_pts and len(geom_pts) >= 2:
            cs_ab = [tuple(g) for g in geom_pts]
            cs_ab[0], cs_ab[-1] = axy, bxy
        else:
            cs_ab = [axy, bxy]
        # 去重(防闭合)
        dd = []
        for q in cs_ab:
            if not dd or hav(dd[-1], q) > 0.5:
                dd.append(q)
        cs_ab = dd
        if len(cs_ab) < 2:
            continue
        cs_ba = list(reversed(cs_ab))
        tmpl = tmpl_near(bxy, vo) or tmpl_near(axy, uo)
        if tmpl is None:
            tmpl = {c: gdf.iloc[0][c] for c in attr}
        for su, sv, rev, cs in [(uo, vo, "False", cs_ab), (vo, uo, "True", cs_ba)]:
            rec = {c: tmpl[c] for c in attr}
            rec["u"], rec["v"] = su, sv
            rec["fid"] = next_fid
            rec["oneway"] = "False"
            rec["reversed"] = rev
            rec["length"] = line_len(cs)
            rec["name"] = None
            next_fid += 1
            new_rows.append(rec)
            new_geoms.append(LineString(cs))
        join_osm.append((uo, vo))
        done_pairs.add(pair)
        log(f"  [join {pj.get('name','')}] {uo}->{vo} len={line_len(cs_ab):.1f}m  ({pj.get('tid')})")

    # ---------- 5. 写回 edges ----------
    keep = gdf.loc[~gdf["fid"].isin(cut_fids)].copy()
    # [v16] oneway 修复: 把冲突的单向边改为双向
    if ow_fix:
        fix_n = 0
        uu = keep["u"].astype(str)
        vv = keep["v"].astype(str)
        for (u, v) in ow_fix:
            m = (uu == u) & (vv == v)
            if m.any():
                keep.loc[m, "oneway"] = "False"
                fix_n += int(m.sum())
        log(f"[oneway修复] 已在 edges 上把 {fix_n} 行改为双向(oneway=False)")
    ng = gpd.GeoDataFrame(new_rows, geometry=new_geoms, crs=gdf.crs)
    out = pd.concat([keep[attr + ["geometry"]], ng], ignore_index=True)
    log(f"写 edges: 原{len(gdf)} - 删{len(cut_fids)} + 增{len(new_rows)} = {len(out)} 行, maxfid={next_fid - 1}")
    out.to_file(ED, driver="ESRI Shapefile", engine="pyogrio", encoding=ENCODING)

    # ---------- 6. 写回 nodes(追加新节点) ----------
    gnd = gpd.read_file(ND, engine="pyogrio", encoding=ENCODING)
    ncols = [c for c in gnd.columns if c != "geometry"]
    nrecs, ngeoms = [], []
    for s in split_out:
        osm = int(s["osm"])
        P = tuple(s["point"])
        r = {c: None for c in ncols}
        if "osmid" in r:
            r["osmid"] = osm
        if "x" in r:
            r["x"] = P[0]
        if "y" in r:
            r["y"] = P[1]
        nrecs.append(r)
        ngeoms.append(Point(P))
    if nrecs:
        nout = pd.concat([gnd[ncols + ["geometry"]],
                          gpd.GeoDataFrame(nrecs, geometry=ngeoms, crs=gnd.crs)], ignore_index=True)
        log(f"写 nodes: 原{len(gnd)} + 增{len(nrecs)} = {len(nout)} 行")
        nout.to_file(ND, driver="ESRI Shapefile", engine="pyogrio", encoding=ENCODING)

    # ---------- 7. 自检(内存对照, 不再查 shp -> 提速) ----------
    log("\n===== 自检 =====")
    ok = True
    left_n = int(out["fid"].isin(cut_fids).sum()) if cut_fids else 0
    log(f"被打断旧边残留: {left_n} (期望0)")
    ok &= left_n == 0
    log(f"新增节点: {len(split_out)} 个")
    for s in split_out:
        log(f"新节点 {s['osm']} @({s['point'][0]:.6f},{s['point'][1]:.6f})")
    for uo, vo in join_osm:
        c1 = int(((out["u"].astype(str) == uo) & (out["v"].astype(str) == vo)).sum())
        c2 = int(((out["u"].astype(str) == vo) & (out["v"].astype(str) == uo)).sum())
        log(f"join {uo}->{vo}: 正向{c1}, 反向{c2} (期望各1)")
        ok &= c1 == 1 and c2 == 1
    log(f"新路网: {OUT_NET}")
    log("DONE" if ok else "DONE(有异常, 请查上面 !!)")


if __name__ == "__main__":
    main()
