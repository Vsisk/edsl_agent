from pathlib import Path

from agent.context_manager.errors import ContextBuildError, RULE_FILE_MISSING
from agent.context_manager.models import BuildContextRequest, ContextAsset, ContextEvidenceItem, GlobalContextBlock


class GlobalContextResolver:
    def __init__(self, rules_root: str | Path | None = None, *, repo_root: str | Path | None = None) -> None:
        if rules_root is not None:
            self.rules_root = Path(rules_root)
        else:
            root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
            self.rules_root = root / "agent_rules"

    def resolve(self, request: BuildContextRequest) -> GlobalContextBlock:
        files = [("GLOBAL.md", "global_rule"), (f"chains/{request.chain_type}.md", "chain_rule")]
        assets, evidence, paths = [], [], []
        for relative, asset_type in files:
            path = self.rules_root / relative
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise ContextBuildError(RULE_FILE_MISSING, str(path)) from exc
            if not text.strip():
                raise ContextBuildError(RULE_FILE_MISSING, str(path))
            asset_id = f"rule:{relative.replace('/', ':')}"
            assets.append(ContextAsset(asset_id=asset_id, asset_type=asset_type, scope="global", content={"path": str(path), "text": text}, index_text=text.strip(), source=str(path)))
            evidence.append(ContextEvidenceItem(source=str(path), action="rule_loaded", asset_id=asset_id, evidence=f"Loaded required {asset_type}"))
            paths.append(str(path))
        return GlobalContextBlock(assets=assets, evidence=evidence, loaded_paths=paths)
