from __future__ import annotations

import argparse
from pathlib import Path

from .cases import find_latest_run_dir


def evolution_report(fitness_dir: Path) -> list[Path]:
    from . import plot as legacy_plot

    fitness_dir = fitness_dir.expanduser().resolve()
    csv_path = fitness_dir / "evo_result.csv"
    if not csv_path.is_file():
        raise FileNotFoundError(f"Could not find evo_result.csv under {fitness_dir}")

    plot_data = legacy_plot.load_plot_data(csv_path, messages=[])
    if plot_data is None:
        raise RuntimeError(f"Could not load plot data from {csv_path}")

    df, metrics, _ = plot_data
    is_multi_objective = legacy_plot.has_effective_objectives(df, metrics)
    out_path = fitness_dir / (
        legacy_plot.MULTI_OBJECTIVE_REPORT_NAME
        if is_multi_objective
        else legacy_plot.FITNESS_REPORT_NAME
    )
    legacy_plot.generate_reports_for_csvs(
        [csv_path],
        custom_output=fitness_dir / legacy_plot.FITNESS_REPORT_NAME,
        strategy_root_dir=None,
        jobs=1,
    )
    return [out_path]


def fitness_trend_report(encoding_dir: Path) -> list[Path]:
    from . import plot as legacy_plot

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
    output_paths: list[Path] = []
    strategy_tasks = [
        (strategy_dir, plot_entries, strategy_dir / legacy_plot.STRATEGY_REPORT_NAME)
        for strategy_dir, plot_entries in strategy_groups.items()
    ]
    if strategy_tasks:
        strategy_results = legacy_plot.run_strategy_tasks_parallel(
            strategy_tasks,
            legacy_plot.resolve_jobs(1, len(strategy_tasks)),
        )
        for messages in strategy_results:
            for message in messages:
                print(message)
        output_paths.extend(task[2] for task in strategy_tasks)

    strategy_objective_groups = legacy_plot.collect_strategy_objective_entries(
        report_results, root_dir=encoding_dir
    )
    strategy_objective_tasks = [
        (
            strategy_dir,
            plot_entries,
            strategy_dir / legacy_plot.STRATEGY_MULTI_OBJECTIVE_REPORT_NAME,
        )
        for strategy_dir, plot_entries in strategy_objective_groups.items()
    ]
    if strategy_objective_tasks:
        strategy_objective_results = legacy_plot.run_strategy_multi_objective_tasks_parallel(
            strategy_objective_tasks,
            legacy_plot.resolve_jobs(1, len(strategy_objective_tasks)),
        )
        for messages in strategy_objective_results:
            for message in messages:
                print(message)
        output_paths.extend(task[2] for task in strategy_objective_tasks)

    if not output_paths:
        raise RuntimeError(f"Could not build any strategy report under {encoding_dir}")

    return output_paths


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

    from .plot import main as legacy_main

    legacy_main([str(target)])
