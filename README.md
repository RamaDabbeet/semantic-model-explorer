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

## How to Connect Your Model

The explorer reads model metadata from `.tmdl` files (the PBIP format). Here's how to get there depending on where your model lives:

### Path A: You already use PBIP format

If you save your Power BI projects as `.pbip` files, you're ready. Your project folder already contains the `.tmdl` files and report definitions the extract script needs. Skip straight to [Quick Start](#quick-start).

### Path B: You have a .pbix file

Convert it to PBIP format in Power BI Desktop:

1. Open your `.pbix` file in Power BI Desktop
2. Go to **File > Save As**
3. Change the file type to **Power BI Project (.pbip)**
4. Save to a folder

This creates a project folder with `.SemanticModel/` and `.Report/` subfolders containing the `.tmdl` files. Then run the extract script against that folder.

### Path C: Your model is published in Microsoft Fabric

If your semantic model lives in a Fabric workspace, use **Git integration** to export it:

1. In the Fabric portal, go to your **workspace settings**
2. Under **Git integration**, connect to a Git repo (Azure DevOps or GitHub)
3. Select the semantic model and reports you want to sync
4. Click **Commit** — Fabric exports your model as PBIP files into the repo

Once synced, your Git repo contains the same `.tmdl` + report structure. Clone it locally and run the extract script.

> **Bonus:** With Fabric Git integration, you can set up a CI/CD pipeline that automatically rebuilds the explorer whenever your model changes. See [CI/CD Integration](#cicd-integration).

### Path D: You have a published model but no Fabric Git integration

Use one of these tools to export your model metadata:

- **Tabular Editor** — connect to your model via XMLA endpoint, then **File > Save to Folder** to export as TMDL
- **Power BI Desktop** — connect to the published model with a live connection, then save as `.pbip`
- **Manual JSON** — create `docs/model-bundle.json` by hand following the [JSON format](#json-format) below

### Which path should I use?

| Scenario | Path | Effort |
|---|---|---|
| Already saving as .pbip | A | Just run the script |
| Have a .pbix file | B | Save As PBIP, then run the script |
| Model in Fabric workspace | C | Connect Git integration, then run the script |
| Published model, no Git | D | Export via Tabular Editor or create JSON manually |

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
