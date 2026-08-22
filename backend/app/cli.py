from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Support both `python -m app.cli` and direct `python backend/app/cli.py`.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analyzer import NavigatorAnalyzer
from app.services.reporter import write_reports


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Test Navigator MVP")
    parser.add_argument("--requirement", required=True, help="需求文档路径")
    parser.add_argument("--projects", nargs="+", required=True, help="相对于工作区的项目目录")
    parser.add_argument("--workspace", default=r"C:\Akua")
    parser.add_argument("--branch", default="integration")
    parser.add_argument("--output", default="reports")
    args = parser.parse_args()
    report = NavigatorAnalyzer(Path(args.workspace)).analyze(Path(args.requirement), args.projects, args.branch)
    outputs = write_reports(report, Path(args.output))
    print(f"报告 {report.report_id} 已生成")
    for kind, path in outputs.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
