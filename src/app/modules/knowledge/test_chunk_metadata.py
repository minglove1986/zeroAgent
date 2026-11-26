"""切块核心 metadata 与 Milvus expr 单测。

@author 赵振明
@date 2026-11-23 16:35:26
"""

from __future__ import annotations

from app.modules.knowledge.chunk_metadata import (
    MILVUS_DOC_ID_IN_LIMIT,
    build_core_metadata,
    build_milvus_filter_expr,
    merge_manual_patch,
    milvus_scalar_fields,
    schema_code_to_doc_type,
)
import pytest

from app.modules.knowledge import focus_lexicon
from app.modules.knowledge.entity_filter import extract_focus_slots


def test_schema_code_to_doc_type() -> None:
    """schema_code 映射为简码。"""
    assert schema_code_to_doc_type("schema_resume") == "resume"
    assert schema_code_to_doc_type("schema_policy") == "policy"
    assert schema_code_to_doc_type(None) == "generic"


def test_build_core_metadata_inherit() -> None:
    """从文档 meta 派生切块核心字段。"""
    meta = build_core_metadata(
        title="好友买项目说明",
        doc_meta={
            "person_name": "",
            "project_name": "好友买",
            "keywords": ["电商"],
        },
        category_codes=["biz.project"],
        primary_schema="schema_generic",
        chunk_text="好友买项目上线计划",
    )
    assert meta["schema_version"] == 1
    assert meta["title"] == "好友买项目说明"
    assert meta["doc_type"] == "generic"
    assert meta["project_name"] == "好友买"
    assert "电商" in meta["keywords"]
    assert meta["source"] == "inherit"
    assert meta["category_codes"] == ["biz.project"]


def test_build_core_metadata_infers_project_from_title_lexicon() -> None:
    """文档未填 project_name 时，标题命中专名词典应回填。"""
    focus_lexicon.clear_focus_lexicon_for_tests()
    focus_lexicon.seed_focus_lexicon(
        [{"term": "好友买", "aliases": ["hoolebuy"], "kind": "project", "priority": 100}]
    )
    try:
        meta = build_core_metadata(
            title="好友买项目介绍文档",
            doc_meta={},
            category_codes=[],
            primary_schema="schema_generic",
            chunk_text="项目背景",
        )
        assert meta["project_name"] == "好友买"
    finally:
        focus_lexicon.clear_focus_lexicon_for_tests()


def test_build_core_metadata_preserves_manual() -> None:
    """manual 源不覆盖非空手改键。"""
    existing = {
        "source": "manual",
        "person_name": "唐亮",
        "project_name": "",
        "keywords": ["手改"],
        "doc_type": "resume",
    }
    meta = build_core_metadata(
        title="简历",
        doc_meta={"person_name": "张三", "keywords": ["自动"]},
        category_codes=[],
        primary_schema="schema_resume",
        chunk_text="工作经历",
        existing=existing,
    )
    assert meta["source"] == "manual"
    assert meta["person_name"] == "唐亮"
    assert meta["doc_type"] == "resume"
    assert meta["keywords"] == ["手改"]
    # 空的 project_name 可被文档侧补上
    assert meta["project_name"] == ""


def test_merge_manual_patch_keywords_string() -> None:
    """管理端关键词字符串补丁。"""
    patched = merge_manual_patch(
        {"title": "t", "source": "inherit"},
        {"person_name": "李四", "keywords": "A, B，C"},
    )
    assert patched["source"] == "manual"
    assert patched["person_name"] == "李四"
    assert patched["keywords"] == ["A", "B", "C"]


def test_build_milvus_filter_expr_kb_and_names() -> None:
    """Milvus expr 含 kb_id 与专名 OR。"""
    expr = build_milvus_filter_expr(
        kb_ids=["kb1", "kb2"],
        person_names=["唐亮"],
        project_names=["好友买"],
        title_terms=["好友买"],
    )
    assert 'kb_id in ["kb1", "kb2"]' in expr
    assert 'person_name == "唐亮"' in expr
    assert 'project_name == "好友买"' in expr
    assert " or " in expr


def test_expr_person_not_in_project_name_clause() -> None:
    """人名槽只写 person_name，不得出现 project_name / title 条件。"""
    expr = build_milvus_filter_expr(kb_ids=["kb1"], person_names=["唐亮"])
    assert 'person_name == "唐亮"' in expr
    assert "project_name" not in expr
    assert "title" not in expr


def test_expr_project_slot_not_person() -> None:
    """项目槽不得写入 person_name。"""
    expr = build_milvus_filter_expr(kb_ids=["kb1"], project_names=["好友买"])
    assert 'project_name == "好友买"' in expr
    assert "person_name" not in expr


def test_expr_document_ids_in() -> None:
    """document_ids 下推为 document_id in [...]。"""
    expr = build_milvus_filter_expr(kb_ids=["kb1"], document_ids=["d1", "d2"])
    assert 'document_id in ["d1", "d2"]' in expr
    assert 'kb_id in ["kb1"]' in expr


def test_expr_never_category_codes_equality() -> None:
    """任何入参组合都不生成 category_codes / keywords 等值。"""
    expr = build_milvus_filter_expr(
        kb_ids=["kb1"],
        person_names=["唐亮"],
        project_names=["好友买"],
        title_terms=["简历"],
        doc_types=["resume"],
        document_ids=["d1"],
    )
    assert "category_codes" not in expr
    assert "keywords" not in expr


def test_expr_document_ids_overflow_omitted() -> None:
    """超过上限不写 document_id；恰好上限仍写入。"""
    over = [f"d{i}" for i in range(MILVUS_DOC_ID_IN_LIMIT + 1)]
    assert "document_id" not in build_milvus_filter_expr(kb_ids=["kb1"], document_ids=over)
    edge = over[:MILVUS_DOC_ID_IN_LIMIT]
    assert "document_id in" in build_milvus_filter_expr(kb_ids=["kb1"], document_ids=edge)


def test_expr_empty_document_ids_fail_closed() -> None:
    """空 document_ids 列表 → 恒不命中，不得放开为全库。"""
    expr = build_milvus_filter_expr(kb_ids=["kb1"], document_ids=[])
    assert 'document_id == ""' in expr


def test_expr_document_id_escaped() -> None:
    """document_id 含引号时转义，防表达式注入。"""
    expr = build_milvus_filter_expr(kb_ids=["kb1"], document_ids=['a"b'])
    assert 'document_id in ["a\\"b"]' in expr


def test_extract_focus_slots_person_and_project() -> None:
    """分槽：人名与项目各归各槽，互不重复。"""
    person = extract_focus_slots("唐亮是谁")
    assert person.persons == ("唐亮",)
    assert person.projects == ()

    project = extract_focus_slots("搜索下好友买项目的文档")
    assert project.projects == ("好友买",)
    assert project.persons == ()


def test_extract_focus_slots_empty_and_keywords() -> None:
    """空问句空槽；英文标识符进 keywords。"""
    assert extract_focus_slots("").is_empty()
    slots = extract_focus_slots("唐亮是谁 Milvus")
    assert slots.persons == ("唐亮",)
    assert "Milvus" in slots.keywords


@pytest.fixture
def clean_lexicon():
    """专名词典缓存隔离：用例前后清空。"""
    focus_lexicon.clear_focus_lexicon_for_tests()
    yield
    focus_lexicon.clear_focus_lexicon_for_tests()


def test_slots_lexicon_project_beats_person_heuristic(clean_lexicon) -> None:
    """词典 kind=project 的「好友买」：即使句式是「X是谁」也不得进 persons。"""
    focus_lexicon.seed_focus_lexicon(
        [{"term": "好友买", "aliases": ["友买"], "kind": "project", "priority": 100}]
    )
    for q in ("好友买是谁", "好友买", "搜索好友买", "友买是谁"):
        slots = extract_focus_slots(q)
        assert slots.persons == (), q
        assert slots.projects == ("好友买",), q


def test_slots_lexicon_kinds_route_to_slots(clean_lexicon) -> None:
    """词典 person / other 分别落 persons / titles。"""
    focus_lexicon.seed_focus_lexicon(
        [
            {"term": "唐亮", "aliases": [], "kind": "person", "priority": 100},
            {"term": "报销制度", "aliases": [], "kind": "other", "priority": 100},
        ]
    )
    slots = extract_focus_slots("唐亮 报销制度")
    assert slots.persons == ("唐亮",)
    assert slots.titles == ("报销制度",)
    assert slots.projects == ()


def test_slots_project_phrase_not_person(clean_lexicon) -> None:
    """「鸿蒙项目」→ projects=鸿蒙，不得出现 person「鸿蒙项目」。"""
    for q in ("鸿蒙项目", "搜索鸿蒙项目", "关于鸿蒙项目的文档"):
        slots = extract_focus_slots(q)
        assert slots.projects == ("鸿蒙",), q
        assert slots.persons == (), q


def test_slots_bare_term_not_person(clean_lexicon) -> None:
    """裸 2–4 字业务词（报销流程）无强后缀 → 不入 persons。"""
    for q in ("报销流程", "搜索报销流程", "报销流程的资料", "搜索唐亮"):
        assert extract_focus_slots(q).persons == (), q


def test_slots_strong_suffix_person_still_works(clean_lexicon) -> None:
    """强信号保留：X是谁 / X的简历 / 去前缀后「X的资料」。"""
    assert extract_focus_slots("唐亮是谁").persons == ("唐亮",)
    assert extract_focus_slots("唐亮的简历").persons == ("唐亮",)
    assert extract_focus_slots("搜索唐亮的资料").persons == ("唐亮",)


def test_slots_person_greedy_left_boundary(clean_lexicon) -> None:
    """左边界 + 贪婪：取最长人名，不取尾部碎片。"""
    assert extract_focus_slots("赵世龙是谁").persons == ("赵世龙",)
    assert extract_focus_slots("尹庆为的简历").persons == ("尹庆为",)
    assert extract_focus_slots("帮我看看唐亮是谁").persons == ("唐亮",)
    assert extract_focus_slots("请问赵世龙是谁？").persons == ("赵世龙",)
    assert extract_focus_slots("好的。尹庆为的简历").persons == ("尹庆为",)


def test_slots_lexicon_project_alias_only_ascii(clean_lexicon) -> None:
    """词典 project 好友买仅有英文别名：好友买是谁 → persons 空、projects=好友买。"""
    focus_lexicon.seed_focus_lexicon(
        [{"term": "好友买", "aliases": ["hoolebuy"], "kind": "project", "priority": 100}]
    )
    slots = extract_focus_slots("好友买是谁")
    assert slots.persons == ()
    assert slots.projects == ("好友买",)


def test_slots_other_lexicon_not_person(clean_lexicon) -> None:
    """「报销制度是谁制定的」+ other 词典 → persons 空、titles=报销制度。"""
    focus_lexicon.seed_focus_lexicon(
        [{"term": "报销制度", "aliases": [], "kind": "other", "priority": 100}]
    )
    slots = extract_focus_slots("报销制度是谁制定的")
    assert slots.persons == ()
    assert slots.titles == ("报销制度",)


def test_slots_drop_fragment_of_lexicon_term(clean_lexicon) -> None:
    """启发式人名若只是词典词的子串碎片（如 世龙 ⊂ 赵世龙项目词），不得进 persons。"""
    focus_lexicon.seed_focus_lexicon(
        [{"term": "赵世龙项目", "aliases": [], "kind": "project", "priority": 100}]
    )
    slots = extract_focus_slots("赵世龙项目是谁")
    assert slots.persons == ()
    assert slots.projects == ("赵世龙项目",)


def test_slots_project_stop_not_person(clean_lexicon) -> None:
    """泛词（文档/代码）不得因「是谁」句式进 persons。"""
    assert extract_focus_slots("代码是谁").persons == ()


def test_milvus_scalar_fields() -> None:
    """标量字段截断与拼接。"""
    fields = milvus_scalar_fields(
        {
            "title": "t",
            "doc_type": "resume",
            "person_name": "唐亮",
            "project_name": "",
            "keywords": ["a", "b"],
            "category_codes": ["hr.resume"],
        },
        chunk_role="child",
    )
    assert fields["keywords"] == "a,b"
    assert fields["category_codes"] == "hr.resume"
    assert fields["chunk_role"] == "child"
