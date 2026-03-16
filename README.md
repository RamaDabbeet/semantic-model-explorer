# Semantic Model Explorer

Generate a self-contained HTML explorer from any Power BI PBIP project. Browse measures, tables, columns, and trace DAX dependencies — all in a single file you can open in your browser.

No build step. No dependencies. Just Python 3.8+.

**[Live Demo](https://ramadabbeet.github.io/semantic-model-explorer/)** — try it with sample Contoso Retail data

## Quick Start

```bash
python generate.py /path/to/your-pbip-project
```

This creates `explorer.html` — open it in your browser.

## What It Parses

- **TMDL files** — tables, columns, measures, DAX expressions
- **Report files** — pages, visuals, field bindings (both PBIR and legacy report.json formats)
- **Domains** — auto-detected from report name prefixes (e.g. "Sales - Pipeline" -> "Sales" domain)

## What You Get

A single HTML file with:

- **Home page** — model stats, domain cards
- **Sidebar** — domain -> report -> measure tree with filter search
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
  YourModel.SemanticModel/
    definition/
      tables/
        Sales.tmdl
        Products.tmdl
        ...
  Report1.Report/
    definition/
      pages/
        ...
  Report2.Report/
    ...
```

## How It Works

1. Walks your PBIP project folder
2. Parses `.tmdl` files to extract tables, columns, measures, and DAX expressions
3. Parses report files (PBIR `visual.json` or legacy `report.json`) for pages, visuals, and field bindings
4. Classifies tables (fact, dimension, measure, parameter) by naming conventions
5. Groups reports into domains by name prefix
6. Generates a single self-contained HTML file with all CSS, JS, and data inline

## License

MIT
