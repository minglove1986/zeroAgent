""".drawio 布局质量检查（替代目检的几何验证）。

检查项：
1. 顶点盒子两两重叠检测
2. 节点是否越出所属背景框 / 画布边界
3. 标签文字估算宽度是否溢出盒子
4. 边的实际路径（sourcePoint → Array points → targetPoint）是否穿越非端点节点盒子

用法: python scripts/check_layout.py <file.drawio>
退出码: 0 = 无问题, 1 = 存在问题
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET


def cjk_len(s: str) -> tuple[int, int]:
    """返回 (CJK 字符数, 非 CJK 字符数)。"""
    cjk = sum(1 for ch in s if "一" <= ch <= "鿿" or "　" <= ch <= "〿")
    return cjk, len(s) - cjk


def est_width(text: str, font_size: float) -> float:
    """粗略估算渲染宽度：CJK ≈ 1.0*fs，其余 ≈ 0.55*fs。"""
    cjk, other = cjk_len(text)
    return (cjk * 1.0 + other * 0.55) * font_size


def parse(path: str):
    root = ET.parse(path).getroot()
    graph = root.find(".//mxGraphModel")
    cells = []
    for c in graph.findall(".//mxCell"):
        cid = c.get("id")
        if not cid or c.get("edge") == "1":
            continue
        g = c.find("mxGeometry")
        if g is None:
            continue
        try:
            x, y = float(g.get("x")), float(g.get("y"))
            w, h = float(g.get("width")), float(g.get("height"))
        except (TypeError, ValueError):
            continue
        style = c.get("style") or ""
        value = (c.get("value") or "").replace("<br/>", "\n").replace("&lt;br/&gt;", "\n")
        font = 11.0
        m = re.search(r"fontSize=(\d+)", style)
        if m:
            font = float(m.group(1))
        cells.append({"id": cid, "x": x, "y": y, "w": w, "h": h,
                      "style": style, "value": value, "font": font,
                      "is_band": "fillColor=none" in style})
    return cells


def parse_edges(path: str):
    """解析边，返回 [{id, src, dst, pts: [(x,y),...]}]。

    pts 顺序：sourcePoint → Array points → targetPoint，即边的实际路径。
    无显式路径的边 pts 为空列表。
    """
    root = ET.parse(path).getroot()
    graph = root.find(".//mxGraphModel")
    edges = []
    for c in graph.findall(".//mxCell"):
        if c.get("edge") != "1":
            continue
        cid = c.get("id")
        src = c.get("source")
        dst = c.get("target")
        pts = []
        g = c.find("mxGeometry")
        if g is not None:
            sp = g.find("mxPoint[@as='sourcePoint']")
            if sp is not None:
                pts.append((float(sp.get("x")), float(sp.get("y"))))
            arr = g.find("Array")
            if arr is not None:
                for mp in arr.findall("mxPoint"):
                    pts.append((float(mp.get("x")), float(mp.get("y"))))
            tp = g.find("mxPoint[@as='targetPoint']")
            if tp is not None:
                pts.append((float(tp.get("x")), float(tp.get("y"))))
        edges.append({"id": cid, "src": src, "dst": dst, "pts": pts})
    return edges


def overlap(a, b) -> bool:
    return not (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"]
                or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])


def seg_crosses_box(x1, y1, x2, y2, box) -> bool:
    """检查水平/垂直线段是否穿过盒子内部（不含边界）。"""
    bx, by, bw, bh = box["x"], box["y"], box["w"], box["h"]
    bx2, by2 = bx + bw, by + bh
    if abs(y1 - y2) < 0.5:  # 水平段
        y = y1
        if by < y < by2:
            xmin, xmax = min(x1, x2), max(x1, x2)
            if xmin < bx2 and xmax > bx:
                return True
        return False
    if abs(x1 - x2) < 0.5:  # 垂直段
        x = x1
        if bx < x < bx2:
            ymin, ymax = min(y1, y2), max(y1, y2)
            if ymin < by2 and ymax > by:
                return True
        return False
    return False


def check(path: str) -> list[str]:
    problems: list[str] = []
    cells = parse(path)

    nodes = [c for c in cells if not c["is_band"] and c["value"].strip()
             and not c["id"].endswith("_lbl")]
    bands = [c for c in cells if c["is_band"]]

    # 1. 节点两两重叠
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if overlap(nodes[i], nodes[j]):
                problems.append(f"节点重叠: {nodes[i]['id']} 与 {nodes[j]['id']}")

    # 2. 背景框两两重叠
    for i in range(len(bands)):
        for j in range(i + 1, len(bands)):
            if overlap(bands[i], bands[j]):
                problems.append(f"背景框重叠: {bands[i]['id']} 与 {bands[j]['id']}")

    # 3. 节点越界（画布 + 所属背景框）。层标签(_lbl)属于背景框一部分，不参与边距检查
    canvas_w, canvas_h = 1600.0, 1200.0
    for n in nodes:
        if n["id"].endswith("_lbl"):
            continue
        if n["x"] < 0 or n["y"] < 0 or n["x"] + n["w"] > canvas_w or n["y"] + n["h"] > canvas_h:
            problems.append(f"节点越出画布: {n['id']} ({n['x']},{n['y']},{n['w']},{n['h']})")
        cx, cy = n["x"] + n["w"] / 2, n["y"] + n["h"] / 2
        for b in bands:
            if b["x"] <= cx <= b["x"] + b["w"] and b["y"] <= cy <= b["y"] + b["h"]:
                margin_ok = (n["x"] - b["x"] >= 30 and b["x"] + b["w"] - (n["x"] + n["w"]) >= 30
                             and n["y"] - b["y"] >= 24 and b["y"] + b["h"] - (n["y"] + n["h"]) >= 24)
                if not margin_ok:
                    problems.append(f"节点 {n['id']} 与背景框 {b['id']} 边距不足 30px")
                break

    # 4. 文字估算溢出
    for n in nodes:
        for line in n["value"].split("\n"):
            line = line.strip()
            if not line:
                continue
            ew = est_width(line, n["font"])
            if ew > n["w"] * 0.98:
                problems.append(f"文字可能溢出: {n['id']} 行「{line[:30]}...」估宽 {ew:.0f}px > 盒宽 {n['w']:.0f}px")

    # 5. 边路径穿越非端点盒子
    edges = parse_edges(path)
    for e in edges:
        pts = e["pts"]
        if len(pts) < 2:
            continue  # 无显式路径的短边跳过
        src_id, dst_id = e["src"], e["dst"]
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            for c in cells:
                if c["id"] in (src_id, dst_id) or c["is_band"]:
                    continue
                if not c["value"].strip() or c["id"].endswith("_lbl"):
                    continue
                if seg_crosses_box(x1, y1, x2, y2, c):
                    problems.append(
                        f"边 {e['id']} 段 ({x1:.0f},{y1:.0f})→({x2:.0f},{y2:.0f}) 穿越节点 {c['id']}")

    return problems


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python scripts/check_layout.py <file.drawio>")
        sys.exit(2)
    errs = check(sys.argv[1])
    if errs:
        print(f"LAYOUT-FAIL: {sys.argv[1]}")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    print(f"LAYOUT-OK: {sys.argv[1]} 布局检查通过（无重叠/越界/溢出/穿越）")
    sys.exit(0)
