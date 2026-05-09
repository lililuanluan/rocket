from __future__ import annotations

import json
import traceback
from pathlib import Path

from .cases import latest_case_input_mtime
from .registry import Analyzer
from .utils import analysis_dir


INDEX_NAME = "analysis_index.json"


def index_path(case_dir: Path) -> Path:
    return analysis_dir(case_dir) / INDEX_NAME


def load_index(case_dir: Path) -> dict:
    path = index_path(case_dir)
    if not path.exists():
        return {"analyzers": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"analyzers": {}}


def save_index(case_dir: Path, index: dict) -> None:
    path = index_path(case_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")


def outputs_exist(paths: list[str]) -> bool:
    return all(Path(path).exists() for path in paths)


def should_run(case_dir: Path, analyzer_name: str, force: bool) -> bool:
    if force:
        return True
    index = load_index(case_dir)
    record = index.get("analyzers", {}).get(analyzer_name)
    if not record or record.get("status") != "ok":
        return True
    if not outputs_exist(record.get("outputs", [])):
        return True
    return float(record.get("input_mtime", 0.0)) < latest_case_input_mtime(case_dir)


def run_case_analyzers(
    case_dir: Path,
    analyzers: list[Analyzer],
    *,
    force: bool = False,
) -> dict[str, str]:
    case_dir = case_dir.expanduser().resolve()
    index = load_index(case_dir)
    index.setdefault("analyzers", {})
    results: dict[str, str] = {}
    input_mtime = latest_case_input_mtime(case_dir)

    for analyzer in analyzers:
        if not should_run(case_dir, analyzer.name, force):
            results[analyzer.name] = "skipped"
            continue

        try:
            outputs = [str(path.resolve()) for path in analyzer.run(case_dir)]
            index["analyzers"][analyzer.name] = {
                "status": "ok",
                "description": analyzer.description,
                "outputs": outputs,
                "input_mtime": input_mtime,
            }
            results[analyzer.name] = "ok"
        except Exception as exc:
            index["analyzers"][analyzer.name] = {
                "status": "error",
                "description": analyzer.description,
                "outputs": [],
                "input_mtime": input_mtime,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
            results[analyzer.name] = "error"

    save_index(case_dir, index)
    return results
