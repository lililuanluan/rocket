from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from evo.utils import get_logs_root


titles = {
    "num_propose_set": "number of proposeset",
    "num_getledger_hashes": "number of distinct getledger hashes",
    "num_getledger_messages": "number of getledger messages",
    "mean_validation_time": "mean validation time",
    "var_validation_time": "variance of validation time",
    "diff_validation_time_max": "max validation time range",
    "validation_distribution_entropy": "validation distribution entropy",
    "validation_distribution_entropy_max": "max validation distribution entropy",
    "validation_distribution_entropy_unl": "validation distribution entropy (UNL)",
    "validation_distribution_entropy_max_unl": "max validation distribution entropy (UNL)",
    "proposal_distribution_entropy": "proposal distribution entropy",
    "message_entropy_integral": "integral of message entropy over time",
    "markov_matrix_non_similarity": "message markov matrix non similarity",
    "message_entropy_average": "message entropy per second",
    "gossip_fiedler": "gossip graph fiedler value",
    "max_tip_distance": "max summed distance to trie tip",
}

FITNESS_REPORT_NAME = "_evolution_report.pdf"
STRATEGY_REPORT_NAME = "_fitness_trend_report.pdf"
MULTI_OBJECTIVE_REPORT_NAME = "_multi_objective_report.pdf"
MULTI_OBJECTIVE_PARALLEL_REPORT_NAME = "_multi_objective_parallel_coordinates.pdf"
MULTI_OBJECTIVE_SCATTER_MATRIX_REPORT_NAME = "_multi_objective_scatter_matrix.pdf"
STRATEGY_MULTI_OBJECTIVE_REPORT_NAME = "_multi_objective_fitness_trend_report.pdf"
OBJECTIVE_COLUMN_PREFIX = "objective_seq_"
METADATA_COLUMNS = {
    "generation",
    "individual_id",
    "fitness_type",
    "objective_metric",
    "objective_status",
    "objective_error",
}
NON_PLOTTED_METRIC_COLUMNS = {"total_failures"}


def _pd():
    import pandas as pd

    return pd


def _np():
    import numpy as np

    return np


def _plot_deps():
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    return plt, MaxNLocator


def emit(message: str, messages: list[str] | None = None) -> None:
    if messages is None:
        print(message)
    else:
        messages.append(message)


def get_metric_title(metric_name: str) -> str:
    if metric_name.startswith(OBJECTIVE_COLUMN_PREFIX):
        seq = metric_name.removeprefix(OBJECTIVE_COLUMN_PREFIX)
        return f"objective seq {seq}"
    return titles.get(metric_name, metric_name)


def is_objective_column(column: str) -> bool:
    return column.startswith(OBJECTIVE_COLUMN_PREFIX)


def objective_sort_key(column: str) -> tuple[int, str]:
    try:
        return int(column.removeprefix(OBJECTIVE_COLUMN_PREFIX)), column
    except ValueError:
        return 10**9, column


def get_objective_columns(metrics: list[str]) -> list[str]:
    return sorted(
        [metric for metric in metrics if is_objective_column(metric)],
        key=objective_sort_key,
    )


def get_effective_objective_columns(df, metrics: list[str]) -> list[str]:
    pd = _pd()
    objective_columns: list[str] = []
    for column in get_objective_columns(metrics):
        numeric = pd.to_numeric(df[column], errors="coerce")
        if numeric.notna().any():
            objective_columns.append(column)
    return objective_columns


def has_effective_objectives(df, metrics: list[str]) -> bool:
    return bool(get_effective_objective_columns(df, metrics))


def format_gt_label(generation: float | int, individual_id) -> str:
    pd = _pd()
    generation_label = str(int(generation)) if pd.notna(generation) else "?"
    individual_numeric = pd.to_numeric(pd.Series([individual_id]), errors="coerce").iloc[0]
    if pd.notna(individual_numeric):
        individual_label = str(int(individual_numeric))
    else:
        individual_label = str(individual_id)
    return f"G{generation_label}T{individual_label}"


def report_violation_cases(
    df,
    csv_path: Path,
    messages: list[str] | None = None,
) -> None:
    pd = _pd()
    required_cols = {"generation", "individual_id", "total_failures"}
    if not required_cols.issubset(df.columns):
        return

    failure_counts = pd.to_numeric(df["total_failures"], errors="coerce").fillna(0)
    violating_rows = df.loc[failure_counts != 0, ["generation", "individual_id", "total_failures"]]
    if violating_rows.empty:
        return

    labels = [
        format_gt_label(row.generation, row.individual_id)
        for row in violating_rows.itertuples(index=False)
    ]
    unique_labels = list(dict.fromkeys(labels))
    emit(
        f"🎉🎉🎉 {csv_path} 中存在 violation(total_failures != 0): {', '.join(unique_labels)}",
        messages,
    )


def find_latest_log_dir() -> Path | None:
    rocket_dir = Path(__file__).resolve().parents[2]
    logs_root = get_logs_root(rocket_dir)
    if not logs_root.exists():
        return None

    subdirs = [p for p in logs_root.iterdir() if p.is_dir()]
    if not subdirs:
        return None

    return max(subdirs, key=lambda p: p.stat().st_mtime)


def collect_csvs_from_logs_dir(root_dir: Path) -> list[Path]:
    direct_csv = root_dir / "evo_result.csv"
    if direct_csv.is_file():
        return [direct_csv]

    csv_files: set[Path] = set()
    for pattern in ("*/evo_result.csv", "*/*/evo_result.csv", "*/*/*/evo_result.csv"):
        for csv_path in root_dir.glob(pattern):
            if csv_path.is_file():
                csv_files.add(csv_path)

    if csv_files:
        return sorted(csv_files)

    return sorted(root_dir.rglob("evo_result.csv"))


def load_plot_data(
    csv_path: Path,
    messages: list[str] | None = None,
):
    pd = _pd()
    if not csv_path.exists():
        emit(f"❌ 错误: 找不到文件 '{csv_path}'，请检查路径是否正确。", messages)
        return None

    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        emit(f"❌ 读取 '{csv_path}' 失败: {exc}", messages)
        return None

    df["generation"] = pd.to_numeric(df.get("generation"), errors="coerce")
    df = df.dropna(subset=["generation"])

    if df.empty:
        emit(f"⚠️  跳过空数据文件: {csv_path}", messages)
        return None

    metrics = [col for col in df.columns if col not in METADATA_COLUMNS]
    if not metrics:
        emit(f"⚠️  未发现可绘制的指标列，跳过: {csv_path}", messages)
        return None

    fitness_types = []
    if "fitness_type" in df.columns:
        fitness_types = sorted(df["fitness_type"].dropna().unique())
    fitness_label = (
        fitness_types[0] if len(fitness_types) == 1 else ", ".join(map(str, fitness_types))
    ) if fitness_types else None

    invalid_metric_rows = df[metrics].eq("-").any(axis=1)
    skipped_rows = int(invalid_metric_rows.sum())
    if skipped_rows:
        emit(f"⚠️  跳过 {skipped_rows} 行未成功运行的测试记录: {csv_path}", messages)
        df = df.loc[~invalid_metric_rows].copy()

    if df.empty:
        emit(f"⚠️  跳过没有有效指标数据的文件: {csv_path}", messages)
        return None

    for col in metrics:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=metrics, how="all")
    if df.empty:
        emit(f"⚠️  跳过没有可绘制数值数据的文件: {csv_path}", messages)
        return None

    plot_metrics = [col for col in metrics if col not in NON_PLOTTED_METRIC_COLUMNS]
    if not plot_metrics:
        emit(f"⚠️  未发现可绘制的趋势指标列，跳过: {csv_path}", messages)
        return None

    report_violation_cases(df, csv_path, messages)

    if not fitness_label:
        fitness_label = csv_path.parent.name

    return df, plot_metrics, fitness_label


def build_metric_stats(df, metrics: list[str]):
    return df.groupby("generation")[metrics].agg(["mean", "std", "max"]).reset_index()


def build_objective_stats(df, objective_columns: list[str]):
    if not objective_columns:
        return None
    complete = df.dropna(subset=objective_columns, how="all")
    if complete.empty:
        return None
    return build_metric_stats(complete, objective_columns)


def build_violation_counts(df):
    pd = _pd()
    if "total_failures" not in df.columns:
        return None

    violations = pd.to_numeric(df["total_failures"], errors="coerce").fillna(0) != 0
    frame = df[["generation"]].copy()
    frame["violation_count"] = violations.astype(int)
    return frame.groupby("generation", as_index=False)["violation_count"].sum()


def configure_violation_axis(ax, violation_counts, MaxNLocator):
    ax2 = ax.twinx()
    ax2.plot(
        violation_counts["generation"],
        violation_counts["violation_count"],
        label="Violations",
        color="#1b9e77",
        linewidth=2,
        marker="s",
        markersize=4,
    )
    max_count = float(violation_counts["violation_count"].max()) if not violation_counts.empty else 0.0
    if max_count <= 0:
        ax2.set_ylim(-0.5, 0.5)
    else:
        ax2.set_ylim(0, max_count * 1.15)
    ax2.set_ylabel("Violation Count")
    ax2.xaxis.set_major_locator(MaxNLocator(integer=True))
    return ax2


def build_subplot_grid(num_metrics: int):
    plt, _ = _plot_deps()
    cols_per_row = 2
    rows = max(1, (num_metrics + cols_per_row - 1) // cols_per_row)
    fig, axes = plt.subplots(
        rows,
        cols_per_row,
        figsize=(12, 3.8 * rows),
        constrained_layout=True,
    )
    return fig, axes.flatten()


def write_metric_report(
    df,
    metrics: list[str],
    fitness_label: str | None,
    output_path: Path,
) -> None:
    plt, MaxNLocator = _plot_deps()
    stats = build_metric_stats(df, metrics)
    violation_counts = build_violation_counts(df)
    fitness_metric_candidates = {
        candidate
        for candidate in [fitness_label, "fitness"]
        if candidate is not None and candidate in metrics
    }
    fig, axes = build_subplot_grid(len(metrics))

    for i, metric in enumerate(metrics):
        ax = axes[i]
        x = stats["generation"]
        y_mean = stats[metric]["mean"]
        y_std = stats[metric]["std"].fillna(0)
        is_primary_fitness_metric = metric in fitness_metric_candidates

        ax.plot(
            x,
            y_mean,
            label="Fitness Mean" if is_primary_fitness_metric else "Mean",
            color="#2c7fb8",
            linewidth=2,
            marker="o",
            markersize=4,
        )
        ax.fill_between(x, y_mean - y_std, y_mean + y_std, alpha=0.2, color="#2c7fb8")
        if is_primary_fitness_metric:
            y_max = stats[metric]["max"]
            ax.plot(
                x,
                y_max,
                label="Fitness Max",
                color="#2c7fb8",
                linewidth=2,
                linestyle="--",
            )
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))

        title = get_metric_title(metric)
        if fitness_label:
            title += f" (fitness={fitness_label})"
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.set_xlabel("Generation")
        ax.set_ylabel("Fitness" if is_primary_fitness_metric else "Value")
        ax.grid(True, linestyle=":", alpha=0.7)

        if is_primary_fitness_metric and violation_counts is not None and not violation_counts.empty:
            ax2 = configure_violation_axis(ax, violation_counts, MaxNLocator)
            lines = list(ax.get_lines()) + list(ax2.get_lines())
            labels = [line.get_label() for line in lines]
            ax.legend(lines, labels, loc="best")
        else:
            ax.legend(loc="best")

    for j in range(i + 1, len(axes)):
        axes[j].axis("off")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)


def write_multi_objective_report(
    df,
    objective_columns: list[str],
    fitness_label: str | None,
    output_path: Path,
) -> bool:
    plt, MaxNLocator = _plot_deps()
    stats = build_objective_stats(df, objective_columns)
    if stats is None:
        return False

    fig, axes = build_subplot_grid(len(objective_columns))
    for i, column in enumerate(objective_columns):
        ax = axes[i]
        x = stats["generation"]
        y_mean = stats[column]["mean"]
        y_std = stats[column]["std"].fillna(0)

        ax.plot(x, y_mean, label="Mean", color="#2c7fb8", linewidth=2, marker="o", markersize=4)
        ax.fill_between(x, y_mean - y_std, y_mean + y_std, alpha=0.2, color="#2c7fb8")
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))

        title = get_metric_title(column)
        if fitness_label:
            title += f" (fitness={fitness_label})"
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.set_xlabel("Generation")
        ax.set_ylabel("Objective")
        ax.grid(True, linestyle=":", alpha=0.7)
        ax.legend(loc="best")

    for j in range(i + 1, len(axes)):
        axes[j].axis("off")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)
    return True


def write_parallel_coordinates_report(
    csv_path: Path,
    df,
    objective_columns: list[str],
    fitness_label: str | None,
    output_path: Path,
) -> bool:
    plt, _ = _plot_deps()
    np = _np()
    pd = _pd()

    if len(objective_columns) < 2:
        return False

    complete = df.dropna(subset=objective_columns, how="any").copy()
    if complete.empty:
        return False

    if len(complete) > 200:
        complete = complete.sample(n=200, random_state=0)
    complete = complete.sort_values(["generation", "individual_id"], na_position="last")

    values = complete[objective_columns].to_numpy(dtype=float)
    mins = np.nanmin(values, axis=0)
    maxs = np.nanmax(values, axis=0)
    spans = np.where(maxs > mins, maxs - mins, 1.0)
    normalized = (values - mins) / spans

    color_values = np.nanmean(values, axis=1)
    color_min = float(np.nanmin(color_values))
    color_max = float(np.nanmax(color_values))
    if color_max == color_min:
        color_max = color_min + 1.0

    cmap = plt.cm.viridis
    norm = plt.Normalize(vmin=color_min, vmax=color_max)

    fig, ax = plt.subplots(figsize=(13, 6), constrained_layout=True)
    x_positions = list(range(len(objective_columns)))
    for row, color_value in zip(normalized, color_values):
        ax.plot(
            x_positions,
            row,
            color=cmap(norm(color_value)),
            alpha=0.3,
            linewidth=1.0,
        )

    ax.set_xticks(x_positions)
    ax.set_xticklabels([get_metric_title(column) for column in objective_columns], rotation=20, ha="right")
    ax.set_ylim(0.0, 1.0)
    ax.set_ylabel("Normalized objective value")
    title = "Multi-objective parallel coordinates"
    if fitness_label:
        title += f" (fitness={fitness_label})"
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.grid(True, linestyle=":", alpha=0.6)

    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    colorbar = fig.colorbar(sm, ax=ax)
    colorbar.set_label("Mean Objective Across Sequences")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)
    return True


def write_scatter_matrix_report(
    csv_path: Path,
    df,
    objective_columns: list[str],
    fitness_label: str | None,
    output_path: Path,
) -> bool:
    plt, _ = _plot_deps()
    pd = _pd()

    if len(objective_columns) < 2:
        return False

    complete = df.dropna(subset=objective_columns, how="any").copy()
    if complete.empty:
        return False

    if len(complete) > 400:
        complete = complete.sample(n=400, random_state=0)

    axes = pd.plotting.scatter_matrix(
        complete[objective_columns],
        diagonal="hist",
        alpha=0.5,
        figsize=(3.2 * len(objective_columns), 3.2 * len(objective_columns)),
    )
    fig = axes[0, 0].figure
    fig.suptitle(
        "Multi-objective scatter matrix" + (f" (fitness={fitness_label})" if fitness_label else ""),
        fontsize=14,
        fontweight="bold",
        y=1.02,
    )
    for ax in axes.flatten():
        ax.grid(True, linestyle=":", alpha=0.4)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)
    return True


def find_strategy_dir(csv_path: Path) -> Path | None:
    if csv_path.name != "evo_result.csv":
        return None
    if len(csv_path.parents) < 2:
        return None
    return csv_path.parent.parent


def is_same_or_child(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_strategy_metric(metrics: list[str], fitness_label: str | None) -> str | None:
    candidates = []
    if fitness_label:
        candidates.append(fitness_label)
    candidates.append("fitness")
    for candidate in candidates:
        if candidate in metrics:
            return candidate
    return None


def write_strategy_report(
    strategy_dir: Path,
    plot_entries,
    output_path: Path,
) -> None:
    plt, MaxNLocator = _plot_deps()
    if not plot_entries:
        return

    fig, axes = build_subplot_grid(len(plot_entries))
    for i, (fitness_label, metric_name, stats, violation_counts) in enumerate(plot_entries):
        ax = axes[i]
        x = stats["generation"]
        y_mean = stats[metric_name]["mean"]
        y_std = stats[metric_name]["std"].fillna(0)
        y_max = stats[metric_name]["max"]

        ax.plot(x, y_mean, label="Fitness Mean", color="#d95f02", linewidth=2, marker="o", markersize=4)
        ax.fill_between(x, y_mean - y_std, y_mean + y_std, alpha=0.2, color="#d95f02")
        ax.plot(
            x,
            y_max,
            label="Fitness Max",
            color="#d95f02",
            linewidth=2,
            linestyle="--",
        )
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_title(get_metric_title(fitness_label), fontsize=12, fontweight="bold")
        ax.set_xlabel("Generation")
        ax.set_ylabel("Fitness")
        ax.grid(True, linestyle=":", alpha=0.7)

        if violation_counts is not None and not violation_counts.empty:
            ax2 = configure_violation_axis(ax, violation_counts, MaxNLocator)
            lines = list(ax.get_lines()) + list(ax2.get_lines())
            labels = [line.get_label() for line in lines]
            ax.legend(lines, labels, loc="best")
        else:
            ax.legend(loc="best")

    for j in range(i + 1, len(axes)):
        axes[j].axis("off")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)


def write_strategy_multi_objective_report(
    strategy_dir: Path,
    plot_entries,
    output_path: Path,
) -> None:
    plt, MaxNLocator = _plot_deps()
    if not plot_entries:
        return

    fig, axes = build_subplot_grid(len(plot_entries))
    palette = [
        "#2c7fb8",
        "#f03b20",
        "#31a354",
        "#756bb1",
        "#e6550d",
        "#636363",
    ]
    for i, (fitness_label, objective_columns, stats, violation_counts) in enumerate(plot_entries):
        ax = axes[i]
        for idx, column in enumerate(objective_columns):
            color = palette[idx % len(palette)]
            y_mean = stats[column]["mean"]
            y_std = stats[column]["std"].fillna(0)
            ax.plot(
                stats["generation"],
                y_mean,
                label=get_metric_title(column),
                color=color,
                linewidth=2,
                marker="o",
                markersize=3,
            )
            ax.fill_between(
                stats["generation"],
                y_mean - y_std,
                y_mean + y_std,
                alpha=0.12,
                color=color,
            )

        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_title(get_metric_title(fitness_label), fontsize=12, fontweight="bold")
        ax.set_xlabel("Generation")
        ax.set_ylabel("Objective")
        ax.grid(True, linestyle=":", alpha=0.7)

        if violation_counts is not None and not violation_counts.empty:
            ax2 = configure_violation_axis(ax, violation_counts, MaxNLocator)
            lines = list(ax.get_lines()) + list(ax2.get_lines())
            labels = [line.get_label() for line in lines]
            ax.legend(lines, labels, loc="best", fontsize=8)
        else:
            ax.legend(loc="best", fontsize=8)

    for j in range(i + 1, len(axes)):
        axes[j].axis("off")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)


def generate_single_strategy_report(task) -> list[str]:
    strategy_dir, plot_entries, output_path = task
    messages: list[str] = []
    emit(f"👉 汇总 strategy 目录 {strategy_dir} -> {output_path}", messages)
    write_strategy_report(strategy_dir, plot_entries, output_path)
    emit(f"✅ 成功！strategy 级 fitness 报告已保存至: {output_path.resolve()}", messages)
    emit(f"输出 strategy_fitness_trend 到 {output_path.resolve()}", messages)
    return messages


def generate_single_strategy_multi_objective_report(task) -> list[str]:
    strategy_dir, plot_entries, output_path = task
    messages: list[str] = []
    emit(f"👉 汇总 strategy 多目标目录 {strategy_dir} -> {output_path}", messages)
    write_strategy_multi_objective_report(strategy_dir, plot_entries, output_path)
    emit(f"✅ 成功！strategy 级多目标 fitness trend 已保存至: {output_path.resolve()}", messages)
    emit(f"输出 strategy_multi_objective_fitness_trend 到 {output_path.resolve()}", messages)
    return messages


def build_strategy_entry(
    csv_path: Path,
    df,
    metrics: list[str],
    fitness_label: str | None,
    messages: list[str] | None = None,
):
    strategy_dir = find_strategy_dir(csv_path)
    if strategy_dir is None:
        return None

    metric_name = resolve_strategy_metric(metrics, fitness_label)
    if metric_name is None:
        emit(f"⚠️  未找到可用于 strategy 聚合的 fitness 列，跳过: {csv_path}", messages)
        return None

    label = fitness_label or csv_path.parent.name
    stats = build_metric_stats(df, [metric_name])
    return {
        "strategy_dir": strategy_dir,
        "csv_path": csv_path,
        "label": label,
        "metric_name": metric_name,
        "stats": stats,
        "violation_counts": build_violation_counts(df),
    }


def build_strategy_objective_entry(
    csv_path: Path,
    df,
    metrics: list[str],
    fitness_label: str | None,
):
    strategy_dir = find_strategy_dir(csv_path)
    if strategy_dir is None:
        return None

    objective_columns = get_effective_objective_columns(df, metrics)
    if not objective_columns:
        return None

    stats = build_objective_stats(df, objective_columns)
    if stats is None:
        return None

    label = fitness_label or csv_path.parent.name
    return {
        "strategy_dir": strategy_dir,
        "csv_path": csv_path,
        "label": label,
        "objective_columns": objective_columns,
        "stats": stats,
        "violation_counts": build_violation_counts(df),
    }


def generate_single_csv_report(task) -> dict:
    csv_path, output_path, write_output = task
    messages: list[str] = []
    emit(f"👉 处理 {csv_path} -> {output_path}", messages)

    plot_data = load_plot_data(csv_path, messages)
    if plot_data is None:
        return {"messages": messages, "strategy_entry": None, "strategy_objective_entry": None}

    df, metrics, fitness_label = plot_data
    objective_columns = get_effective_objective_columns(df, metrics)
    is_multi_objective = bool(objective_columns)

    if write_output:
        if is_multi_objective:
            objective_output = output_path.with_name(MULTI_OBJECTIVE_REPORT_NAME)
            wrote_objective_report = write_multi_objective_report(
                df,
                objective_columns,
                fitness_label,
                objective_output,
            )
            if wrote_objective_report:
                emit("📌 检测到多目标结果，仅生成多目标报告。", messages)
                emit(f"✅ 多目标报告已保存至: {objective_output.resolve()}", messages)
                emit(f"输出 multi_objective_report 到 {objective_output.resolve()}", messages)

            parallel_output = output_path.with_name(MULTI_OBJECTIVE_PARALLEL_REPORT_NAME)
            wrote_parallel_report = write_parallel_coordinates_report(
                csv_path,
                df,
                objective_columns,
                fitness_label,
                parallel_output,
            )
            if wrote_parallel_report:
                emit(f"✅ parallel coordinates 已保存至: {parallel_output.resolve()}", messages)
                emit(
                    f"输出 multi_objective_parallel_coordinates 到 {parallel_output.resolve()}",
                    messages,
                )

            scatter_output = output_path.with_name(MULTI_OBJECTIVE_SCATTER_MATRIX_REPORT_NAME)
            wrote_scatter_report = write_scatter_matrix_report(
                csv_path,
                df,
                objective_columns,
                fitness_label,
                scatter_output,
            )
            if wrote_scatter_report:
                emit(f"✅ scatter matrix 已保存至: {scatter_output.resolve()}", messages)
                emit(
                    f"输出 multi_objective_scatter_matrix 到 {scatter_output.resolve()}",
                    messages,
                )
        else:
            write_metric_report(df, metrics, fitness_label, output_path)
            emit("📌 未检测到多目标结果，仅生成单目标报告。", messages)
            emit(f"✅ 成功！报告已保存至: {output_path.resolve()}", messages)
            emit(f"输出 evolution_report 到 {output_path.resolve()}", messages)

    strategy_entry = None
    strategy_objective_entry = None
    if is_multi_objective:
        strategy_objective_entry = build_strategy_objective_entry(
            csv_path,
            df,
            metrics,
            fitness_label,
        )
    else:
        strategy_entry = build_strategy_entry(csv_path, df, metrics, fitness_label, messages)

    return {
        "messages": messages,
        "strategy_entry": strategy_entry,
        "strategy_objective_entry": strategy_objective_entry,
    }


def resolve_jobs(requested_jobs: int | None, num_tasks: int) -> int:
    if num_tasks <= 1:
        return 1
    if requested_jobs is not None:
        return max(1, min(requested_jobs, num_tasks))
    cpu_count = os.cpu_count() or 1
    return max(1, min(num_tasks, cpu_count))


def run_report_tasks_parallel(
    tasks: list[tuple[Path, Path, bool]],
    worker_count: int,
) -> list[dict]:
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(generate_single_csv_report, tasks))


def run_strategy_tasks_parallel(
    tasks,
    worker_count: int,
) -> list[list[str]]:
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(generate_single_strategy_report, tasks))


def run_strategy_multi_objective_tasks_parallel(
    tasks,
    worker_count: int,
) -> list[list[str]]:
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(generate_single_strategy_multi_objective_report, tasks))


def collect_strategy_entries(
    report_results: list[dict],
    root_dir: Path | None = None,
):
    groups: dict[Path, list[dict]] = {}
    for result in report_results:
        entry = result.get("strategy_entry")
        if entry is None:
            continue
        strategy_dir = entry["strategy_dir"]
        if root_dir is not None and not (
            is_same_or_child(strategy_dir, root_dir) or is_same_or_child(root_dir, strategy_dir)
        ):
            continue
        groups.setdefault(strategy_dir, []).append(entry)

    grouped_entries = {}
    for strategy_dir, entries in groups.items():
        entries.sort(key=lambda item: item["csv_path"].parent.name)
        grouped_entries[strategy_dir] = [
            (item["label"], item["metric_name"], item["stats"], item["violation_counts"])
            for item in entries
        ]
    return grouped_entries


def collect_strategy_objective_entries(
    report_results: list[dict],
    root_dir: Path | None = None,
):
    groups: dict[Path, list[dict]] = {}
    for result in report_results:
        entry = result.get("strategy_objective_entry")
        if entry is None:
            continue
        strategy_dir = entry["strategy_dir"]
        if root_dir is not None and not (
            is_same_or_child(strategy_dir, root_dir) or is_same_or_child(root_dir, strategy_dir)
        ):
            continue
        groups.setdefault(strategy_dir, []).append(entry)

    grouped_entries = {}
    for strategy_dir, entries in groups.items():
        entries.sort(key=lambda item: item["csv_path"].parent.name)
        grouped_entries[strategy_dir] = [
            (
                item["label"],
                item["objective_columns"],
                item["stats"],
                item["violation_counts"],
            )
            for item in entries
        ]
    return grouped_entries


def collect_csvs_from_input(input_path: Path) -> list[Path]:
    if input_path.is_dir():
        return collect_csvs_from_logs_dir(input_path)
    return [input_path]


def generate_reports_for_csvs(
    csv_files: list[Path],
    custom_output: Path | None = None,
    strategy_root_dir: Path | None = None,
    jobs: int | None = None,
) -> None:
    use_custom_output = custom_output is not None and len(csv_files) == 1
    tasks = [
        (
            csv_path,
            custom_output if use_custom_output else csv_path.with_name(FITNESS_REPORT_NAME),
            True,
        )
        for csv_path in csv_files
    ]

    worker_count = resolve_jobs(jobs, len(tasks))
    print(f"🚀 并行生成报告，worker 数: {worker_count}")
    report_results = run_report_tasks_parallel(tasks, worker_count)
    for result in report_results:
        for message in result["messages"]:
            print(message)

    if strategy_root_dir is None:
        return

    strategy_groups = collect_strategy_entries(report_results, root_dir=strategy_root_dir)
    strategy_tasks = [
        (strategy_dir, plot_entries, strategy_dir / STRATEGY_REPORT_NAME)
        for strategy_dir, plot_entries in strategy_groups.items()
    ]
    if strategy_tasks:
        strategy_worker_count = resolve_jobs(jobs, len(strategy_tasks))
        strategy_results = run_strategy_tasks_parallel(strategy_tasks, strategy_worker_count)
        for messages in strategy_results:
            for message in messages:
                print(message)

    strategy_objective_groups = collect_strategy_objective_entries(
        report_results,
        root_dir=strategy_root_dir,
    )
    strategy_objective_tasks = [
        (
            strategy_dir,
            plot_entries,
            strategy_dir / STRATEGY_MULTI_OBJECTIVE_REPORT_NAME,
        )
        for strategy_dir, plot_entries in strategy_objective_groups.items()
    ]
    if strategy_objective_tasks:
        strategy_objective_worker_count = resolve_jobs(jobs, len(strategy_objective_tasks))
        strategy_objective_results = run_strategy_multi_objective_tasks_parallel(
            strategy_objective_tasks,
            strategy_objective_worker_count,
        )
        for messages in strategy_objective_results:
            for message in messages:
                print(message)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="绘制演化算法指标趋势图")
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="可以是 evo_result.csv 文件路径，或 logs 下的目录路径；若不提供则自动搜索最新日志目录",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="out/evolution_report.pdf",
        help="输出的 PDF 文件名（仅当 input 指定为单个 CSV 文件时生效；若 input 为目录则忽略）",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="并行 worker 数；默认自动选择，传 1 可禁用并行",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.input is None:
        latest_dir = find_latest_log_dir()
        if latest_dir is None:
            print("❌ 未找到最新日志目录或其中的 evo_result.csv。")
            raise SystemExit(1)

        csv_files = collect_csvs_from_logs_dir(latest_dir)
        if not csv_files:
            print("❌ 未找到最新日志目录或其中的 evo_result.csv。")
            raise SystemExit(1)

        generate_reports_for_csvs(csv_files, strategy_root_dir=latest_dir, jobs=args.jobs)
        return

    input_path = Path(args.input).expanduser().resolve()
    csv_files = collect_csvs_from_input(input_path)
    if not csv_files:
        print(f"❌ 在 {input_path} 下未找到 evo_result.csv。")
        raise SystemExit(1)

    custom_output = Path(args.output) if len(csv_files) == 1 and input_path.is_file() else None
    if input_path.is_dir():
        strategy_root_dir = input_path.parent if (input_path / "evo_result.csv").is_file() else input_path
    else:
        strategy_root_dir = find_strategy_dir(input_path)
    generate_reports_for_csvs(
        csv_files,
        custom_output=custom_output,
        strategy_root_dir=strategy_root_dir,
        jobs=args.jobs,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
