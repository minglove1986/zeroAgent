"""通用 Metadata 抽取 / CoreMetadata 投影单测。

@author 赵振明
@date 2026-11-25 09:37:45
"""

from __future__ import annotations

from app.modules.knowledge.core_metadata import CoreMetadata, project_core_metadata
from app.modules.knowledge.metadata_extract import (
    extract_common_fields,
    extract_resume_metadata,
    guess_person_from_title,
    guess_project_from_title,
    merge_metadata_for_schemas,
)


def test_guess_person_from_title_hyphen_years() -> None:
    """文件名常识「-高扬 6年-」抽出人名。"""
    assert guess_person_from_title("14日下午三点半-高扬 6年-前端.pdf") == "高扬"


def test_guess_project_from_title() -> None:
    """标题常识「好友买项目介绍」抽出项目名。"""
    assert guess_project_from_title("好友买项目介绍文档.pdf") == "好友买"


def test_project_label_requires_colon() -> None:
    """「新项目搭建…」不得误写入 project_name。"""
    meta = extract_common_fields(
        "将新项目搭建时间缩短 40%。\n项目名称：学支联",
        title="简历.pdf",
    )
    assert meta.get("project_name") == "学支联"


def test_extract_common_no_tech_whitelist() -> None:
    """关键词来自标识符/章节，不依赖 Vue 白名单写死。"""
    text = """高扬
男 | 年龄：28岁 |
gy_98031@163.com
核心技能
Vue.js、Uni-app、CSS3、Element UI
工作经历
某某公司
"""
    meta = extract_common_fields(
        text, title="14日下午三点半-高扬 6年-前端.pdf"
    )
    assert meta["person_name"] == "高扬"
    assert "Vue.js" in meta["keywords"] or "CSS3" in meta["keywords"]
    assert "种过渡动画" not in meta.get("keywords", [])


def test_extract_resume_extends_common() -> None:
    """简历 schema 只追加扩展字段，核心仍走通用对象。"""
    text = """高扬
男 | 28岁
gy_98031@163.com
6年工作经验 | 求职意向：前端开发工程师
精通 React Native 与 TypeScript
"""
    meta = extract_resume_metadata(
        text, title="14日下午三点半-高扬 6年-前端.pdf"
    )
    assert meta["person_name"] == "高扬"
    assert meta["email"] == "gy_98031@163.com"
    assert meta["years_experience"] == 6
    assert meta["target_title"] == "前端开发工程师"


def test_project_core_metadata_object() -> None:
    """Document bag 投影为 CoreMetadata 再回填。"""
    core = project_core_metadata(
        title="好友买项目说明",
        doc_meta={"project_name": "好友买", "keywords": ["电商"]},
        category_codes=["biz.project"],
        primary_schema="schema_generic",
        chunk_text="使用 CSS3 与 Vite 构建",
    )
    assert isinstance(core, CoreMetadata)
    assert core.project_name == "好友买"
    assert "电商" in core.keywords
    assert "CSS3" in core.keywords or "Vite" in core.keywords
    assert "使用" not in core.keywords


def test_merge_passes_title() -> None:
    """merge 须吃 title 做通用人名推断。"""
    meta = merge_metadata_for_schemas(
        text="邮箱 test@x.com\n6年工作经验",
        schema_codes=["schema_resume"],
        primary_schema="schema_resume",
        title="候选人-张三 5年-后端.pdf",
    )
    assert meta["person_name"] == "张三"


# 兼容旧测试名
person_name_from_title = guess_person_from_title
