from pathlib import Path

import yaml

from ai_context_map.models.context import (
    Anchor,
    ContextDocument,
    NavigationMap,
    ProjectSummary,
    ProvenanceInfo,
    TaskRouteFile,
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
        anchors=[
            Anchor(
                file="src/app/service.py",
                symbol="Service.run",
                symbol_type="method",
                line=12,
                reasons=["central inference path"],
            )
        ],
        task_routes={
            "model_or_logic_change": [
                TaskRouteFile(path="src/app/service.py", reasons=["located in core/service module"])
            ]
        },
        constraints=[],
        known_issues=[],
        provenance=ProvenanceInfo(enabled=False, history_file=".ai/history.yaml"),
    )

    write_context_yaml(document, output)

    data = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert data["project"]["name"] == "demo"
    assert data["anchors"][0]["symbol"] == "Service.run"
    assert data["task_routes"]["model_or_logic_change"][0]["path"] == "src/app/service.py"
