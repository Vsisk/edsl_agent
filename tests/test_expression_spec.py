from pathlib import Path

import pytest

from agent.expression_generation.expression_spec import (
    ExpressionSkillLibrary,
    ExpressionSpecGenerator,
)
from agent.models import NodeDef, ValueLogicRequest


def list_tree():
    return {
        "mapping_content": {
            "node_id": "root",
            "tree_node_type": "parent",
            "children": [
                {
                    "node_id": "customers",
                    "tree_node_type": "parent_list",
                    "data_source": {
                        "data_source_type": "sql",
                        "sql_query": {"bo_name": "Customer"},
                    },
                    "children": [
                        {
                            "node_id": "name",
                            "tree_node_type": "simple_leaf",
                            "annotation": "客户名称",
                        }
                    ],
                }
            ],
        }
    }


def request(*, query="生成客户名称", path="$.mapping_content.children[0].children[0]", tree=None):
    tree = list_tree() if tree is None else tree
    return ValueLogicRequest(
        site_id="site",
        project_id="project",
        node_path=path,
        node={"node_id": "name", "annotation": "客户名称"},
        query=query,
        edsl_tree=tree,
    )


def node(path="$.mapping_content.children[0].children[0]", name="NAME", description="客户名称"):
    return NodeDef(
        node_id="name",
        node_path=path,
        node_name=name,
        description=description,
    )


def test_spec_recalls_list_skill_from_structure_without_query_keyword():
    spec = ExpressionSpecGenerator().generate(
        request=request(),
        node_info=node(),
    )

    assert spec.nl == "生成客户名称"
    assert spec.scope_context.inside_parent_list is True
    assert spec.scope_context.parent_list_path == "$.mapping_content.children[0]"
    assert spec.scope_context.iter_path == "$iter$"
    assert spec.scope_context.iter_return_type == {
        "data_type": "bo",
        "data_type_name": "Customer",
        "is_list": False,
    }
    assert [item.skill_id for item in spec.skill_instructions] == ["list-current-element"]
    assert "$iter$.FIELD" in spec.skill_instructions[0].markdown


def test_spec_outside_list_does_not_recall_list_skill():
    tree = {
        "mapping_content": {
            "node_id": "root",
            "tree_node_type": "parent",
            "children": [{"node_id": "name", "tree_node_type": "simple_leaf"}],
        }
    }
    spec = ExpressionSpecGenerator().generate(
        request=request(query="生成名称", path="$.mapping_content.children[0]", tree=tree),
        node_info=node(path="$.mapping_content.children[0]"),
    )

    assert spec.scope_context.inside_parent_list is False
    assert spec.scope_context.iter_path is None
    assert spec.skill_instructions == []


@pytest.mark.parametrize(
    ("query", "expected_skill", "expected_expression"),
    [
        ("获取账期日期所在年份", "date-year", 'addDays(1).toString("yyyy")'),
        ("获取账期日期所在月份", "date-month", 'addDays(1).toString("MM")'),
    ],
)
def test_spec_recalls_date_skill_without_contaminating_nl(query, expected_skill, expected_expression):
    tree = {
        "mapping_content": {
            "node_id": "date",
            "tree_node_type": "simple_leaf",
            "annotation": "账期日期",
        }
    }
    spec = ExpressionSpecGenerator().generate(
        request=request(query=query, path="$.mapping_content", tree=tree),
        node_info=node(path="$.mapping_content", name="BILL_DATE", description="账期日期"),
    )

    assert spec.nl == query
    assert [item.skill_id for item in spec.skill_instructions] == [expected_skill]
    assert expected_expression in spec.skill_instructions[0].markdown


def test_expression_skill_library_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        ExpressionSkillLibrary(tmp_path / "missing.md")
