from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .cases import detect_level, find_latest_run_dir
from .levels import Level


OUTPUT_NAME = "_fitness_violation_boxplots.pdf"
OBJECTIVE_COLUMN_PREFIX = "objective_seq_"
VIOLATION_GROUP_COLUMN = "__violation_group"
VIOLATION_SOURCE_COLUMN = "__violation_source"
CASE_DIR_COLUMN = "__case_dir"
CSV_PATH_COLUMN = "__csv_path"
FITNESS_DIR_COLUMN = "__fitness_dir"
ENCODING_DIR_COLUMN = "__encoding_dir"
IMAGE_DIR_COLUMN = "__image_dir"
UNKNOWN_GROUP = "Unknown"

METRIC_TITLES = {
    "num_propose_set": "Number of proposeSet messages",
    "num_getledger_hashes": "Number of distinct getLedger hashes",
    "num_getledger_messages": "Number of getLedger messages",
    "mean_validation_time": "Mean validation time",
    "var_validation_time": "Validation time variance",
    "diff_validation_time_max": "Max validation time range",
    "validation_distribution_entropy": "Validation distribution entropy",
    "validation_distribution_entropy_max": "Max validation distribution entropy",
    "validation_distribution_entropy_unl": "Validation distribution entropy (UNL)",
    "validation_distribution_entropy_max_unl": "Max validation distribution entropy (UNL)",
    "proposal_distribution_entropy": "Proposal distribution entropy",
    "proposal_position_entropy": "Proposal position entropy",
    "proposal_position_entropy_max": "Max proposal position entropy",
    "proposal_late_position_entropy_max": "Max late proposal position entropy",
    "proposal_close_time_entropy_max": "Max proposal close-time entropy",
    "message_entropy_integral": "Message entropy integral",
    "message_entropy_average": "Mean message entropy per second",
    "markov_matrix_non_similarity": "Message Markov non-similarity",
    "gossip_fiedler": "Gossip graph Fiedler value",
    "max_tip_distance": "Max tip distance",
    "sum_tip_distance": "Sum tip distance",
}
PREFERRED_METRIC_ORDER = list(METRIC_TITLES.keys())
EXCLUDED_COLUMNS = {
    "generation",
    "individual_id",
    "fitness_type",
    "fitness",
    "total_failures",
    "objective_metric",
    "objective_status",
    "objective_error",
    VIOLATION_GROUP_COLUMN,
    VIOLATION_SOURCE_COLUMN,
    CASE_DIR_COLUMN,
    CSV_PATH_COLUMN,
    FITNESS_DIR_COLUMN,
    ENCODING_DIR_COLUMN,
    IMAGE_DIR_COLUMN,
}
VIOLATION_SUMMARY_KEYS = (
    "timeout_before_startup",
    "errors",
    "failed_termination",
    "failed_agreement",
    "failed_final_agreement",
)


def _pd():
    import pandas as pd

    return pd


def _plot_deps():
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    return plt, PdfPages


@dataclass
class CollectionStats:
    image_dir: Path
    csv_files: int = 0
    total_rows: int = 0
    violation_rows: int = 0
    non_violation_rows: int = 0
    unknown_rows: int = 0
    labeled_from_aggregated: int = 0
    labeled_from_total_failures: int = 0
    missing_case_dirs: int = 0


def _metric_sort_key(metric: str) -> tuple[int, str]:
    if metric in PREFERRED_METRIC_ORDER:
        return PREFERRED_METRIC_ORDER.index(metric), metric
    return len(PREFERRED_METRIC_ORDER), metric


def _display_metric_name(metric: str) -> str:
    return METRIC_TITLES.get(metric, metric.replace("_", " "))


def _coerce_number(value) -> float | None:
    pd = _pd()
    series = pd.to_numeric(pd.Series([value]), errors="coerce")
    number = series.iloc[0]
    if pd.isna(number):
        return None
    return float(number)


def _normalize_case_component(value) -> str | None:
    number = _coerce_number(value)
    if number is not None:
        return str(int(number))
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_case_dir(fitness_dir: Path, generation, individual_id) -> Path | None:
    generation_label = _normalize_case_component(generation)
    individual_label = _normalize_case_component(individual_id)
    if generation_label is None or individual_label is None:
        return None
    return fitness_dir / f"G{generation_label}T{individual_label}"


def _summary_has_violation(summary: dict) -> bool:
    for key in VIOLATION_SUMMARY_KEYS:
        number = _coerce_number(summary.get(key))
        if number is not None and number != 0:
            return True

    total_iterations = _coerce_number(summary.get("total_iterations"))
    correct_runs = _coerce_number(summary.get("correct_runs"))
    if total_iterations is not None and correct_runs is not None:
        if int(total_iterations) != int(correct_runs):
            return True

    return False


def _label_from_case_summary(case_dir: Path | None, cache: dict[Path, tuple[bool, str]]) -> tuple[bool | None, str]:
    if case_dir is None:
        return None, "missing_case_dir"

    summary_path = case_dir / "aggregated_spec_check_log.json"
    if not summary_path.is_file():
        return None, "missing_summary"

    cached = cache.get(summary_path)
    if cached is not None:
        return cached

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None, "invalid_summary"

    result = (_summary_has_violation(summary), "aggregated_spec_check_log")
    cache[summary_path] = result
    return result


def _label_violation(case_dir: Path | None, total_failures, cache: dict[Path, tuple[bool, str]]) -> tuple[bool | None, str]:
    label, source = _label_from_case_summary(case_dir, cache)
    if label is not None:
        return label, source

    failure_count = _coerce_number(total_failures)
    if failure_count is None:
        return None, source
    return failure_count != 0, "total_failures"


def _collect_image_dataframe(image_dir: Path):
    pd = _pd()

    csv_paths = sorted(image_dir.rglob("evo_result.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"No evo_result.csv files found under {image_dir}")

    frames = []
    stats = CollectionStats(image_dir=image_dir, csv_files=len(csv_paths))
    violation_cache: dict[Path, tuple[bool, str]] = {}

    for csv_path in csv_paths:
        try:
            df = pd.read_csv(csv_path)
        except Exception as exc:
            print(f"⚠️  跳过无法读取的文件 {csv_path}: {exc}")
            continue

        if df.empty:
            continue

        labels: list[str] = []
        sources: list[str] = []
        case_dirs: list[str] = []

        for row in df.itertuples(index=False):
            case_dir = _resolve_case_dir(
                csv_path.parent,
                getattr(row, "generation", None),
                getattr(row, "individual_id", None),
            )
            label, source = _label_violation(
                case_dir,
                getattr(row, "total_failures", None),
                violation_cache,
            )
            if case_dir is None or not case_dir.exists():
                stats.missing_case_dirs += 1
            case_dirs.append("" if case_dir is None else str(case_dir))
            labels.append("Violation" if label is True else "No violation" if label is False else UNKNOWN_GROUP)
            sources.append(source)

        df = df.copy()
        df[VIOLATION_GROUP_COLUMN] = labels
        df[VIOLATION_SOURCE_COLUMN] = sources
        df[CASE_DIR_COLUMN] = case_dirs
        df[CSV_PATH_COLUMN] = str(csv_path)
        df[FITNESS_DIR_COLUMN] = csv_path.parent.name
        df[ENCODING_DIR_COLUMN] = csv_path.parent.parent.name
        df[IMAGE_DIR_COLUMN] = image_dir.name
        frames.append(df)

    if not frames:
        raise RuntimeError(f"Could not read any evo_result.csv data under {image_dir}")

    combined = pd.concat(frames, ignore_index=True)
    stats.total_rows = int(len(combined))
    stats.violation_rows = int((combined[VIOLATION_GROUP_COLUMN] == "Violation").sum())
    stats.non_violation_rows = int((combined[VIOLATION_GROUP_COLUMN] == "No violation").sum())
    stats.unknown_rows = int((combined[VIOLATION_GROUP_COLUMN] == UNKNOWN_GROUP).sum())
    stats.labeled_from_aggregated = int(
        (combined[VIOLATION_SOURCE_COLUMN] == "aggregated_spec_check_log").sum()
    )
    stats.labeled_from_total_failures = int(
        (combined[VIOLATION_SOURCE_COLUMN] == "total_failures").sum()
    )
    return combined, stats


def _collect_metric_columns(df) -> list[str]:
    pd = _pd()
    metrics: list[str] = []
    for column in df.columns:
        if column in EXCLUDED_COLUMNS or column.startswith(OBJECTIVE_COLUMN_PREFIX):
            continue
        numeric = pd.to_numeric(df[column], errors="coerce")
        if numeric.notna().any():
            metrics.append(column)
    return sorted(metrics, key=_metric_sort_key)


def _build_summary_page(fig, stats: CollectionStats, metrics: list[str]) -> None:
    ax = fig.add_subplot(111)
    ax.axis("off")

    lines = [
        "Fitness vs Violation Boxplots",
        "",
        f"image_dir: {stats.image_dir}",
        f"csv_files: {stats.csv_files}",
        f"rows_total: {stats.total_rows}",
        f"rows_no_violation: {stats.non_violation_rows}",
        f"rows_violation: {stats.violation_rows}",
        f"rows_unknown: {stats.unknown_rows}",
        "",
        "violation_label_rule:",
        "1. Prefer case_dir/aggregated_spec_check_log.json",
        "2. Fallback to evo_result.csv total_failures != 0",
        "",
        f"labels_from_aggregated_spec: {stats.labeled_from_aggregated}",
        f"labels_from_total_failures: {stats.labeled_from_total_failures}",
        f"rows_with_missing_case_dir: {stats.missing_case_dirs}",
        "",
        "excluded_columns:",
        "- generic fitness column (mixed semantics across fitness_type)",
        "- total_failures (used only for labeling)",
        "- objective_seq_* / objective metadata columns",
        "",
        f"metrics_plotted: {len(metrics)}",
        ", ".join(metrics),
    ]
    ax.text(
        0.03,
        0.97,
        "\n".join(lines),
        va="top",
        ha="left",
        family="monospace",
        fontsize=10,
    )


def _plot_metric_boxplot(ax, df, metric: str) -> None:
    pd = _pd()

    no_violation = pd.to_numeric(
        df.loc[df[VIOLATION_GROUP_COLUMN] == "No violation", metric],
        errors="coerce",
    ).dropna()
    violation = pd.to_numeric(
        df.loc[df[VIOLATION_GROUP_COLUMN] == "Violation", metric],
        errors="coerce",
    ).dropna()

    datasets = []
    labels = []
    colors = []

    if not no_violation.empty:
        datasets.append(no_violation.to_list())
        labels.append(f"No violation\nn={len(no_violation)}")
        colors.append("#4C8EDA")
    if not violation.empty:
        datasets.append(violation.to_list())
        labels.append(f"Violation\nn={len(violation)}")
        colors.append("#D95F5F")

    ax.set_title(_display_metric_name(metric), fontsize=11, fontweight="bold")
    ax.grid(axis="y", linestyle=":", alpha=0.5)

    if not datasets:
        ax.text(0.5, 0.5, "No numeric data", ha="center", va="center")
        return

    boxplot = ax.boxplot(
        datasets,
        tick_labels=labels,
        patch_artist=True,
        widths=0.6,
        medianprops={"color": "#222222", "linewidth": 1.5},
        boxprops={"linewidth": 1.0},
        whiskerprops={"linewidth": 1.0},
        capprops={"linewidth": 1.0},
        flierprops={
            "marker": "o",
            "markersize": 3,
            "markerfacecolor": "#555555",
            "markeredgecolor": "#555555",
            "alpha": 0.45,
        },
    )
    for patch, color in zip(boxplot["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.tick_params(axis="x", labelsize=9)
    ax.tick_params(axis="y", labelsize=9)


def generate_report_for_image(image_dir: Path, *, output_name: str = OUTPUT_NAME) -> Path:
    plt, PdfPages = _plot_deps()
    df, stats = _collect_image_dataframe(image_dir)
    df = df[df[VIOLATION_GROUP_COLUMN] != UNKNOWN_GROUP].copy()
    metrics = _collect_metric_columns(df)
    if not metrics:
        raise RuntimeError(f"No plottable metric columns found under {image_dir}")

    output_path = image_dir / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with PdfPages(output_path) as pdf:
        summary_fig = plt.figure(figsize=(12, 8))
        _build_summary_page(summary_fig, stats, metrics)
        pdf.savefig(summary_fig, bbox_inches="tight")
        plt.close(summary_fig)

        plots_per_page = 6
        rows = 3
        cols = 2
        for start in range(0, len(metrics), plots_per_page):
            chunk = metrics[start : start + plots_per_page]
            fig, axes = plt.subplots(rows, cols, figsize=(13, 15), constrained_layout=True)
            flat_axes = axes.flatten()
            for ax, metric in zip(flat_axes, chunk):
                _plot_metric_boxplot(ax, df, metric)
            for ax in flat_axes[len(chunk) :]:
                ax.axis("off")
            fig.suptitle(
                f"{image_dir.name}: violation vs non-violation metric distributions",
                fontsize=14,
                fontweight="bold",
            )
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)

    return output_path


def _resolve_image_dirs(target: Path | None) -> list[Path]:
    if target is None:
        target = find_latest_run_dir()
        if target is None:
            raise FileNotFoundError("Could not find the latest logs run directory.")

    target = target.expanduser().resolve()
    level = detect_level(target)

    if level == Level.DATE:
        return sorted(
            path for path in target.iterdir() if path.is_dir() and detect_level(path) == Level.IMAGE
        )
    if level == Level.IMAGE:
        return [target]
    if level == Level.ENCODING:
        return [target.parent]
    if level == Level.FITNESS:
        return [target.parent.parent]
    if level == Level.CASE:
        return [target.parent.parent.parent]
    raise ValueError(f"Unsupported analysis level for {target}")


def run(target: Path | None = None, *, output_name: str = OUTPUT_NAME) -> list[Path]:
    outputs: list[Path] = []
    for image_dir in _resolve_image_dirs(target):
        print(f"👉 汇总 image 目录 {image_dir} -> {image_dir / output_name}")
        output_path = generate_report_for_image(image_dir, output_name=output_name)
        print(f"✅ image 级 violation boxplots 已保存至: {output_path}")
        outputs.append(output_path)
    return outputs


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate image-level boxplots that compare metric distributions "
            "between violation and non-violation tests."
        )
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=None,
        help="Date/image/encoding/fitness/case directory. Defaults to the latest run under logs/.",
    )
    parser.add_argument(
        "--output-name",
        default=OUTPUT_NAME,
        help=f"Output PDF name inside each image directory (default: {OUTPUT_NAME}).",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    run(args.path, output_name=args.output_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
