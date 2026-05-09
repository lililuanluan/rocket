from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .cases import resolve_live_logs_dir
from .group_plot import evolution_report, fitness_trend_report
from .levels import Level
from .utils import analysis_dir, cleanup_files, repo_root, run_command_capture, tex_to_pdf


@dataclass(frozen=True)
class Analyzer:
    name: str
    level: Level
    description: str
    run: Callable[[Path], list[Path]]


def _saved_run_timeline(case_dir: Path) -> list[Path]:
    output_dir = analysis_dir(case_dir)
    json_path = output_dir / "saved_run_timeline.json"
    md_path = output_dir / "saved_run_timeline.md"
    run_command_capture(
        [
            sys.executable,
            "-m",
            "evo.analyze_saved_run_timeline",
            str(case_dir),
            "--json-out",
            str(json_path),
            "--md-out",
            str(md_path),
        ],
        cwd=repo_root(),
    )
    return [json_path, md_path]


def _close_time_causality(case_dir: Path) -> list[Path]:
    output_dir = analysis_dir(case_dir)
    out_path = output_dir / "close_time_causality.txt"
    run_command_capture(
        [
            sys.executable,
            str(repo_root() / "evo" / "analyze_close_time_causality.py"),
            str(case_dir),
        ],
        cwd=repo_root(),
        stdout_path=out_path,
    )
    return [out_path]


def _onaccept_table(case_dir: Path) -> list[Path]:
    output_dir = analysis_dir(case_dir)
    out_path = output_dir / "onaccept_table.tex"
    run_command_capture(
        [
            sys.executable,
            "-m",
            "evo.onaccept_table",
            str(resolve_live_logs_dir(case_dir)),
        ],
        cwd=repo_root(),
        stdout_path=out_path,
    )
    return [out_path]


def _preferred_trie(case_dir: Path) -> list[Path]:
    output_dir = analysis_dir(case_dir)
    json_path = output_dir / "preferred_trie.json"
    tex_path = output_dir / "preferred_trie.tex"
    run_command_capture(
        [
            sys.executable,
            "-m",
            "evo.preferred",
            str(case_dir),
            "--out",
            str(json_path),
            "--tex-out",
            str(tex_path),
        ],
        cwd=repo_root(),
    )
    try:
        pdf_path = tex_to_pdf(tex_path)
        return [json_path, pdf_path]
    except Exception as exc:
        print(f"[WARNING] Failed to convert preferred_trie TEX to PDF: {exc}", file=sys.stderr)
        return [json_path, tex_path]


def _validation_matrix(case_dir: Path) -> list[Path]:
    output_dir = analysis_dir(case_dir)
    json_path = output_dir / "validation_matrix.json"
    csv_path = output_dir / "validation_matrix.csv"
    pdf_path = output_dir / "validation_matrix.pdf"
    build_tex_path = output_dir / ".validation_matrix_build.tex"
    build_sidecars = [
        build_tex_path,
        build_tex_path.with_suffix(".aux"),
        build_tex_path.with_suffix(".log"),
        build_tex_path.with_suffix(".out"),
        build_tex_path.with_suffix(".fls"),
        build_tex_path.with_suffix(".fdb_latexmk"),
        output_dir / ".validation_matrix_build.pdf",
    ]

    try:
        run_command_capture(
            [
                sys.executable,
                "-m",
                "evo.validation",
                str(case_dir),
                "--json-out",
                str(json_path),
                "--csv-out",
                str(csv_path),
                "--pdf-out",
                str(pdf_path),
                "--standalone-tex-out",
                str(build_tex_path),
            ],
            cwd=repo_root(),
        )
    finally:
        cleanup_files(build_sidecars)

    return [json_path, csv_path, pdf_path]


def _proposal_timeline(case_dir: Path) -> list[Path]:
    output_dir = analysis_dir(case_dir)
    pdf_path = output_dir / "proposal_timeline.pdf"
    csv_path = output_dir / "proposal_events.csv"
    run_command_capture(
        [
            sys.executable,
            "-m",
            "evo.proposal",
            str(case_dir),
            "--plot-out",
            str(pdf_path),
            "--csv-out",
            str(csv_path),
            "--no-annotations",
        ],
        cwd=repo_root(),
    )
    return [pdf_path, csv_path]


ANALYZERS: dict[str, Analyzer] = {
    "fitness_trend_report": Analyzer(
        name="fitness_trend_report",
        level=Level.ENCODING,
        description="在 encoding 层级生成 _fitness_trend_report.pdf。",
        run=fitness_trend_report,
    ),
    "evolution_report": Analyzer(
        name="evolution_report",
        level=Level.FITNESS,
        description="在 fitness 层级生成 _evolution_report.pdf。",
        run=evolution_report,
    ),
    "saved_run_timeline": Analyzer(
        name="saved_run_timeline",
        level=Level.CASE,
        description="跨 action/result/log 的总时间线。",
        run=_saved_run_timeline,
    ),
    "close_time_causality": Analyzer(
        name="close_time_causality",
        level=Level.CASE,
        description="分析 close time 分叉因果。",
        run=_close_time_causality,
    ),
    "onaccept_table": Analyzer(
        name="onaccept_table",
        level=Level.CASE,
        description="生成 onAccept 时长表。",
        run=_onaccept_table,
    ),
    "preferred_trie": Analyzer(
        name="preferred_trie",
        level=Level.CASE,
        description="提取 ValidationTrie 快照并生成表格。",
        run=_preferred_trie,
    ),
    "validation_matrix": Analyzer(
        name="validation_matrix",
        level=Level.CASE,
        description="生成 validation 接收矩阵。",
        run=_validation_matrix,
    ),
    "proposal_timeline": Analyzer(
        name="proposal_timeline",
        level=Level.CASE,
        description="生成 proposal 时间线图。",
        run=_proposal_timeline,
    ),
}


DEFAULT_GROUP_ANALYZERS = ["fitness_trend_report", "evolution_report"]
DEFAULT_CASE_ANALYZERS = [
    "saved_run_timeline",
    "close_time_causality",
    "onaccept_table",
    "preferred_trie",
    "validation_matrix",
    "proposal_timeline",
]


def get_analyzer(name: str) -> Analyzer:
    if name not in ANALYZERS:
        raise KeyError(f"Unknown analyzer: {name}")
    return ANALYZERS[name]


def list_analyzers() -> list[Analyzer]:
    return [ANALYZERS[name] for name in sorted(ANALYZERS.keys())]


def resolve_analyzers(names: list[str] | None) -> list[Analyzer]:
    if not names:
        return []
    return [get_analyzer(name) for name in names]
