from pathlib import Path

from ai_context_map.memory.git_history import build_file_memory, extract_git_cochange_memory


def test_build_file_memory_is_deterministic() -> None:
    commits = [
        ["src/c.py", "src/a.py", "src/b.py"],
        ["src/a.py", "src/b.py"],
        ["src/a.py", "src/c.py"],
    ]

    memory = build_file_memory(commits)

    assert [item.path for item in memory] == ["src/a.py", "src/b.py", "src/c.py"]
    assert [(item.path, item.count, item.weight) for item in memory[0].related] == [
        ("src/b.py", 2, 0.6667),
        ("src/c.py", 2, 0.6667),
    ]
    assert [(item.path, item.count, item.weight) for item in memory[1].related] == [
        ("src/a.py", 2, 0.6667),
        ("src/c.py", 1, 0.5),
    ]


def test_build_file_memory_counts_single_file_commits_in_weights() -> None:
    commits = [
        ["src/a.py"],
        ["src/a.py", "src/b.py"],
    ]

    memory = build_file_memory(commits)

    assert [item.path for item in memory] == ["src/a.py", "src/b.py"]
    assert [(item.path, item.count, item.weight) for item in memory[0].related] == [
        ("src/b.py", 1, 0.5),
    ]
    assert [(item.path, item.count, item.weight) for item in memory[1].related] == [
        ("src/a.py", 1, 0.5),
    ]


def test_build_file_memory_includes_files_with_no_cochange_relationships() -> None:
    commits = [
        ["src/a.py"],
        ["src/b.py"],
    ]

    memory = build_file_memory(commits)

    assert [item.path for item in memory] == ["src/a.py", "src/b.py"]
    assert memory[0].related == []
    assert memory[1].related == []


def test_extract_git_cochange_memory_reads_recent_commits(tmp_path: Path) -> None:
    _git(["init"], tmp_path)
    _git(["config", "user.name", "Test User"], tmp_path)
    _git(["config", "user.email", "test@example.com"], tmp_path)

    _write_file(tmp_path, "src/a.py", "print('a1')\n")
    _write_file(tmp_path, "src/b.py", "print('b1')\n")
    _write_file(tmp_path, ".ai/context.yaml", "ignored: true\n")
    _git(["add", "."], tmp_path)
    _git(["commit", "-m", "add a and b"], tmp_path)

    _write_file(tmp_path, "src/a.py", "print('a2')\n")
    _write_file(tmp_path, "src/c.py", "print('c1')\n")
    _git(["add", "."], tmp_path)
    _git(["commit", "-m", "update a and add c"], tmp_path)

    _write_file(tmp_path, "src/b.py", "print('b2')\n")
    _write_file(tmp_path, "src/c.py", "print('c2')\n")
    _git(["add", "."], tmp_path)
    _git(["commit", "-m", "update b and c"], tmp_path)

    _write_file(tmp_path, "src/a.py", "print('a3')\n")
    _git(["add", "."], tmp_path)
    _git(["commit", "-m", "update a only"], tmp_path)

    memory = extract_git_cochange_memory(tmp_path, commit_limit=10)

    assert memory.provenance is not None
    assert memory.provenance.source == "git"
    assert memory.provenance.commit_limit == 10
    assert [item.path for item in memory.files] == ["src/a.py", "src/b.py", "src/c.py"]
    assert [(item.path, item.count, item.weight) for item in memory.files[0].related] == [
        ("src/b.py", 1, 0.3333),
        ("src/c.py", 1, 0.3333),
    ]
    assert [(item.path, item.count, item.weight) for item in memory.files[1].related] == [
        ("src/a.py", 1, 0.3333),
        ("src/c.py", 1, 0.5),
    ]
    assert [(item.path, item.count, item.weight) for item in memory.files[2].related] == [
        ("src/a.py", 1, 0.3333),
        ("src/b.py", 1, 0.5),
    ]


def _git(args: list[str], root: Path) -> None:
    import subprocess

    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _write_file(root: Path, relative_path: str, contents: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
