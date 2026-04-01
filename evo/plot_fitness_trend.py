import pandas as pd
import matplotlib.pyplot as plt
import argparse
import sys
from matplotlib.ticker import MaxNLocator
from pathlib import Path
from utils import get_logs_root

titles = {

    "num_propose_set": "number of proposeset",
    "num_getledger_hashes": "number of distinct getledger hashes",
    "num_getledger_messages": "number of getledger messages",
    "mean_validation_time": "mean validation time",
    "var_validation_time": "variance of validation time",
    "validation_distribution_entropy": "validation distribution entropy",
    "message_entropy_integral": "integral of message entropy over time",
    "markov_matrix_non_similarity": "message markov matrix non similarity",
    "message_entropy_average": "message entropy per second"
}

FITNESS_REPORT_NAME = "evolution_report.pdf"
STRATEGY_REPORT_NAME = "fitness_trend_report.pdf"


def get_metric_title(metric_name: str) -> str:
    """Return the display title for a metric/fitness name."""
    return titles.get(metric_name, metric_name)

def find_latest_log_dir() -> Path | None:
    """Locate the newest child directory under ../logs relative to this file."""
    rocket_dir = Path(__file__).resolve().parent.parent
    logs_root = get_logs_root(rocket_dir)
    if not logs_root.exists():
        return None

    subdirs = [p for p in logs_root.iterdir() if p.is_dir()]
    if not subdirs:
        return None

    return max(subdirs, key=lambda p: p.stat().st_mtime)


def get_csv_files() -> list[Path]:
    """Return evo_result.csv files under the newest logs subdirectory."""
    latest_dir = find_latest_log_dir()
    if latest_dir is None:
        return []

    # 递归搜索最新日志目录下的所有 evo_result.csv
    return sorted(latest_dir.rglob("evo_result.csv"))


def load_plot_data(csv_path: Path) -> tuple[pd.DataFrame, list[str], str | None] | None:
    """Load, clean and describe a CSV for plotting."""
    if not csv_path.exists():
        print(f"❌ 错误: 找不到文件 '{csv_path}'，请检查路径是否正确。")
        return None

    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:  # 捕获任何读取错误
        print(f"❌ 读取 '{csv_path}' 失败: {exc}")
        return None

    # 尝试将 generation 列转换为数值，若失败则丢弃该行
    df['generation'] = pd.to_numeric(df.get('generation'), errors='coerce')
    df = df.dropna(subset=['generation'])

    if df.empty:
        print(f"⚠️  跳过空数据文件: {csv_path}")
        return None

    # 3. 提取指标列
    exclude_cols = ['generation', 'individual_id', 'fitness_type']
    metrics = [col for col in df.columns if col not in exclude_cols]

    if not metrics:
        print(f"⚠️  未发现可绘制的指标列，跳过: {csv_path}")
        return None

    # 尝试从 CSV 中读取 fitness_type（如果存在）用于图表标题
    fitness_types = []
    if 'fitness_type' in df.columns:
        fitness_types = sorted(df['fitness_type'].dropna().unique())
    fitness_label = (
        fitness_types[0] if len(fitness_types) == 1 else ', '.join(fitness_types)
    ) if fitness_types else None

    # 如果某个测试的任一指标列出现 '-'，说明该测试实际没有跑起来；
    # 这种行虽然 fitness 可能被置为 0，但不应纳入趋势统计。
    invalid_metric_rows = df[metrics].apply(
        lambda row: any(isinstance(value, str) and value.strip() == '-' for value in row),
        axis=1,
    )
    skipped_rows = int(invalid_metric_rows.sum())
    if skipped_rows:
        print(f"⚠️  跳过 {skipped_rows} 行未成功运行的测试记录: {csv_path}")
        df = df.loc[~invalid_metric_rows].copy()

    if df.empty:
        print(f"⚠️  跳过没有有效指标数据的文件: {csv_path}")
        return None

    # 将所有指标列转换为数值，以便在出现其他非数字字段时不报错
    for col in metrics:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # 若某行所有指标都无法解析为数值，也视为无效测试并跳过。
    df = df.dropna(subset=metrics, how='all')

    if df.empty:
        print(f"⚠️  跳过没有可绘制数值数据的文件: {csv_path}")
        return None

    if not fitness_label:
        fitness_label = csv_path.parent.name

    return df, metrics, fitness_label


def build_metric_stats(df: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    """Aggregate mean/std by generation for the selected metrics."""
    return df.groupby('generation')[metrics].agg(['mean', 'std']).reset_index()


def build_subplot_grid(num_metrics: int):
    cols_per_row = 2
    rows = (num_metrics + cols_per_row - 1) // cols_per_row
    fig, axes = plt.subplots(
        rows,
        cols_per_row,
        figsize=(12, 3.8 * rows),
        constrained_layout=True,
    )
    axes = axes.flatten()
    return fig, axes


def generate_report(csv_path: Path, output_path: Path) -> None:
    """Load a CSV and write a PDF report next to it."""
    plot_data = load_plot_data(csv_path)
    if plot_data is None:
        return

    df, metrics, fitness_label = plot_data

    # 按代数分组计算均值和标准差
    stats = build_metric_stats(df, metrics)

    # 4. 绘图配置
    num_metrics = len(metrics)
    fig, axes = build_subplot_grid(num_metrics)

    for i, metric in enumerate(metrics):
        ax = axes[i]
        x = stats['generation']
        y_mean = stats[metric]['mean']
        y_std = stats[metric]['std'].fillna(0)
        
        # 绘图
        ax.plot(x, y_mean, label='Mean', color='#2c7fb8', linewidth=2, marker='o', markersize=4)
        ax.fill_between(x, y_mean - y_std, y_mean + y_std, alpha=0.2, color='#2c7fb8')
        
        # 强制 X 轴为整数
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        
        # 添加 fitness_type 到标题
        title = get_metric_title(metric)
        if fitness_label:
            title += f' (fitness={fitness_label})'
        ax.set_title(title, fontsize=12, fontweight='bold')
        
        ax.set_xlabel('Generation')
        ax.set_ylabel('Value')
        ax.grid(True, linestyle=':', alpha=0.7)
        ax.legend(loc='best')

    # 隐藏多余子图
    for j in range(i + 1, len(axes)):
        axes[j].axis('off')

    # 5. 保存 PDF
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, format='pdf', bbox_inches='tight')
    plt.close(fig)
    print(f"✅ 成功！报告已保存至: {output_path}")


def find_strategy_dir(csv_path: Path) -> Path | None:
    """Infer the strategy directory from .../<strategy>/<fitness>/evo_result.csv."""
    if csv_path.name != 'evo_result.csv':
        return None
    if len(csv_path.parents) < 3:
        return None
    return csv_path.parent.parent


def is_same_or_child(path: Path, root: Path) -> bool:
    """Return True when path is root or inside root."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def collect_strategy_csv_groups(csv_files: list[Path], root_dir: Path | None = None) -> dict[Path, list[Path]]:
    """Group CSVs by their strategy directory."""
    groups: dict[Path, list[Path]] = {}
    for csv_path in csv_files:
        strategy_dir = find_strategy_dir(csv_path)
        if strategy_dir is None:
            continue
        if root_dir is not None and not is_same_or_child(strategy_dir, root_dir):
            continue
        groups.setdefault(strategy_dir, []).append(csv_path)

    for strategy_dir, group_csvs in groups.items():
        group_csvs.sort(key=lambda path: path.parent.name)
    return groups


def resolve_strategy_metric(metrics: list[str], fitness_label: str | None) -> str | None:
    """Choose the best column to represent a fitness trend for strategy-level plots."""
    candidates = []
    if fitness_label:
        candidates.append(fitness_label)
    candidates.append('fitness')

    for candidate in candidates:
        if candidate in metrics:
            return candidate
    return None


def generate_strategy_report(strategy_dir: Path, csv_files: list[Path], output_path: Path) -> None:
    """Generate one report under a strategy directory with all fitness trends."""
    plot_entries: list[tuple[str, str, pd.DataFrame]] = []

    for csv_path in csv_files:
        plot_data = load_plot_data(csv_path)
        if plot_data is None:
            continue

        df, metrics, fitness_label = plot_data
        metric_name = resolve_strategy_metric(metrics, fitness_label)
        if metric_name is None:
            print(f"⚠️  未找到可用于 strategy 聚合的 fitness 列，跳过: {csv_path}")
            continue

        label = fitness_label or csv_path.parent.name
        stats = build_metric_stats(df, [metric_name])
        plot_entries.append((label, metric_name, stats))

    if not plot_entries:
        print(f"⚠️  strategy 目录下没有可绘制的 fitness 趋势: {strategy_dir}")
        return

    fig, axes = build_subplot_grid(len(plot_entries))

    for i, (fitness_label, metric_name, stats) in enumerate(plot_entries):
        ax = axes[i]
        x = stats['generation']
        y_mean = stats[metric_name]['mean']
        y_std = stats[metric_name]['std'].fillna(0)

        ax.plot(x, y_mean, label='Mean', color='#d95f02', linewidth=2, marker='o', markersize=4)
        ax.fill_between(x, y_mean - y_std, y_mean + y_std, alpha=0.2, color='#d95f02')
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_title(get_metric_title(fitness_label), fontsize=12, fontweight='bold')
        ax.set_xlabel('Generation')
        ax.set_ylabel('Value')
        ax.grid(True, linestyle=':', alpha=0.7)
        ax.legend(loc='best')

    for j in range(i + 1, len(axes)):
        axes[j].axis('off')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, format='pdf', bbox_inches='tight')
    plt.close(fig)
    print(f"✅ 成功！strategy 级 fitness 报告已保存至: {output_path}")


def collect_csvs_from_input(input_path: Path) -> list[Path]:
    """Accept either a CSV file path or a directory under logs and return csv list."""
    if input_path.is_dir():
        csvs = sorted(input_path.rglob("evo_result.csv"))
        return csvs
    return [input_path]


def generate_reports_for_csvs(
    csv_files: list[Path],
    custom_output: Path | None = None,
    strategy_root_dir: Path | None = None,
) -> None:
    """Generate per-fitness reports and optional per-strategy aggregate reports."""
    use_custom_output = custom_output is not None and len(csv_files) == 1

    for csv_path in csv_files:
        output_path = custom_output if use_custom_output else csv_path.with_name(FITNESS_REPORT_NAME)
        print(f"👉 处理 {csv_path} -> {output_path}")
        generate_report(csv_path, output_path)

    if strategy_root_dir is None:
        return

    strategy_groups = collect_strategy_csv_groups(csv_files, root_dir=strategy_root_dir)
    for strategy_dir, strategy_csvs in strategy_groups.items():
        output_path = strategy_dir / STRATEGY_REPORT_NAME
        print(f"👉 汇总 strategy 目录 {strategy_dir} -> {output_path}")
        generate_strategy_report(strategy_dir, strategy_csvs, output_path)


def main():
    # 1. 配置命令行参数
    parser = argparse.ArgumentParser(description='绘制演化算法指标趋势图')
    parser.add_argument('input', nargs='?', default=None, help='可以是 evo_result.csv 文件路径，或 logs 下的目录路径；若不提供则自动搜索最新日志目录')
    parser.add_argument('-o', '--output', default='out/evolution_report.pdf', help='输出的 PDF 文件名（仅当 input 指定为单个 CSV 文件时生效；若 input 为目录则忽略）')

    args = parser.parse_args()

    # 如果没有 input，自动搜索最新日志目录下的所有 evo_result.csv
    if args.input is None:
        latest_dir = find_latest_log_dir()
        if latest_dir is None:
            print("❌ 未找到最新日志目录或其中的 evo_result.csv。")
            sys.exit(1)

        csv_files = sorted(latest_dir.rglob("evo_result.csv"))
        if not csv_files:
            print("❌ 未找到最新日志目录或其中的 evo_result.csv。")
            sys.exit(1)

        generate_reports_for_csvs(csv_files, strategy_root_dir=latest_dir)
    else:
        input_path = Path(args.input).expanduser().resolve()
        csv_files = collect_csvs_from_input(input_path)
        if not csv_files:
            print(f"❌ 在 {input_path} 下未找到 evo_result.csv。")
            sys.exit(1)

        # 如果用户传入的是目录，则忽略 --output，按原地生成
        custom_output = Path(args.output) if len(csv_files) == 1 and input_path.is_file() else None
        strategy_root_dir = input_path if input_path.is_dir() else None
        generate_reports_for_csvs(
            csv_files,
            custom_output=custom_output,
            strategy_root_dir=strategy_root_dir,
        )


if __name__ == "__main__":
    main()
