"""draw.io XML 生成公共库（遵循 draw-io 技能规范：原子写入、正交边、透明背景、6 位 hex 色）。

- 所有单元格 parent=1（根级），坐标均为绝对坐标；
- 组装顺序：背景框(bands) → 连接线(edges) → 节点(nodes)，保证箭头压在背景框上、节点压在箭头上。
"""
from __future__ import annotations

import xml.sax.saxutils as su

HEADER = (
    '<mxfile host="hermes-agent" type="device" modified="2026-11-24T15:00:00.000Z" '
    'agent="hermes" version="24.0.0">\n'
)


def esc(s: str) -> str:
    return su.escape(s, {'"': "&quot;"})


def cell(cid, value, x, y, w, h, style, parent="1", edge=False, geometry=None):
    """生成一个 mxCell 字符串。"""
    attrs = f'id="{cid}" value="{esc(value)}" style="{style}"'
    if edge:
        attrs += ' edge="1"'
    else:
        attrs += ' vertex="1"'
    attrs += f' parent="{parent}"'
    if geometry is None:
        geometry = f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />'
    return f'<mxCell {attrs}>{geometry}</mxCell>\n'


def band(cid, label, x, y, w, h, color):
    """生成一个分层背景框（透明底、彩色边框 + 左上角层标签）。"""
    bg = cell(cid, "", x, y, w, h,
              f'rounded=1;fillColor=none;strokeColor={color};strokeWidth=2;dashed=0;')
    label_cell = cell(f"{cid}_lbl", label, x + 8, y + 4, w - 16, 24,
                      f'text;html=1;fontSize=14;fontStyle=1;align=left;'
                      f'verticalAlign=middle;fontColor={color};')
    return bg + label_cell


def edge(cid, src, dst, label="", entry="entryX=0.5;entryY=0;exitX=0.5;exitY=1;",
         points=None, src_pt=None, dst_pt=None):
    """生成正交边，支持显式路径。

    points: 中间拐点列表 [(x,y), ...]，边按此路径绕行；
    src_pt/dst_pt: 显式源/目标点 (x, y)，缺省由 entry/exit 自动计算。
    """
    lbl = 'edgeLabel=1;html=1;fontSize=11;' if label else ""
    style = f'edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;{lbl}{entry}'
    val = esc(label) if label else ""
    geo_parts = []
    if src_pt:
        geo_parts.append(f'<mxPoint x="{src_pt[0]}" y="{src_pt[1]}" as="sourcePoint" />')
    if dst_pt:
        geo_parts.append(f'<mxPoint x="{dst_pt[0]}" y="{dst_pt[1]}" as="targetPoint" />')
    if points:
        pts = "".join(f'<mxPoint x="{p[0]}" y="{p[1]}" />' for p in points)
        geo_parts.append(f'<Array as="points">{pts}</Array>')
    geo = f'<mxGeometry relative="1" as="geometry">{"".join(geo_parts)}</mxGeometry>'
    return (f'<mxCell id="{cid}" value="{val}" style="{style}" edge="1" '
            f'parent="1" source="{src}" target="{dst}">{geo}</mxCell>\n')


def mxfile(cells_xml: str) -> str:
    """组装完整 mxfile（单页）。必须在内存中拼完后一次性写入，禁止分次写。"""
    return (
        HEADER
        + '<diagram id="page1" name="diagram">\n'
        + '<mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" '
        'gui="1" guides="1" tooltips="1" connect="1" arrows="1" '
        'fold="1" page="1" pageScale="1" pageWidth="1600" pageHeight="1200" '
        'math="0" shadow="0">\n'
        + '<root>\n'
        + '<mxCell id="0" />\n'
        + '<mxCell id="1" parent="0" />\n'
        + cells_xml
        + '</root>\n</mxGraphModel>\n</diagram>\n</mxfile>\n'
    )
