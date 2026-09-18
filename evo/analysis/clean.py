from __future__ import annotations

import argparse
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from collections.abc import Iterator
from pathlib import Path


FAILURE_KEYS = (
    "failed_termination",
    "failed_agreement",
    "failed_final_agreement",
    "total_failures",
)

INVALID_RUN_KEYS = (
    "timeout_before_startup",
    "errors",
)

DEFAULT_DELETE_DIRS = (
    "validator_live_logs",
    "validator_logs",
)

DEFAULT_DELETE_FILES = (
    "action-*.csv",
)

# run_evotests2.archive_retry_log_dir() 把 runtime-invalid 的那次 attempt 的日志目录
# 改名成 "<case>__attempt<N>_<reason>"，然后才重试。这些目录没有
# aggregated_spec_check_log.json，因此 iter_case_dirs() 永远不会访问它们 ——
# 而每个里面都躺着一份完整的 Rust panic backtrace（rocket_stderr.log），会无限堆积。
# 它们是纯开销：这次 attempt 失败以及失败原因已经记在 evo_excluded_runs.csv 里了。
ATTEMPT_DIR_MARKER = "__attempt"


@dataclass
class CleanStats:
    scanned_cases: int = 0
    cleaned_cases: int = 0
    skipped_failures: int = 0
    skipped_invalid: int = 0
    skipped_unknown: int = 0
    deleted_attempt_dirs: int = 0
    deleted_paths: int = 0
    freed_bytes: int = 0


@dataclass(frozen=True)
class CleanupResult:
    path: Path
    affected: bool
    size: int


def parse_args() -> argparse.Namespace:
    default_workers = int(os.environ.get("ROCKET_CLEAN_WORKERS", "16"))
    parser = argparse.ArgumentParser(
        description=(
            "Slim Rocket log directories by removing bulky replay/debug files "
            "from cases that definitely have no violation."
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Run, image, encoding, fitness, or case directory to clean.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted without deleting anything.",
    )
    parser.add_argument(
        "--keep-action-log",
        action="store_true",
        help="Keep iteration-*/action-*.csv. By default it is removed for non-violation cases.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Only inspect the first N case directories. Useful for smoke tests.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each skipped case and each deleted path.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only print the final summary. Useful with --dry-run on large runs.",
    )
    parser.add_argument(
        "--no-size",
        action="store_true",
        help="Do not measure deleted path sizes. This is much faster on very large runs.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=default_workers,
        help="Number of parallel deletion workers. Defaults to ROCKET_CLEAN_WORKERS or 16.",
    )
    return parser.parse_args()


def format_size(num_bytes: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def int_field(data: dict, key: str) -> int:
    value = data.get(key, 0)
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def classify_case(case_dir: Path) -> str:
    summary_path = case_dir / "aggregated_spec_check_log.json"
    if not summary_path.is_file():
        return "unknown"

    try:
        summary = json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError):
        return "unknown"

    if any(int_field(summary, key) != 0 for key in FAILURE_KEYS):
        return "violation"

    total_iterations = int_field(summary, "total_iterations")
    correct_runs = int_field(summary, "correct_runs")
    if total_iterations <= 0 or correct_runs != total_iterations:
        return "invalid"

    if any(int_field(summary, key) != 0 for key in INVALID_RUN_KEYS):
        return "invalid"

    return "cleanable"


def iter_case_dirs(root: Path) -> Iterator[Path]:
    root = root.expanduser().resolve()
    if (root / "aggregated_spec_check_log.json").is_file():
        yield root
        return

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in DEFAULT_DELETE_DIRS
        ]

        if "aggregated_spec_check_log.json" in filenames:
            yield Path(dirpath).resolve()
            dirnames[:] = []


def iter_archived_attempt_dirs(root: Path) -> Iterator[Path]:
    """Yield the archived failed-attempt directories under ``root``.

    这些目录是重试机制归档下来的（见 ATTEMPT_DIR_MARKER 的注释）。它们整个都应该
    被删掉，而不是瘦身 —— 里面除了 panic backtrace 没有别的东西。
    """
    root = root.expanduser().resolve()
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [
            dirname for dirname in dirnames if dirname not in DEFAULT_DELETE_DIRS
        ]
        for dirname in list(dirnames):
            if ATTEMPT_DIR_MARKER in dirname:
                yield (Path(dirpath) / dirname).resolve()
                # 不往下走：整个目录都要删，没必要再枚举里面的内容
                dirnames.remove(dirname)


def iter_cleanup_targets(case_dir: Path, keep_action_log: bool) -> list[Path]:
    targets: list[Path] = []

    iteration_dirs = sorted(case_dir.glob("iteration-*"))
    if not iteration_dirs:
        iteration_dirs = [case_dir]

    for iteration_dir in iteration_dirs:
        if not iteration_dir.is_dir():
            continue

        for dirname in DEFAULT_DELETE_DIRS:
            target = iteration_dir / dirname
            if target.exists():
                targets.append(target)

        if not keep_action_log:
            for pattern in DEFAULT_DELETE_FILES:
                targets.extend(sorted(iteration_dir.glob(pattern)))

    return targets


def path_size(path: Path) -> int:
    try:
        if path.is_symlink() or path.is_file():
            return path.lstat().st_size
        if path.is_dir():
            return sum(child.lstat().st_size for child in path.rglob("*"))
    except OSError:
        return 0
    return 0


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def process_cleanup_target(
    target: Path, *, dry_run: bool, no_size: bool
) -> CleanupResult:
    if not target.exists():
        return CleanupResult(target, affected=False, size=0)

    size = 0 if no_size else path_size(target)
    if not dry_run:
        remove_path(target)
    return CleanupResult(target, affected=True, size=size)


def print_cleanup_result(result: CleanupResult, args: argparse.Namespace) -> None:
    if not result.affected:
        return
    if not (args.verbose or (args.dry_run and not args.summary_only)):
        return

    action = "Would delete" if args.dry_run else "Delete"
    suffix = "" if args.no_size else f" ({format_size(result.size)})"
    print(f"{action} {result.path}{suffix}")


def run_cleanup_targets(
    targets: list[Path], args: argparse.Namespace, stats: CleanStats
) -> None:
    if not targets:
        return

    workers = max(1, args.workers)
    if workers == 1:
        for target in targets:
            result = process_cleanup_target(
                target, dry_run=args.dry_run, no_size=args.no_size
            )
            if result.affected:
                stats.deleted_paths += 1
                stats.freed_bytes += result.size
            print_cleanup_result(result, args)
        return

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_target = {
            executor.submit(
                process_cleanup_target,
                target,
                dry_run=args.dry_run,
                no_size=args.no_size,
            ): target
            for target in targets
        }
        for future in as_completed(future_to_target):
            result = future.result()
            if result.affected:
                stats.deleted_paths += 1
                stats.freed_bytes += result.size
            print_cleanup_result(result, args)


def clean_roots(args: argparse.Namespace) -> CleanStats:
    stats = CleanStats()
    seen: set[Path] = set()
    cleanup_targets: list[Path] = []
    stop = False
    for root in args.paths:
        if not root.exists():
            raise FileNotFoundError(root)

        for case_dir in iter_case_dirs(root):
            if case_dir in seen:
                continue
            seen.add(case_dir)

            if args.max_cases is not None and stats.scanned_cases >= args.max_cases:
                stop = True
                break

            stats.scanned_cases += 1
            label = classify_case(case_dir)
            if label == "cleanable":
                targets = iter_cleanup_targets(case_dir, args.keep_action_log)
                if targets:
                    stats.cleaned_cases += 1
                    cleanup_targets.extend(targets)
            elif label == "violation":
                stats.skipped_failures += 1
                if args.verbose:
                    print(f"Skip failure case {case_dir}")
            elif label == "invalid":
                stats.skipped_invalid += 1
                if args.verbose:
                    print(f"Skip invalid/incomplete case {case_dir}")
            else:
                stats.skipped_unknown += 1
                if args.verbose:
                    print(f"Skip unknown case {case_dir}")

        # 重试归档下来的失败 attempt：整个目录删掉，只保留重试后那份结果。
        for attempt_dir in iter_archived_attempt_dirs(root):
            stats.deleted_attempt_dirs += 1
            cleanup_targets.append(attempt_dir)

        if stop:
            break

    run_cleanup_targets(cleanup_targets, args, stats)
    return stats


def main() -> int:
    args = parse_args()
    stats = clean_roots(args)

    verb = "Would free" if args.dry_run else "Freed"
    print(
        f"Scanned {stats.scanned_cases} cases; "
        f"cleaned {stats.cleaned_cases}; "
        f"skipped failure cases {stats.skipped_failures}; "
        f"skipped invalid {stats.skipped_invalid}; "
        f"skipped unknown {stats.skipped_unknown}; "
        f"deleted archived attempts {stats.deleted_attempt_dirs}."
    )
    if args.no_size:
        action = "Would delete" if args.dry_run else "Deleted"
        print(f"{action} {stats.deleted_paths} paths; size not measured.")
    else:
        print(
            f"{verb} {format_size(stats.freed_bytes)} "
            f"from {stats.deleted_paths} paths."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
