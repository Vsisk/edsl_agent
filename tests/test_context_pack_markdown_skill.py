from agent.context_pack.indexing.markdown_skill import MarkdownSkillParser
from agent.context_pack.models import ContextPackRequest
from agent.context_pack.project_context import ProjectContext
from agent.context_pack.providers.dev_skill import DevSkillProvider
from agent.context_pack.registry import RecallProfile
from agent.context_pack.search import LocalResourceSearchTool


SKILL = """# 开发取值规范

## 客户信息

### 客户完整姓名
依次考虑 title、firstName、middleName、lastName。

#### 规则
过滤空值后，按 title、firstName、middleName、lastName 拼接。

#### 示例
```text
Dr / Jane / Q / Doe -> Dr Jane Q Doe
```
"""


def test_parser_keeps_recipe_rules_examples_and_parent_headings(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(SKILL, encoding="utf-8")

    [recipe] = MarkdownSkillParser().parse(path, "dev-skill")

    assert recipe.content["heading_path"] == ["开发取值规范", "客户信息", "客户完整姓名"]
    assert "#### 规则" in recipe.content["markdown"]
    assert "```text" in recipe.content["markdown"]
    assert recipe.locator.start_line == 5
    assert recipe.content_hash


def test_dev_skill_provider_recalls_complete_customer_name_recipe(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(SKILL, encoding="utf-8")
    provider = DevSkillProvider(LocalResourceSearchTool())
    request = ContextPackRequest(
        node={"node_id": "n", "annotation": "客户姓名"},
        query="生成客户姓名",
        resource_names=["dev_skill"],
    )

    section = provider.retrieve(request, ProjectContext(dev_skill_path=path), RecallProfile(3, 8000))

    assert section.status.value == "ready"
    assert len(section.items) == 1
    markdown = section.items[0].content["markdown"]
    assert all(term in markdown for term in ("title", "firstName", "middleName", "lastName", "过滤空值", "拼接"))
    assert section.items[0].authority.value == "normative"


def test_dev_skill_provider_marks_missing_file_unavailable(tmp_path):
    provider = DevSkillProvider(LocalResourceSearchTool())
    request = ContextPackRequest(node={"node_id": "n"}, query="客户", resource_names=["dev_skill"])

    section = provider.retrieve(
        request, ProjectContext(dev_skill_path=tmp_path / "missing.md"), RecallProfile(3, 8000)
    )

    assert section.status.value == "unavailable"
    assert section.items == []
