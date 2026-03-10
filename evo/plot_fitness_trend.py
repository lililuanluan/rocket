import pandas as pd
import matplotlib.pyplot as plt
import argparse
import sys
from matplotlib.ticker import MaxNLocator
from matplotlib.backends.backend_pdf import PdfPages

def main():
    # 1. 配置命令行参数
    parser = argparse.ArgumentParser(description='绘制演化算法指标趋势图')
    parser.add_argument('input', help='输入的 CSV 文件路径 (例如: evo_result.csv)')
    parser.add_argument('-o', '--output', default='out/evolution_report.pdf', help='输出的 PDF 文件名 (默认: evolution_report.pdf)')
    
    args = parser.parse_args()

    # 2. 加载数据并检查文件是否存在
    try:
        df = pd.read_csv(args.input)
    except FileNotFoundError:
        print(f"❌ 错误: 找不到文件 '{args.input}'，请检查路径是否正确。")
        sys.exit(1)

    # 3. 提取指标列
    exclude_cols = ['generation', 'individual_id', 'fitness_type']
    metrics = [col for col in df.columns if col not in exclude_cols]

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
        
        ax.set_title(f'Metric: {metric}', fontsize=12, fontweight='bold')
        ax.set_xlabel('Generation')
        ax.set_ylabel('Value')
        ax.grid(True, linestyle=':', alpha=0.7)
        ax.legend(loc='best')

    # 隐藏多余子图
    for j in range(i + 1, len(axes)):
        axes[j].axis('off')

    # 5. 保存 PDF
    plt.savefig(args.output, format='pdf', bbox_inches='tight')
    plt.close(fig)
    print(f"✅ 成功！报告已保存至: {args.output}")

if __name__ == "__main__":
    main()