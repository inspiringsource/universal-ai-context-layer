"""A reproducible navigation proxy, not an agent-quality or token benchmark."""

from __future__ import annotations

import json
from pathlib import Path

from ai_context_map.navigation.index import build_index, render_brief, select_records


def evaluate(root: Path) -> dict:
    tasks = json.loads((root / "benchmarks/navigation_tasks.json").read_text())
    index = build_index(root)
    # Equal-size shortlist baseline: UACL's existing task-independent ranking.
    baseline = [
        record["path"]
        for record in sorted(
            index["records"], key=lambda record: (-record["rank"], record["path"])
        )[:6]
    ]
    results = []
    for task in tasks:
        paths = [record["path"] for record in select_records(index, task["task"], 6)]
        results.append(
            {
                **task,
                "found_in_six": task["expected"] in paths,
                "position": paths.index(task["expected"]) + 1
                if task["expected"] in paths
                else None,
                "baseline_found_in_six": task["expected"] in baseline,
                "selected": paths,
                "entry_characters": len(render_brief(root, index, task["task"])),
            }
        )
    return {
        "scope": "Six transparent tasks on UACL itself; lexical retrieval proxy only. Not independent validation or measured usage savings.",
        "indexed_files": len(index["records"]),
        "baseline": baseline,
        "task_hits": sum(result["found_in_six"] for result in results),
        "baseline_hits": sum(result["baseline_found_in_six"] for result in results),
        "full_index_characters": len(json.dumps(index, indent=2) + "\n"),
        "results": results,
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(Path(__file__).resolve().parents[1]), indent=2))
