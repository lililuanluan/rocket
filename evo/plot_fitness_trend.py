import pandas as pd
import matplotlib.pyplot as plt
import argparse
import sys
from matplotlib.ticker import MaxNLocator
from matplotlib.backends.backend_pdf import PdfPages
from pathlib import Path
from typing import Iterable

def find_latest_log_dir() -> Path | None:
    """Locate the newest child directory under ../logs relative to this file."""
    logs_root = Path(__file__).resolve().parent.parent / "logs"
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


def generate_report(csv_path: Path, output_path: Path) -> None:
    """Load a CSV and write a PDF report next to it."""
    if not csv_path.exists():
        print(f"❌ 错误: 找不到文件 '{csv_path}'，请检查路径是否正确。")
        return

    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:  # 捕获任何读取错误
        print(f"❌ 读取 '{csv_path}' 失败: {exc}")
        return

    # 尝试将 generation 列转换为数值，若失败则丢弃该行
    df['generation'] = pd.to_numeric(df.get('generation'), errors='coerce')
    df = df.dropna(subset=['generation'])

    if df.empty:
        print(f"⚠️  跳过空数据文件: {csv_path}")
        return

    # 3. 提取指标列
    exclude_cols = ['generation', 'individual_id', 'fitness_type']
    metrics = [col for col in df.columns if col not in exclude_cols]

    if not metrics:
        print(f"⚠️  未发现可绘制的指标列，跳过: {csv_path}")
        return

    # 尝试从 CSV 中读取 fitness_type（如果存在）用于图表标题
    fitness_types = []
    if 'fitness_type' in df.columns:
        fitness_types = sorted(df['fitness_type'].dropna().unique())
    fitness_label = (
        fitness_types[0] if len(fitness_types) == 1 else ', '.join(fitness_types)
    ) if fitness_types else None

    # 将所有指标列转换为数值，以便在出现 '-' 或其他非数字字段时不报错
    for col in metrics:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # 按代数分组计算均值和标准差
    stats = df.groupby('generation')[metrics].agg(['mean', 'std']).reset_index()

    # 4. 绘图配置
    num_metrics = len(metrics)
    cols_per_row = 2
    rows = (num_metrics + 1) // cols_per_row

    fig, axes = plt.subplots(rows, cols_per_row, figsize=(12, 3.8 * rows), constrained_layout=True)
    axes = axes.flatten()

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
        title = f'Metric: {metric}'
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


def collect_csvs_from_input(input_path: Path) -> list[Path]:
    """Accept either a CSV file path or a directory under logs and return csv list."""
    if input_path.is_dir():
        csvs = sorted(input_path.rglob("evo_result.csv"))
        return csvs
    return [input_path]


def main():
    # 1. 配置命令行参数
    parser = argparse.ArgumentParser(description='绘制演化算法指标趋势图')
    parser.add_argument('input', nargs='?', default=None, help='可以是 evo_result.csv 文件路径，或 logs 下的目录路径；若不提供则自动搜索最新日志目录')
    parser.add_argument('-o', '--output', default='out/evolution_report.pdf', help='输出的 PDF 文件名（仅当 input 指定为单个 CSV 文件时生效；若 input 为目录则忽略）')

    args = parser.parse_args()

    # 如果没有 input，自动搜索最新日志目录下的所有 evo_result.csv
    if args.input is None:
        csv_files = get_csv_files()
        if not csv_files:
            print("❌ 未找到最新日志目录或其中的 evo_result.csv。")
            sys.exit(1)

        for csv_path in csv_files:
            report_path = csv_path.with_name('evolution_report.pdf')
            print(f"👉 处理 {csv_path} -> {report_path}")
            generate_report(csv_path, report_path)
    else:
        input_path = Path(args.input).expanduser().resolve()
        csv_files = collect_csvs_from_input(input_path)
        if not csv_files:
            print(f"❌ 在 {input_path} 下未找到 evo_result.csv。")
            sys.exit(1)

        # 如果用户传入的是目录，则忽略 --output，按原地生成
        use_custom_output = len(csv_files) == 1 and input_path.is_file()

        for csv_path in csv_files:
            if use_custom_output:
                output_path = Path(args.output)
            else:
                output_path = csv_path.with_name('evolution_report.pdf')
            print(f"👉 处理 {csv_path} -> {output_path}")
            generate_report(csv_path, output_path)


if __name__ == "__main__":
    main()