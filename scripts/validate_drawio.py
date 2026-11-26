"""校验 .drawio XML 的结构完整性与引用一致性。

用法: python scripts/validate_drawio.py <file.drawio>
退出码: 0 = 通过, 1 = 存在错误, 2 = 用法错误
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET


def validate(path: str) -> list[str]:
    errors: list[str] = []
    try:
        root = ET.parse(path).getroot()
    except FileNotFoundError:
        return [f"文件不存在: {path}"]
    except ET.ParseError as exc:
        return [f"XML 解析失败: {exc}"]

    if root.tag != "mxfile":
        errors.append(f"根元素应为 <mxfile>，实际为 <{root.tag}>")
        return errors

    graph = root.find(".//mxGraphModel")
    if graph is None:
        return errors + ["缺少 <mxGraphModel> 节点"]

    cells = graph.findall(".//mxCell")
    ids = {c.get("id") for c in cells if c.get("id")}

    for cell in cells:
        cid = cell.get("id") or "?"
        for attr in ("source", "target", "parent"):
            rid = cell.get(attr)
            if rid and rid not in ids and rid != "1":
                errors.append(f"cell {cid} 的 {attr}={rid} 不存在")
        if cell.get("edge") == "1":
            style = cell.get("style") or ""
            if "edgeStyle=orthogonalEdgeStyle" not in style:
                errors.append(f"边 {cid} 未使用 orthogonalEdgeStyle")
        if cell.get("vertex") == "1":
            style = cell.get("style") or ""
            if "background=" in style or "background:#" in style:
                errors.append(f"顶点 {cid} 设置了背景色（应透明）")

    values = [c.get("value") or "" for c in cells]
    if not any(("拓扑" in v or "架构" in v) for v in values):
        errors.append("缺少标题文本（应含「拓扑」或「架构」）")

    edges = [c for c in cells if c.get("edge") == "1"]
    if not edges:
        errors.append("没有任何连接线（edge）")
    return errors


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python scripts/validate_drawio.py <file.drawio>")
        sys.exit(2)
    errs = validate(sys.argv[1])
    if errs:
        print(f"FAIL: {sys.argv[1]}")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    print(f"OK: {sys.argv[1]} 结构校验通过")
    sys.exit(0)
