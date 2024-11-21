"""This script is responsible for calculating branch coverage shown in GitLab from the json coverage report."""

import json


def calculate_branch_coverage(filepath: str) -> None:
    """
    Calculate branch coverage from the given coverage report and print it to terminal.

    Args:
        filepath (str): the path to the json coverage report.
    """
    with open(filepath) as f:
        data = json.load(f)

    total_branches = 0
    covered_branches = 0

    for file_info in data["files"].values():
        total_branches += file_info["summary"]["num_branches"]
        covered_branches += file_info["summary"]["covered_branches"]

    if total_branches == 0:
        print("No branches found in the coverage report.")
    else:
        branch_coverage = covered_branches / total_branches * 100
        print(f"Total branches: {total_branches}")
        print(f"Covered branches: {covered_branches}")
        print(f"Branch coverage: {branch_coverage:.2f}%")


calculate_branch_coverage("coverage_reports/coverage.json")
