import pytest

from agent.context_pack import (
    ContextPackRequest,
    ProjectContext,
    create_context_pack_manager,
)
from agent.context_pack.errors import RESOURCE_NOT_REGISTERED, ContextProviderError


SKILL = """# 开发取值规范

## 客户信息

### 客户完整姓名
考虑 title、firstName、middleName、lastName，过滤空值后按顺序拼接。
"""


def tree():
    return {
        "mapping_content": {
            "node_id": "root",
            "tree_node_type": "parent",
            "children": [{
                "node_id": "customers",
                "tree_node_type": "parent_list",
                "local_context": [{
                    "property_name": "title",
                    "annotation": "称谓",
                    "return_type": {"data_type": "basic", "data_type_name": "String", "is_list": False},
                }],
                "children": [{
                    "node_id": "name",
                    "tree_node_type": "simple_leaf",
                    "annotation": "客户完整姓名",
                    "xml_name_property": {"xml_name": "FULL_NAME"},
                }],
            }],
        }
    }


def request(resources):
    return ContextPackRequest(
        node={"node_id": "name", "tree_node_type": "simple_leaf", "annotation": "客户完整姓名"},
        query="生成客户完整姓名 title 判空拼接",
        resource_names=resources,
    )


def test_customer_name_pack_combines_recipe_and_existing_tree_facts(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text(SKILL, encoding="utf-8")

    pack = create_context_pack_manager().build(
        request(["dev_skill", "current_tree"]),
        ProjectContext(current_tree=tree(), dev_skill_path=skill),
    )

    assert pack.status.value == "complete"
    assert [section.resource_name.value for section in pack.sections] == ["current_tree", "dev_skill"]
    recipe = pack.sections[1].items[0].content["markdown"]
    assert all(term in recipe for term in ("title", "firstName", "middleName", "lastName", "过滤空值", "拼接"))
    tree_names = {item.content.get("name") for item in pack.sections[0].items}
    assert tree_names >= {"FULL_NAME", "title"}


def test_unrequested_sources_are_not_required_and_output_is_deterministic(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text(SKILL, encoding="utf-8")
    manager = create_context_pack_manager()
    project = ProjectContext(dev_skill_path=skill)

    first = manager.build(request(["dev_skill"]), project)
    second = manager.build(request(["dev_skill"]), project)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [section.resource_name.value for section in first.sections] == ["dev_skill"]


def test_missing_ootb_returns_partial_pack_with_skill_results(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text(SKILL, encoding="utf-8")

    pack = create_context_pack_manager().build(
        request(["dev_skill", "ootb_edsl"]), ProjectContext(dev_skill_path=skill)
    )

    assert pack.status.value == "partial"
    assert pack.sections[0].items
    assert pack.sections[1].status.value == "unavailable"


def test_phase_one_factory_rejects_namingsql_until_migration():
    with pytest.raises(ContextProviderError) as error:
        create_context_pack_manager().build(request(["namingsql"]), ProjectContext())
    assert error.value.code == RESOURCE_NOT_REGISTERED
