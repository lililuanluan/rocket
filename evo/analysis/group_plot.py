from __future__ import annotations

import argparse
from pathlib import Path

from .cases import find_latest_run_dir


def evolution_report(fitness_dir: Path) -> list[Path]:
    from evo.analysis_bak import plot as legacy_plot

    fitness_dir = fitness_dir.expanduser().resolve()
    csv_path = fitness_dir / "evo_result.csv"
    if not csv_path.is_file():
        raise FileNotFoundError(f"Could not find evo_result.csv under {fitness_dir}")

    out_path = fitness_dir / legacy_plot.FITNESS_REPORT_NAME
    legacy_plot.generate_reports_for_csvs(
        [csv_path],
        custom_output=out_path,
        strategy_root_dir=None,
        jobs=1,
    )
    return [out_path]


def fitness_trend_report(encoding_dir: Path) -> list[Path]:
    from evo.analysis_bak import plot as legacy_plot

    encoding_dir = encoding_dir.expanduser().resolve()
    csv_files = legacy_plot.collect_csvs_from_logs_dir(encoding_dir)
    if not csv_files:
        raise FileNotFoundError(f"No evo_result.csv files found under {encoding_dir}")

    tasks = [
        (
            csv_path,
            csv_path.with_name(legacy_plot.FITNESS_REPORT_NAME),
            False,
        )
        for csv_path in csv_files
    ]
    report_results = legacy_plot.run_report_tasks_parallel(
        tasks,
        legacy_plot.resolve_jobs(1, len(tasks)),
    )
    for result in report_results:
        for message in result["messages"]:
            print(message)

    strategy_groups = legacy_plot.collect_strategy_entries(
        report_results, root_dir=encoding_dir
    )
    if not strategy_groups:
        raise RuntimeError(f"Could not build strategy entries under {encoding_dir}")

    strategy_tasks = [
        (strategy_dir, plot_entries, strategy_dir / legacy_plot.STRATEGY_REPORT_NAME)
        for strategy_dir, plot_entries in strategy_groups.items()
    ]
    strategy_results = legacy_plot.run_strategy_tasks_parallel(
        strategy_tasks,
        legacy_plot.resolve_jobs(1, len(strategy_tasks)),
    )
    for messages in strategy_results:
        for message in messages:
            print(message)

    return [task[2] for task in strategy_tasks]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compatibility wrapper for the legacy group-level plotting entrypoint."
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=None,
        help="Optional logs directory path; defaults to the newest run under logs/.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    target = args.path
    if target is None:
        target = find_latest_run_dir()
        if target is None:
            raise SystemExit("Could not find the latest logs run directory.")

    from evo.analysis_bak.plot import main as legacy_main

    legacy_main([str(target)])
