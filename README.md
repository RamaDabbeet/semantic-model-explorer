# Semantic Model Explorer

A free, open-source tool that turns any Power BI semantic model into a searchable, interactive encyclopedia. Browse measures, trace DAX dependencies, check model health — all from a single HTML page hosted on GitHub Pages.

No server. No database. No cost. Just your model metadata in a browser.

**[Live Demo](https://ramadabbeet.github.io/semantic-model-explorer/)** — try it with Contoso Retail sample data

![Semantic Model Explorer](https://img.shields.io/badge/Power_BI-Semantic_Model_Explorer-2563EB?style=for-the-badge)

## Features

- **Domain overview** — stats, measures, fact tables, and dimensions per domain
- **Report glossary** — every measure, page, and table used on each report
- **Measure detail** — DAX with syntax highlighting, business descriptions, dependency chips
- **Measure lineage** — visual dependency tree showing sub-measures and column references
- **Table lineage** — which measures depend on a fact/dimension table and which columns they use
- **Model health check** — coverage analysis for measures, tables, and columns with domain filters and searchable table dropdowns
- **Global search** — find any measure, table, column, or report instantly (press `/`)
- **Dark/light theme** — toggle with one click
- **Hash routing** — shareable URLs for every view

## Quick Start

### Option 1: Use with your own PBIP project (recommended)

```bash
# 1. Fork this repo on GitHub

# 2. Clone your fork
git clone https://github.com/<your-username>/semantic-model-explorer.git
cd semantic-model-explorer

# 3. Extract your model metadata
python scripts/extract-model.py /path/to/your-pbip-project

# 4. Push
git add docs/model-bundle.json
git commit -m "Add my model data"
git push

# 5. Enable GitHub Pages
#    Settings > Pages > Source: main, Folder: /docs
```

Your explorer is live at `https://<your-username>.github.io/semantic-model-explorer/`

### Option 2: Manual JSON

If you don't have a PBIP project, create `docs/model-bundle.json` manually following the [JSON format](#json-format) below.

## How It Works

```
Your PBIP Project          extract-model.py          GitHub Pages
┌──────────────┐          ┌──────────────┐          ┌──────────────┐
│ *.tmdl files │──parse──>│ model-bundle │──push───>│  index.html  │
│ report pages │          │    .json     │          │  loads JSON  │
└──────────────┘          └──────────────┘          └──────────────┘
```

1. `scripts/extract-model.py` walks your PBIP folder
2. Parses `.tmdl` files for tables, columns, measures, and DAX expressions
3. Parses report files (PBIR `visual.json` or legacy `report.json`) for pages, visuals, and field bindings
4. Groups reports into domains by name prefix (e.g. "Sales - Pipeline" → "Sales")
5. Outputs `docs/model-bundle.json`
6. `docs/index.html` loads the JSON and renders everything client-side

## Extract Script Options

```bash
# Default output to docs/model-bundle.json
python scripts/extract-model.py /path/to/project

# Custom output path
python scripts/extract-model.py /path/to/project -o my-model.json

# Custom model name
python scripts/extract-model.py /path/to/project -n "My Analytics Model"
```

## Expected Project Structure

```
your-pbip-project/
  YourModel.SemanticModel/
    definition/
      tables/
        Fact Sales.tmdl
        Dim Customer.tmdl
        _Sales Measures.tmdl
        ...
  Report1.Report/
    definition/
      pages/
        page1/
          visuals/
            ...
  Report2.Report/
    ...
```

## JSON Format

The `model-bundle.json` file follows this structure:

```json
{
  "modelName": "Your Model Name",
  "tables": [
    {
      "name": "Fact Sales",
      "type": "fact",
      "columns": [
        { "name": "OrderID", "dataType": "Int64" },
        { "name": "Revenue", "dataType": "Decimal" }
      ],
      "measures": []
    },
    {
      "name": "_Sales Measures",
      "type": "measure",
      "columns": [],
      "measures": [
        {
          "name": "Total Revenue",
          "expression": "SUM('Fact Sales'[Revenue])",
          "description": "Sum of all sales revenue"
        }
      ]
    }
  ],
  "reports": [
    {
      "name": "Sales - Dashboard",
      "domain": "Sales",
      "pages": [
        {
          "name": "Overview",
          "visuals": 6,
          "measures": ["Total Revenue"],
          "tables": ["Fact Sales", "Dim Date"]
        }
      ]
    }
  ],
  "domains": {
    "Sales": ["Sales - Dashboard"]
  }
}
```

### Table types

The extract script classifies tables automatically:

| Prefix/Pattern | Type | Badge |
|---|---|---|
| `Fact ...` | `fact` | Cyan |
| `Dim ...` | `dimension` | Purple |
| `_ ...` or measures-only | `measure` | Green |
| Contains "parameter"/"selector" | `parameter` | Amber |
| Everything else | `other` | Grey |

## Hosting Alternatives

While GitHub Pages is the easiest option, the explorer works anywhere that serves static files:

- **Azure Static Web Apps** — free tier, supports Azure AD auth
- **SharePoint** — upload `index.html` + `model-bundle.json` to a document library
- **Local file** — open `docs/index.html` directly in your browser (requires a local server for the JSON fetch, e.g. `python -m http.server 8000 -d docs`)

## CI/CD Integration

To keep the explorer updated automatically when your model changes:

```yaml
# Azure DevOps pipeline example
steps:
  - checkout: self
  - checkout: YourModelRepo

  - script: |
      python scripts/extract-model.py $(Build.SourcesDirectory)/your-model-repo
    displayName: 'Generate model bundle'

  - task: AzureStaticWebApp@0
    inputs:
      app_location: 'docs'
      skip_app_build: true
```

## Requirements

- **Python 3.8+** (for the extract script only — no pip packages needed)
- A Power BI PBIP project with `.tmdl` files and report definitions

## License

MIT
