#!/usr/bin/env python3
"""Backward-compatible CLI for Rocket analysis."""
import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, List

from evo.analysis.case_runner import run_case_analyzers, load_index
from evo.analysis.registry import resolve_analyzers, DEFAULT_CASE_ANALYZERS


def _get_log_dir() -> Path:
    """Get the most recent run directory."""
    logs_dir = Path("/data/workspace/lli21/logs")
    if not logs_dir.exists():
        raise FileNotFoundError(f"Logs directory not found: {logs_dir}")
    
    run_dirs = sorted([d for d in logs_dir.iterdir() if d.is_dir()])
    if not run_dirs:
        raise FileNotFoundError(f"No run directories found in {logs_dir}")
    
    return run_dirs[-1]


def is_case_dir(path: Path) -> bool:
    """Check if path is a testcase directory (has iteration-X subdirectories or images/)."""
    return (path / "images").exists() or (path / "iteration-1").exists()


def _contains_case_dirs(path: Path) -> bool:
    """Check if path contains any nested case directories."""
    if not path.exists():
        return False
    try:
        for d in path.rglob("iteration-1"):
            return True
    except (OSError, PermissionError):
        pass
    return False


def _clean_artifacts(target: Path, verbose: bool = False) -> int:
    """Remove analysis artifacts. Returns count of removed files."""
    removed_count = 0
    
    if is_case_dir(target):
        # Clean single case directory
        index_path = target / "analysis_index.json"
        if index_path.exists():
            index_path.unlink()
            if verbose:
                print(f"Removed {index_path}")
            removed_count += 1
        
        for pattern in ["analysis_*.json", "analysis_*.csv", "analysis_*.tex", "analysis_*.pdf", "analysis_*.log"]:
            for file in target.glob(pattern):
                file.unlink()
                if verbose:
                    print(f"Removed {file}")
                removed_count += 1
    else:
        # Clean directory recursively
        index_path = target / "analysis_index.json"
        if index_path.exists():
            index_path.unlink()
            if verbose:
                print(f"Removed {index_path}")
            removed_count += 1
        
        for pattern in ["analysis_*.json", "analysis_*.csv", "analysis_*.tex", "analysis_*.pdf", "analysis_*.log"]:
            for file in target.glob(f"**/{pattern}"):
                file.unlink()
                if verbose:
                    print(f"Removed {file}")
                removed_count += 1
    
    return removed_count


def _find_case_dirs(log_dir: Path) -> list[Path]:
    """Find all testcase directories in a log directory."""
    case_dirs = []
    if not log_dir.exists():
        # If directory doesn't exist, return empty list
        return []
    try:
        for d in log_dir.rglob("*"):
            if d.is_dir() and is_case_dir(d):
                case_dirs.append(d)
    except (OSError, PermissionError):
        # Handle permission errors or mount issues
        pass
    # Remove duplicates and sort
    return sorted(set(case_dirs))


def _run_case_analysis(log_dir: Path, verbose: bool = False, force: bool = False, max_workers: int = 6) -> None:
    """Analyze testcase directories under a log directory."""
    print(f"Analyzing testcase directories under: {log_dir}")
    
    # Find all testcase directories
    testcase_dirs = _find_case_dirs(log_dir)
    
    if not testcase_dirs:
        print("No testcase directories found.")
        return
    
    print(f"Found {len(testcase_dirs)} testcase directories")
    
    # Get analyzers
    analyzers = resolve_analyzers(DEFAULT_CASE_ANALYZERS)
    
    # Parallel analysis
    futures_map = {}
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for case_dir in testcase_dirs:
            future = executor.submit(run_case_analyzers, case_dir, analyzers, force=force)
            futures_map[future] = case_dir
        
        for future in as_completed(futures_map):
            case_dir = futures_map[future]
            try:
                future.result()
                case_name = case_dir.name
                print(f"✓ {case_name}")
            except Exception as e:
                case_name = case_dir.name if hasattr(case_dir, 'name') else str(case_dir)
                print(f"✗ {case_name}: {e}")


def _run_trend_analysis(log_dir: Path) -> None:
    """Generate trend reports at fitness level."""
    print(f"Generating trend plots from: {log_dir}")
    
    from evo.analysis.group_plot import main as plot_main
    # plot_main only takes argv parameter with just the path
    plot_main([str(log_dir)])


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entry point with backward compatibility."""
    if argv is None:
        argv = sys.argv[1:]
    
    # Backward compatibility: if first arg is not a known command, prepend "analyze"
    # Also handle the case where there are no args at all (default to analyze)
    if not argv or (argv and argv[0] not in ("analyze", "clean", "debug")):
        argv = ["analyze"] + argv
    
    # Parse arguments
    parser = argparse.ArgumentParser(description="Rocket analysis CLI")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze logs")
    analyze_parser.add_argument(
        "log_dir",
        nargs="?",
        default=None,
        help="Long-run directory or testcase directory. If omitted, use the newest run under logs/."
    )
    analyze_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    analyze_parser.add_argument("--force", action="store_true", help="Force re-analysis")
    analyze_parser.add_argument("--workers", type=int, default=6, help="Number of parallel workers")
    
    # Clean command
    clean_parser = subparsers.add_parser("clean", help="Clean analysis artifacts")
    clean_parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Target directory to clean"
    )
    clean_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    
    # Debug command
    debug_parser = subparsers.add_parser("debug", help="Debug case analysis")
    debug_parser.add_argument(
        "case_dir",
        help="Case directory to debug"
    )
    
    args = parser.parse_args(argv)
    
    # Handle commands
    if args.command == "analyze":
        log_dir = Path(args.log_dir) if args.log_dir else _get_log_dir()
        # Allow non-existent directories if they're explicitly passed (might be mounted differently in Docker)
        # but use exists() check only for auto-detected directories
        if args.log_dir and not log_dir.exists():
            # For explicitly passed paths, don't fail - they might be mounted elsewhere
            print(f"Warning: Directory may not exist (or not mounted): {log_dir}", file=sys.stderr)
        elif not log_dir.exists():
            print(f"Error: Directory not found: {log_dir}", file=sys.stderr)
            return 1
        
        # Default: always do trend analysis (group-level)
        _run_trend_analysis(log_dir)
        
        # If -v flag is set, also do case analysis
        if args.verbose:
            _run_case_analysis(log_dir, verbose=args.verbose, force=args.force, max_workers=args.workers)
        
        return 0
    
    elif args.command == "clean":
        target = Path(args.target) if args.target else _get_log_dir()
        if not target.exists():
            print(f"Error: Directory not found: {target}", file=sys.stderr)
            return 1
        
        removed = _clean_artifacts(target, verbose=args.verbose)
        print(f"Removed {removed} artifacts")
        return 0
    
    elif args.command == "debug":
        case_dir = Path(args.case_dir)
        if not case_dir.exists():
            print(f"Error: Directory not found: {case_dir}", file=sys.stderr)
            return 1
        
        # Check if has index
        index_path = case_dir / "analysis_index.json"
        if index_path.exists():
            index = load_index(case_dir)
            print(f"Analysis index found with {len(index.get('analyzers', {}))} entries")
            for name, entry in index.get("analyzers", {}).items():
                print(f"  {name}: {entry.get('status', 'unknown')}")
        else:
            print("No analysis index found")
        
        return 0
    
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
