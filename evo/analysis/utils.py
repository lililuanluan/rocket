from __future__ import annotations

import subprocess
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def analysis_dir(case_dir: Path) -> Path:
    out = case_dir.expanduser().resolve() / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    return out


def cleanup_files(paths: list[Path]) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass


def run_command_capture(
    cmd: list[str],
    *,
    cwd: Path,
    stdout_path: Path | None = None,
) -> None:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if stdout_path is not None:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0:
        tail = "\n".join(result.stdout.splitlines()[-80:])
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n{tail}"
        )


def tex_to_pdf(tex_path: Path) -> Path:
    pdf_path = tex_path.with_suffix(".pdf")
    tex_content = tex_path.read_text(encoding="utf-8")

    if "\\documentclass" not in tex_content:
        wrapped_content = r"""\documentclass[12pt]{article}
\usepackage[utf-8]{inputenc}
\usepackage[margin=1in]{geometry}
\usepackage{array}
\usepackage{tabularx}
\usepackage{booktabs}
\usepackage{diagbox}
\usepackage{multirow}
\usepackage{multicol}
\begin{document}
""" + tex_content + r"""
\end{document}
"""
        wrapped_tex_path = tex_path.with_stem(tex_path.stem + "_wrapped")
        wrapped_tex_path.write_text(wrapped_content, encoding="utf-8")
        tex_to_compile = wrapped_tex_path
    else:
        wrapped_tex_path = None
        tex_to_compile = tex_path

    result = subprocess.run(
        [
            "pdflatex",
            "-interaction=nonstopmode",
            "-output-directory",
            str(tex_to_compile.parent),
            str(tex_to_compile),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        error_msg = result.stdout or result.stderr or "Unknown error"
        error_lines = error_msg.splitlines()
        last_error = next(
            (line for line in reversed(error_lines) if line.strip().startswith("!")),
            error_lines[-1] if error_lines else "Unknown error",
        )
        cleanup_files(
            [
                path
                for path in [
                    wrapped_tex_path,
                    None if wrapped_tex_path is None else wrapped_tex_path.with_suffix(".aux"),
                    None if wrapped_tex_path is None else wrapped_tex_path.with_suffix(".log"),
                    None if wrapped_tex_path is None else wrapped_tex_path.with_suffix(".out"),
                ]
                if path is not None
            ]
        )
        raise RuntimeError(f"pdflatex failed: {last_error}")

    cleanup_files(
        [
            tex_to_compile.with_suffix(".aux"),
            tex_to_compile.with_suffix(".log"),
            tex_to_compile.with_suffix(".out"),
            tex_to_compile.with_suffix(".fls"),
            tex_to_compile.with_suffix(".fdb_latexmk"),
        ]
    )
    if wrapped_tex_path is not None:
        cleanup_files([wrapped_tex_path])
    if pdf_path.exists() and tex_path.exists():
        cleanup_files([tex_path])
    return pdf_path
