from __future__ import annotations

import re
from pathlib import Path

from evo.utils import get_logs_root

from .levels import Level
from .utils import repo_root


CASE_DIR_RE = re.compile(r"^G\d+T\d+$")


def logs_root() -> Path:
    return get_logs_root(repo_root())


def is_case_dir(path: Path) -> bool:
    return path.is_dir() and CASE_DIR_RE.fullmatch(path.name) is not None


def is_fitness_dir(path: Path) -> bool:
    return path.is_dir() and (path / "evo_result.csv").is_file()


def find_latest_run_dir() -> Path | None:
    root = logs_root()
    if not root.exists():
        return None
    subdirs = [path for path in root.iterdir() if path.is_dir()]
    if not subdirs:
        return None
    return max(subdirs, key=lambda path: path.stat().st_mtime)


def detect_level(path: Path) -> Level:
    path = path.expanduser().resolve()
    if is_case_dir(path):
        return Level.CASE
    if is_fitness_dir(path):
        return Level.FITNESS

    root = logs_root().resolve()
    try:
        rel = path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Cannot determine analysis level for path outside logs root: {path}") from exc

    depth = len(rel.parts)
    level_by_depth = {
        1: Level.DATE,
        2: Level.IMAGE,
        3: Level.ENCODING,
        4: Level.FITNESS,
        5: Level.CASE,
    }
    if depth not in level_by_depth:
        raise ValueError(f"Unsupported logs path depth for {path}")
    return level_by_depth[depth]


def find_targets_at_level(root: Path, target_level: Level) -> list[Path]:
    root = root.expanduser().resolve()
    root_level = detect_level(root)
    if root_level == target_level:
        return [root]
    if root_level > target_level:
        raise ValueError(
            f"Input path {root} is already more specific than target level {target_level.name}"
        )

    matches: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        try:
            if detect_level(path) == target_level:
                matches.append(path)
        except ValueError:
            continue
    return sorted(matches)


def resolve_iteration_dir(case_dir: Path, iteration: int = 1) -> Path:
    direct = case_dir / f"iteration-{iteration}"
    if direct.is_dir():
        return direct
    if (case_dir / "action-1.csv").exists():
        return case_dir
    raise FileNotFoundError(f"Could not find iteration-{iteration} under {case_dir}")


def resolve_live_logs_dir(case_dir: Path, iteration: int = 1) -> Path:
    iteration_dir = resolve_iteration_dir(case_dir, iteration=iteration)
    for candidate in (
        iteration_dir / "validator_live_logs",
        iteration_dir / "validator_logs",
    ):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"No validator log directory found under {iteration_dir}")


def latest_case_input_mtime(case_dir: Path, iteration: int = 1) -> float:
    case_dir = case_dir.expanduser().resolve()
    iteration_dir = resolve_iteration_dir(case_dir, iteration=iteration)

    candidates = [
        case_dir / "strategy_input.yaml",
        iteration_dir / "action-1.csv",
        iteration_dir / "result-1.csv",
    ]

    mtimes = [path.stat().st_mtime for path in candidates if path.exists()]
    try:
        live_logs_dir = resolve_live_logs_dir(case_dir, iteration=iteration)
    except FileNotFoundError:
        live_logs_dir = None

    if live_logs_dir is not None:
        for log_path in live_logs_dir.glob("validator_*_*.txt"):
            mtimes.append(log_path.stat().st_mtime)

    if not mtimes:
        return case_dir.stat().st_mtime
    return max(mtimes)
