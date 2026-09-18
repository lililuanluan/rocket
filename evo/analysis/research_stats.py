#!/usr/bin/env python3
"""Research-question statistics for Rocket experiment logs.

The input layout is the normal Rocket layout::

    <run>/<image>/<encoding>/<fitness>/evo_result.csv

The command accepts the same benchmark more than once.  Each occurrence is
treated as a separate repeat, so future experiments do not require changes to
the analysis code.

Examples (run inside docker/debug.sh):

    python -m evo.analysis.research_stats all \
        --benchmark bug1=/path/to/repeat-1 \
        --benchmark bug1=/path/to/repeat-2 \
        --benchmark bug2=/path/to/repeat-1 \
        --output-root /data/workspace/lli21/EvotestPaper/data

The generated directory is organized as ``<date>/{rq1,rq2,rq3}``.  Each RQ
directory contains one self-contained table per benchmark. RQ1 writes one PDF
per benchmark; RQ2 and RQ3 write one PDF per fitness. Narrative analysis stays in the manuscript's
``evaluation.tex`` so it can be edited without regenerating the data files.

No scipy dependency is required.  RQ1 uses a one-covariate Cox model
implemented locally; rank tests elsewhere use the normal approximation with
tie correction.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import threading
from bisect import bisect_left, bisect_right
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Iterable


FITNESS_METRICS = (
    "mean_validation_time",
    "validation_distribution_entropy",
    "validation_distribution_entropy_max",
    "message_entropy_integral",
    "message_entropy_integral_max_seq",
    "num_getledger_hashes",
    "num_getledger_hashes_max_seq",
)

FITNESS_NAMES = {
    "mean_validation_time": "Validation time",
    "validation_distribution_entropy": "Validation entropy",
    "validation_distribution_entropy_max": "Maximum validation entropy",
    "message_entropy_integral": "Communication asynchrony",
    "message_entropy_integral_max_seq": "Maximum communication asynchrony",
    "num_getledger_hashes": "Information exchange",
    "num_getledger_hashes_max_seq": "Maximum information exchange",
    "no_fitness": "No objective",
}

BENCHMARK_DESCRIPTIONS = {
    "Bench-ripple-bf": "A customized Ripple 2.6.0 version injecting the bug found by ByzzFuzz.",
    "Bench-ripple-unl": "A rippled 3.1.0 deployment with insufficient UNL overlap.",
    "Bench-ripple-3.1.0": "A seven-node rippled 3.1.0 deployment with fully trusted UNLs and close-time-zero mutation enabled.",
    "Bench-ripple-3.1.0*": "A seven-node rippled 3.1.0 deployment with fully trusted UNLs and close-time-zero mutation disabled.",
}
BENCHMARK_ORDER = tuple(BENCHMARK_DESCRIPTIONS)

VIOLATION_SUMMARY_KEYS = (
    "timeout_before_startup",
    "errors",
    "failed_termination",
    "failed_agreement",
    "failed_final_agreement",
)

CASE_RE = re.compile(r"^G(?P<generation>\d+)T(?P<individual>\d+)$")

# Violation labels are resolved with one filesystem round-trip per row, which
# dominates the runtime when the logs sit on network storage.  The lookups are
# independent and almost entirely I/O wait, so a thread pool scales them far
# better than more CPU would.  The default is a latency-hiding width rather than
# a function of the core count; raise it with --workers on slow mounts.
DEFAULT_LABEL_WORKERS = 32


@dataclass(frozen=True)
class BenchmarkInput:
    name: str
    path: Path
    repeat: int


def _pd():
    import pandas as pd

    return pd


def _plot_deps():
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    return plt, PdfPages


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def _int_label(value) -> str | None:
    number = _number(value)
    if number is None:
        return None
    return str(int(number))


def _summary_label(summary: dict) -> bool | None:
    # Startup failures and empty retry summaries are runtime-invalid, not
    # protocol violations.  Do not let them inflate the violation group.
    for key in ("timeout_before_startup", "errors"):
        value = _number(summary.get(key))
        if value is not None and value != 0:
            return None

    for key in VIOLATION_SUMMARY_KEYS:
        value = _number(summary.get(key))
        if value is not None and value != 0:
            return True

    total = _number(summary.get("total_iterations"))
    correct = _number(summary.get("correct_runs"))
    if total is not None and correct is not None:
        if int(total) == 0 or (int(total) > 0 and int(correct) == 0):
            return None
        return int(total) != int(correct)
    return None


def _case_dir(csv_path: Path, generation, individual_id) -> Path | None:
    generation_label = _int_label(generation)
    individual_label = _int_label(individual_id)
    if generation_label is None or individual_label is None:
        return None

    direct = csv_path.parent / f"G{generation_label}T{individual_label}"
    if direct.is_dir():
        return direct

    # A runtime retry may archive the original case with a suffix.
    matches = sorted(csv_path.parent.glob(f"G{generation_label}T{individual_label}*"))
    return next((path for path in matches if path.is_dir()), None)


class _LabelCache:
    """Memo for resolved case labels, shared by the label worker threads.

    The lock only guards the dictionary itself, never the JSON read, so workers
    still overlap their I/O.  Two threads racing on the same missing key may
    both read the file, which is harmless: the value they compute is identical.
    """

    def __init__(self) -> None:
        self._entries: dict[Path, tuple[bool | None, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: Path) -> tuple[bool | None, str] | None:
        with self._lock:
            return self._entries.get(key)

    def put(self, key: Path, value: tuple[bool | None, str]) -> None:
        with self._lock:
            self._entries[key] = value


def _case_label(
    case_dir: Path | None,
    total_failures,
    cache: _LabelCache,
) -> tuple[bool | None, str]:
    if case_dir is not None:
        summary_path = case_dir / "aggregated_spec_check_log.json"
        if summary_path.is_file():
            cached = cache.get(summary_path)
            if cached is not None:
                return cached
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                result = (_summary_label(summary), "aggregated_spec_check_log")
            except (OSError, json.JSONDecodeError):
                result = (None, "invalid_summary")
            cache.put(summary_path, result)
            return result

    failures = _number(total_failures)
    if failures is not None:
        return failures != 0, "total_failures"
    return None, "missing_failure_metadata"


def _resolve_case_label(
    csv_path: Path,
    cache: _LabelCache,
    task: tuple[object, object, object],
) -> tuple[bool | None, str, str]:
    """Resolve one CSV row's violation label; runs on a worker thread."""

    generation, individual_id, total_failures = task
    case_dir = _case_dir(csv_path, generation, individual_id)
    label, source = _case_label(case_dir, total_failures, cache)
    return label, source, "" if case_dir is None else str(case_dir)


def _method_from_csv(csv_path: Path) -> str:
    # The runner names same-space random baselines as random-<encoding>.
    encoding_name = csv_path.parent.parent.name
    if encoding_name == "random" or encoding_name.startswith(("random-", "random_")):
        return "random"
    return "ea"


def _fitness_type(csv_path: Path, frame) -> str:
    if _method_from_csv(csv_path) == "random":
        return "no_fitness"
    if "fitness_type" in frame.columns:
        values = frame["fitness_type"].dropna().astype(str).unique()
        if len(values) == 1 and values[0].strip():
            return values[0].strip()
    return csv_path.parent.name


def parse_benchmarks(values: Iterable[str]) -> list[BenchmarkInput]:
    repeats: Counter[str] = Counter()
    result: list[BenchmarkInput] = []
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"Benchmark must have NAME=PATH form: {raw}")
        name, raw_path = raw.split("=", 1)
        name = name.strip()
        path = Path(raw_path).expanduser().resolve()
        if not name or not path.exists():
            raise ValueError(f"Invalid benchmark specification: {raw}")
        repeats[name] += 1
        result.append(BenchmarkInput(name=name, path=path, repeat=repeats[name]))
    return result


def collect_data(inputs: list[BenchmarkInput], max_workers: int | None = None):
    """Read all experiment rows and attach case-level violation labels.

    Label resolution costs one filesystem round-trip per row, so it dominates
    the runtime on network-backed log storage.  The lookups are independent and
    I/O bound, so they run on a thread pool; ``max_workers`` tunes its width.
    """

    pd = _pd()
    frames = []
    cache = _LabelCache()

    with ThreadPoolExecutor(max_workers=max_workers or DEFAULT_LABEL_WORKERS) as executor:
        for item in inputs:
            csv_paths = [item.path] if item.path.name == "evo_result.csv" else sorted(item.path.rglob("evo_result.csv"))
            if not csv_paths:
                raise FileNotFoundError(f"No evo_result.csv found under {item.path}")

            for csv_path in csv_paths:
                print(f"Loading {item.name} repeat {item.repeat}: {csv_path}", flush=True)
                try:
                    frame = pd.read_csv(csv_path)
                except Exception as exc:
                    print(f"Warning: skipping unreadable CSV {csv_path}: {exc}")
                    continue
                if frame.empty:
                    continue

                frame = frame.copy()
                frame["__benchmark"] = item.name
                frame["__repeat"] = item.repeat
                frame["__method"] = _method_from_csv(csv_path)
                frame["__fitness_type"] = _fitness_type(csv_path, frame)
                frame["__source_csv"] = str(csv_path)

                tasks = [
                    (
                        getattr(row, "generation", None),
                        getattr(row, "individual_id", None),
                        getattr(row, "total_failures", None),
                    )
                    for row in frame.itertuples(index=False)
                ]
                resolved = list(executor.map(partial(_resolve_case_label, csv_path, cache), tasks))

                frame["__violation"] = [label for label, _, _ in resolved]
                frame["__violation_source"] = [source for _, source, _ in resolved]
                frame["__case_dir"] = [case_dir for _, _, case_dir in resolved]

                generations = pd.to_numeric(frame.get("generation"), errors="coerce")
                individual_ids = pd.to_numeric(frame.get("individual_id"), errors="coerce")
                max_individual = individual_ids.max()
                if pd.isna(max_individual) or max_individual <= 0:
                    frame["__evaluation_index"] = generations
                else:
                    frame["__evaluation_index"] = generations * int(max_individual) + individual_ids
                frames.append(frame)
                print(f"  Resolved {len(frame)} rows", flush=True)

    if not frames:
        raise RuntimeError("No non-empty evo_result.csv could be read.")
    return pd.concat(frames, ignore_index=True)


def _numeric_series(frame, column):
    pd = _pd()
    if column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def mann_whitney_u(left, right) -> tuple[float | None, float | None]:
    """Return U and a tie-corrected normal-approximation two-sided p value."""

    left = [float(value) for value in left]
    right = [float(value) for value in right]
    n1, n2 = len(left), len(right)
    if n1 == 0 or n2 == 0:
        return None, None

    combined = sorted((value, 0) for value in left) + sorted((value, 1) for value in right)
    combined.sort(key=lambda pair: pair[0])
    rank_sum = 0.0
    tie_counts = []
    index = 0
    while index < len(combined):
        end = index + 1
        while end < len(combined) and combined[end][0] == combined[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        rank_sum += average_rank * sum(group == 0 for _, group in combined[index:end])
        tie_counts.append(end - index)
        index = end

    u1 = rank_sum - n1 * (n1 + 1) / 2.0
    if n1 < 2 or n2 < 2:
        return u1, None
    n = n1 + n2
    mean = n1 * n2 / 2.0
    tie_term = sum(count**3 - count for count in tie_counts)
    if n <= 1:
        return u1, None
    variance = n1 * n2 / 12.0 * (n + 1 - tie_term / (n * (n - 1)))
    if variance <= 0:
        return u1, 1.0
    correction = 0.5 if u1 > mean else -0.5 if u1 < mean else 0.0
    z = (u1 - mean - correction) / math.sqrt(variance)
    return u1, _normal_two_sided_p(z)


def cliffs_delta(left, right) -> float | None:
    """Return P(left > right) - P(left < right), efficiently handling ties."""

    left = sorted(float(value) for value in left)
    right = [float(value) for value in right]
    if not left or not right:
        return None
    wins = 0
    losses = 0
    for value in right:
        lower = bisect_left(left, value)
        upper = bisect_right(left, value)
        wins += len(left) - upper
        losses += lower
    return (wins - losses) / (len(left) * len(right))


def mann_kendall(values) -> tuple[float | None, float | None]:
    """Return Kendall tau and a tie-corrected Mann-Kendall p value."""

    values = [float(value) for value in values]
    n = len(values)
    if n < 3:
        return None, None

    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            s += (values[j] > values[i]) - (values[j] < values[i])

    ties = Counter(values)
    tie_term = sum(count * (count - 1) * (2 * count + 5) for count in ties.values())
    variance = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if variance <= 0:
        return 0.0, 1.0
    if s > 0:
        z = (s - 1) / math.sqrt(variance)
    elif s < 0:
        z = (s + 1) / math.sqrt(variance)
    else:
        z = 0.0
    tau = s / (n * (n - 1) / 2.0)
    return tau, _normal_two_sided_p(z)


def ols_slope(values) -> float | None:
    values = [float(value) for value in values]
    n = len(values)
    if n < 2:
        return None
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    denominator = sum((index - x_mean) ** 2 for index in range(n))
    if denominator == 0:
        return None
    return sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values)) / denominator


def _fmt(value, digits: int = 3) -> str:
    if value is None:
        return "NA"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "NA"
    if not math.isfinite(value):
        return "NA"
    return f"{value:.{digits}f}"


def _tex_escape(value) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "_": r"\_",
        "#": r"\#",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _fitness_name(value: str) -> str:
    return FITNESS_NAMES.get(value, value)


def _benchmark_filename(value: str) -> str:
    if value.endswith("*"):
        value = f"{value[:-1]}-star"
    return re.sub(r"[^A-Za-z0-9.-]+", "_", value)


def _ordered_benchmarks(frame) -> list[str]:
    present = set(frame["__benchmark"].dropna().astype(str))
    known = [benchmark for benchmark in BENCHMARK_ORDER if benchmark in present]
    extras = sorted(present.difference(BENCHMARK_ORDER))
    return known + extras


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _group_values(frame, column: str, *, benchmark: str | None = None, method: str | None = None):
    part = frame
    if benchmark is not None:
        part = part[part["__benchmark"] == benchmark]
    if method is not None:
        part = part[part["__method"] == method]
    return _numeric_series(part, column).to_numpy()


def _rq1_rows(frame):
    pd = _pd()
    valid = frame[frame["__violation"].notna()].copy()
    rows = []

    def add_campaign(part, benchmark, method, fitness_type, source_csv):
        found_rows = part[part["__violation"] == True]  # noqa: E712
        first_values = _numeric_series(found_rows, "__evaluation_index")
        follow_up_values = _numeric_series(part, "__evaluation_index")
        if follow_up_values.empty:
            return
        first = float(first_values.min()) if not first_values.empty else None
        follow_up = float(follow_up_values.max())
        rows.append(
            {
                "benchmark": benchmark,
                "method": method,
                "fitness_type": fitness_type,
                "source_csv": source_csv,
                "found": first is not None,
                "event": int(first is not None),
                "first_evaluation": first,
                "follow_up": follow_up,
                "duration": first if first is not None else follow_up,
            }
        )

    # Each EA CSV is one fitness campaign.  A random baseline can be emitted
    # into one fitness directory per configured objective, but those files are
    # one baseline campaign, not one repeat per objective.
    ea = valid[valid["__method"] == "ea"]
    for keys, part in ea.groupby(
        ["__benchmark", "__method", "__fitness_type", "__source_csv"], dropna=False
    ):
        benchmark, method, fitness_type, source_csv = keys
        add_campaign(part, benchmark, method, fitness_type, source_csv)

    random = valid[valid["__method"] == "random"]
    for keys, part in random.groupby(
        ["__benchmark", "__method", "__repeat"], dropna=False
    ):
        benchmark, method, repeat = keys
        source = "random baseline" if part["__source_csv"].nunique() > 1 else part["__source_csv"].iloc[0]
        add_campaign(part, benchmark, method, "no_fitness", f"{source} (repeat {repeat})")
    return pd.DataFrame(rows)


def _rq1_summary_rows(run_rows):
    pd = _pd()
    if run_rows.empty:
        return pd.DataFrame(), pd.DataFrame()

    summary = []
    for keys, part in run_rows.groupby(["benchmark", "method", "fitness_type"]):
        benchmark, method, fitness_type = keys
        first_values = part.loc[part["found"], "first_evaluation"].dropna().tolist()
        summary.append(
            {
                "benchmark": benchmark,
                "method": method,
                "fitness_type": fitness_type,
                "n": len(part),
                "events": int(part["event"].sum()),
                "censored": int((part["event"] == 0).sum()),
                "median_event_time": (float(pd.Series(first_values).median()) if first_values else None),
                "median_follow_up": float(pd.to_numeric(part["follow_up"]).median()),
            }
        )

    comparisons = []
    random_part = run_rows[run_rows["method"] == "random"]
    for (benchmark, fitness_type), part in run_rows[
        run_rows["method"] == "ea"
    ].groupby(["benchmark", "fitness_type"]):
        baseline = random_part[random_part["benchmark"] == benchmark]
        samples = [
            (float(row.duration), bool(row.event), 1)
            for row in part.itertuples(index=False)
        ] + [
            (float(row.duration), bool(row.event), 0)
            for row in baseline.itertuples(index=False)
        ]
        cox = _cox_binary(samples)
        comparisons.append(
            {
                "benchmark": benchmark,
                "fitness_type": fitness_type,
                "n_ea": len(part),
                "n_random": len(baseline),
                "events_ea": int(part["event"].sum()),
                "events_random": int(baseline["event"].sum()),
                "hazard_ratio": cox[0] if cox is not None else None,
                "ci_low": cox[1] if cox is not None else None,
                "ci_high": cox[2] if cox is not None else None,
                "cox_p": cox[3] if cox is not None else None,
            }
        )

    return pd.DataFrame(summary), pd.DataFrame(comparisons)


def _cox_binary(samples):
    """Fit a one-covariate Cox model using Breslow ties.

    The covariate is one for EA and zero for random.  A finite estimate is not
    available when one group has no observed events, which is reported as NA.
    """

    event_times = sorted({duration for duration, event, _ in samples if event})
    if not event_times:
        return None

    beta = 0.0
    for _ in range(100):
        score = 0.0
        information = 0.0
        for time in event_times:
            risk = [sample for sample in samples if sample[0] >= time]
            events = [sample for sample in risk if sample[0] == time and sample[1]]
            d = len(events)
            risk_ea = sum(sample[2] for sample in risk)
            risk_random = len(risk) - risk_ea
            weight_ea = risk_ea * math.exp(max(-700.0, min(700.0, beta)))
            denominator = risk_random + weight_ea
            if denominator <= 0:
                return None
            probability_ea = weight_ea / denominator
            score += sum(sample[2] for sample in events) - d * probability_ea
            information += d * probability_ea * (1.0 - probability_ea)
        if information <= 1e-12:
            return None
        step = score / information
        beta += step
        if abs(step) < 1e-9:
            break
        if abs(beta) > 50:
            return None

    information = 0.0
    for time in event_times:
        risk = [sample for sample in samples if sample[0] >= time]
        events = [sample for sample in risk if sample[0] == time and sample[1]]
        d = len(events)
        risk_ea = sum(sample[2] for sample in risk)
        risk_random = len(risk) - risk_ea
        weight_ea = risk_ea * math.exp(beta)
        denominator = risk_random + weight_ea
        probability_ea = weight_ea / denominator
        information += d * probability_ea * (1.0 - probability_ea)
    if information <= 1e-12:
        return None
    standard_error = math.sqrt(1.0 / information)
    z = beta / standard_error
    return (
        math.exp(beta),
        math.exp(beta - 1.96 * standard_error),
        math.exp(beta + 1.96 * standard_error),
        _normal_two_sided_p(z),
    )


def _benchmark_placeholder(benchmark: str) -> str:
    return r"\textit{TODO.}"


def _build_rq1_tex(summary, comparisons, benchmark: str) -> str:
    label_suffix = _benchmark_filename(benchmark)
    lines = [
        "% Generated by evo.analysis.research_stats; do not edit by hand.",
        r"\begin{table}[H]",
        r"\centering",
        r"\scriptsize",
        r"\resizebox{\columnwidth}{!}{%",
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Fitness & Cox $p$ \\",
        r"\midrule",
    ]
    for row in comparisons.itertuples(index=False):
        lines.append(
            f"{_tex_escape(_fitness_name(row.fitness_type))} & "
            f"{_fmt(row.cox_p)} \\\\"
        )
    if comparisons.empty:
        lines.append(f"\\multicolumn{{2}}{{c}}{{{_benchmark_placeholder(benchmark)}}} \\\\")
    lines += [
        r"\bottomrule",
        r"\end{tabular}}",
        f"\\caption{{Cox-regression $p$-values for \\texttt{{{_tex_escape(benchmark)}}}; $p<0.05$ indicates a significant difference in discovery time.}}",
        f"\\label{{tab:rq1-discovery-{label_suffix}}}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


def _write_rq1_pdf(frame, pdf_path: Path, benchmark: str) -> Path:
    """Plot cumulative violations by generation for one benchmark."""

    pd = _pd()
    plt, PdfPages = _plot_deps()
    from matplotlib.ticker import MaxNLocator
    part = frame[
        (frame["__benchmark"] == benchmark) & frame["__violation"].notna()
    ].copy()
    part["__generation_value"] = pd.to_numeric(part["generation"], errors="coerce")
    part = part.dropna(subset=["__generation_value"])

    fig, ax = plt.subplots(figsize=(9, 5.5), constrained_layout=True)
    colors = plt.get_cmap("tab10")
    curve_count = 0

    ea = part[part["__method"] == "ea"]
    for index, (fitness_type, group) in enumerate(
        ea.groupby("__fitness_type", sort=True)
    ):
        counts = (
            group.assign(__is_violation=group["__violation"].astype(bool))
            .groupby("__generation_value")["__is_violation"]
            .sum()
            .sort_index()
        )
        if counts.empty:
            continue
        ax.plot(
            counts.index,
            counts.cumsum(),
            linewidth=2,
            color=colors(index % 10),
            label=_fitness_name(fitness_type),
        )
        curve_count += 1

    random = part[part["__method"] == "random"]
    if not random.empty:
        # One random campaign may be copied into several objective folders.
        dedupe_columns = ["__repeat", "generation", "individual_id"]
        available = [column for column in dedupe_columns if column in random.columns]
        random = random.drop_duplicates(subset=available) if available else random
        counts = (
            random.assign(__is_violation=random["__violation"].astype(bool))
            .groupby("__generation_value")["__is_violation"]
            .sum()
            .sort_index()
        )
        if not counts.empty:
            ax.plot(
                counts.index,
                counts.cumsum(),
                linewidth=2,
                linestyle="--",
                color="#444444",
                label="Random baseline",
            )
            curve_count += 1

    if curve_count == 0:
        ax.text(0.5, 0.5, "No labeled generation data", ha="center", va="center")
    else:
        ax.legend(fontsize=8, loc="best")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlabel("Generation")
    ax.set_ylabel("Cumulative violations found")
    ax.set_title(f"RQ1: cumulative violation discovery - {benchmark}")
    ax.grid(linestyle=":", alpha=0.5)

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(pdf_path) as pdf:
        pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)
    return pdf_path


def run_rq1(frame, out_dir: Path, benchmarks: list[str] | None = None) -> list[Path]:
    run_rows = _rq1_rows(frame)
    summary, comparisons = _rq1_summary_rows(run_rows)
    benchmarks = benchmarks or _ordered_benchmarks(frame)
    rq_dir = out_dir / "rq1"
    generated: list[Path] = []
    for benchmark in benchmarks:
        part_summary = summary[summary["benchmark"] == benchmark] if not summary.empty else summary
        part_comparisons = (
            comparisons[comparisons["benchmark"] == benchmark]
            if not comparisons.empty
            else comparisons
        )
        slug = _benchmark_filename(benchmark)
        generated.append(
            _write_text(
                rq_dir / f"{slug}.tex",
                _build_rq1_tex(part_summary, part_comparisons, benchmark),
            )
        )
        benchmark_frame = frame[frame["__benchmark"] == benchmark]
        if not benchmark_frame.empty:
            generated.append(_write_rq1_pdf(frame, rq_dir / f"{slug}.pdf", benchmark))
    return generated


def _rq2_rows(frame, metrics: list[str]):
    pd = _pd()
    rows = []
    for benchmark in sorted(frame["__benchmark"].unique()):
        part = frame[(frame["__benchmark"] == benchmark) & frame["__violation"].notna()]
        local_rows = []
        for metric in metrics:
            no_violation = _numeric_series(part[part["__violation"] == False], metric).tolist()  # noqa: E712
            violation = _numeric_series(part[part["__violation"] == True], metric).tolist()  # noqa: E712
            u_value, p_value = mann_whitney_u(violation, no_violation)
            delta = cliffs_delta(violation, no_violation)
            row = {
                "benchmark": benchmark,
                "metric": metric,
                "n_no_violation": len(no_violation),
                "n_violation": len(violation),
                "median_no_violation": float(pd.Series(no_violation).median()) if no_violation else None,
                "median_violation": float(pd.Series(violation).median()) if violation else None,
                "u": u_value,
                "p": p_value,
                "cliffs_delta": delta,
            }
            local_rows.append(row)
        rows.extend(local_rows)
    return pd.DataFrame(rows)


def _build_rq2_tex(rows, benchmark: str) -> str:
    label_suffix = _benchmark_filename(benchmark)
    lines = [
        "% Generated by evo.analysis.research_stats; do not edit by hand.",
        r"\begin{table}[H]",
        r"\centering",
        r"\scriptsize",
        r"\resizebox{\columnwidth}{!}{%",
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Fitness & Mann--Whitney $p$ \\",
        r"\midrule",
    ]
    for row in rows.itertuples(index=False):
        lines.append(
            f"{_tex_escape(_fitness_name(row.metric))} & "
            f"{_fmt(row.p)} \\\\"
        )
    if rows.empty:
        lines.append(f"\\multicolumn{{2}}{{c}}{{{_benchmark_placeholder(benchmark)}}} \\\\")
    lines += [
        r"\bottomrule",
        r"\end{tabular}}",
        f"\\caption{{Mann--Whitney U $p$-values for fitness discrimination on \\texttt{{{_tex_escape(benchmark)}}}; $p<0.05$ indicates significant discrimination.}}",
        f"\\label{{tab:rq2-fitness-separation-{label_suffix}}}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


def _boxplot_page(frame, metric: str, benchmark: str):
    plt, _ = _plot_deps()
    part = frame[(frame["__benchmark"] == benchmark) & frame["__violation"].notna()]
    fig, ax = plt.subplots(figsize=(6, 4), constrained_layout=True)
    no_violation = _numeric_series(part[part["__violation"] == False], metric).tolist()  # noqa: E712
    violation = _numeric_series(part[part["__violation"] == True], metric).tolist()  # noqa: E712
    groups = []
    labels = []
    colors = []
    if no_violation:
        groups.append(no_violation)
        labels.append(f"No violation\nn={len(no_violation)}")
        colors.append("#4C8EDA")
    if violation:
        groups.append(violation)
        labels.append(f"Violation\nn={len(violation)}")
        colors.append("#D95F5F")
    ax.set_title(_fitness_name(metric), fontsize=10, fontweight="bold")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    if not groups:
        ax.text(0.5, 0.5, "No labeled numeric data", ha="center", va="center")
    else:
        box = ax.boxplot(groups, tick_labels=labels, patch_artist=True, widths=0.6)
        for patch, color in zip(box["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
    return fig


def run_rq2(
    frame,
    out_dir: Path,
    metrics: list[str],
    benchmarks: list[str] | None = None,
) -> list[Path]:
    _, PdfPages = _plot_deps()
    rows = _rq2_rows(frame, metrics)
    benchmarks = benchmarks or _ordered_benchmarks(frame)
    rq_dir = out_dir / "rq2"
    generated: list[Path] = []
    for benchmark in benchmarks:
        part_rows = rows[rows["benchmark"] == benchmark] if not rows.empty else rows
        slug = _benchmark_filename(benchmark)
        generated.append(_write_text(rq_dir / f"{slug}.tex", _build_rq2_tex(part_rows, benchmark)))
        benchmark_frame = frame[frame["__benchmark"] == benchmark]
        if not benchmark_frame.empty:
            for metric in metrics:
                pdf_path = rq_dir / f"{slug}--{metric}.pdf"
                with PdfPages(pdf_path) as pdf:
                    fig = _boxplot_page(frame, metric, benchmark)
                    pdf.savefig(fig, bbox_inches="tight")
                    _plot_deps()[0].close(fig)
                generated.append(pdf_path)
    return generated


def _fitness_stats_by_generation(frame, benchmark: str, method: str, fitness_type: str):
    pd = _pd()
    from evo.analysis.plot import build_metric_stats

    part = frame[
        (frame["__benchmark"] == benchmark)
        & (frame["__method"] == method)
    ].copy()
    if method == "ea":
        part = part[part["__fitness_type"] == fitness_type]
        value_column = fitness_type if fitness_type in part.columns else "fitness"
    else:
        # Random baseline is one no-objective campaign in the same encoding
        # space.  Its CSV still records every metric column, so compare each EA
        # fitness against the matching metric column from that single random
        # campaign instead of treating random as seven separate objectives.
        value_column = fitness_type if fitness_type in part.columns else "fitness"
    if value_column not in part.columns:
        return pd.DataFrame()
    part[value_column] = pd.to_numeric(part[value_column], errors="coerce")
    part["generation"] = pd.to_numeric(part.get("generation"), errors="coerce")
    part = part.dropna(subset=[value_column, "generation"])
    if part.empty:
        return pd.DataFrame()

    # Match plot.sh's _fitness_trend_report.pdf exactly: aggregate each
    # strategy/fitness data with build_metric_stats, then draw only mean/std.
    return build_metric_stats(part, [value_column])


def _rq3_fitnesses(frame, benchmark: str) -> list[str]:
    part = frame[
        (frame["__benchmark"] == benchmark)
        & (frame["__method"] == "ea")
    ]
    return sorted(part["__fitness_type"].dropna().astype(str).unique())


def _stats_metric_name(stats, fitness_type: str) -> str | None:
    roots = set(stats.columns.get_level_values(0))
    if fitness_type in roots:
        return fitness_type
    if "fitness" in roots:
        return "fitness"
    return None


def _stats_series(stats, metric_name: str, stat_name: str):
    pd = _pd()
    generations = stats["generation"]
    if isinstance(generations, pd.DataFrame):
        generations = generations.iloc[:, 0]
    values = pd.DataFrame(
        {
            "generation": pd.to_numeric(generations, errors="coerce"),
            "value": pd.to_numeric(stats[metric_name][stat_name], errors="coerce"),
        }
    ).dropna()
    return values.set_index("generation")["value"].sort_index()


def _rq3_rows(frame):
    pd = _pd()
    trend_rows = []
    comparison_rows = []

    for benchmark in sorted(frame["__benchmark"].dropna().astype(str).unique()):
        for fitness_type in _rq3_fitnesses(frame, benchmark):
            stats_by_method = {}
            for method in ("ea", "random"):
                stats = _fitness_stats_by_generation(
                    frame,
                    benchmark,
                    method,
                    fitness_type,
                )
                if stats.empty:
                    continue
                metric_name = _stats_metric_name(stats, fitness_type)
                if metric_name is None:
                    continue

                stats_by_method[method] = (stats, metric_name)
                mean_values = _stats_series(stats, metric_name, "mean")
                tau, p_value = mann_kendall(mean_values.tolist())
                if method == "ea":
                    trend_rows.append(
                        {
                            "benchmark": benchmark,
                            "method": method,
                            "fitness_type": fitness_type,
                            "generations": len(mean_values),
                            "tau": tau,
                            "p": p_value,
                            "slope": ols_slope(mean_values.tolist()),
                        }
                    )

            if "ea" not in stats_by_method or "random" not in stats_by_method:
                continue
            ea_stats, ea_metric = stats_by_method["ea"]
            random_stats, random_metric = stats_by_method["random"]
            ea_best = _stats_series(ea_stats, ea_metric, "max")
            random_best = _stats_series(random_stats, random_metric, "max")
            common = sorted(set(ea_best.index) & set(random_best.index))
            ea_values = [float(ea_best.loc[index]) for index in common]
            random_values = [float(random_best.loc[index]) for index in common]
            u_value, p_value = mann_whitney_u(ea_values, random_values)
            comparison_rows.append(
                {
                    "benchmark": benchmark,
                    "fitness_type": fitness_type,
                    "generations_compared": len(common),
                    "ea_median_best": pd.Series(ea_values).median() if ea_values else None,
                    "random_median_best": pd.Series(random_values).median() if random_values else None,
                    "u": u_value,
                    "p": p_value,
                    "cliffs_delta": cliffs_delta(ea_values, random_values),
                }
            )
    return pd.DataFrame(trend_rows), pd.DataFrame(comparison_rows)


def _build_rq3_tex(trends, comparisons, benchmark: str) -> str:
    if trends.empty and comparisons.empty:
        return "TODO.\n"

    label_suffix = _benchmark_filename(benchmark)
    lines = [
        "% Generated by evo.analysis.research_stats; do not edit by hand.",
        r"\begin{table}[H]",
        r"\centering",
        r"\scriptsize",
        r"\resizebox{\columnwidth}{!}{%",
        r"\begin{tabular}{lrl}",
        r"\toprule",
        r"Method & Fitness & Mann--Kendall $p$ \\",
        r"\midrule",
    ]
    for row in trends.itertuples(index=False):
        lines.append(
            f"{_tex_escape(row.method)} & "
            f"{_tex_escape(_fitness_name(row.fitness_type))} & "
            f"{_fmt(row.p)} \\\\"
        )
    if trends.empty:
        lines.append(f"\\multicolumn{{3}}{{c}}{{{_benchmark_placeholder(benchmark)}}} \\\\")
    lines += [
        r"\bottomrule",
        r"\end{tabular}}",
        f"\\caption{{Mann--Kendall $p$-values for \\texttt{{{_tex_escape(benchmark)}}}; $p<0.05$ indicates a significant monotonic trend.}}",
        f"\\label{{tab:rq3-trends-{label_suffix}}}",
        r"\end{table}",
        "",
        r"\begin{table}[H]",
        r"\centering",
        r"\scriptsize",
        r"\resizebox{\columnwidth}{!}{%",
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Fitness & Mann--Whitney $p$ \\",
        r"\midrule",
    ]
    for row in comparisons.itertuples(index=False):
        lines.append(
            f"{_tex_escape(_fitness_name(row.fitness_type))} & "
            f"{_fmt(row.p)} \\\\"
        )
    if comparisons.empty:
        lines.append(f"\\multicolumn{{2}}{{c}}{{{_benchmark_placeholder(benchmark)}}} \\\\")
    lines += [
        r"\bottomrule",
        r"\end{tabular}}",
        r"\caption{Mann--Whitney U $p$-values comparing EA and random generation-best fitness values; $p<0.05$ indicates a significant difference.}",
        f"\\label{{tab:rq3-ea-random-{label_suffix}}}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


def _write_rq3_pdf(frame, pdf_path: Path, benchmark: str, fitness_type: str) -> Path:
    plt, PdfPages = _plot_deps()
    from matplotlib.ticker import MaxNLocator

    with PdfPages(pdf_path) as pdf:
        fig, ax = plt.subplots(figsize=(6, 4), constrained_layout=True)
        for method, color, label in (
            ("ea", "#d95f02", "EA mean"),
            ("random", "#2c7fb8", "Random mean"),
        ):
            stats = _fitness_stats_by_generation(frame, benchmark, method, fitness_type)
            if stats.empty:
                continue
            metric_name = fitness_type if fitness_type in stats.columns.get_level_values(0) else "fitness"
            x = stats["generation"]
            mean = stats[metric_name]["mean"]
            std = stats[metric_name]["std"].fillna(0)
            ax.plot(
                x, mean, marker="o", markersize=4, linewidth=2, label=label, color=color,
            )
            ax.fill_between(x, mean - std, mean + std, alpha=0.18, color=color)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_title(_fitness_name(fitness_type), fontsize=12, fontweight="bold")
        ax.set_xlabel("Generation")
        ax.set_ylabel("Fitness")
        ax.grid(True, linestyle=":", alpha=0.7)
        ax.legend(fontsize=8)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)
    return pdf_path


def run_rq3(frame, out_dir: Path, benchmarks: list[str] | None = None) -> list[Path]:
    trends, comparisons = _rq3_rows(frame)
    benchmarks = benchmarks or _ordered_benchmarks(frame)
    rq_dir = out_dir / "rq3"
    generated: list[Path] = []
    for benchmark in benchmarks:
        part_trends = trends[trends["benchmark"] == benchmark] if not trends.empty else trends
        part_comparisons = comparisons[comparisons["benchmark"] == benchmark] if not comparisons.empty else comparisons
        slug = _benchmark_filename(benchmark)
        generated.append(
            _write_text(rq_dir / f"{slug}.tex", _build_rq3_tex(part_trends, part_comparisons, benchmark))
        )
        for fitness_type in _rq3_fitnesses(frame, benchmark):
            generated.append(_write_rq3_pdf(
                frame, rq_dir / f"{slug}--{fitness_type}.pdf", benchmark, fitness_type
            ))
    return generated


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate parameterized RQ statistics and PDF/TeX artifacts.")
    parser.add_argument("command", choices=("rq1", "rq2", "rq3", "all"))
    parser.add_argument(
        "--benchmark",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="Benchmark run root; repeat this option for repeats and benchmarks.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/data/workspace/lli21/EvotestPaper/data"),
        help="Root of the paper data directory.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Output directory label (default: UTC YY-MM-DD).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Use this exact output directory instead of output-root/date.",
    )
    parser.add_argument(
        "--metric",
        action="append",
        dest="metrics",
        choices=FITNESS_METRICS,
        help="RQ2 metrics to include; repeat option. Defaults to all current fitness metrics.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=(
            "Threads used to resolve per-row violation labels "
            f"(default: {DEFAULT_LABEL_WORKERS}). Raise it on high-latency storage."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be at least 1")
    try:
        inputs = parse_benchmarks(args.benchmark)
        frame = collect_data(inputs, max_workers=args.workers)
        out_dir = args.out_dir.expanduser().resolve() if args.out_dir else args.output_root.expanduser().resolve() / (
            args.date or datetime.now(timezone.utc).strftime("%y-%m-%d")
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        generated: list[Path] = []
        metrics = args.metrics or list(FITNESS_METRICS)
        benchmarks = _ordered_benchmarks(frame)

        if args.command in ("rq1", "all"):
            generated.extend(run_rq1(frame, out_dir, benchmarks))
        if args.command in ("rq2", "all"):
            available = [metric for metric in metrics if metric in frame.columns]
            if not available:
                raise RuntimeError("None of the requested RQ2 metrics are present in the input.")
            generated.extend(run_rq2(frame, out_dir, available, benchmarks))
        if args.command in ("rq3", "all"):
            generated.extend(run_rq3(frame, out_dir, benchmarks))

        print(f"Loaded {len(frame)} rows from {frame['__source_csv'].nunique()} evo_result.csv files.")
        print(
            "Labeled rows: "
            f"violation={(frame['__violation'] == True).sum()}, "  # noqa: E712
            f"no_violation={(frame['__violation'] == False).sum()}, "  # noqa: E712
            f"unknown={frame['__violation'].isna().sum()}"
        )
        for path in generated:
            print(path)
        return 0
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
