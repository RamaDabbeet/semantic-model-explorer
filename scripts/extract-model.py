#!/usr/bin/env python3
"""
Extract metadata from a Power BI PBIP project and generate model-bundle.json.

Usage:
    python scripts/extract-model.py path/to/your-pbip-project
    python scripts/extract-model.py path/to/your-pbip-project -o docs/model-bundle.json
    python scripts/extract-model.py path/to/your-pbip-project -n "My Model Name"

The script parses TMDL files (tables, columns, measures, DAX) and report files
(pages, visuals, field bindings) from a PBIP project folder. It outputs a single
model-bundle.json file that the Semantic Model Explorer app loads.

No dependencies beyond Python 3.8+.
"""
import sys
import os

# Add parent directory to path so we can import from generate.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generate import (
    find_pbip_project,
    parse_model,
    parse_reports,
    detect_domains,
)
import json
import argparse


def extract(project_path, model_name=None):
    """Extract model metadata from a PBIP project folder."""
    model_dir, report_dirs = find_pbip_project(project_path)

    if not model_dir:
        print(f"Error: No .SemanticModel folder found in {project_path}")
        print("Expected structure:")
        print("  your-project/")
        print("    YourModel.SemanticModel/")
        print("      definition/tables/*.tmdl")
        print("    YourReport.Report/")
        print("      definition/pages/...")
        sys.exit(1)

    print(f"Model: {model_dir}")
    tables = parse_model(model_dir)
    print(f"  Found {len(tables)} tables, {sum(len(t['measures']) for t in tables)} measures")

    # Clean up table data (remove partitions, keep only what the app needs)
    for t in tables:
        t.pop("partitions", None)
        for col in t.get("columns", []):
            col.pop("expression", None)

    print(f"Reports: {len(report_dirs)} found")
    reports = parse_reports(report_dirs)
    for r in reports:
        print(f"  {r['name']}: {len(r.get('pages', []))} pages")

    domains = detect_domains(reports)
    print(f"Domains: {', '.join(domains.keys())}")

    name = model_name
    if not name:
        # Derive from the .SemanticModel folder name
        for item in os.listdir(project_path):
            if item.endswith(".SemanticModel"):
                name = item.replace(".SemanticModel", "")
                break
    if not name:
        name = os.path.basename(os.path.abspath(project_path))

    return {
        "modelName": name,
        "tables": tables,
        "reports": reports,
        "domains": domains,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Extract Power BI model metadata into model-bundle.json"
    )
    parser.add_argument("project", help="Path to PBIP project folder")
    parser.add_argument(
        "-o",
        "--output",
        default="docs/model-bundle.json",
        help="Output file path (default: docs/model-bundle.json)",
    )
    parser.add_argument(
        "-n", "--name", default=None, help="Custom model name"
    )
    args = parser.parse_args()

    if not os.path.isdir(args.project):
        print(f"Error: {args.project} is not a directory")
        sys.exit(1)

    bundle = extract(args.project, args.name)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)

    size_kb = os.path.getsize(args.output) / 1024
    print(f"\nSaved: {args.output} ({size_kb:.1f} KB)")
    print(f"  {bundle['modelName']}")
    print(f"  {len(bundle['tables'])} tables")
    print(f"  {sum(len(t['measures']) for t in bundle['tables'])} measures")
    print(f"  {len(bundle['reports'])} reports")
    print(f"  {len(bundle['domains'])} domains")


if __name__ == "__main__":
    main()
