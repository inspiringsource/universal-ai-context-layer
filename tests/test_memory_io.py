from pathlib import Path

from ai_context_map.memory.io import read_memory_yaml, write_memory_yaml
from ai_context_map.memory.models import FileMemory, MemoryLink, MemoryProvenance, RepositoryMemory


def test_memory_yaml_round_trip(tmp_path: Path) -> None:
    output = tmp_path / ".ai" / "memory.yaml"
    memory = RepositoryMemory(
        provenance=MemoryProvenance(
            source="git",
            commit_limit=25,
            generated_at="2026-03-25T10:00:00Z",
        ),
        files=[
            FileMemory(
                path="src/a.py",
                related=[
                    MemoryLink(path="src/b.py", count=3, weight=1.0),
                    MemoryLink(path="src/c.py", count=1, weight=0.3333),
                ],
            )
        ],
    )

    write_memory_yaml(memory, output)
    loaded = read_memory_yaml(output)

    assert loaded == memory
    text = output.read_text(encoding="utf-8")
    assert "memory_version: 1" in text
    assert "generated_at:" in text
