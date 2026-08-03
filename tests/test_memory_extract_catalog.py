"""记忆抽取字段 Catalog 缓存与种子。

@author 赵振明
@date 2026-07-29 11:21:36
"""

from __future__ import annotations

from app.modules.memory.extract_catalog_cache import (
    get_extract_fields_catalog,
    reset_extract_fields_for_tests,
    set_extract_fields_fallback,
)
from app.modules.memory.extract_seed import DEFAULT_EXTRACT_FIELDS


def test_seed_has_hobby_and_display_name() -> None:
    keys = {x["field_key"] for x in DEFAULT_EXTRACT_FIELDS}
    assert "hobby" in keys
    assert "display_name" in keys
    assert "person_of_interest" not in keys


def test_get_catalog_falls_back_to_seed() -> None:
    reset_extract_fields_for_tests()
    cat = get_extract_fields_catalog()
    assert any(x["field_key"] == "hobby" for x in cat)


def test_set_fallback_overrides() -> None:
    reset_extract_fields_for_tests()
    set_extract_fields_fallback(
        [
            {
                "category": "fact",
                "field_key": "hobby",
                "label": "爱好",
                "description": "用户兴趣爱好",
                "priority": 1,
            }
        ]
    )
    cat = get_extract_fields_catalog()
    assert len(cat) == 1
    assert cat[0]["field_key"] == "hobby"
