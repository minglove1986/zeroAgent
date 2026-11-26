"""生成 zeroAgent 系统拓扑图 → docs/02-架构设计/zeroagent-topology.drawio

用法: python scripts/gen_topology_drawio.py
数据来源: 2026-11-24 源码盘点（src/app、deploy/docker-compose.yml、README.md）
设计原则: 层高含标签空间，盒子距层边 ≥30px；层间留 40px 间隙走线；
         边用显式路径点绕开所有盒子，核心连接 8 条，其余用盒子内文字标注。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from drawio_common import band, cell, edge, mxfile  # noqa: E402

OUT = os.path.join("docs", "02-架构设计", "zeroagent-topology.drawio")

C_USER = "#D5E8FF"
C_WEB = "#D5E8FF"
C_APP = "#D5F5E3"
C_SVC = "#E8DAEF"
C_INFRA = "#FAD7A0"
C_CLOUD = "#E5E8E8"

BOX = "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={c};strokeWidth=2;fontSize=12;"


def build() -> str:
    bands, nodes, edges = [], [], []

    # ---- 标题与图例 ----
    nodes.append(cell("title", "<b>ZeroAgent 系统拓扑图</b>",
                      150, 20, 640, 30,
                      "text;html=1;fontSize=20;fontStyle=1;fontColor=#333333;"))

    legend = [("用户", C_USER), ("前端", C_WEB), ("应用", C_APP),
              ("服务", C_SVC), ("基础设施", C_INFRA), ("云服务", C_CLOUD)]
    lx = 150
    for name, color in legend:
        nodes.append(cell(f"lg_{name}", name, lx, 1060, 180, 24,
                          f"rounded=0;fillColor={color};strokeColor=#333333;fontSize=11;"))
        lx += 190

    # ---- 分层背景框（层高 = 标签24 + 上边距30 + 盒子高 + 下边距30）----
    for cid, label, y, h, c in [
        ("b_user",   "用户层",       50,  110, C_USER),    # 50..160
        ("b_web",    "前端层",       200, 130, C_WEB),    # 200..330
        ("b_app",    "应用层",       370, 140, C_APP),    # 370..510
        ("b_svc",    "服务层",       550, 140, C_SVC),    # 550..690
        ("b_infra",  "基础设施层",    730, 140, C_INFRA),  # 730..870
        ("b_cloud",  "云服务",       910, 110, C_CLOUD),  # 910..1020
    ]:
        bands.append(band(cid, label, 40, y, 1520, h, c))

    def box(cid, label, x, y, w, h, c):
        nodes.append(cell(cid, label, x, y, w, h, BOX.format(c=c)))

    # 用户层 (y=80, h=50)
    box("u_emp", "企业用户", 200, 80, 220, 50, "#4A90D9")
    box("u_adm", "管理员",   560, 80, 220, 50, "#4A90D9")

    # 前端层 (y=230, h=70)
    box("f_web", "Next.js Web :3000", 150, 230, 380, 70, "#4A90D9")
    box("f_adm", "Next.js 管理端 :3001", 620, 230, 420, 70, "#4A90D9")

    # 应用层 (y=400, h=80)
    box("a_api", "FastAPI API（src/app）<br/>:8000 · core/ 配置·安全·权限<br/>api/v1 共 31 路由",
        150, 400, 420, 80, "#27AE60")
    box("a_worker", "Celery Worker<br/>文档入库 / 记忆抽取 / 上下文压缩",
        650, 400, 380, 80, "#27AE60")
    box("a_beat", "Celery Beat<br/>定时调度", 1110, 400, 240, 80, "#27AE60")

    # 服务层 (y=580, h=80)
    box("s_litellm", "LiteLLM Proxy<br/>:4000 · LLM 网关<br/>→ Langfuse 追踪",
        150, 580, 300, 80, "#8E44AD")
    box("s_embed", "Embed / Rerank 服务<br/>:8088 · CPU 本地 BGE",
        520, 580, 340, 80, "#8E44AD")
    box("s_lf", "Langfuse<br/>LLM 可观测性", 930, 580, 260, 80, "#8E44AD")

    # 基础设施层 (y=760, h=80)
    box("i_mysql", "MySQL<br/>:3306<br/>API/Worker 读写",
        150, 760, 240, 80, "#E67E22")
    box("i_redis", "Redis<br/>:6379<br/>缓存 / 会话",
        450, 760, 240, 80, "#E67E22")
    box("i_rabbit", "RabbitMQ<br/>:5672<br/>任务队列（Worker 消费）",
        750, 760, 280, 80, "#E67E22")
    box("i_milvus", "Milvus<br/>standalone full<br/>向量检索",
        1070, 760, 270, 80, "#E67E22")
    box("i_neo4j", "Neo4j<br/>:7474 full<br/>知识图谱",
        1370, 760, 160, 80, "#E67E22")

    # 云服务 (y=940, h=50)
    box("i_oss", "阿里云 OSS（shared/oss.py）", 150, 940, 300, 50, "#95A5A6")

    # ---- 边（8 条，显式路径，走层间 40px 间隙）----
    # 用户 → 前端（间隙 y=160..200）
    edges.append(edge("e1", "u_emp", "f_web",
                      src_pt=(310, 130), dst_pt=(340, 230)))
    edges.append(edge("e2", "u_adm", "f_adm",
                      src_pt=(670, 130), dst_pt=(830, 230),
                      points=[(670, 180), (830, 180)]))
    # 前端 → 应用（间隙 y=330..370）
    edges.append(edge("e3", "f_web", "a_api",
                      src_pt=(340, 300), dst_pt=(360, 400)))
    edges.append(edge("e4", "f_adm", "a_api",
                      src_pt=(830, 300), dst_pt=(360, 400),
                      points=[(830, 350), (360, 350)]))
    # 应用 → 服务（间隙 y=510..550）
    edges.append(edge("e5", "a_api", "s_litellm", "LLM 调用",
                      src_pt=(360, 480), dst_pt=(300, 580),
                      points=[(360, 530), (300, 530)]))
    edges.append(edge("e6", "a_worker", "s_embed", "向量 / 重排",
                      src_pt=(840, 480), dst_pt=(690, 580),
                      points=[(840, 530), (690, 530)]))
    # 应用 → 基础设施（间隙 y=690..730）
    edges.append(edge("e7", "a_api", "i_mysql", "读写",
                      src_pt=(360, 480), dst_pt=(270, 760),
                      points=[(360, 530), (500, 530), (500, 710), (270, 710)]))
    edges.append(edge("e8", "a_worker", "i_rabbit", "消费任务",
                      src_pt=(840, 480), dst_pt=(890, 760),
                      points=[(840, 530), (900, 530), (900, 710), (890, 710)]))

    return mxfile("".join(bands + edges + nodes))


if __name__ == "__main__":
    xml_text = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(xml_text)
    print(f"written: {OUT} ({len(xml_text)} bytes)")
