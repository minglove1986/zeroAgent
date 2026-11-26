"""Prompt 统一常量管理回归测试。

校验：原导入路径 re-export 不变、动态拼装结果正确、业务模块无内联 LLM 提示词。

@author 赵振明
@date 2026-11-26 10:15:10
"""

from __future__ import annotations

from pathlib import Path

from app.modules.agent.graph.planner_prompt import build_planner_system_prompt
from app.modules.conversation import context_blocks
from app.modules.knowledge.doc_analyze_graph import _task_system_prompt, _task_user_prompt
from app.modules.system import persona_seed, platform_safety
from app.prompts import agent, knowledge, system

_MODULES_DIR = Path(__file__).resolve().parents[1] / "src" / "app" / "modules"


def test_reexport_keeps_old_import_paths() -> None:
    """旧路径导入的必须与 app.prompts 为同一对象，避免出现两份文案。"""
    assert context_blocks.SOURCE_BOUNDARY_RULE is system.SOURCE_BOUNDARY_RULE
    assert platform_safety.PLATFORM_SAFETY_RULE is system.PLATFORM_SAFETY_RULE
    assert persona_seed.DEFAULT_PERSONA_PROMPT is system.DEFAULT_PERSONA_PROMPT


def test_planner_prompt_composition() -> None:
    """Planner 提示 = 头 + 技能目录 + 规则 + 动态黑名单/失败原因。"""
    out = build_planner_system_prompt(
        [{"id": "s1", "name": "搜索", "description": "d"}],
        blacklist=[{"kind": "rag", "skill_id": None}],
        last_failure="no_recall",
    )
    assert out.startswith(agent.PLANNER_SYSTEM_HEAD)
    assert "- s1: 搜索" in out
    assert agent.PLANNER_SYSTEM_RULES in out
    assert out.endswith("禁止选用（黑名单）：rag:-\n上次失败：no_recall\n")


def test_doc_analyze_prompt_templates_tolerate_braces() -> None:
    """正文含花括号时 format 不得抛错（正文仅作实参）。"""
    body = '{"a": 1} {x}'
    text = _task_user_prompt(task="summarize", title="标题", body=body, query="问")
    assert text == "文档标题：标题\n任务：summarize\n用户问题：问\n\n请总结以下文档：\n\n" + body
    assert _task_system_prompt("dump") == knowledge.DOC_ANALYZE_SYSTEM_DUMP
    assert _task_system_prompt("critique") == knowledge.DOC_ANALYZE_SYSTEM_CRITIQUE
    assert _task_system_prompt("summarize") == knowledge.DOC_ANALYZE_SYSTEM_SUMMARY


def test_no_inline_role_prompt_in_modules() -> None:
    """业务模块禁止再内联「你是…」角色提示词，须统一放 app/prompts。"""
    offenders: list[str] = []
    for path in _MODULES_DIR.rglob("*.py"):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if '"你是' in line or "'你是" in line:
                offenders.append(f"{path.relative_to(_MODULES_DIR)}:{no}")
    assert not offenders, f"发现内联 prompt，请迁移到 app/prompts: {offenders}"
