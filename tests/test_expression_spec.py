from pathlib import Path

import pytest

from agent.expression_generation.expression_spec import ExpressionSkillLibrary


def test_expression_skill_library_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        ExpressionSkillLibrary(tmp_path / "missing.md")
