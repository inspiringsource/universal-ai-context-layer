import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_context_map.analyzers.js_ts_analyzer import JsTsAnalyzer
from ai_context_map.analyzers.js_ts_structure import extract_structure
from ai_context_map.cli import app
from ai_context_map.navigation.index import (
    BRIEF_PATH,
    INDEX_PATH,
    build_index,
    load_index,
    pack_context,
    render_brief,
    select_records,
)
from ai_context_map.navigation.retrieve import (
    RetrievalError,
    list_symbols,
    retrieve_symbol,
)
from ai_context_map.workstate.checkpoint import (
    briefing_sections,
    cited_paths,
    load_checkpoint,
    update_checkpoint,
)

FIXTURE = Path(__file__).parent / "fixtures" / "jsts"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    return root


def facts(relative: str) -> dict:
    path = FIXTURE / relative
    structure = extract_structure(path.read_bytes(), path.suffix)
    return {
        "status": structure.parse_status,
        "errors": structure.error_lines,
        "symbols": {
            s.get("id", s["name"]): (s["kind"], s["line"], s["end_line"])
            for s in structure.symbols
        },
        "raw": structure.symbols,
        "imports": [
            (i["spec"], i["kind"], i.get("names", [])) for i in structure.imports
        ],
    }


def by_name(raw: list[dict], name: str) -> dict:
    return next(s for s in raw if s["name"] == name)


# --- extraction ---------------------------------------------------------------


def test_typescript_declarations_ranges_and_signatures() -> None:
    result = facts("src/payments.ts")
    assert result["status"] == "ok"
    assert result["symbols"] == {
        "notADeclaration": ("const", 11, 11),
        "template": ("const", 12, 12),
        "PaymentResult": ("interface", 14, 17),
        "Currency": ("type", 19, 19),
        "chargePayment": ("function", 22, 28),
        "refundPayment": ("function", 30, 35),
        "PaymentService": ("class", 37, 47),
        "PaymentService.constructor": ("method", 38, 38),
        "PaymentService.process": ("method", 40, 42),
        "PaymentService.fromEnv": ("method", 44, 46),
        "RefundService": ("class", 49, 57),
        "RefundService.process": ("method", 50, 56),
        "RefundService.process.audit": ("function", 51, 53),
        # Two overload signatures are grouped with the implementation.
        "parseAmount": ("function", 59, 63),
    }
    raw = result["raw"]
    charge = by_name(raw, "chargePayment")
    # Multiline parameters keep types, defaults, and the return type.
    assert charge["signature"] == (
        "async chargePayment(order: Order, currency: Currency = 'USD'): "
        "Promise<PaymentResult>"
    )
    assert charge["doc_line"] == 21 and charge["exported"] is True
    assert by_name(raw, "refundPayment")["signature"] == (
        "async refundPayment(paymentId: string, reason?: string): Promise<void>"
    )
    assert by_name(raw, "PaymentService.fromEnv")["signature"] == (
        "static PaymentService.fromEnv(): PaymentService"
    )
    assert by_name(raw, "parseAmount")["overloads"] is True
    assert "exported" not in by_name(raw, "notADeclaration")


def test_declarations_in_comments_and_strings_are_ignored() -> None:
    names = set(facts("src/payments.ts")["symbols"])
    assert not {
        "commentedOut",
        "FakeInComment",
        "fakeInString",
        "FakeInTemplate",
    }.intersection(names)


def test_duplicate_method_names_are_qualified_by_scope() -> None:
    raw = facts("src/payments.ts")["raw"]
    processes = [s for s in raw if s["name"].endswith(".process")]
    assert [(s["name"], s["parent"]) for s in processes] == [
        ("PaymentService.process", "PaymentService"),
        ("RefundService.process", "RefundService"),
    ]


def test_imports_reexports_requires_and_type_only_imports() -> None:
    assert facts("src/payments.ts")["imports"] == [
        ("./gateway", "import", ["send"]),
        ("@models/order", "import", ["Order"]),
        ("./format.js", "import", ["formatCents"]),
        ("stripe", "import", ["default as Stripe"]),
        ("./does-not-exist", "import", ["missing"]),
    ]
    type_import = extract_structure(
        (FIXTURE / "src/payments.ts").read_bytes(), ".ts"
    ).imports[1]
    assert type_import["type_only"] is True
    assert facts("src/gateway/index.ts")["imports"] == [
        ("./client", "reexport", ["*"]),
        ("./retry", "reexport", ["retryPolicy as defaultRetryPolicy"]),
    ]
    assert facts("src/legacy/util.js")["imports"] == [("path", "require", [])]


def test_jsx_and_tsx_components_and_nested_handlers() -> None:
    button = facts("src/components/Button.jsx")
    assert button["symbols"] == {
        "Button": ("function", 3, 9),
        "Button.handleClick": ("function", 4, 7),
    }
    assert by_name(button["raw"], "Button")["default"] is True
    tsx = facts("src/components/List.tsx")
    assert tsx["status"] == "ok"
    assert tsx["symbols"] == {"ListProps": ("type", 4, 7), "List": ("function", 9, 19)}
    list_symbol = by_name(tsx["raw"], "List")
    assert list_symbol["signature"] == (
        "List<T>({items, render}: ListProps<T>): JSX.Element"
    )
    # JSX component usage is recorded as a syntactic call; DOM tags are not.
    assert "<Button>" in list_symbol["calls"]
    assert not any(call in {"<ul>", "<li>"} for call in list_symbol["calls"])


def test_commonjs_exports() -> None:
    result = facts("src/legacy/util.js")
    raw = result["raw"]
    assert by_name(raw, "joinSlug")["exported"] is True
    assert by_name(raw, "slugify")["exported"] is True
    assert result["symbols"]["joinSlug"] == ("function", 7, 9)
    assert "exported" not in by_name(raw, "path")


def test_partial_syntax_is_reported_and_earlier_declarations_survive() -> None:
    result = facts("src/broken.ts")
    assert result["status"] == "partial"
    assert result["errors"] == [5, 8]
    before = by_name(result["raw"], "beforeError")
    assert (before["line"], before["end_line"]) == (1, 3)
    assert "syntax_error" not in before
    broken = by_name(result["raw"], "incomplete")
    assert broken["syntax_error"] is True
    # Swallowed by the unclosed body: nested, and flagged as such.
    assert by_name(result["raw"], "incomplete.afterError")["syntax_error"] is True


def test_unsupported_syntax_region_recovers_labelled_declarations() -> None:
    # Generic call signatures in an interface are rejected by the grammar version.
    source = (
        b"interface Get {\n"
        b"  <Key extends string>(key: Key): Key\n"
        b"  <\n"
        b"}\n"
        b"export type Later = string\n"
        b"export function afterRegion(): void {}\n"
        b"// export function notCode() {}\n"
    )
    structure = extract_structure(source, ".ts")
    assert structure.parse_status == "partial"
    names = {s["name"]: s for s in structure.symbols}
    assert "notCode" not in names
    for name in ("Later", "afterRegion"):
        assert name in names
        if names[name].get("recovered"):
            assert names[name]["syntax_error"] is True


def test_graph_builder_uses_tree_sitter_imports() -> None:
    references = JsTsAnalyzer().analyze(FIXTURE / "src/gateway/index.ts")
    assert [ref.module for ref in references] == ["./client", "./retry"]


# --- index relationships ----------------------------------------------------------


def test_import_resolution_statuses_across_directories(repo: Path) -> None:
    index = build_index(repo)
    by_path = {r["path"]: r for r in index["records"]}
    refs = {
        e["spec"]: (e["status"], e.get("target"), e.get("alternatives"))
        for e in by_path["src/payments.ts"]["import_refs"]
    }
    assert refs == {
        "./gateway": ("resolved", "src/gateway/index.ts", None),
        "@models/order": ("alias", "src/models/order.ts", None),
        # A TS importer of `./format.js` resolves to format.ts first, but an
        # emitted format.js also exists, so the relationship is flagged.
        "./format.js": ("ambiguous", "src/format.ts", ["src/format.js"]),
        "stripe": ("package", None, None),
        "./does-not-exist": ("unresolved", None, None),
    }
    assert by_path["tests/payments.test.ts"]["imports"] == ["src/payments.ts"]
    assert "tests/payments.test.ts" in by_path["src/payments.ts"]["imported_by"]
    assert index["relationships"]["ambiguous"] == 1
    assert index["relationships"]["unresolved"] == 1


def test_call_targets_follow_reexports_and_are_labelled_inferred(repo: Path) -> None:
    index = build_index(repo)
    by_path = {r["path"]: r for r in index["records"]}
    charge = next(
        s for s in by_path["src/payments.ts"]["symbols"] if s["name"] == "chargePayment"
    )
    targets = {t["call"]: (t["status"], t["targets"]) for t in charge["call_targets"]}
    # `send` is imported from the gateway barrel, which re-exports ./client.
    assert targets["send"] == ("inferred", ["src/gateway/client.ts::send"])
    # The ambiguous ./format.js import still names one TS declaration.
    assert targets["formatCents"] == ("inferred", ["src/format.ts::formatCents"])
    list_symbol = next(
        s for s in by_path["src/components/List.tsx"]["symbols"] if s["name"] == "List"
    )
    assert list_symbol["call_targets"] == [
        {
            "call": "<Button>",
            "status": "inferred",
            "targets": ["src/components/Button.jsx::Button"],
        }
    ]
    # Calls to locals that are not imported are never given a target.
    process = next(
        s
        for s in by_path["src/payments.ts"]["symbols"]
        if s["name"] == "RefundService.process"
    )
    assert "call_targets" not in process


def test_partial_parse_is_a_warning_not_a_skipped_file(repo: Path) -> None:
    index = build_index(repo)
    record = next(r for r in index["records"] if r["path"] == "src/broken.ts")
    assert record["parse"] == {"status": "partial", "error_lines": [5, 8]}
    assert any(
        "src/broken.ts" in w and "Partially parsed" in w for w in index["warnings"]
    )


def test_symbol_body_words_find_differently_named_code(repo: Path) -> None:
    index = build_index(repo)
    # "amount" and "cents" occur only inside chargePayment's body.
    selected = select_records(index, "cents amount conversion", 6)
    assert selected[0]["path"] in {"src/payments.ts", "src/format.ts"}
    brief = render_brief(repo, index, "cents amount conversion")
    assert "chargePayment(order: Order" in brief


# --- entry map ------------------------------------------------------------------


def test_entry_map_lists_relevant_structure_with_legend(repo: Path) -> None:
    _, _, brief = pack_context(repo, "charge payment through gateway")
    assert len(brief) <= 6000
    assert "Legend:" in brief and "inferred; runtime target unverified" in brief
    assert (
        "EXPORT async function chargePayment(order: Order, currency: Currency = 'USD'): "
        "Promise<PaymentResult> @22-28" in brief
    )
    assert "CALLS from chargePayment: " in brief
    assert "send → src/gateway/client.ts::send" in brief
    # Flagged relationships are shown; imports of shortlisted files are not repeated.
    assert "IMPORT ./format.js → AMBIGUOUS src/format.ts (also src/format.js)" in brief
    assert "IMPORT ./gateway" not in brief
    # Irrelevant declarations of the same file are not dumped into the entry.
    assert "notADeclaration" not in brief and "template @" not in brief
    assert "Structure lines:" in brief
    # Index is separate; source bodies are never stored.
    index_text = (repo / INDEX_PATH).read_text()
    assert "toFixed" not in index_text and "return send(" not in index_text


def test_partial_files_are_marked_in_the_entry(repo: Path) -> None:
    index = build_index(repo)
    brief = render_brief(repo, index, "before error incomplete")
    assert "`src/broken.ts` [current; unknown; parse partial]" in brief
    assert "PARTIAL PARSE near line(s) 5, 8" in brief


def test_budget_omits_structure_explicitly_and_keeps_constraints(repo: Path) -> None:
    update_checkpoint(
        repo,
        {
            "objective": "Refund payments safely",
            "next": "Inspect RefundService.process",
            "records": [
                {"kind": "constraint", "basis": "user", "text": "Never double refund."},
                *[{"kind": "todo", "text": f"Todo {n} " + "z" * 80} for n in range(8)],
            ],
        },
    )
    sections = briefing_sections(repo, load_checkpoint(repo))
    index = build_index(repo)
    saw_omission = False
    for budget in range(1400, 7000, 53):
        try:
            brief = render_brief(
                repo, index, "refund payment", budget, checkpoint=sections
            )
        except ValueError as exc:
            assert "cannot safely contain" in str(exc)
            continue
        assert len(brief) <= budget
        assert "Never double refund." in brief
        assert "Objective: [obj1; user instruction] Refund payments safely" in brief
        if "Structure lines:" in brief:
            shown, omitted = (
                brief.split("Structure lines: ")[1]
                .split(" omitted")[0]
                .split(" shown, ")
            )
            body = brief.split("## Suggested starting points")[1].split("\nIndex:")[0]
            assert int(shown) == sum(
                1 for line in body.splitlines() if line.startswith("  ")
            )
            saw_omission |= int(omitted) > 0
    assert saw_omission


def test_checkpoint_refs_are_pinned_and_labelled_as_recorded(repo: Path) -> None:
    update_checkpoint(
        repo,
        {
            "objective": "Harden retries",
            "next": "Change the retry policy",
            "records": [
                {
                    "kind": "decision",
                    "text": "Keep retries in the gateway layer.",
                    "reason": "Callers must not retry twice.",
                    "refs": ["src/gateway/retry.ts:1"],
                }
            ],
        },
    )
    state = load_checkpoint(repo)
    assert cited_paths(state) == [("src/gateway/retry.ts", "d1")]
    result = CliRunner().invoke(app, ["pack", str(repo)])
    assert result.exit_code == 0, result.output
    brief = (repo / BRIEF_PATH).read_text()
    assert (
        "`src/gateway/retry.ts` [current; unknown]: cited by checkpoint record d1 "
        "(agent-recorded)" in brief
    )
    # Recorded conclusions stay in the checkpoint section, apart from parsed facts.
    checkpoint_part, pointers = brief.split("## Suggested starting points")
    assert "Keep retries in the gateway layer." in checkpoint_part
    assert "Keep retries" not in pointers


# --- retrieval --------------------------------------------------------------------


def test_retrieve_symbol_returns_exact_numbered_range(repo: Path) -> None:
    index = build_index(repo)
    text = retrieve_symbol(repo, index, "src/payments.ts::RefundService.process")
    assert text.startswith(
        "src/payments.ts::RefundService.process  [method; fingerprint current]"
    )
    # The enclosing class header gives the method its context.
    assert "49 | export class RefundService {" in text
    assert "50 |   process(paymentId: string): Promise<void> {" in text
    assert "56 |   }" in text
    assert "57 |" not in text and "40 |" not in text
    assert "[Complete: lines 50-56.]" in text
    doc = retrieve_symbol(repo, index, "src/payments.ts::chargePayment")
    assert "21 | /** Charge an order through the gateway. */" in doc
    assert "send → src/gateway/client.ts::send" in doc


def test_retrieval_is_bounded_and_explains_expansion(repo: Path) -> None:
    index = build_index(repo)
    text = retrieve_symbol(repo, index, "src/payments.ts::PaymentService", max_lines=4)
    assert "40 |" in text and "41 |" not in text
    assert "[Lines 41-47 omitted (7 of 11)" in text
    assert "--max-lines 11" in text and "--full" in text
    assert "src/payments.ts::PaymentService.fromEnv @44" in text
    full = retrieve_symbol(
        repo, index, "src/payments.ts::PaymentService", max_lines=4, full=True
    )
    assert "47 | }" in full and "[Complete: lines 37-47.]" in full


def test_ambiguous_and_unresolved_names_are_never_guessed(repo: Path) -> None:
    index = build_index(repo)
    with pytest.raises(RetrievalError) as error:
        retrieve_symbol(repo, index, "src/payments.ts::process")
    message = str(error.value)
    assert message.startswith("AMBIGUOUS: 2 symbols match 'process'")
    assert "src/payments.ts::PaymentService.process" in message
    assert "src/payments.ts::RefundService.process" in message
    # The bare name formatCents is declared in format.ts and format.js.
    with pytest.raises(RetrievalError, match="AMBIGUOUS: 2 indexed symbols"):
        retrieve_symbol(repo, index, "formatCents")
    with pytest.raises(RetrievalError, match="UNRESOLVED"):
        retrieve_symbol(repo, index, "src/payments.ts::nothingHere")
    unique = retrieve_symbol(repo, index, "fromEnv")
    assert unique.startswith("src/payments.ts::PaymentService.fromEnv")


def test_duplicate_declarations_get_stable_ids(tmp_path: Path) -> None:
    (tmp_path / "dup.js").write_text(
        "function helper() { return 1; }\nfunction helper() { return 2; }\n"
    )
    index = build_index(tmp_path)
    with pytest.raises(RetrievalError, match="use one id"):
        retrieve_symbol(tmp_path, index, "dup.js::helper")
    second = retrieve_symbol(tmp_path, index, "dup.js::helper#2")
    assert "2 | function helper() { return 2; }" in second
    assert "1 |" not in second.split("\n", 2)[2]


def test_changed_deleted_and_renamed_files(repo: Path) -> None:
    pack_context(repo, "payment")
    index = load_index(repo)
    payments = repo / "src/payments.ts"
    payments.write_text("// inserted line\n" + payments.read_text())
    moved = retrieve_symbol(repo, index, "src/payments.ts::RefundService.process")
    assert (
        "fingerprint CHANGED" in moved and "re-derived from the current file" in moved
    )
    assert "51 |   process(paymentId: string): Promise<void> {" in moved
    # A symbol removed from a changed file is reported, not substituted.
    payments.write_text(payments.read_text().replace("fromEnv", "fromConfig"))
    with pytest.raises(RetrievalError, match=r"CHANGED: .*indexed at lines 44-46"):
        retrieve_symbol(repo, index, "src/payments.ts::PaymentService.fromEnv")
    # Deleted and renamed files.
    (repo / "src/gateway/client.ts").rename(repo / "src/gateway/transport.ts")
    with pytest.raises(RetrievalError, match=r"MISSING: src/gateway/client\.ts"):
        retrieve_symbol(repo, index, "src/gateway/client.ts::send")
    with pytest.raises(RetrievalError, match=r"NOT INDEXED: src/gateway/transport\.ts"):
        retrieve_symbol(repo, index, "src/gateway/transport.ts::send")
    brief = render_brief(repo, index, "send gateway")
    assert "MISSING/UNSAFE" in brief
    # A rebuild notices the added, deleted, and renamed files.
    _, rebuilt, _ = pack_context(repo, "send gateway")
    paths = {r["path"] for r in rebuilt["records"]}
    assert "src/gateway/transport.ts" in paths and "src/gateway/client.ts" not in paths
    barrel = next(r for r in rebuilt["records"] if r["path"] == "src/gateway/index.ts")
    assert barrel["import_refs"][0]["status"] == "unresolved"
    assert "send →" not in render_brief(repo, rebuilt, "charge payment")


def test_retrieval_refuses_unsafe_and_generated_paths(repo: Path) -> None:
    index = build_index(repo)
    with pytest.raises(ValueError, match="escapes repository"):
        retrieve_symbol(repo, index, "../outside.ts::x")
    with pytest.raises(RetrievalError, match="Generated UACL state"):
        retrieve_symbol(repo, index, ".ai/work/checkpoint.json::x")
    outside = repo.parent / "outside.ts"
    outside.write_text("export function secret() {}\n")
    (repo / "src/link.ts").symlink_to(outside)
    rebuilt = build_index(repo)
    assert "src/link.ts" not in {r["path"] for r in rebuilt["records"]}
    with pytest.raises(ValueError, match=r"escapes repository|NOT INDEXED"):
        retrieve_symbol(repo, rebuilt, "src/link.ts::secret")


def test_list_symbols_is_bounded(repo: Path) -> None:
    index = build_index(repo)
    listing = list_symbols(repo, index, "src/payments.ts")
    assert listing.startswith("FILE src/payments.ts [current]")
    assert "[src/payments.ts::RefundService.process.audit]" in listing
    assert "IMPORT ./does-not-exist → UNRESOLVED" in listing
    short = list_symbols(repo, index, "src/payments.ts", max_chars=1000)
    assert len(short) <= 1000 and "more lines omitted by --max-chars" in short


def test_symbol_cli_for_typescript_and_python(repo: Path) -> None:
    (repo / "src/tools.py").write_text(
        "import functools\n\n\nclass Ledger:\n    @functools.cache\n"
        "    def balance(self, account: str) -> int:\n        return 0\n"
    )
    runner = CliRunner()
    assert runner.invoke(app, ["pack", str(repo)]).exit_code == 0
    result = runner.invoke(
        app, ["symbol", "src/tools.py::Ledger.balance", "--root", str(repo)]
    )
    assert result.exit_code == 0, result.output
    assert "DEF method Ledger.balance(self, account: str) -> int @6-7" in result.output
    assert "5 |     @functools.cache" in result.output
    missing = runner.invoke(
        app, ["symbol", "src/payments.ts::nope", "--root", str(repo)]
    )
    assert missing.exit_code == 1 and "UNRESOLVED" in missing.output
    listing = runner.invoke(app, ["symbol", "src/payments.ts", "--root", str(repo)])
    assert listing.exit_code == 0 and listing.output.startswith("FILE src/payments.ts")
    index = json.loads((repo / INDEX_PATH).read_text())
    assert index["schema_version"] == 2 and "tree-sitter 0.25" in index["parser"]


def test_routes_need_a_handler_and_client_calls_are_not_routes() -> None:
    source = (
        b"app.get('/users/:id', (c) => c.json(load(c)))\n"
        b"axios.get('/users', { params: { page: 1 } })\n"
        b"router.post('/orders', auth, async function create(req, res) {})\n"
    )
    routes = [
        (s["name"], s["line"], s["signature"])
        for s in extract_structure(source, ".js").symbols
        if s["kind"] == "route"
    ]
    assert routes == [
        ("GET /users/:id", 1, "GET /users/:id via app.get(…)"),
        ("POST /orders", 3, "POST /orders via router.post(…)"),
    ]


def test_default_object_export_members_match_calls(tmp_path: Path) -> None:
    (tmp_path / "utils.js").write_text(
        "function isFunction(x) { return typeof x === 'function'; }\n"
        "const merge = (a, b) => ({ ...a, ...b });\n"
        "export default { isFunction, extend: merge };\n"
    )
    (tmp_path / "core.js").write_text(
        "import utils from './utils.js';\n"
        "export function run(a) { return utils.isFunction(a) && utils.extend(a, {}); }\n"
    )
    index = build_index(tmp_path)
    run = next(
        s
        for r in index["records"]
        if r["path"] == "core.js"
        for s in r["symbols"]
        if s["name"] == "run"
    )
    assert run["call_targets"] == [
        {
            "call": "utils.isFunction",
            "status": "inferred",
            "targets": ["utils.js::isFunction"],
        },
        {"call": "utils.extend", "status": "inferred", "targets": ["utils.js::merge"]},
    ]


def test_reexported_imports_default_expressions_and_member_fallback(
    tmp_path: Path,
) -> None:
    (tmp_path / "hono.ts").write_text("export class Hono {}\n")
    (tmp_path / "index.ts").write_text(
        "import { Hono } from './hono'\nexport { Hono }\n"
    )
    (tmp_path / "flags.js").write_text(
        "const isArray = Array.isArray;\nexport default typeof window !== 'undefined'\n"
    )
    (tmp_path / "utils.js").write_text(
        "const { isArray } = Array;\nfunction kindOf(x) { return typeof x; }\n"
        "export default { isArray, kindOf };\n"
    )
    (tmp_path / "app.ts").write_text(
        "import { Hono } from './index'\nimport browser from './flags.js'\n"
        "import utils from './utils.js'\n"
        "export function main() { return [new Hono(), browser(), utils.isArray([]), "
        "utils.kindOf(1)]; }\n"
    )
    index = build_index(tmp_path)
    flags = next(r for r in index["records"] if r["path"] == "flags.js")
    default = next(s for s in flags["symbols"] if s["name"] == "default")
    assert (default["kind"], default["line"], default["default"]) == ("value", 2, True)
    main = next(
        s
        for r in index["records"]
        if r["path"] == "app.ts"
        for s in r["symbols"]
        if s["name"] == "main"
    )
    targets = {t["call"]: (t["status"], t["targets"]) for t in main["call_targets"]}
    assert targets == {
        "new Hono": ("inferred", ["hono.ts::Hono"]),
        "browser": ("inferred", ["flags.js::default"]),
        # isArray is destructured, so only the default object can be named.
        "utils.isArray": ("owner-only", ["utils.js::default"]),
        "utils.kindOf": ("inferred", ["utils.js::kindOf"]),
    }


def test_method_overload_signatures_join_the_implementation() -> None:
    source = (
        b"class Request {\n"
        b"  parse(raw: string): object\n"
        b"  parse(raw: Buffer): object\n"
        b"  parse(raw: string | Buffer): object {\n"
        b"    return {}\n"
        b"  }\n"
        b"}\n"
    )
    methods = [
        (s["name"], s["line"], s["end_line"], s.get("overloads"))
        for s in extract_structure(source, ".ts").symbols
        if s["kind"] == "method"
    ]
    assert methods == [("Request.parse", 2, 6, True)]


def test_static_member_calls_resolve_to_the_declared_method(tmp_path: Path) -> None:
    (tmp_path / "headers.js").write_text(
        "export default class Headers {\n  static from(x) { return new Headers(); }\n}\n"
        "export class Named {\n  static make() {}\n}\n"
    )
    (tmp_path / "use.js").write_text(
        "import Headers, { Named } from './headers.js';\n"
        "export function build() { Headers.from({}); Named.make(); Named.missing(); }\n"
    )
    index = build_index(tmp_path)
    build = next(
        s
        for r in index["records"]
        if r["path"] == "use.js"
        for s in r["symbols"]
        if s["name"] == "build"
    )
    assert {t["call"]: (t["status"], t["targets"]) for t in build["call_targets"]} == {
        "Headers.from": ("inferred", ["headers.js::Headers.from"]),
        "Named.make": ("inferred", ["headers.js::Named.make"]),
        # No declared member: only the owning class can be named, and is labelled.
        "Named.missing": ("owner-only", ["headers.js::Named"]),
    }
