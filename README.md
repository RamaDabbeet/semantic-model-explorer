# Semantic Model Explorer

Generate a self-contained HTML explorer from any Power BI PBIP project. Browse measures, tables, columns, and trace DAX dependencies — all in a single file you can open in your browser.

No build step. No dependencies. Just Python 3.8+.

## Quick Start

```bash
python generate.py /path/to/your-pbip-project
```

This creates `explorer.html` — open it in your browser.

## What It Parses

- **TMDL files** — tables, columns, measures, DAX expressions
- **Report files** — pages, visuals, field bindings (both PBIR and legacy report.json formats)
- **Domains** — auto-detected from report name prefixes (e.g. "Sales - Pipeline" → "Sales" domain)

## What You Get

A single HTML file with:

- **Home page** — model stats, domain cards
- **Sidebar** — domain → report → measure tree with filter search
- **Report view** — glossary of measures, pages, and tables used
- **Measure view** — DAX expression with syntax highlighting
- **Table view** — columns, measures, and report usage
- **Lineage view** — measure dependency tree (sub-measures and columns)
- **Global search** — find any measure, table, column, or report (press `/`)
- **Dark/light theme** toggle

## Options

```bash
python generate.py /path/to/project -o my-model.html    # custom output filename
python generate.py /path/to/project -n "My Model Name"  # custom model name
```

## Project Structure Expected

```
your-project/
├── YourModel.SemanticModel/
│   └── definition/
│       └── tables/
│           ├── Sales.tmdl
│           ├── Products.tmdl
│           └── ...
├── Report1.Report/
│   └── definition/
│       └── pages/
│           └── ...
└── Report2.Report/
    └── ...
```

## Screenshots

Open `explorer.html` in your browser to see:

- Measure encyclopedia with DAX syntax highlighting
- Interactive lineage tree showing measure dependencies
- Searchable sidebar with domain/report/measure hierarchy
- Light and dark themes

## License

MIT
