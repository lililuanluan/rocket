from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .violation_boxplot import (
    OBJECTIVE_COLUMN_PREFIX,
    UNKNOWN_GROUP,
    VIOLATION_GROUP_COLUMN,
    _collect_image_dataframe,
    _resolve_image_dirs,
)


OUTPUT_NAME = "_multi_objective_violation_analysis.pdf"


def _pd():
    import pandas as pd

    return pd


def _np():
    import numpy as np

    return np


def _plot_deps():
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    return plt, PdfPages


@dataclass
class FitnessTypeSummary:
    fitness_type: str
    objective_columns: list[str]
    total_rows: int
    no_violation_rows: int
    violation_rows: int
    complete_rows: int
    mean_abs_cliffs_delta: float
    centroid_distance: float


def _objective_sort_key(column: str) -> tuple[int, str]:
    try:
        return int(column.removeprefix(OBJECTIVE_COLUMN_PREFIX)), column
    except ValueError:
        return 10**9, column


def _objective_title(column: str) -> str:
    seq = column.removeprefix(OBJECTIVE_COLUMN_PREFIX)
    return f"Seq {seq}"


def _collect_objective_columns(df) -> list[str]:
    pd = _pd()
    objective_columns: list[str] = []
    for column in df.columns:
        if not column.startswith(OBJECTIVE_COLUMN_PREFIX):
            continue
        numeric = pd.to_numeric(df[column], errors="coerce")
        if numeric.notna().any():
            objective_columns.append(column)
    return sorted(objective_columns, key=_objective_sort_key)


def _cliffs_delta(no_violation_values, violation_values) -> float:
    np = _np()
    if len(no_violation_values) == 0 or len(violation_values) == 0:
        return 0.0
    comparison = violation_values[:, None] - no_violation_values[None, :]
    wins = np.sum(comparison > 0)
    losses = np.sum(comparison < 0)
    return float((wins - losses) / comparison.size)


def _prepare_dataframe(image_dir: Path):
    pd = _pd()
    df, _ = _collect_image_dataframe(image_dir)
    df = df[df[VIOLATION_GROUP_COLUMN] != UNKNOWN_GROUP].copy()
    if "fitness_type" not in df.columns:
        raise RuntimeError("Missing fitness_type column in collected data.")

    objective_columns = _collect_objective_columns(df)
    if not objective_columns:
        raise RuntimeError(f"No objective_seq_* columns found under {image_dir}")

    for column in objective_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    return df, objective_columns


def _summarize_fitness_types(df, objective_columns: list[str]):
    summaries: list[FitnessTypeSummary] = []

    for fitness_type, part in df.groupby("fitness_type", dropna=True):
        fitness_objectives = [column for column in objective_columns if part[column].notna().any()]
        if not fitness_objectives:
            continue

        no_violation_rows = int((part[VIOLATION_GROUP_COLUMN] == "No violation").sum())
        violation_rows = int((part[VIOLATION_GROUP_COLUMN] == "Violation").sum())

        deltas = []
        for column in fitness_objectives:
            no_violation = part.loc[part[VIOLATION_GROUP_COLUMN] == "No violation", column].dropna()
            violation = part.loc[part[VIOLATION_GROUP_COLUMN] == "Violation", column].dropna()
            if not no_violation.empty and not violation.empty:
                deltas.append(abs(_cliffs_delta(no_violation.to_numpy(), violation.to_numpy())))

        summaries.append(
            FitnessTypeSummary(
                fitness_type=str(fitness_type),
                objective_columns=fitness_objectives,
                total_rows=int(len(part)),
                no_violation_rows=no_violation_rows,
                violation_rows=violation_rows,
                complete_rows=int(part.dropna(subset=fitness_objectives, how="any").shape[0]),
                mean_abs_cliffs_delta=float(sum(deltas) / len(deltas)) if deltas else 0.0,
                centroid_distance=0.0,
            )
        )

    return sorted(
        summaries,
        key=lambda item: (
            item.fitness_type,
        ),
    )


def _plot_fitness_type_page(pdf, df, summary: FitnessTypeSummary) -> None:
    plt, _ = _plot_deps()

    part = df[df["fitness_type"] == summary.fitness_type].copy()
    objective_columns = summary.objective_columns

    fig, axes = plt.subplots(3, 2, figsize=(13, 15), constrained_layout=True)
    flat_axes = axes.flatten()
    for ax, column in zip(flat_axes, objective_columns):
        no_violation = part.loc[part[VIOLATION_GROUP_COLUMN] == "No violation", column].dropna()
        violation = part.loc[part[VIOLATION_GROUP_COLUMN] == "Violation", column].dropna()
        delta = _cliffs_delta(no_violation.to_numpy(), violation.to_numpy()) if not no_violation.empty and not violation.empty else 0.0

        data = []
        labels = []
        colors = []
        if not no_violation.empty:
            data.append(no_violation.to_list())
            labels.append(f"No violation\nn={len(no_violation)}")
            colors.append("#4C8EDA")
        if not violation.empty:
            data.append(violation.to_list())
            labels.append(f"Violation\nn={len(violation)}")
            colors.append("#D95F5F")

        ax.set_title(
            f"{_objective_title(column)}\nCliff's delta={delta:.3f}",
            fontsize=10.5,
            fontweight="bold",
        )
        ax.grid(axis="y", linestyle=":", alpha=0.5)
        if data:
            boxplot = ax.boxplot(
                data,
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
        else:
            ax.text(0.5, 0.5, "No numeric data", ha="center", va="center")

    for ax in flat_axes[len(objective_columns) :]:
        ax.axis("off")

    fig.suptitle(
        (
            f"{summary.fitness_type}: multi-objective distributions by sequence\n"
            f"rows={summary.total_rows}, no_violation={summary.no_violation_rows}, "
            f"violation={summary.violation_rows}, mean|delta|={summary.mean_abs_cliffs_delta:.3f}"
        ),
        fontsize=14,
        fontweight="bold",
    )
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def generate_report_for_image(image_dir: Path, *, output_name: str = OUTPUT_NAME) -> Path:
    plt, PdfPages = _plot_deps()
    df, objective_columns = _prepare_dataframe(image_dir)
    summaries = _summarize_fitness_types(df, objective_columns)

    output_path = image_dir / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with PdfPages(output_path) as pdf:
        for summary in summaries:
            print(
                f"  - {summary.fitness_type}: "
                f"nVio={summary.violation_rows}, nOk={summary.no_violation_rows}, "
                f"seqs={len(summary.objective_columns)}"
            )
            _plot_fitness_type_page(pdf, df, summary)

    return output_path


def run(target: Path | None = None, *, output_name: str = OUTPUT_NAME) -> list[Path]:
    outputs: list[Path] = []
    for image_dir in _resolve_image_dirs(target):
        print(f"👉 汇总 image 多目标目录 {image_dir} -> {image_dir / output_name}")
        output_path = generate_report_for_image(image_dir, output_name=output_name)
        print(f"✅ image 级多目标 violation 分析已保存至: {output_path}")
        outputs.append(output_path)
    return outputs


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze each fitness_type as a multi-objective vector over objective_seq_* "
            "and compare its violation separability."
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
