import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_context_map.cli import app
from ai_context_map.navigation.index import (
    BRIEF_PATH,
    INDEX_PATH,
    build_index,
    pack_context,
    render_brief,
    select_records,
)


def write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_one_command_indexes_task_code_and_importing_test(tmp_path: Path) -> None:
    write(
        tmp_path,
        "src/payment.py",
        "def reconcile_invoice(invoice):\n    return invoice\n",
    )
    write(tmp_path, "tests/test_payment.py", "from payment import reconcile_invoice\n")
    write(tmp_path, "src/unrelated.py", "def paint_screen():\n    return 'red'\n")
    write(tmp_path, "AGENTS.md", "# Rules\nPreserve unrelated work.\n")
    canonical = write(
        tmp_path, ".ai/context.yaml", "decisions:\n- Keep invoices immutable\n"
    )
    original = canonical.read_bytes()
    result = CliRunner().invoke(
        app, ["pack", str(tmp_path), "--task", "reconcile invoice"]
    )
    assert result.exit_code == 0, result.output
    brief = (tmp_path / BRIEF_PATH).read_text()
    assert "src/payment.py" in brief
    assert "tests/test_payment.py" in brief
    assert "reconcile_invoice:1" in brief
    assert "`AGENTS.md`" in brief
    assert "`.ai/context.yaml`" in brief
    assert canonical.read_bytes() == original
    index = json.loads((tmp_path / INDEX_PATH).read_text())
    assert "return invoice" not in json.dumps(index)
    assert ".ai/context.yaml" not in {record["path"] for record in index["records"]}


def test_parent_directory_js_imports_include_related_tests(tmp_path: Path) -> None:
    write(
        tmp_path,
        "src/auth/token.ts",
        "// module\n\nexport function renewToken() { return 1; }\n",
    )
    write(
        tmp_path,
        "tests/token.spec.ts",
        "import { renewToken } from '../src/auth/token';\n",
    )
    index = build_index(tmp_path)
    selected = select_records(index, "renewToken")
    source = next(
        record for record in selected if record["path"] == "src/auth/token.ts"
    )
    assert source["imported_by"] == ["tests/token.spec.ts"]
    assert source["symbols"] == [{"name": "renewToken", "line": 3}]
    assert any(
        record["path"] == "tests/token.spec.ts" and record["role"] == "test"
        for record in selected
    )


def test_stale_fingerprint_suppresses_line_numbers_even_same_size(
    tmp_path: Path,
) -> None:
    source = write(tmp_path, "src/auth.py", "def renew_token():\n    return 1\n")
    index = build_index(tmp_path)
    stat = source.stat()
    source.write_text("def renew_token():\n    return 2\n")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    brief = render_brief(tmp_path, index, "renew token")
    assert "STALE" in brief
    assert "renew_token:1" not in brief
    source.unlink()
    assert "MISSING/UNSAFE" in render_brief(tmp_path, index, "renew token")


def test_unknown_query_does_not_fallback_to_confident_random_files(
    tmp_path: Path,
) -> None:
    write(tmp_path, "src/main.py", "print('hello')\n")
    index = build_index(tmp_path)
    assert select_records(index, "quantum reimbursement") == []
    assert "No indexed match" in render_brief(tmp_path, index, "quantum reimbursement")


def test_small_budget_never_truncates_instructions_or_overflows(tmp_path: Path) -> None:
    write(tmp_path, "CLAUDE.md", "# Rules\nDon't delete data.\n")
    write(tmp_path, "GEMINI.md", "# Rules\nVerify behaviour.\n")
    for number in range(8):
        write(
            tmp_path,
            f"src/invoice_{number}.py",
            f"def reconcile_invoice_{number}():\n    return 1\n",
        )
    index = build_index(tmp_path)
    brief = render_brief(tmp_path, index, "invoice", max_chars=1500)
    assert len(brief) <= 1500
    assert "`CLAUDE.md`" in brief and "`GEMINI.md`" in brief
    assert "Omitted by budget: 0" not in brief
    assert "read" in brief.lower()
    with pytest.raises(ValueError, match="budget too small"):
        render_brief(tmp_path, index, "x" * 2000, max_chars=1500)
    assert not (tmp_path / INDEX_PATH).exists()


def test_exclusions_symlinks_invalid_python_and_large_files(tmp_path: Path) -> None:
    write(tmp_path, ".aicontext.toml", 'exclude_paths = ["private"]\n')
    write(tmp_path, "private/secret.py", "PASSWORD = 'secret'\n")
    write(tmp_path, "node_modules/pkg/main.js", "export const privateKey = 1;\n")
    outside = write(
        tmp_path.parent, tmp_path.name + "-outside.py", "def outside_secret(): pass\n"
    )
    (tmp_path / "linked.py").symlink_to(outside)
    write(tmp_path, "broken.py", "def broken(:\n")
    write(tmp_path, "huge.py", "x" * 1_000_001)
    write(tmp_path, "good.py", "def useful(): return 1\n")
    index = build_index(tmp_path)
    paths = {record["path"] for record in index["records"]}
    assert not {
        "private/secret.py",
        "node_modules/pkg/main.js",
        "linked.py",
    }.intersection(paths)
    assert {"broken.py", "huge.py", "good.py"}.issubset(paths)
    assert len(index["warnings"]) == 2
    assert "outside_secret" not in json.dumps(index)


def test_symlinked_output_directory_cannot_write_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / (tmp_path.name + "-output")
    outside.mkdir()
    (tmp_path / ".ai").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes repository"):
        pack_context(tmp_path)
    assert not list(outside.iterdir())


def test_find_requires_index_and_retrieves_bounded_output(tmp_path: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["find", "invoice", str(tmp_path)]).exit_code == 1
    write(tmp_path, "src/service.py", "def invoice_total(): return 1\n")
    pack_context(tmp_path)
    result = runner.invoke(
        app, ["find", "invoice", str(tmp_path), "--limit", "1", "--max-chars", "1500"]
    )
    assert result.exit_code == 0
    assert len(result.stdout) <= 1500
    assert "invoice_total:1" in result.stdout


def test_examples_are_not_treated_as_root_instructions(tmp_path: Path) -> None:
    write(tmp_path, "examples/AGENTS.md", "# Example\nExample instructions only.\n")
    write(tmp_path, "src/inspect.py", "def inspect_invoice(): return 1\n")
    index = build_index(tmp_path)
    assert (
        next(
            record for record in index["records"] if record["path"] == "src/inspect.py"
        )["role"]
        != "test"
    )
    brief = render_brief(tmp_path, index, "invoice")
    assert "- `examples/AGENTS.md`" not in brief
