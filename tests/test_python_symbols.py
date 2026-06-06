from pathlib import Path

from ai_context_map.analyzers.python_symbols import PythonSymbolAnalyzer


def test_python_symbol_analyzer_extracts_navigation_symbols(tmp_path: Path) -> None:
    file_path = tmp_path / "app.py"
    file_path.write_text(
        "\n".join(
            [
                "from fastapi import FastAPI",
                "",
                "app = FastAPI()",
                "",
                "@app.get('/health')",
                "async def healthcheck():",
                "    return {'ok': True}",
                "",
                "class Detector:",
                "    def predict(self):",
                "        return 1",
                "",
                "def helper():",
                "    return 'value'",
                "",
                "if __name__ == '__main__':",
                "    print('run')",
            ]
        ),
        encoding="utf-8",
    )

    symbols = PythonSymbolAnalyzer().extract(file_path)

    assert any(
        symbol.name == "app" and symbol.symbol_type == "entrypoint"
        for symbol in symbols
    )
    assert any(
        symbol.name == "healthcheck" and symbol.symbol_type == "route_handler"
        for symbol in symbols
    )
    assert any(
        symbol.name == "Detector" and symbol.symbol_type == "class"
        for symbol in symbols
    )
    assert any(
        symbol.name == "Detector.predict" and symbol.symbol_type == "method"
        for symbol in symbols
    )
    assert any(
        symbol.name == "helper" and symbol.symbol_type == "function"
        for symbol in symbols
    )
    assert any(
        symbol.name == "__main__" and symbol.symbol_type == "entrypoint"
        for symbol in symbols
    )
