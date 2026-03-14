from pathlib import Path

import yaml

from ai_context_map.models.context import (
    ContextDocument,
    NavigationMap,
    ProjectSummary,
    ProvenanceInfo,
)
from ai_context_map.emitter.yaml_writer import write_context_yaml


def test_write_context_yaml(tmp_path: Path) -> None:
    output = tmp_path / ".ai" / "context.yaml"
    document = ContextDocument(
        aicontext_version=1,
        project=ProjectSummary(name="demo", root=".", detected_languages=["python"]),
        architecture={"entry_points": [], "core_modules": [], "layers": []},
        navigation_map=NavigationMap(),
        hotspots=[],
        anchors=[],
        constraints=[],
        known_issues=[],
        provenance=ProvenanceInfo(enabled=False, history_file=".ai/history.yaml"),
    )

    write_context_yaml(document, output)

    data = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert data["project"]["name"] == "demo"

