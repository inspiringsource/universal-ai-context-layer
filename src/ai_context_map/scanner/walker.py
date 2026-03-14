from __future__ import annotations

from pathlib import Path

from ai_context_map.config import Config
from ai_context_map.models.repo import RepositoryFile, ScanResult
from ai_context_map.scanner.classifier import classify_file
from ai_context_map.scanner.ignore import IgnoreRules


def scan_repository(root: Path, config: Config) -> ScanResult:
    root = root.resolve()
    ignore_rules = IgnoreRules(exclude_paths=config.exclude_paths)
    include_paths = [root / path for path in config.include_paths] if config.include_paths else [root]
    seen: set[Path] = set()
    result = ScanResult(root=root)

    for include_root in include_paths:
        if not include_root.exists():
            continue
        for path in include_root.rglob("*"):
            if path in seen:
                continue
            seen.add(path)
            rel = path.relative_to(root).as_posix()
            if path.is_dir():
                if ignore_rules.should_ignore_dir(rel):
                    continue
                continue
            if ignore_rules.should_ignore_file(rel):
                continue
            language, is_source = classify_file(path)
            if language and language not in config.languages:
                is_source = False
                language = None
            result.files.append(
                RepositoryFile(
                    path=path,
                    relative_path=rel,
                    language=language,
                    extension=path.suffix.lower(),
                    is_source=is_source,
                    size_bytes=path.stat().st_size,
                )
            )
            if language:
                result.languages.add(language)
    result.files.sort(key=lambda item: item.relative_path)
    return result

