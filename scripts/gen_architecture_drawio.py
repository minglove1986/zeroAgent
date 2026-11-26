"""生成 zeroAgent 系统架构图 → docs/02-架构设计/zeroagent-architecture.drawio

用法: python scripts/gen_architecture_drawio.py
数据来源: 2026-11-24 源码盘点（src/app/modules、src/app/api/v1/router.py、src/app/models）
设计原则: 五层泳道，层高含标签空间，盒子距层边 ≥30px；层间留 40px 间隙走线；
         边用显式路径点绕开所有盒子，核心连接 12 条，其余用盒子内文字标注。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from drawio_common import band, cell, edge, mxfile  # noqa: E402

OUT = os.path.join("docs", "02-架构设计", "zeroagent-architecture.drawio")


def build() -> str:
    bands, nodes, edges = [], [], []

    # ---- 标题与图例（不重叠：title 150..790，legend 800..1580）----
    nodes.append(cell("title", "<b>ZeroAgent 系统架构图</b>",
                      150, 20, 640, 30,
                      "text;html=1;fontSize=20;fontStyle=1;fontColor=#333333;"))
    nodes.append(cell("legend", "图例：接入层 ▶ API层 ▶ Agent编排 ▶ 能力模块 ▶ 数据/基础设施；箭头=调用方向",
                      800, 28, 780, 24,
                      "text;html=1;fontSize=11;fontColor=#666666;"))

    # ---- 分层背景框（层高 = 标签24 + 上边距30 + 内容 + 下边距30）----
    for cid, label, y, h, c in [
        ("band_web",   "接入层（前端 Next.js）",   50,  160, "#D5E8FF"),   # 50..210
        ("band_api",   "API 层（FastAPI）",       250, 140, "#D5F5E3"),   # 250..390
        ("band_agent", "Agent 编排层（LangGraph）", 430, 150, "#E8DAEF"),  # 430..580
        ("band_cap",   "能力模块层",               620, 260, "#FAD7A0"),  # 620..880（两行）
        ("band_infra", "数据 / 基础设施层",        920, 150, "#E5E8E8"),  # 920..1070
    ]:
        bands.append(band(cid, label, 40, y, 1520, h, c))

    def box(cid, label, x, y, w, h, c):
        nodes.append(cell(cid, label, x, y, w, h,
                          f"rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={c};strokeWidth=2;fontSize=12;"))

    # 接入层 (y=80, h=100)
    box("web_staff", "web/（员工端 :3000）<br/>chat · agents · knowledge · memories",
        100, 80, 400, 100, "#4A90D9")
    box("web_admin", "admin-web/（管理端 :3001）<br/>overview · agents · knowledge · knowledge-graph<br/>models · operations · organization · skills · system · workflows",
        560, 80, 520, 100, "#4A90D9")

    # API 层 (y=280, h=80)
    box("api_core", "core/<br/>config · security · permissions<br/>request_id · response · redis_client",
        100, 280, 300, 80, "#27AE60")
    box("api_v1", "api/v1/（31 路由）<br/>auth · users · sessions · agents<br/>knowledge · memories · workflows<br/>approvals · llm_models · usage<br/>notifications · prompts · audit",
        440, 280, 420, 80, "#27AE60")
    box("api_main", "main.py<br/>lifespan 启动加载 Catalog<br/>CORS · Session · 中间件",
        900, 280, 280, 80, "#27AE60")

    # Agent 层 (y=460, h=90)
    box("agent_conv", "modules/conversation/<br/>turn_graph · route · context_compress<br/>intent_node · kb_lookup · doc_analyze",
        100, 460, 320, 90, "#8E44AD")
    box("agent_intent", "modules/intent/<br/>funnel · classifier · rules · gates<br/>thresholds · memory_signal",
        460, 460, 300, 90, "#8E44AD")
    box("agent_graph", "modules/agent/graph/<br/>plan_execute · skill_react<br/>plan_replan · plan_normalize",
        800, 460, 320, 90, "#8E44AD")
    box("agent_skill", "modules/agent/<br/>skill_tools · skill_prompt",
        1160, 460, 280, 90, "#8E44AD")

    # 能力模块层 行1 (y=650, h=90)
    box("cap_llm", "modules/llm/<br/>gateway · client · model_chain<br/>context_budget · tokens",
        100, 650, 300, 90, "#E67E22")
    box("cap_kb", "modules/knowledge/<br/>ingest · chunking · bm25 · search<br/>kb_milvus · permissions · publish",
        460, 650, 300, 90, "#E67E22")
    box("cap_mem", "modules/memory/<br/>service · extract_scheduler<br/>milvus_store · embedding",
        820, 650, 300, 90, "#E67E22")
    box("cap_tool", "modules/tool/<br/>registry · executor",
        1180, 650, 280, 90, "#E67E22")

    # 能力模块层 行2 (y=760, h=90)
    box("cap_ws", "modules/web_search/<br/>facade · providers(baidu/searxng)",
        100, 760, 300, 90, "#E67E22")
    box("cap_wf", "modules/workflow/<br/>engine（技能 workflow_call）",
        460, 760, 300, 90, "#E67E22")
    box("cap_appr", "approval · notification · feedback<br/>audit · alert · sessions<br/>usage · vector",
        820, 760, 300, 90, "#E67E22")
    box("cap_sys", "modules/system/<br/>persona · platform_safety<br/>modules/litellm/ http_client",
        1180, 760, 280, 90, "#E67E22")

    # 数据 / 基础设施层 (y=950, h=90)
    box("infra_mysql", "MySQL（models/ 19 模型）<br/>用户·会话·知识·记忆·工作流<br/>审批·用量·通知·审计",
        100, 950, 300, 90, "#95A5A6")
    box("infra_redis", "Redis<br/>缓存 / 会话 / Catalog 缓存",
        460, 950, 300, 90, "#95A5A6")
    box("infra_rabbit", "RabbitMQ + Celery<br/>ingest_document · extract_memories<br/>compress_context · expire_approvals<br/>process_message_feedback · parent_summary",
        820, 950, 380, 90, "#95A5A6")
    box("infra_milvus", "Milvus（向量）<br/>+ Neo4j（知识图谱）<br/>+ OSS（shared/oss.py）",
        1240, 950, 260, 90, "#95A5A6")

    # ---- 边（12 条，显式路径，走层间 40px 间隙）----
    # 接入层 → API 层（间隙 y=210..250）
    edges.append(edge("a1", "web_staff", "api_v1",
                      src_pt=(300, 180), dst_pt=(440, 280),
                      points=[(300, 230), (440, 230)]))
    edges.append(edge("a2", "web_admin", "api_v1",
                      src_pt=(820, 180), dst_pt=(650, 280),
                      points=[(820, 230), (650, 230)]))
    # API 层内部
    edges.append(edge("a3", "api_core", "api_v1",
                      src_pt=(400, 320), dst_pt=(440, 320)))
    # API 层 → Agent 层（间隙 y=390..430）
    edges.append(edge("a4", "api_v1", "agent_conv", "对话入口",
                      src_pt=(650, 360), dst_pt=(260, 460),
                      points=[(650, 400), (260, 400)]))
    # Agent 层内部
    edges.append(edge("a5", "agent_conv", "agent_intent", "意图识别",
                      src_pt=(420, 505), dst_pt=(460, 505)))
    edges.append(edge("a6", "agent_intent", "agent_graph",
                      src_pt=(760, 505), dst_pt=(800, 505)))
    edges.append(edge("a7", "agent_graph", "agent_skill",
                      src_pt=(1120, 505), dst_pt=(1160, 505)))
    # Agent 层 → 能力模块层（间隙 y=580..620）
    edges.append(edge("a8", "agent_conv", "cap_kb", "知识检索",
                      src_pt=(260, 550), dst_pt=(610, 650),
                      points=[(260, 600), (610, 600)]))
    edges.append(edge("a9", "agent_graph", "cap_llm", "LLM 调用",
                      src_pt=(960, 550), dst_pt=(250, 650),
                      points=[(960, 610), (250, 610)]))
    edges.append(edge("a10", "agent_graph", "cap_mem", "记忆读写",
                      src_pt=(960, 550), dst_pt=(970, 650),
                      points=[(960, 650)]))
    edges.append(edge("a11", "agent_graph", "cap_tool", "工具执行",
                      src_pt=(1120, 550), dst_pt=(1320, 650),
                      points=[(1120, 600), (1320, 600)]))
    edges.append(edge("a12", "agent_intent", "cap_ws", "联网搜索",
                      src_pt=(610, 550), dst_pt=(250, 760),
                      points=[(610, 600), (430, 600), (430, 740), (250, 740)]))

    return mxfile("".join(bands + edges + nodes))


if __name__ == "__main__":
    xml_text = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(xml_text)
    print(f"written: {OUT} ({len(xml_text)} bytes)")
