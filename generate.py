#!/usr/bin/env python3
"""
Semantic Model Explorer — Generate a self-contained HTML explorer from a Power BI PBIP project.

Usage:
    python generate.py /path/to/your-pbip-project
    python generate.py /path/to/your-pbip-project -o explorer.html

The script walks the PBIP folder, parses TMDL files (tables, measures, columns, DAX),
parses report.json files (pages, visuals, field bindings), and generates a single HTML
file you can open directly in a browser. No build step, no dependencies beyond Python 3.8+.
"""
import json, sys, os, re, glob, argparse
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ---------------------------------------------------------------------------
# TMDL Parser
# ---------------------------------------------------------------------------

def get_indent(line):
    tabs = len(line) - len(line.lstrip('\t'))
    if tabs > 0:
        return tabs
    spaces = len(line) - len(line.lstrip(' '))
    return spaces // 4 if spaces else 0

def unquote(name):
    if name and name.startswith("'") and name.endswith("'"):
        return name[1:-1]
    return name or ''

def extract_dax(lines, start):
    trimmed = lines[start].strip()
    eq = trimmed.find('=')
    if eq == -1:
        return ''
    first = trimmed[eq+1:].strip()
    base = get_indent(lines[start])
    parts = [first]
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        lt = ln.strip()
        if not lt:
            i += 1
            continue
        indent = get_indent(ln)
        if indent <= base:
            break
        if re.match(r'^\w+\s*:', lt):
            break
        parts.append(lt)
        i += 1
    return '\n'.join(parts).strip()

def parse_table_file(content, path=''):
    lines = content.replace('\r\n', '\n').split('\n')
    result = {'name': '', 'columns': [], 'measures': [], 'partitions': []}

    # Find table name
    for line in lines:
        m = re.match(r'^table\s+(.+)$', line.strip())
        if m:
            result['name'] = unquote(m.group(1).strip())
            break
    if not result['name'] and path:
        result['name'] = os.path.splitext(os.path.basename(path))[0]

    i = 0
    while i < len(lines):
        line = lines[i]
        trimmed = line.strip()
        indent = get_indent(line)

        if indent >= 1 or (indent == 0 and not trimmed.startswith('table ')):
            # Column
            col_m = re.match(r'^column\s+(.+)$', trimmed)
            if col_m:
                col = {'name': unquote(col_m.group(1).strip()), 'dataType': '', 'expression': None}
                base_indent = indent
                j = i + 1
                while j < len(lines):
                    cl = lines[j]
                    ct = cl.strip()
                    if not ct:
                        j += 1
                        continue
                    if get_indent(cl) <= base_indent:
                        break
                    pm = re.match(r'^(\w+)\s*[:=]\s*(.+)$', ct)
                    if pm:
                        key = pm.group(1).lower()
                        val = pm.group(2).strip()
                        if key == 'datatype':
                            col['dataType'] = val
                        elif key == 'expression':
                            col['expression'] = val
                    j += 1
                if col['expression']:
                    pass  # calculated column, skip for now
                else:
                    result['columns'].append(col)
                i += 1
                continue

            # Measure
            meas_m = re.match(r'^measure\s+(.+?)\s*=\s*(.*)$', trimmed)
            if meas_m:
                mname = unquote(meas_m.group(1).strip())
                dax = extract_dax(lines, i) or meas_m.group(2).strip()
                result['measures'].append({'name': mname, 'expression': dax})
                i += 1
                continue

            # Partition
            part_m = re.match(r'^partition\s+(.+)$', trimmed)
            if part_m:
                praw = part_m.group(1).strip()
                peq = re.match(r'^(.+?)\s*=\s*(.*)$', praw)
                pname = unquote((peq.group(1) if peq else praw).strip())
                ptype = peq.group(2).strip().lower() if peq else ''
                result['partitions'].append({'name': pname, 'type': ptype})
                i += 1
                continue

        i += 1

    return result

def classify_table(table):
    name = table['name'].lower()
    if name.startswith('dim ') or name.startswith('dim_'):
        return 'dimension'
    if name.startswith('fact ') or name.startswith('fact_'):
        return 'fact'
    if name.startswith('_') or (len(table['measures']) > 0 and len(table['columns']) <= 1):
        return 'measure'
    if 'parameter' in name or 'selector' in name or 'toggle' in name:
        return 'parameter'
    if len(table['measures']) > 0 and len(table['columns']) == 0:
        return 'measure'
    return 'other'

# ---------------------------------------------------------------------------
# Report Parser (report.json / PBIR)
# ---------------------------------------------------------------------------

def parse_report_json(content):
    """Parse a report.json (legacy format) to extract pages and visual field bindings."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []

    config = data.get('config')
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            config = {}
    elif not config:
        config = {}

    pages = []
    sections = data.get('sections', [])
    for section in sections:
        page_name = section.get('displayName', section.get('name', 'Unnamed'))
        containers = section.get('visualContainers', [])
        page_measures = set()
        page_tables = set()
        visual_types = {}

        for vc in containers:
            vc_config = vc.get('config', '{}')
            if isinstance(vc_config, str):
                try:
                    vc_config = json.loads(vc_config)
                except json.JSONDecodeError:
                    vc_config = {}

            sv = vc_config.get('singleVisual', {})
            vtype = sv.get('visualType', 'unknown')
            visual_types[vtype] = visual_types.get(vtype, 0) + 1

            # Extract field bindings from projections
            projections = sv.get('projections', {})
            for role, fields in projections.items():
                if not isinstance(fields, list):
                    continue
                for field in fields:
                    qr = field.get('queryRef', '')
                    if '.' in qr:
                        parts = qr.rsplit('.', 1)
                        table_name = parts[0]
                        field_name = parts[1]
                        page_tables.add(table_name)

            # Extract from prototypeQuery
            query = sv.get('prototypeQuery', {})
            from_map = {}
            for f in query.get('From', []):
                if 'Name' in f and 'Entity' in f:
                    from_map[f['Name']] = f['Entity']
            for sel in query.get('Select', []):
                for ref_type in ['Measure', 'Column', 'Aggregation']:
                    ref = sel.get(ref_type, {})
                    if ref_type == 'Aggregation':
                        ref = ref.get('Expression', {}).get('Column', {})
                    source = ref.get('Expression', {}).get('SourceRef', {})
                    entity = source.get('Entity') or from_map.get(source.get('Source', ''), '')
                    prop = ref.get('Property', '')
                    if entity:
                        page_tables.add(entity)
                    if ref_type == 'Measure' and prop:
                        page_measures.add(prop)
                    elif sel.get('Measure') and sel['Measure'].get('Property'):
                        page_measures.add(sel['Measure']['Property'])

        pages.append({
            'name': page_name,
            'visuals': len(containers),
            'visualTypes': visual_types,
            'measures': sorted(page_measures),
            'tables': sorted(page_tables)
        })

    return pages

def parse_pbir_report(report_dir):
    """Parse PBIR format report (pages/*/visuals/*/visual.json)."""
    pages = []
    pages_dir = os.path.join(report_dir, 'pages')
    if not os.path.isdir(pages_dir):
        return pages

    for page_folder in sorted(os.listdir(pages_dir)):
        page_path = os.path.join(pages_dir, page_folder)
        if not os.path.isdir(page_path):
            continue

        # Read page.json for display name
        page_json = os.path.join(page_path, 'page.json')
        page_name = page_folder
        if os.path.isfile(page_json):
            try:
                with open(page_json, 'r', encoding='utf-8') as f:
                    pj = json.load(f)
                page_name = pj.get('displayName', pj.get('name', page_folder))
            except (json.JSONDecodeError, IOError):
                pass

        # Parse visuals
        visuals_dir = os.path.join(page_path, 'visuals')
        page_measures = set()
        page_tables = set()
        visual_types = {}
        visual_count = 0

        if os.path.isdir(visuals_dir):
            for vis_folder in os.listdir(visuals_dir):
                vis_json = os.path.join(visuals_dir, vis_folder, 'visual.json')
                if not os.path.isfile(vis_json):
                    continue
                visual_count += 1
                try:
                    with open(vis_json, 'r', encoding='utf-8') as f:
                        vis = json.load(f)
                    visual = vis.get('visual', vis)
                    vtype = visual.get('visualType', 'unknown')
                    visual_types[vtype] = visual_types.get(vtype, 0) + 1

                    # Extract from queryState
                    query_state = visual.get('query', {}).get('queryState', {})
                    for role, role_state in query_state.items():
                        if not isinstance(role_state, dict):
                            continue
                        for proj in role_state.get('projections', []):
                            field = proj.get('field', {})
                            for ftype in ['Measure', 'Column']:
                                ref = field.get(ftype, {})
                                entity = ref.get('Expression', {}).get('SourceRef', {}).get('Entity', '')
                                prop = ref.get('Property', '')
                                if entity:
                                    page_tables.add(entity)
                                if ftype == 'Measure' and prop:
                                    page_measures.add(prop)
                            # Aggregation wrapper
                            agg = field.get('Aggregation', {})
                            col = agg.get('Expression', {}).get('Column', {})
                            if col:
                                entity = col.get('Expression', {}).get('SourceRef', {}).get('Entity', '')
                                if entity:
                                    page_tables.add(entity)
                except (json.JSONDecodeError, IOError):
                    pass

        if visual_count > 0 or page_measures:
            pages.append({
                'name': page_name,
                'visuals': visual_count,
                'visualTypes': visual_types,
                'measures': sorted(page_measures),
                'tables': sorted(page_tables)
            })

    return pages

# ---------------------------------------------------------------------------
# Project Walker
# ---------------------------------------------------------------------------

def find_pbip_project(root_path):
    """Find .SemanticModel and .Report folders in a PBIP project."""
    model_dir = None
    report_dirs = []

    for item in os.listdir(root_path):
        full = os.path.join(root_path, item)
        if os.path.isdir(full):
            if item.endswith('.SemanticModel'):
                model_dir = full
            elif item.endswith('.Report'):
                report_dirs.append(full)

    # Also check if root IS a SemanticModel folder
    if not model_dir:
        if any(f.endswith('.tmdl') for f in os.listdir(root_path) if os.path.isfile(os.path.join(root_path, f))):
            model_dir = root_path
        tables_dir = os.path.join(root_path, 'definition', 'tables')
        if os.path.isdir(tables_dir):
            model_dir = os.path.join(root_path, 'definition')

    return model_dir, report_dirs

def parse_model(model_dir):
    """Parse all TMDL files from a semantic model directory."""
    tables = []

    # Find all .tmdl files
    tables_dir = os.path.join(model_dir, 'tables')
    if not os.path.isdir(tables_dir):
        tables_dir = os.path.join(model_dir, 'definition', 'tables')

    if os.path.isdir(tables_dir):
        for root, dirs, files in os.walk(tables_dir):
            for fname in files:
                if fname.endswith('.tmdl'):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        table = parse_table_file(content, fpath)
                        if table['name']:
                            table['type'] = classify_table(table)
                            tables.append(table)
                    except (IOError, UnicodeDecodeError):
                        pass

    return tables

def parse_reports(report_dirs):
    """Parse all report directories."""
    reports = []

    for rdir in report_dirs:
        report_name = os.path.basename(rdir).replace('.Report', '')

        # Try PBIR format first (pages/*/visuals/*)
        definition_dir = os.path.join(rdir, 'definition')
        if os.path.isdir(os.path.join(definition_dir, 'pages')):
            pages = parse_pbir_report(definition_dir)
        else:
            # Try legacy report.json
            report_json_path = os.path.join(rdir, 'report.json')
            if not os.path.isfile(report_json_path):
                report_json_path = os.path.join(definition_dir, 'report.json')

            pages = []
            if os.path.isfile(report_json_path):
                try:
                    with open(report_json_path, 'r', encoding='utf-8') as f:
                        pages = parse_report_json(f.read())
                except (IOError, UnicodeDecodeError):
                    pass

        if pages:
            reports.append({'name': report_name, 'pages': pages})

    return reports

def detect_domains(reports):
    """Group reports into domains by common prefix (before ' - ' delimiter)."""
    domains = {}
    for r in reports:
        parts = r['name'].split(' - ', 1)
        domain = parts[0].strip() if len(parts) > 1 else 'Default'
        r['domain'] = domain
        if domain not in domains:
            domains[domain] = []
        domains[domain].append(r['name'])
    return domains

# ---------------------------------------------------------------------------
# HTML Generation
# ---------------------------------------------------------------------------

CSS = r"""
:root, [data-theme="light"] {
  --accent: #2563EB; --accent-hover: #1D4ED8; --accent-bg: #EFF6FF; --accent-light: #93C5FD;
  --toolbar-bg: #1E293B; --toolbar-border: #3B82F6;
  --bg-primary: #FFFFFF; --bg-secondary: #F8FAFC; --bg-tertiary: #F1F5F9;
  --bg-sidebar: #F8FAFC; --bg-card: #FFFFFF; --bg-hover: #EFF6FF; --bg-active: #DBEAFE;
  --text-primary: #1E293B; --text-secondary: #475569; --text-muted: #94A3B8;
  --border: #E2E8F0; --border-hover: #93C5FD;
  --danger: #EF4444;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.06); --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
  --radius-sm: 4px; --radius-md: 8px;
  --badge-measure: #2563EB; --badge-table: #1E293B; --badge-column: #94A3B8; --badge-report: #DC2626;
  --badge-fact: #0891B2; --badge-dimension: #7C3AED; --badge-measure-table: #059669; --badge-parameter: #D97706;
}
[data-theme="dark"] {
  --accent: #60A5FA; --accent-hover: #93C5FD; --accent-bg: #1E3A5F; --accent-light: #3B82F6;
  --toolbar-bg: #0F172A; --toolbar-border: #3B82F6;
  --bg-primary: #0F172A; --bg-secondary: #1E293B; --bg-tertiary: #334155;
  --bg-sidebar: #0F172A; --bg-card: #1E293B; --bg-hover: #1E3A5F; --bg-active: #1E40AF;
  --text-primary: #F1F5F9; --text-secondary: #CBD5E1; --text-muted: #64748B;
  --border: #334155; --border-hover: #60A5FA;
  --danger: #F87171;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.3); --shadow-md: 0 4px 12px rgba(0,0,0,0.4);
  --badge-measure: #60A5FA; --badge-table: #93C5FD; --badge-column: #64748B; --badge-report: #F87171;
  --badge-fact: #22D3EE; --badge-dimension: #A78BFA; --badge-measure-table: #34D399; --badge-parameter: #FBBF24;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg-primary);color:var(--text-primary);line-height:1.5;overflow:hidden;height:100vh}
#toolbar{display:flex;align-items:center;justify-content:space-between;height:52px;padding:0 16px;background:var(--toolbar-bg);color:#FFF;border-bottom:2px solid var(--toolbar-border);z-index:100;gap:16px}
.toolbar-left{display:flex;align-items:center;gap:10px;flex-shrink:0}
.app-title{font-size:15px;font-weight:600;letter-spacing:0.3px}
.toolbar-center{flex:1;max-width:480px}
#global-search{width:100%;padding:6px 12px;border:1px solid rgba(255,255,255,0.2);border-radius:var(--radius-sm);background:rgba(255,255,255,0.1);color:#FFF;font-size:13px;outline:none}
#global-search::placeholder{color:rgba(255,255,255,0.5)}
#global-search:focus{border-color:var(--accent);background:rgba(255,255,255,0.15)}
.search-results{position:absolute;top:100%;left:0;right:0;max-height:400px;overflow-y:auto;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-md);box-shadow:var(--shadow-md);z-index:200;margin-top:4px}
.search-result-item{display:flex;align-items:center;gap:8px;padding:8px 12px;cursor:pointer;color:var(--text-primary);font-size:13px}
.search-result-item:hover{background:var(--bg-hover)}
.search-type-badge{font-size:10px;font-weight:600;text-transform:uppercase;padding:2px 6px;border-radius:3px;color:#fff;flex-shrink:0}
.search-type-badge[data-type="measure"]{background:var(--badge-measure)}
.search-type-badge[data-type="table"]{background:var(--badge-table)}
.search-type-badge[data-type="column"]{background:var(--badge-column)}
.search-type-badge[data-type="report"]{background:var(--badge-report)}
.toolbar-right{display:flex;align-items:center;gap:8px;flex-shrink:0}
.btn-icon{width:32px;height:32px;border:1px solid rgba(255,255,255,0.2);border-radius:var(--radius-sm);background:transparent;color:#FFF;font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center}
.btn-icon:hover{background:rgba(255,255,255,0.1)}
.toolbar-meta{font-size:11px;color:rgba(255,255,255,0.5)}
.app-layout{display:flex;height:calc(100vh - 52px)}
.sidebar{width:280px;flex-shrink:0;background:var(--bg-sidebar);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.tab-panel{flex:1;overflow-y:auto;padding:8px}
.tree-group{margin-bottom:2px}
.tree-group-header{display:flex;align-items:center;gap:6px;padding:6px 8px;font-size:13px;font-weight:600;color:var(--text-primary);cursor:pointer;border-radius:var(--radius-sm)}
.tree-group-header:hover{background:var(--bg-hover)}
.tree-group-header .chevron{font-size:10px;color:var(--text-muted);transition:transform 0.2s}
.tree-group-header .chevron.open{transform:rotate(90deg)}
.tree-group-header .count{margin-left:auto;font-size:11px;color:var(--text-muted);font-weight:400}
.tree-children{padding-left:16px}
.tree-children .tree-children{padding-left:12px}
.tree-children .tree-children .tree-item{padding:3px 6px;font-size:11px}
.tree-item{display:flex;align-items:center;gap:6px;padding:4px 8px;font-size:12px;color:var(--text-secondary);cursor:pointer;border-radius:var(--radius-sm);overflow:hidden}
.tree-item:hover{background:var(--bg-hover);color:var(--text-primary)}
.main-content{flex:1;overflow-y:auto;padding:24px}
.view{animation:fadeIn 0.2s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
.card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-md);padding:20px;box-shadow:var(--shadow-sm);margin-bottom:16px}
.card-title{font-size:16px;font-weight:600;color:var(--text-primary);margin-bottom:8px}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:24px}
.stat-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-md);padding:16px;text-align:center;cursor:pointer;transition:all 0.2s}
.stat-card:hover{border-color:var(--accent);box-shadow:var(--shadow-md);transform:translateY(-1px)}
.stat-value{font-size:28px;font-weight:700;color:var(--accent)}
.stat-label{font-size:12px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;margin-top:4px}
.domain-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-top:20px}
.domain-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-md);padding:20px;cursor:pointer;transition:all 0.2s;border-left:4px solid var(--accent)}
.domain-card:hover{box-shadow:var(--shadow-md);transform:translateY(-2px)}
.domain-card h3{font-size:16px;font-weight:600;margin-bottom:8px}
.domain-card .domain-meta{font-size:13px;color:var(--text-secondary)}
.breadcrumbs{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-muted);margin-bottom:16px}
.breadcrumbs a{color:var(--accent);text-decoration:none;cursor:pointer}
.breadcrumbs a:hover{text-decoration:underline}
.section-title{font-size:18px;font-weight:700;color:var(--text-primary);margin-bottom:8px}
.section-subtitle{font-size:13px;color:var(--text-muted);margin-bottom:20px}
.column-table{width:100%;border-collapse:collapse;font-size:13px}
.column-table th{text-align:left;padding:8px 12px;background:var(--bg-tertiary);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid var(--border)}
.column-table td{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--text-primary)}
.column-table tbody tr:hover td{background:var(--bg-hover)}
.glossary-cat-header td{background:var(--bg-tertiary);font-weight:700;font-size:13px;padding:10px 12px !important;border-bottom:2px solid var(--border)}
.glossary-cat-icon{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:4px;color:#fff;font-size:11px;font-weight:700;margin-right:6px;vertical-align:middle}
.glossary-cat-badge{display:inline-block;font-size:10px;font-weight:600;padding:2px 8px;border-radius:3px;color:#fff;white-space:nowrap}
.glossary-row.clickable{cursor:pointer}
.glossary-row.clickable:hover td{background:var(--bg-hover)}
.glossary-row.clickable .glossary-term{color:var(--accent)}
.glossary-term{font-weight:500}
.glossary-desc{color:var(--text-secondary);font-size:12px;line-height:1.5}
.glossary-pages{color:var(--text-muted);font-size:11px}
.table-type-badge{font-size:9px;font-weight:600;text-transform:uppercase;padding:1px 4px;border-radius:2px;color:#fff}
.table-type-badge.fact{background:var(--badge-fact)}
.table-type-badge.dimension{background:var(--badge-dimension)}
.table-type-badge.measure{background:var(--badge-measure-table)}
.table-type-badge.parameter{background:var(--badge-parameter)}
.table-type-badge.other{background:var(--badge-column)}
.view-toggle{display:inline-flex;border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden;margin-bottom:16px}
.view-toggle button{padding:6px 16px;border:none;background:transparent;color:var(--text-secondary);font-size:13px;cursor:pointer}
.view-toggle button.active{background:var(--accent);color:#fff}
.biz-section{margin-bottom:16px}
.biz-section h4{font-size:12px;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted);margin-bottom:6px}
.biz-section p{font-size:14px;color:var(--text-primary);line-height:1.6}
.dax-block{background:var(--bg-tertiary);border:1px solid var(--border);border-radius:var(--radius-md);padding:16px;font-family:'Cascadia Code','Fira Code','Consolas',monospace;font-size:13px;line-height:1.6;white-space:pre-wrap;overflow-x:auto}
.dax-keyword{color:#0000FF;font-weight:600}
.dax-number{color:#098658}
[data-theme="dark"] .dax-keyword{color:#569CD6}
[data-theme="dark"] .dax-number{color:#B5CEA8}
.confusion-warning{background:#FFF7ED;border:1px solid #FED7AA;border-radius:var(--radius-sm);padding:10px 12px;font-size:13px;color:#9A3412}
[data-theme="dark"] .confusion-warning{background:#451A03;border-color:#92400E;color:#FED7AA}
.dep-chip{display:inline-flex;align-items:center;padding:3px 10px;border-radius:20px;font-size:12px;cursor:pointer}
.dep-chip.measure-dep{background:var(--accent-bg);color:var(--accent);border:1px solid var(--accent)}
.measure-list{list-style:none}
.measure-list-item{display:flex;align-items:center;gap:8px;padding:6px 10px;font-size:13px;color:var(--text-secondary);cursor:pointer;border-radius:var(--radius-sm)}
.measure-list-item:hover{background:var(--bg-hover);color:var(--text-primary)}
.hidden{display:none !important}
@media(max-width:768px){.sidebar{width:240px}.toolbar-center{display:none}}
@media(max-width:600px){.sidebar{display:none}}
.lineage-page-btn{padding:6px 14px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-card);color:var(--text-secondary);font-size:12px;cursor:pointer;transition:all 0.15s}
.lineage-page-btn:hover{border-color:var(--accent);color:var(--text-primary)}
.lineage-page-btn.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.lin-grid{display:grid;grid-template-columns:280px 1fr;gap:20px;min-height:400px}
.lin-pick{border-right:1px solid var(--border);padding-right:16px}
.lin-pick-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:var(--text-muted);margin-bottom:10px}
.lin-pick-item{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:var(--radius-sm);cursor:pointer;font-size:13px;color:var(--text-secondary);border:1px solid transparent;transition:all 0.15s;margin-bottom:2px}
.lin-pick-item:hover{background:var(--bg-hover);color:var(--text-primary)}
.lin-pick-item.active{background:var(--accent-bg);color:var(--accent);border-color:var(--accent);font-weight:600}
.lin-pick-dot{width:8px;height:8px;border-radius:50%;background:var(--badge-measure);flex-shrink:0}
.lin-tree{padding:4px 0}
.lin-empty{color:var(--text-muted);font-size:13px;font-style:italic;padding:40px 20px;text-align:center}
.lin-root{margin-bottom:24px}
.lin-root-header{display:flex;align-items:center;gap:10px;padding:12px 16px;background:linear-gradient(135deg,#78350F,#92400E);border:1.5px solid #D97706;border-radius:8px;color:#FDE68A;font-weight:600;font-size:14px;margin-bottom:12px}
[data-theme="light"] .lin-root-header{background:linear-gradient(135deg,#FFFBEB,#FEF3C7);border-color:#FCD34D;color:#92400E}
.lin-root-dot{width:10px;height:10px;border-radius:50%;background:#FBBF24;flex-shrink:0}
.lin-root-table{font-size:11px;font-weight:400;margin-left:auto;opacity:0.7}
.lin-deps{padding-left:24px;border-left:2px solid var(--border);margin-left:20px}
.lin-dep{display:flex;align-items:center;gap:8px;padding:8px 12px;margin-bottom:4px;border-radius:6px;font-size:12px;cursor:pointer;transition:all 0.15s;position:relative}
.lin-dep::before{content:'';position:absolute;left:-25px;top:50%;width:24px;height:0;border-top:2px solid var(--border)}
.lin-dep:hover{transform:translateX(2px)}
.lin-dep-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.lin-dep-name{font-weight:500}
.lin-dep-type{font-size:10px;margin-left:auto;opacity:0.6;flex-shrink:0}
.lin-dep.submeasure{background:#1E1B4B;border:1px solid #6366F1;color:#C7D2FE}
.lin-dep.submeasure .lin-dep-dot{background:#818CF8}
.lin-dep.column{background:#4C1D95;border:1px solid #7C3AED;color:#DDD6FE}
.lin-dep.column .lin-dep-dot{background:#A78BFA}
[data-theme="light"] .lin-dep.submeasure{background:#EEF2FF;border-color:#A5B4FC;color:#3730A3}
[data-theme="light"] .lin-dep.submeasure .lin-dep-dot{background:#6366F1}
[data-theme="light"] .lin-dep.column{background:#F5F3FF;border-color:#C4B5FD;color:#5B21B6}
[data-theme="light"] .lin-dep.column .lin-dep-dot{background:#7C3AED}
.lin-dep-group-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:var(--text-muted);padding:8px 0 4px 0}
.lin-no-deps{color:var(--text-muted);font-size:12px;font-style:italic;padding:8px 12px}
@media(max-width:900px){.lin-grid{grid-template-columns:1fr}}
.sdrop{position:relative;display:inline-block}
.sdrop-btn{padding:5px 28px 5px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg-secondary);color:var(--text-primary);cursor:pointer;min-width:180px;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%2394A3B8'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 8px center}
.sdrop-panel{display:none;position:absolute;top:100%;left:0;z-index:100;min-width:100%;max-height:260px;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-sm);box-shadow:var(--shadow-md);margin-top:2px;overflow:hidden}
.sdrop-panel.open{display:block}
.sdrop-search{width:100%;padding:6px 10px;border:none;border-bottom:1px solid var(--border);font-size:12px;outline:none;background:var(--bg-secondary);color:var(--text-primary);box-sizing:border-box}
.sdrop-list{max-height:220px;overflow-y:auto}
.sdrop-opt{padding:6px 10px;font-size:12px;cursor:pointer;color:var(--text-secondary)}
.sdrop-opt:hover,.sdrop-opt.active{background:var(--bg-hover);color:var(--text-primary)}
"""

JS_APP = r"""
const BUNDLE = { model: { name: RAW_DATA.modelName || "Semantic Model", tables: RAW_DATA.tables || [], relationships: RAW_DATA.relationships || [] }, reports: RAW_DATA.reports || [], domainMap: RAW_DATA.domains || {} };

// Filter report measures to only include actual model measures
const allMeasureNames = new Set();
for(const t of BUNDLE.model.tables) for(const m of t.measures) allMeasureNames.add(m.name);
for(const r of BUNDLE.reports) {
  r.pages = (r.pages||[]).map(p => {
    const realMeasures = (p.measures||[]).filter(m => allMeasureNames.has(m));
    return { name: p.name, measures: realMeasures, tables: p.tables||[], visuals: p.visuals||realMeasures.length, visualTypes: p.visualTypes||{} };
  });
}

const MEASURE_USAGE = {};
for (const r of BUNDLE.reports) for (const p of (r.pages||[])) for (const m of (p.measures||[])) {
  if (!MEASURE_USAGE[m]) MEASURE_USAGE[m] = [];
  MEASURE_USAGE[m].push({ report: r.name, domain: r.domain, page: p.name, visuals: p.visuals, visualTypes: p.visualTypes||{} });
}

function esc(s){const d=document.createElement('div');d.textContent=s||'';return d.innerHTML}
function showView(n){document.querySelectorAll('.view').forEach(v=>v.classList.add('hidden'));const e=document.getElementById('view-'+n);if(e){e.classList.remove('hidden');e.style.animation='none';e.offsetHeight;e.style.animation=''}}
function findMeasure(n){for(const t of BUNDLE.model.tables){const m=t.measures.find(x=>x.name===n);if(m)return{measure:m,table:t.name}}return null}
function findTable(n){return BUNDLE.model.tables.find(t=>t.name===n)}
function typeBadge(t){return `<span class="table-type-badge ${t}">${(t||'other').charAt(0).toUpperCase()+(t||'other').slice(1)}</span>`}
function highlightDax(e){let s=esc(e);['CALCULATE','FILTER','ALL','ALLEXCEPT','ALLSELECTED','SUM','SUMX','AVERAGE','AVERAGEX','COUNTROWS','COUNT','COUNTA','DISTINCTCOUNT','DIVIDE','IF','SWITCH','VAR','RETURN','BLANK','TRUE','FALSE','RELATED','RELATEDTABLE','SELECTEDVALUE','VALUES','FIRSTDATE','LASTDATE','NOT','ISBLANK','COALESCE','MAX','MAXX','MIN','MINX','EARLIER','RANKX','TOPN','ADDCOLUMNS','SUMMARIZE','KEEPFILTERS','REMOVEFILTERS','USERELATIONSHIP','CROSSFILTER','TREATAS','IN','DATATABLE','ROW','ERROR','FORMAT','YEAR','MONTH','DAY','DATE','TODAY','NOW','DATESYTD','DATESMTD','DATESQTD','TOTALYTD','TOTALMTD','TOTALQTD','SAMEPERIODLASTYEAR','DATEADD','PARALLELPERIOD','PREVIOUSMONTH','PREVIOUSYEAR','NEXTMONTH','NEXTYEAR','STARTOFMONTH','ENDOFMONTH','STARTOFYEAR','ENDOFYEAR','CALENDAR','CALENDARAUTO','EXCEPT','CALCULATETABLE','DATESINPERIOD'].forEach(k=>{s=s.replace(new RegExp('\\b('+k+')\\b','gi'),'<span class="dax-keyword">$1</span>')});return s.replace(/\b(\d+\.?\d*)\b/g,'<span class="dax-number">$1</span>')}
function toggleView(show,hide,btn){document.getElementById('mv-'+show)?.classList.remove('hidden');document.getElementById('mv-'+hide)?.classList.add('hidden');btn.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));btn.classList.add('active')}
function filterGlossary(q,tid){q=q.toLowerCase();let last=null,vis=false;document.getElementById(tid).querySelectorAll('tbody tr').forEach(r=>{if(r.classList.contains('glossary-cat-header')){if(last)last.style.display=vis?'':'none';last=r;vis=false}else{const m=!q||r.textContent.toLowerCase().includes(q);r.style.display=m?'':'none';if(m)vis=true}});if(last)last.style.display=vis?'':'none'}
function toggleGroup(h){const c=h.nextElementSibling,ch=h.querySelector('.chevron');if(c.style.display==='none'){c.style.display='';ch.classList.add('open')}else{c.style.display='none';ch.classList.remove('open')}}

// --- Hash routing ---
function setHash(view, param) { location.hash = '#/' + view + (param ? '/' + encodeURIComponent(param) : ''); }
function handleHash() {
  const h = location.hash.replace('#/', '');
  if (!h) { renderHome(); return; }
  const parts = h.split('/');
  const view = parts[0];
  const rest = decodeURIComponent(parts.slice(1).join('/'));
  switch(view) {
    case 'domain': showDomain(rest, true); break;
    case 'report': showReport(rest, true); break;
    case 'measure': showMeasure(rest, true); break;
    case 'table': showTable(rest, true); break;
    case 'lineage': showLineage(rest.split('\\')[0], rest.split('\\')[1], true); break;
    case 'table-lineage': showTableLineage(rest, true); break;
    case 'unused': showUnused(true); break;
    default: renderHome();
  }
}
window.addEventListener('hashchange', handleHash);

function renderHome(){
  setHash('','');
  const T=BUNDLE.model.tables,tM=T.reduce((s,t)=>s+t.measures.length,0),tC=T.reduce((s,t)=>s+t.columns.length,0);
  const bt={};T.forEach(t=>{bt[t.type]=(bt[t.type]||0)+1});
  const tbHtml=Object.entries(bt).map(([t,c])=>`<span style="margin-right:12px">${typeBadge(t)} ${c} ${t}</span>`).join('');
  let dc='';
  for(const[d,rn]of Object.entries(BUNDLE.domainMap)){const reps=BUNDLE.reports.filter(r=>rn.includes(r.name));const ms=new Set(reps.flatMap(r=>(r.pages||[]).flatMap(p=>p.measures||[]))).size;dc+=`<div class="domain-card" onclick="showDomain('${esc(d)}')"><h3>${esc(d)}</h3><div class="domain-meta">${reps.length} reports &middot; ${ms} measures</div></div>`}
  document.getElementById('view-home').innerHTML=`<div class="section-title">${esc(BUNDLE.model.name)}</div><div class="section-subtitle">Explore measures, tables, and dependencies across your semantic model.</div><div class="stats-grid"><div class="stat-card"><div class="stat-value">${tM}</div><div class="stat-label">Measures</div></div><div class="stat-card"><div class="stat-value">${T.length}</div><div class="stat-label">Tables</div></div><div class="stat-card"><div class="stat-value">${tC}</div><div class="stat-label">Columns</div></div><div class="stat-card"><div class="stat-value">${BUNDLE.reports.length}</div><div class="stat-label">Reports</div></div></div><div style="font-size:12px;color:var(--text-secondary);margin-bottom:16px">${tbHtml}</div>${Object.keys(BUNDLE.domainMap).length>0?`<h3 style="font-size:16px;font-weight:600">${Object.keys(BUNDLE.domainMap).length>1?'Domains':'Reports'}</h3><div class="domain-grid">${dc}</div>`:''}`;
  showView('home');
}

function showDomain(name, fromHash){
  if(!fromHash) setHash('domain', name);
  const rn=BUNDLE.domainMap[name]||[],reps=BUNDLE.reports.filter(r=>rn.includes(r.name));
  const domainMeasureNames = new Set(reps.flatMap(r=>(r.pages||[]).flatMap(p=>p.measures||[])));
  const measTables = BUNDLE.model.tables.filter(t=>t.type==='measure'&&t.measures.some(m=>domainMeasureNames.has(m.name)));
  const factTableNames = new Set(reps.flatMap(r=>(r.pages||[]).flatMap(p=>(p.tables||[]).filter(t=>{const tbl=findTable(t);return tbl&&tbl.type==='fact'}))));
  const dimTableNames = new Set(reps.flatMap(r=>(r.pages||[]).flatMap(p=>(p.tables||[]).filter(t=>{const tbl=findTable(t);return tbl&&tbl.type==='dimension'}))));
  const totalMeas = domainMeasureNames.size;
  let statsHtml=`<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-bottom:16px">
    <div class="card" style="text-align:center;padding:16px"><div style="font-size:24px;font-weight:700;color:var(--accent)">${reps.length}</div><div style="font-size:11px;color:var(--text-muted)">Reports</div></div>
    <div class="card" style="text-align:center;padding:16px"><div style="font-size:24px;font-weight:700;color:var(--accent)">${totalMeas}</div><div style="font-size:11px;color:var(--text-muted)">Measures</div></div>
    <div class="card" style="text-align:center;padding:16px"><div style="font-size:24px;font-weight:700;color:var(--accent)">${factTableNames.size}</div><div style="font-size:11px;color:var(--text-muted)">Fact Tables</div></div>
    <div class="card" style="text-align:center;padding:16px"><div style="font-size:24px;font-weight:700;color:var(--accent)">${dimTableNames.size}</div><div style="font-size:11px;color:var(--text-muted)">Dimensions</div></div>
  </div>`;
  let reportsHtml=`<div class="card"><div class="card-title">Reports (${reps.length})</div><ul class="measure-list">${reps.map(r=>{const pg=r.pages||[];return`<li class="measure-list-item" onclick="showReport('${esc(r.name)}')"><span class="search-type-badge" data-type="report">Report</span><span>${esc(r.name)}</span><span style="margin-left:auto;font-size:11px;color:var(--text-muted)">${pg.length} pages, ${new Set(pg.flatMap(p=>p.measures||[])).size} measures</span></li>`}).join('')}</ul></div>`;

  // Measures listing
  let measHtml='';
  const domMeasures=[];
  for(const t of measTables){for(const m of t.measures){if(domainMeasureNames.has(m.name))domMeasures.push({name:m.name,table:t.name,description:m.description||''})}}
  domMeasures.sort((a,b)=>a.name.localeCompare(b.name));
  if(domMeasures.length>0){
    measHtml=`<div class="card"><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px"><div class="card-title" style="margin-bottom:0">Measures (${domMeasures.length})</div><input type="text" placeholder="Search measures..." style="padding:5px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg-secondary);color:var(--text-primary);outline:none;width:200px" oninput="filterGlossary(this.value,'dom-meas-table')" /></div><table class="column-table" id="dom-meas-table"><thead><tr><th style="width:200px">Measure</th><th>Description</th><th style="width:140px">Table</th></tr></thead><tbody>${domMeasures.map(m=>`<tr class="glossary-row clickable" onclick="showMeasure('${esc(m.name)}')"><td class="glossary-term">${esc(m.name)}</td><td style="font-size:12px;color:var(--text-secondary)">${esc(m.description)}</td><td style="font-size:11px;color:var(--text-muted)">${esc(m.table)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  // Fact tables
  let factHtml='';
  if(factTableNames.size>0){
    factHtml=`<div class="card"><div class="card-title">Fact Tables (${factTableNames.size})</div><ul class="measure-list">${[...factTableNames].sort().map(t=>{const tbl=findTable(t);return`<li class="measure-list-item" onclick="showTableLineage('${esc(t)}')"><span class="search-type-badge" data-type="table" style="font-size:9px;padding:1px 5px;background:var(--badge-fact)">F</span><span>${esc(t)}</span><span style="margin-left:auto;font-size:11px;color:var(--text-muted)">${tbl?tbl.columns.length+' columns':''}</span></li>`}).join('')}</ul></div>`;
  }

  // Dimension tables
  let dimHtml='';
  if(dimTableNames.size>0){
    dimHtml=`<div class="card"><div class="card-title">Dimensions (${dimTableNames.size})</div><ul class="measure-list">${[...dimTableNames].sort().map(t=>{const tbl=findTable(t);return`<li class="measure-list-item" onclick="showTable('${esc(t)}')"><span class="search-type-badge" data-type="dimension" style="font-size:9px;padding:1px 5px;background:var(--badge-dimension)">D</span><span>${esc(t)}</span><span style="margin-left:auto;font-size:11px;color:var(--text-muted)">${tbl?tbl.columns.length+' columns':''}</span></li>`}).join('')}</ul></div>`;
  }

  document.getElementById('view-domain').innerHTML=`<div class="breadcrumbs"><a onclick="renderHome()">Home</a><span class="separator">/</span><span>${esc(name)}</span></div><div class="section-title">${esc(name)}</div><div class="section-subtitle">${reps.length} reports &middot; ${totalMeas} measures &middot; ${factTableNames.size+dimTableNames.size} tables</div>${statsHtml}${reportsHtml}${measHtml}${factHtml}${dimHtml}`;
  showView('domain');
}

function showReport(name, fromHash){
  if(!fromHash) setHash('report', name);
  const r=BUNDLE.reports.find(x=>x.name===name);if(!r)return;
  const pages=r.pages||[],tv=pages.reduce((s,p)=>s+p.visuals,0),am=[...new Set(pages.flatMap(p=>p.measures||[]))].sort(),at=[...new Set(pages.flatMap(p=>p.tables||[]))].sort();
  const mp={};pages.forEach(p=>{for(const m of(p.measures||[]))if(!mp[m])mp[m]=[],mp[m].push(p.name);else mp[m].push(p.name)});
  let rows='';
  if(am.length>0){rows+=`<tr class="glossary-cat-header"><td colspan="4"><span class="glossary-cat-icon" style="background:var(--badge-measure)">M</span> Measures (${am.length})</td></tr>`;for(const m of am){const pl=(mp[m]||[]).join(', ');const f=findMeasure(m);const desc=f&&f.measure.description?f.measure.description:'';rows+=`<tr class="glossary-row clickable" onclick="showMeasure('${esc(m)}')"><td><span class="glossary-cat-badge" style="background:var(--badge-measure)">Measure</span></td><td class="glossary-term">${esc(m)}</td><td class="glossary-desc">${desc?esc(desc):'<em style="color:var(--text-muted)">—</em>'}</td><td class="glossary-pages">${esc(pl)}</td></tr>`}}
  rows+=`<tr class="glossary-cat-header"><td colspan="4"><span class="glossary-cat-icon" style="background:var(--badge-report)">P</span> Report Pages (${pages.length})</td></tr>`;
  pages.forEach(p=>{const vt=Object.entries(p.visualTypes||{}).filter(([k])=>k!=='other').slice(0,5).map(([t,c])=>`${c} ${t}`).join(', ');rows+=`<tr class="glossary-row"><td><span class="glossary-cat-badge" style="background:var(--badge-report)">Page</span></td><td class="glossary-term">${esc(p.name)}</td><td class="glossary-desc">${p.visuals} visuals${vt?' — '+esc(vt):''}</td><td class="glossary-pages">${(p.measures||[]).length} measures</td></tr>`});
  if(at.length>0){rows+=`<tr class="glossary-cat-header"><td colspan="4"><span class="glossary-cat-icon" style="background:var(--badge-table)">T</span> Tables (${at.length})</td></tr>`;for(const t of at){const tbl=findTable(t),type=tbl?tbl.type:'other',pl=[...new Set(pages.filter(p=>(p.tables||[]).includes(t)).map(p=>p.name))].join(', ');rows+=`<tr class="glossary-row clickable" onclick="showTable('${esc(t)}')"><td>${typeBadge(type)}</td><td class="glossary-term">${esc(t)}</td><td class="glossary-desc">${tbl?`${tbl.columns.length} columns, ${tbl.measures.length} measures`:''}</td><td class="glossary-pages">${esc(pl)}</td></tr>`}}
  const domainCrumb = r.domain && r.domain !== 'Default' ? `<a onclick="showDomain('${esc(r.domain)}')">${esc(r.domain)}</a><span class="separator">/</span>` : '';
  document.getElementById('view-report').innerHTML=`<div class="breadcrumbs"><a onclick="renderHome()">Home</a><span class="separator">/</span>${domainCrumb}<span>${esc(name)}</span></div><div style="display:flex;align-items:center;gap:16px;margin-bottom:8px"><div class="section-title" style="margin-bottom:0">${esc(name)}</div><button class="lineage-page-btn" onclick="showLineage('${esc(name)}')" style="font-size:11px;padding:4px 12px">&#9654; View Lineage</button></div><div class="section-subtitle">${r.domain&&r.domain!=='Default'?esc(r.domain)+' &middot; ':''}${pages.length} pages &middot; ${tv} visuals &middot; ${am.length} measures &middot; ${at.length} tables</div><div class="card"><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px"><div class="card-title" style="margin-bottom:0">Report Glossary</div><input type="text" placeholder="Filter terms..." style="padding:5px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg-secondary);color:var(--text-primary);outline:none;width:200px" oninput="filterGlossary(this.value,'rg-table')" /></div><table class="column-table" id="rg-table"><thead><tr><th style="width:80px">Category</th><th style="width:190px">Term</th><th>Description</th><th style="width:150px">Found On</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  showView('report');
}

function showMeasure(name, fromHash){
  if(!fromHash) setHash('measure', name);
  const f=findMeasure(name);if(!f)return;
  const{measure,table:st}=f,dax=highlightDax(measure.expression||'N/A'),usage=MEASURE_USAGE[name]||[];
  const desc = measure.description || '';
  const byR={};for(const u of usage){if(!byR[u.report])byR[u.report]={domain:u.domain,pages:[]};byR[u.report].pages.push(u)}
  let uh='';if(usage.length>0){uh=`<div class="card"><div class="card-title">Used In Reports (${Object.keys(byR).length})</div>`;for(const[rn,info]of Object.entries(byR))uh+=`<div style="padding:6px 0;border-bottom:1px solid var(--border)"><a onclick="showReport('${esc(rn)}')" style="font-weight:500;color:var(--accent);cursor:pointer;font-size:13px">${esc(rn)}</a><span style="font-size:11px;color:var(--text-muted);margin-left:8px">${info.pages.map(p=>esc(p.page)).join(', ')}</span></div>`;uh+='</div>'}
  const deps=parseDaxDeps(measure.expression||'');const depMeasures=deps.measures;const depColumns=deps.columns;
  let depHtml='';if(depMeasures.length>0||depColumns.length>0){depHtml='<div class="biz-section"><h4>Dependencies</h4><div style="display:flex;flex-wrap:wrap;gap:6px">';for(const dm of depMeasures)depHtml+=`<span class="dep-chip measure-dep" onclick="showMeasure('${esc(dm)}')">${esc(dm)}</span>`;for(const dc of depColumns)depHtml+=`<span class="dep-chip" style="background:var(--bg-tertiary);color:var(--text-secondary);border:1px solid var(--border);cursor:pointer" onclick="showTable('${esc(dc.table)}')">${esc(dc.table)}[${esc(dc.column)}]</span>`;depHtml+='</div></div>'}
  const descHtml = desc ? `<p>${esc(desc)}</p>` : `<p style="color:var(--text-muted);font-style:italic">No business description available.</p>`;
  document.getElementById('view-measure').innerHTML=`<div class="breadcrumbs"><a onclick="renderHome()">Home</a><span class="separator">/</span><a onclick="showTable('${esc(st)}')">${esc(st)}</a><span class="separator">/</span><span>${esc(name)}</span></div><div class="section-title">${esc(name)}</div><div class="section-subtitle">Table: ${esc(st)}</div><div class="view-toggle"><button class="active" onclick="toggleView('biz','tech',this)">Business</button><button onclick="toggleView('tech','biz',this)">Technical</button></div><div id="mv-biz"><div class="card"><div class="biz-section"><h4>Description</h4>${descHtml}</div>${depHtml}</div>${uh}</div><div id="mv-tech" class="hidden"><div class="card"><div class="biz-section"><h4>DAX Expression</h4><div class="dax-block">${dax}</div></div></div></div>`;
  showView('measure');
}

function showTable(name, fromHash){
  if(!fromHash) setHash('table', name);
  const table=findTable(name);
  if(!table){document.getElementById('view-table').innerHTML=`<div class="breadcrumbs"><a onclick="renderHome()">Home</a><span class="separator">/</span><span>${esc(name)}</span></div><div class="section-title">${esc(name)}</div><div class="card"><p style="color:var(--text-muted)">Referenced in reports but detailed metadata not available.</p></div>`;showView('table');return}
  const usedIn=[];for(const r of BUNDLE.reports){const pgs=(r.pages||[]).filter(p=>(p.tables||[]).includes(name));if(pgs.length>0)usedIn.push({report:r.name,domain:r.domain,pages:pgs.map(p=>p.name)})}
  let bizDesc='';
  if(table.type==='dimension')bizDesc=`<p>A <strong>dimension table</strong> providing descriptive attributes for filtering and grouping. Use "${name.replace('Dim ','')}" fields as slicers, row headers, or column headers in reports.</p><p style="margin-top:8px;color:var(--text-secondary)"><strong>${table.columns.length}</strong> attributes available for analysis.</p>`;
  else if(table.type==='fact')bizDesc=`<p>A <strong>fact table</strong> containing transactional/event data — the raw numbers behind your measures. Measures aggregate values from this table's columns.</p><p style="margin-top:8px;color:var(--text-secondary)"><strong>${table.columns.length}</strong> data columns.</p>`;
  else if(table.type==='measure')bizDesc=`<p>A <strong>measure table</strong> — a container for DAX calculations. No raw data stored here; it holds <strong>${table.measures.length}</strong> formulas that compute values from fact tables.</p>`;
  else if(table.type==='parameter')bizDesc=`<p>A <strong>parameter/selector table</strong> for report interactivity — toggles, dropdowns, and view switches that control how data is displayed.</p>`;
  else bizDesc=`<p>A supporting table used in the data model.</p>`;
  let colsHtml='';
  if(table.columns.length>0)colsHtml=`<div class="card"><div class="card-title">Columns (${table.columns.length})</div><table class="column-table"><thead><tr><th>Name</th><th>Type</th></tr></thead><tbody>${table.columns.map(c=>`<tr><td>${esc(c.name)}</td><td style="color:var(--text-muted);font-size:12px">${esc(c.dataType||'')}</td></tr>`).join('')}</tbody></table></div>`;
  let measHtml='';
  if(table.measures.length>0)measHtml=`<div class="card"><div class="card-title">Measures (${table.measures.length})</div><ul class="measure-list">${table.measures.map(m=>`<li class="measure-list-item" onclick="showMeasure('${esc(m.name)}')"><span class="search-type-badge" data-type="measure" style="font-size:9px;padding:1px 5px">M</span><span>${esc(m.name)}</span></li>`).join('')}</ul></div>`;
  let usedHtml='';
  if(usedIn.length>0)usedHtml=`<div class="card"><div class="card-title">Used In Reports (${usedIn.length})</div>${usedIn.map(u=>`<div style="padding:6px 0;border-bottom:1px solid var(--border)"><a onclick="showReport('${esc(u.report)}')" style="font-weight:500;color:var(--accent);cursor:pointer;font-size:13px">${esc(u.report)}</a><span style="font-size:11px;color:var(--text-muted);margin-left:8px">${esc(u.pages.join(', '))}</span></div>`).join('')}</div>`;
  const lineageBtn = (table.type==='fact'||table.type==='dimension') ? `<button class="lineage-page-btn" onclick="showTableLineage('${esc(name)}')" style="font-size:11px;padding:4px 12px">&#9654; View Lineage</button>` : '';
  document.getElementById('view-table').innerHTML=`<div class="breadcrumbs"><a onclick="renderHome()">Home</a><span class="separator">/</span><span>${esc(name)}</span></div><div style="display:flex;align-items:center;gap:16px;margin-bottom:8px"><div class="section-title" style="margin-bottom:0">${esc(name)}</div>${lineageBtn}</div><div class="section-subtitle">${typeBadge(table.type)} &middot; ${table.columns.length} columns &middot; ${table.measures.length} measures &middot; Used in ${usedIn.length} reports</div><div class="view-toggle"><button class="active" onclick="toggleView('tbl-biz','tbl-tech',this)">Business</button><button onclick="toggleView('tbl-tech','tbl-biz',this)">Technical</button></div><div id="mv-tbl-biz"><div class="card">${bizDesc}</div>${usedHtml}</div><div id="mv-tbl-tech" class="hidden">${colsHtml}${measHtml}</div>`;
  showView('table');
}

// --- Table Lineage ---
function showTableLineage(tableName, fromHash) {
  if(!fromHash) setHash('table-lineage', tableName);
  const table = findTable(tableName);
  if(!table) return;
  const pattern = "'"+tableName+"'[";
  const dependentMeasures = [];
  for(const t of BUNDLE.model.tables) {
    for(const m of t.measures) {
      if(m.expression && m.expression.includes(pattern)) {
        dependentMeasures.push({name:m.name, table:t.name, expression:m.expression, description:m.description||''});
      }
    }
  }
  dependentMeasures.sort((a,b)=>a.name.localeCompare(b.name));
  const colUsage = {};
  const colRe = new RegExp("'"+tableName.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+"'\\[([^\\]]+)\\]","g");
  for(const dm of dependentMeasures) {
    let match;
    const re = new RegExp(colRe.source, 'g');
    while((match=re.exec(dm.expression))!==null) {
      if(!colUsage[match[1]]) colUsage[match[1]]=[];
      if(!colUsage[match[1]].includes(dm.name)) colUsage[match[1]].push(dm.name);
    }
  }
  const usedIn=[];
  for(const r of BUNDLE.reports){const pgs=(r.pages||[]).filter(p=>(p.tables||[]).includes(tableName));if(pgs.length>0)usedIn.push({report:r.name,domain:r.domain,pages:pgs.map(p=>p.name)})}
  const usedCols = Object.entries(colUsage).sort((a,b)=>b[1].length-a[1].length);
  let colHtml='';
  if(usedCols.length>0){
    colHtml=`<div class="card"><div class="card-title">Column Usage (${usedCols.length} columns referenced by measures)</div><table class="column-table"><thead><tr><th style="width:200px">Column</th><th style="width:60px">Used By</th><th>Measures</th></tr></thead><tbody>${usedCols.map(([col,ms])=>`<tr><td class="glossary-term">${esc(col)}</td><td style="text-align:center;font-weight:600;color:var(--accent)">${ms.length}</td><td style="font-size:12px">${ms.map(m=>`<a onclick="showMeasure('${esc(m)}')" style="color:var(--accent);cursor:pointer;margin-right:8px">${esc(m)}</a>`).join('')}</td></tr>`).join('')}</tbody></table></div>`;
  }
  let mHtml='';
  if(dependentMeasures.length>0){
    mHtml=`<div class="card"><div class="card-title">Dependent Measures (${dependentMeasures.length})</div><table class="column-table"><thead><tr><th style="width:220px">Measure</th><th>Description</th><th style="width:150px">Measure Table</th></tr></thead><tbody>${dependentMeasures.map(m=>`<tr class="glossary-row clickable" onclick="showMeasure('${esc(m.name)}')"><td class="glossary-term">${esc(m.name)}</td><td style="font-size:12px;color:var(--text-secondary)">${esc(m.description)}</td><td style="font-size:11px;color:var(--text-muted)">${esc(m.table)}</td></tr>`).join('')}</tbody></table></div>`;
  }
  let repHtml='';
  if(usedIn.length>0){
    repHtml=`<div class="card"><div class="card-title">Used In Reports (${usedIn.length})</div>${usedIn.map(u=>`<div style="padding:6px 0;border-bottom:1px solid var(--border)"><a onclick="showReport('${esc(u.report)}')" style="font-weight:500;color:var(--accent);cursor:pointer;font-size:13px">${esc(u.report)}</a><span style="font-size:11px;color:var(--text-muted);margin-left:8px">${esc(u.pages.join(', '))}</span></div>`).join('')}</div>`;
  }
  const noUsage = dependentMeasures.length===0&&usedIn.length===0;
  document.getElementById('view-table-lineage').innerHTML=`
    <div class="breadcrumbs"><a onclick="renderHome()">Home</a><span class="separator">/</span><a onclick="showTable('${esc(tableName)}')">${esc(tableName)}</a><span class="separator">/</span><span>Lineage</span></div>
    <div class="section-title">Lineage: ${esc(tableName)}</div>
    <div class="section-subtitle">${typeBadge(table.type)} &middot; ${dependentMeasures.length} measures depend on this table &middot; Used in ${usedIn.length} reports</div>
    ${noUsage?'<div class="card"><p style="color:var(--text-muted);font-style:italic">This table is not directly referenced by any measures or reports.</p></div>':''}
    ${colHtml}${mHtml}${repHtml}`;
  showView('table-lineage');
}

// --- Searchable Dropdown ---
function initSearchDrop(id, options, onChange) {
  const el=document.getElementById(id);if(!el)return;
  el.dataset.selected='all';
  el.innerHTML=`<button class="sdrop-btn" type="button">All Tables</button><div class="sdrop-panel"><input class="sdrop-search" type="text" placeholder="Search tables..."><div class="sdrop-list"></div></div>`;
  const btn=el.querySelector('.sdrop-btn'),panel=el.querySelector('.sdrop-panel'),search=el.querySelector('.sdrop-search'),list=el.querySelector('.sdrop-list');
  function render(q){
    const f=q?options.filter(o=>o.label.toLowerCase().includes(q.toLowerCase())):options;
    list.innerHTML=[{value:'all',label:'All Tables'},...f].map(o=>`<div class="sdrop-opt${o.value===el.dataset.selected?' active':''}" data-val="${esc(o.value)}">${esc(o.label)}</div>`).join('');
    list.querySelectorAll('.sdrop-opt').forEach(o=>o.addEventListener('click',()=>{
      el.dataset.selected=o.dataset.val;
      btn.textContent=el.dataset.selected==='all'?'All Tables':options.find(x=>x.value===el.dataset.selected)?.label||el.dataset.selected;
      panel.classList.remove('open');search.value='';
      onChange(el.dataset.selected);
    }));
  }
  btn.addEventListener('click',()=>{panel.classList.toggle('open');if(panel.classList.contains('open')){render('');search.focus()}});
  search.addEventListener('input',()=>render(search.value));
  document.addEventListener('click',e=>{if(!el.contains(e.target))panel.classList.remove('open')});
  render('');
}

// --- Health Check Filter Functions ---
function _hcApplyFilters(){
  const domBtn=document.querySelector('#hc-dom-filters button.active');
  const dom=domBtn?domBtn.dataset.dom:'all';
  const drop=document.getElementById('hc-tbl-drop');
  const tbl=drop?drop.dataset.selected||'all':'all';
  document.querySelectorAll('#unused-meas-table tbody tr').forEach(r=>{
    const dMatch=dom==='all'||r.dataset.domain===dom;
    const tMatch=tbl==='all'||r.dataset.table===tbl;
    r.style.display=(dMatch&&tMatch)?'':'none';
  });
}
function filterHcDomain(btn,domain){
  btn.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  _hcApplyFilters();
}
function filterHcTable(val){
  _hcApplyFilters();
}
function _hcApplyColFilters(){
  const domBtn=document.querySelector('#hc-col-dom-filters button.active');
  const dom=domBtn?domBtn.dataset.dom:'all';
  const drop=document.getElementById('hc-col-tbl-drop');
  const tbl=drop?drop.dataset.selected||'all':'all';
  document.querySelectorAll('#unused-col-table tbody tr').forEach(r=>{
    const dMatch=dom==='all'||r.dataset.domain===dom;
    const tMatch=tbl==='all'||r.dataset.table===tbl;
    r.style.display=(dMatch&&tMatch)?'':'none';
  });
}
function filterHcColDomain(btn,domain){
  btn.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  _hcApplyColFilters();
}
function filterHcColTable(val){
  _hcApplyColFilters();
}

// --- Model Health Check ---
function showUnused(fromHash) {
  if(!fromHash) setHash('unused', '');
  const totalMeasures = BUNDLE.model.tables.reduce((s,t)=>s+t.measures.length,0);
  const totalTables = BUNDLE.model.tables.length;
  const totalColumns = BUNDLE.model.tables.reduce((s,t)=>s+t.columns.length,0);
  const usedMeasureNames = new Set();
  for(const r of BUNDLE.reports) for(const p of (r.pages||[])) for(const m of (p.measures||[])) usedMeasureNames.add(m);
  const referencedByDax = new Set();
  for(const t of BUNDLE.model.tables) for(const m of t.measures) {
    if(!m.expression) continue;
    const deps = parseDaxDeps(m.expression);
    for(const dep of deps.measures) referencedByDax.add(dep);
  }
  const unusedMeasures = [];
  for(const t of BUNDLE.model.tables) for(const m of t.measures) {
    if(!usedMeasureNames.has(m.name) && !referencedByDax.has(m.name)) {
      const domain = getDomainForTable(t.name);
      unusedMeasures.push({name:m.name, table:t.name, domain:domain, description:m.description||''});
    }
  }
  unusedMeasures.sort((a,b)=>a.name.localeCompare(b.name));
  const usedTableNames = new Set();
  for(const r of BUNDLE.reports) for(const p of (r.pages||[])) for(const tbl of (p.tables||[])) usedTableNames.add(tbl);
  for(const t of BUNDLE.model.tables) for(const m of t.measures) {
    if(!m.expression) continue;
    for(const t2 of BUNDLE.model.tables) {
      if(m.expression.includes("'"+t2.name+"'[")) usedTableNames.add(t2.name);
    }
  }
  for(const t of BUNDLE.model.tables) if(t.type==='measure') usedTableNames.add(t.name);
  const unusedTables = BUNDLE.model.tables.filter(t=>!usedTableNames.has(t.name)).sort((a,b)=>a.name.localeCompare(b.name));
  const usedColKeys = new Set();
  for(const t of BUNDLE.model.tables) for(const m of t.measures) {
    if(!m.expression) continue;
    const deps = parseDaxDeps(m.expression);
    for(const c of deps.columns) usedColKeys.add(c.table+'||'+c.column);
  }
  for(const rel of (BUNDLE.model.relationships||[])) {
    usedColKeys.add(rel.fromTable+'||'+rel.fromColumn);
    usedColKeys.add(rel.toTable+'||'+rel.toColumn);
  }
  const unusedColumns = [];
  for(const t of BUNDLE.model.tables) {
    if(t.type==='measure') continue;
    for(const c of t.columns) {
      if(!usedColKeys.has(t.name+'||'+c.name)) {
        const domain = getDomainForTable(t.name);
        unusedColumns.push({name:c.name, table:t.name, tableType:t.type, domain:domain, dataType:c.dataType||''});
      }
    }
  }
  unusedColumns.sort((a,b)=>a.table.localeCompare(b.table)||a.name.localeCompare(b.name));
  const measUsedPct = totalMeasures>0 ? Math.round((totalMeasures-unusedMeasures.length)/totalMeasures*100) : 100;
  const tblUsedPct = totalTables>0 ? Math.round((totalTables-unusedTables.length)/totalTables*100) : 100;
  const colUsedPct = totalColumns>0 ? Math.round((totalColumns-unusedColumns.length)/totalColumns*100) : 100;
  const measByDomain = {};
  for(const m of unusedMeasures) { measByDomain[m.domain]=(measByDomain[m.domain]||0)+1; }
  const tblByType = {};
  for(const t of unusedTables) { tblByType[t.type]=(tblByType[t.type]||0)+1; }
  const colByTable = {};
  for(const c of unusedColumns) { colByTable[c.table]=(colByTable[c.table]||0)+1; }
  const colByTableSorted = Object.entries(colByTable).sort((a,b)=>b[1]-a[1]);
  function covBar(pct, used, total, label) {
    return `<div class="card" style="padding:16px">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">
        <span style="font-size:13px;font-weight:600">${label}</span>
        <span style="font-size:20px;font-weight:700;color:var(--text-primary)">${pct}%</span>
      </div>
      <div style="background:var(--bg-tertiary);border-radius:4px;height:8px;overflow:hidden;margin-bottom:6px">
        <div style="width:${pct}%;height:100%;background:var(--accent);border-radius:4px;transition:width 0.3s"></div>
      </div>
      <div style="font-size:11px;color:var(--text-muted)">${used} used &middot; ${total-used} unused &middot; ${total} total</div>
    </div>`;
  }
  let measTblOpts=[], colTblOpts=[];
  let measHtml='';
  if(unusedMeasures.length>0){
    const domains = Object.keys(measByDomain).sort();
    const domFilterBtns = `<button class="lineage-page-btn active" data-dom="all" onclick="filterHcDomain(this,'all')">All (${unusedMeasures.length})</button>`+domains.map(d=>`<button class="lineage-page-btn" data-dom="${esc(d)}" onclick="filterHcDomain(this,'${esc(d)}')">${esc(d)} (${measByDomain[d]})</button>`).join('');
    const measByTable = {};
    for(const m of unusedMeasures) { measByTable[m.table]=(measByTable[m.table]||0)+1; }
    measTblOpts = Object.entries(measByTable).sort((a,b)=>b[1]-a[1]).map(([t,c])=>({value:t,label:t+' ('+c+')'}));
    measHtml=`<div class="card"><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px"><div class="card-title" style="margin-bottom:0">Unused Measures</div><div style="display:flex;gap:8px;align-items:center"><div id="hc-tbl-drop" class="sdrop"></div><input type="text" placeholder="Search measures..." style="padding:5px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg-secondary);color:var(--text-primary);outline:none;width:180px" oninput="filterGlossary(this.value,'unused-meas-table')" /></div></div><p style="font-size:12px;color:var(--text-muted);margin-bottom:8px">Not used on any report page and not referenced by any other measure.</p><div id="hc-dom-filters" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">${domFilterBtns}</div><table class="column-table" id="unused-meas-table"><thead><tr><th style="width:200px">Measure</th><th>Description</th><th style="width:120px">Domain</th><th style="width:140px">Table</th></tr></thead><tbody>${unusedMeasures.map(m=>`<tr class="glossary-row clickable" data-domain="${esc(m.domain)}" data-table="${esc(m.table)}" onclick="showMeasure('${esc(m.name)}')"><td class="glossary-term">${esc(m.name)}</td><td style="font-size:12px;color:var(--text-secondary)">${esc(m.description)}</td><td style="font-size:11px;color:var(--text-muted)">${esc(m.domain)}</td><td style="font-size:11px;color:var(--text-muted)">${esc(m.table)}</td></tr>`).join('')}</tbody></table></div>`;
  } else {
    measHtml='<div class="card" style="padding:20px;text-align:center"><span style="font-size:20px">&#9989;</span><p style="color:var(--text-muted);margin-top:8px">All measures are used in reports or referenced by other measures.</p></div>';
  }
  let tblHtml='';
  if(unusedTables.length>0){
    const typeBreakdown = Object.entries(tblByType).map(([t,c])=>`<span style="margin-right:12px;font-size:11px">${typeBadge(t)} ${c}</span>`).join('');
    tblHtml=`<div class="card"><div class="card-title">Unused Tables (${unusedTables.length})</div><p style="font-size:12px;color:var(--text-muted);margin-bottom:4px">Not used on any report page and not referenced by any measure.</p><div style="margin-bottom:12px">${typeBreakdown}</div><table class="column-table"><thead><tr><th style="width:220px">Table</th><th style="width:80px">Type</th><th>Description</th><th style="width:70px">Columns</th></tr></thead><tbody>${unusedTables.map(t=>`<tr class="glossary-row clickable" onclick="showTable('${esc(t.name)}')"><td class="glossary-term">${esc(t.name)}</td><td>${typeBadge(t.type)}</td><td style="font-size:12px;color:var(--text-secondary)"></td><td style="text-align:center">${t.columns.length}</td></tr>`).join('')}</tbody></table></div>`;
  } else {
    tblHtml='<div class="card" style="padding:20px;text-align:center"><span style="font-size:20px">&#9989;</span><p style="color:var(--text-muted);margin-top:8px">All tables are used in reports or referenced by measures.</p></div>';
  }
  let colHtml='';
  if(unusedColumns.length>0){
    const colByDomain = {};
    for(const c of unusedColumns) { colByDomain[c.domain]=(colByDomain[c.domain]||0)+1; }
    const colDomains = Object.keys(colByDomain).sort();
    const colDomBtns = `<button class="lineage-page-btn active" data-dom="all" onclick="filterHcColDomain(this,'all')">All (${unusedColumns.length})</button>`+colDomains.map(d=>`<button class="lineage-page-btn" data-dom="${esc(d)}" onclick="filterHcColDomain(this,'${esc(d)}')">${esc(d)} (${colByDomain[d]})</button>`).join('');
    colTblOpts = colByTableSorted.map(([t,c])=>({value:t,label:t+' ('+c+')'}));
    colHtml=`<div class="card"><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px"><div class="card-title" style="margin-bottom:0">Unused Columns</div><div style="display:flex;gap:8px;align-items:center"><div id="hc-col-tbl-drop" class="sdrop"></div><input type="text" placeholder="Search columns..." style="padding:5px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg-secondary);color:var(--text-primary);outline:none;width:180px" oninput="filterGlossary(this.value,'unused-col-table')" /></div></div><p style="font-size:12px;color:var(--text-muted);margin-bottom:8px">Not referenced in any measure's DAX formula and not used in any relationship.</p><div id="hc-col-dom-filters" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">${colDomBtns}</div><table class="column-table" id="unused-col-table"><thead><tr><th style="width:200px">Column</th><th style="width:220px">Table</th><th style="width:80px">Type</th><th>Data Type</th></tr></thead><tbody>${unusedColumns.map(c=>`<tr class="glossary-row clickable" data-domain="${esc(c.domain)}" data-table="${esc(c.table)}" onclick="showTable('${esc(c.table)}')"><td class="glossary-term">${esc(c.name)}</td><td style="font-size:12px">${esc(c.table)}</td><td>${typeBadge(c.tableType)}</td><td style="font-size:11px;color:var(--text-muted)">${esc(c.dataType)}</td></tr>`).join('')}</tbody></table></div>`;
  } else {
    colHtml='<div class="card" style="padding:20px;text-align:center"><span style="font-size:20px">&#9989;</span><p style="color:var(--text-muted);margin-top:8px">All columns are referenced by measures or used in relationships.</p></div>';
  }
  document.getElementById('view-unused').innerHTML=`
    <div class="breadcrumbs"><a onclick="renderHome()">Home</a><span class="separator">/</span><span>Model Health Check</span></div>
    <div class="section-title">Model Health Check</div>
    <div class="section-subtitle">Usage analysis across ${totalMeasures} measures, ${totalTables} tables and ${totalColumns} columns</div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px">
      ${covBar(measUsedPct, totalMeasures-unusedMeasures.length, totalMeasures, 'Measure Coverage')}
      ${covBar(tblUsedPct, totalTables-unusedTables.length, totalTables, 'Table Coverage')}
      ${covBar(colUsedPct, totalColumns-unusedColumns.length, totalColumns, 'Column Coverage')}
    </div>
    <div class="view-toggle" style="margin-bottom:16px">
      <button class="active" onclick="document.getElementById('hc-measures').classList.remove('hidden');document.getElementById('hc-columns').classList.add('hidden');document.getElementById('hc-tables').classList.add('hidden');this.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));this.classList.add('active')">Measures</button>
      <button onclick="document.getElementById('hc-columns').classList.remove('hidden');document.getElementById('hc-measures').classList.add('hidden');document.getElementById('hc-tables').classList.add('hidden');this.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));this.classList.add('active')">Columns</button>
      <button onclick="document.getElementById('hc-tables').classList.remove('hidden');document.getElementById('hc-measures').classList.add('hidden');document.getElementById('hc-columns').classList.add('hidden');this.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));this.classList.add('active')">Tables</button>
    </div>
    <div id="hc-measures">${measHtml}</div>
    <div id="hc-columns" class="hidden">${colHtml}</div>
    <div id="hc-tables" class="hidden">${tblHtml}</div>`;
  showView('unused');
  if(unusedMeasures.length>0) initSearchDrop('hc-tbl-drop', measTblOpts, filterHcTable);
  if(unusedColumns.length>0) initSearchDrop('hc-col-tbl-drop', colTblOpts, filterHcColTable);
}

function getDomainForTable(tableName) {
  for(const[d,rn]of Object.entries(BUNDLE.domainMap)){
    const reps=BUNDLE.reports.filter(r=>rn.includes(r.name));
    for(const r of reps) for(const p of (r.pages||[])) {
      if((p.tables||[]).includes(tableName)||(p.measures||[]).some(m=>{const f=findMeasure(m);return f&&f.table===tableName})) return d;
    }
  }
  return 'Uncategorized';
}

// Sidebar
function renderSidebar(){
  let h='';
  h+='<div style="padding:6px 8px;font-size:11px;font-weight:600;text-transform:uppercase;color:var(--text-muted);letter-spacing:0.5px">Domains</div>';
  for(const[domain,repNames]of Object.entries(BUNDLE.domainMap)){
    const reps=BUNDLE.reports.filter(r=>repNames.includes(r.name));
    const domMeas=new Set(reps.flatMap(r=>(r.pages||[]).flatMap(p=>p.measures||[]))).size;
    h+=`<div class="tree-group" data-sb-domain="${esc(domain)}"><div class="tree-group-header" onclick="toggleGroup(this);showDomain('${esc(domain)}')"><span class="chevron">&#9654;</span><span>${esc(domain)}</span><span class="count">${reps.length} reports, ${domMeas} measures</span></div><div class="tree-children" style="display:none">${reps.map(r=>{const short=r.name.replace(domain+' - ','');return`<div class="tree-item" data-sb-report="${esc(r.name)}" onclick="event.stopPropagation();showReport('${esc(r.name)}')" title="${esc(r.name)}"><span class="search-type-badge" data-type="report" style="font-size:9px;padding:1px 4px">R</span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(short)}</span></div>`}).join('')}</div></div>`;
  }
  const measureTables=BUNDLE.model.tables.filter(t=>t.measures.length>0).sort((a,b)=>{if(a.type==='measure'&&b.type!=='measure')return -1;if(a.type!=='measure'&&b.type==='measure')return 1;return b.measures.length-a.measures.length});
  const totalM=measureTables.reduce((s,t)=>s+t.measures.length,0);
  h+='<div style="margin-top:16px;padding:6px 8px;font-size:11px;font-weight:600;text-transform:uppercase;color:var(--text-muted);letter-spacing:0.5px">Measures ('+totalM+')</div>';
  for(const t of measureTables){const ms=t.measures.map(m=>m.name).sort();h+=`<div class="tree-group" data-sb-tgroup="${esc(t.name)}"><div class="tree-group-header" onclick="toggleGroup(this);event.stopPropagation();showTable('${esc(t.name)}')"><span class="chevron">&#9654;</span>${typeBadge(t.type)}<span style="font-weight:500;font-size:12px">${esc(t.name)}</span><span class="count">${ms.length}</span></div><div class="tree-children" style="display:none">${ms.map(m=>`<div class="tree-item" data-sb-measure="${esc(m)}" onclick="event.stopPropagation();showMeasure('${esc(m)}')" title="${esc(m)}"><span class="search-type-badge" data-type="measure" style="font-size:9px;padding:1px 4px">M</span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(m)}</span></div>`).join('')}</div></div>`}
  h+='<div style="margin-top:16px;padding:6px 8px;font-size:11px;font-weight:600;text-transform:uppercase;color:var(--text-muted);letter-spacing:0.5px">Tables</div>';
  for(const type of['fact','dimension','parameter','other']){const ts=BUNDLE.model.tables.filter(t=>t.type===type).sort((a,b)=>a.name.localeCompare(b.name));if(!ts.length)continue;const l=type.charAt(0).toUpperCase()+type.slice(1);h+=`<div class="tree-group" data-sb-tgroup="${type}"><div class="tree-group-header" onclick="toggleGroup(this)"><span class="chevron">&#9654;</span>${typeBadge(type)}<span>${l}</span><span class="count">${ts.length}</span></div><div class="tree-children" style="display:none">${ts.map(t=>`<div class="tree-item" data-sb-table="${esc(t.name)}" onclick="event.stopPropagation();showTable('${esc(t.name)}')">${esc(t.name)}</div>`).join('')}</div></div>`}
  h+='<div style="margin-top:16px;padding:6px 8px;font-size:11px;font-weight:600;text-transform:uppercase;color:var(--text-muted);letter-spacing:0.5px">Health Check</div>';
  h+='<div class="tree-item" onclick="showUnused()" style="cursor:pointer;padding:6px 12px;display:flex;align-items:center;gap:8px"><span style="display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:4px;background:var(--bg-tertiary);font-size:10px">&#128269;</span><span style="font-size:12px">Model Health Check</span></div>';
  document.getElementById('sidebar-content').innerHTML=h;
}

// Sidebar filter
document.getElementById('sidebar-search').addEventListener('input',function(){
  const q=this.value.toLowerCase().trim();
  const panel=document.getElementById('sidebar-content');
  if(!q){panel.querySelectorAll('.tree-group,.tree-item').forEach(el=>el.style.display='');return}
  panel.querySelectorAll('[data-sb-measure]').forEach(el=>{el.style.display=el.dataset.sbMeasure.toLowerCase().includes(q)?'':'none'});
  panel.querySelectorAll('[data-sb-table]').forEach(el=>{el.style.display=el.dataset.sbTable.toLowerCase().includes(q)?'':'none'});
  panel.querySelectorAll('[data-sb-report]').forEach(el=>{const nameMatch=el.dataset.sbReport.toLowerCase().includes(q);el.style.display=nameMatch?'':'none'});
  panel.querySelectorAll('[data-sb-domain]').forEach(el=>{const hasVisible=el.querySelector('[data-sb-report]:not([style*="display: none"])');el.style.display=hasVisible?'':'none';if(hasVisible){el.querySelector('.tree-children').style.display=''}});
  panel.querySelectorAll('[data-sb-tgroup]').forEach(el=>{const hasVisible=el.querySelector('[data-sb-table]:not([style*="display: none"])');const hasMeasVis=el.querySelector('[data-sb-measure]:not([style*="display: none"])');el.style.display=(hasVisible||hasMeasVis)?'':'none';if(hasVisible||hasMeasVis){el.querySelector('.tree-children').style.display=''}});
});

// Theme, search
document.getElementById('btn-theme-toggle').addEventListener('click',()=>{const c=document.documentElement.getAttribute('data-theme'),n=c==='dark'?'light':'dark';document.documentElement.setAttribute('data-theme',n);document.getElementById('theme-icon').textContent=n==='dark'?'\u2600':'\u263E'});
const si=[];for(const t of BUNDLE.model.tables){for(const m of t.measures)si.push({type:'measure',name:m.name,meta:t.name,action:()=>showMeasure(m.name)});for(const c of t.columns)si.push({type:'column',name:c.name,meta:t.name,action:()=>showTable(t.name)});si.push({type:'table',name:t.name,meta:t.type,action:()=>showTable(t.name)})}
for(const r of BUNDLE.reports)si.push({type:'report',name:r.name,meta:r.domain,action:()=>showReport(r.name)});
const sI=document.getElementById('global-search'),sR=document.getElementById('search-results');
sI.addEventListener('input',()=>{const q=sI.value.toLowerCase();if(q.length<2){sR.classList.add('hidden');return}const h=si.filter(i=>i.name.toLowerCase().includes(q)).slice(0,15);if(!h.length){sR.classList.add('hidden');return}sR.innerHTML=h.map((x,i)=>`<div class="search-result-item" data-idx="${i}"><span class="search-type-badge" data-type="${x.type}">${x.type.charAt(0).toUpperCase()+x.type.slice(1)}</span><span>${esc(x.name)}</span><span style="margin-left:auto;font-size:11px;color:var(--text-muted)">${esc(x.meta)}</span></div>`).join('');sR.classList.remove('hidden');sR.querySelectorAll('.search-result-item').forEach(el=>{el.addEventListener('click',()=>{h[+el.dataset.idx].action();sR.classList.add('hidden');sI.value=''})})});
document.addEventListener('click',e=>{if(!sI.contains(e.target)&&!sR.contains(e.target))sR.classList.add('hidden')});
document.addEventListener('keydown',e=>{if(e.key==='/'&&!['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)){e.preventDefault();sI.focus()}});

// --- Lineage ---
function parseDaxDeps(expr) {
  if (!expr) return { measures: [], columns: [] };
  const measures = [], columns = [], seen = new Set();
  const mRe = /(?<!')\[([^\]]+)\]/g; let m;
  while ((m = mRe.exec(expr)) !== null) { const n = m[1]; if (!seen.has('m:'+n)) { seen.add('m:'+n); measures.push(n); } }
  const cRe = /'([^']+)'\[([^\]]+)\]/g;
  while ((m = cRe.exec(expr)) !== null) { const k = m[1]+'['+m[2]+']'; if (!seen.has('c:'+k)) { seen.add('c:'+k); columns.push({ table: m[1], column: m[2] }); } }
  const colNames = new Set(columns.map(c => c.column));
  const pureMeasures = measures.filter(mm => !colNames.has(mm));
  return { measures: pureMeasures, columns };
}

function showLineage(reportName, pageName, fromHash) {
  if(!fromHash) setHash('lineage', reportName + (pageName ? '\\' + pageName : ''));
  const r = BUNDLE.reports.find(x => x.name === reportName);
  if (!r) return;
  const pages = r.pages || [];
  const page = pageName ? pages.find(p => p.name === pageName) : pages[0];
  if (!page) return;
  let pageBtns = pages.map(p =>
    `<button class="lineage-page-btn${p.name===page.name?' active':''}" onclick="showLineage('${esc(reportName)}','${esc(p.name)}')">${esc(p.name)}</button>`
  ).join('');
  const pageMeasures = [...new Set(page.measures || [])].sort();
  let pickerHtml = pageMeasures.map((mn, i) =>
    `<div class="lin-pick-item${i===0?' active':''}" data-measure="${esc(mn)}" onclick="selectLineageMeasure(this,'${esc(mn)}')"><span class="lin-pick-dot"></span><span>${esc(mn)}</span></div>`
  ).join('');
  if (!pickerHtml) pickerHtml = '<div class="lin-empty">No measures on this page</div>';
  const firstTree = pageMeasures.length > 0 ? buildMeasureTree(pageMeasures[0]) : '<div class="lin-empty">Select a measure to explore its dependencies</div>';
  const domainCrumb = r.domain && r.domain !== 'Default' ? `<a onclick="showDomain('${esc(r.domain)}')">${esc(r.domain)}</a><span class="separator">/</span>` : '';
  document.getElementById('view-lineage').innerHTML = `
    <div class="breadcrumbs"><a onclick="renderHome()">Home</a><span class="separator">/</span>${domainCrumb}<a onclick="showReport('${esc(reportName)}')">${esc(reportName)}</a><span class="separator">/</span><span>Lineage</span></div>
    <div class="section-title">Lineage: ${esc(page.name)}</div>
    <div class="section-subtitle">Select a measure to see what it depends on.</div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:20px"><div style="font-size:11px;font-weight:600;text-transform:uppercase;color:var(--text-muted);padding:8px 0;margin-right:4px">Report Pages</div>${pageBtns}</div>
    <div class="lin-grid"><div class="lin-pick"><div class="lin-pick-title">Measures (${pageMeasures.length})</div>${pickerHtml}</div><div class="lin-tree" id="lin-tree-content">${firstTree}</div></div>`;
  showView('lineage');
}

function selectLineageMeasure(el, name) {
  el.parentElement.querySelectorAll('.lin-pick-item').forEach(e => e.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('lin-tree-content').innerHTML = buildMeasureTree(name);
}

function buildMeasureTree(name, depth) {
  depth = depth || 0;
  if (depth > 3) return '<div class="lin-no-deps">Max depth reached</div>';
  const f = findMeasure(name);
  if (!f) return `<div class="lin-root"><div class="lin-root-header"><span class="lin-root-dot"></span>${esc(name)}<span class="lin-root-table">Not found in model</span></div></div>`;
  const { measure, table: tbl } = f;
  const deps = parseDaxDeps(measure.expression);
  const hasDeps = deps.measures.length > 0 || deps.columns.length > 0;
  let depsHtml = '';
  if (deps.measures.length > 0) {
    depsHtml += `<div class="lin-dep-group-label">Sub-Measures (${deps.measures.length})</div>`;
    for (const sm of deps.measures) {
      const smFound = findMeasure(sm);
      const smDeps = smFound ? parseDaxDeps(smFound.measure.expression) : { measures: [], columns: [] };
      const smTotal = smDeps.measures.length + smDeps.columns.length;
      depsHtml += `<div class="lin-dep submeasure" onclick="showMeasure('${esc(sm)}')"><span class="lin-dep-dot"></span><span class="lin-dep-name">${esc(sm)}</span><span class="lin-dep-type">${smFound ? smTotal + ' deps' : 'not in model'}</span></div>`;
      if (smFound && smTotal > 0 && depth < 2) {
        depsHtml += '<div style="padding-left:20px;border-left:1.5px dashed var(--border);margin-left:16px;margin-bottom:4px">';
        for (const ssm of smDeps.measures.slice(0, 5)) {
          depsHtml += `<div class="lin-dep submeasure" style="padding:5px 10px;font-size:11px;margin-bottom:2px" onclick="showMeasure('${esc(ssm)}')"><span class="lin-dep-dot"></span><span class="lin-dep-name">${esc(ssm)}</span><span class="lin-dep-type">Sub-Measure</span></div>`;
        }
        for (const sc of smDeps.columns.slice(0, 5)) {
          depsHtml += `<div class="lin-dep column" style="padding:5px 10px;font-size:11px;margin-bottom:2px" onclick="showTable('${esc(sc.table)}')"><span class="lin-dep-dot"></span><span class="lin-dep-name">${esc(sc.table)}[${esc(sc.column)}]</span><span class="lin-dep-type">Column</span></div>`;
        }
        if (smDeps.measures.length + smDeps.columns.length > 10) depsHtml += '<div style="font-size:10px;color:var(--text-muted);padding:2px 10px">+ more...</div>';
        depsHtml += '</div>';
      }
    }
  }
  if (deps.columns.length > 0) {
    depsHtml += `<div class="lin-dep-group-label">Columns (${deps.columns.length})</div>`;
    for (const c of deps.columns) {
      depsHtml += `<div class="lin-dep column" onclick="showTable('${esc(c.table)}')"><span class="lin-dep-dot"></span><span class="lin-dep-name">${esc(c.table)}[${esc(c.column)}]</span><span class="lin-dep-type">Table & Column</span></div>`;
    }
  }
  if (!hasDeps) depsHtml = '<div class="lin-no-deps">No dependencies — this is a leaf measure or uses only constants.</div>';
  return `<div class="lin-root"><div class="lin-root-header" style="cursor:pointer" onclick="showMeasure('${esc(name)}')"><span class="lin-root-dot"></span>${esc(name)}<span class="lin-root-table">${esc(tbl)}</span></div><div class="lin-deps">${depsHtml}</div></div>`;
}

renderSidebar();
if(location.hash && location.hash !== '#/') { handleHash(); } else { renderHome(); }
"""

HTML_BODY = """
  <header id="toolbar">
    <div class="toolbar-left" onclick="renderHome()" style="cursor:pointer" title="Home">
      <svg width="28" height="28" viewBox="0 0 28 28" fill="none"><rect width="28" height="28" rx="4" fill="#3B82F6"/><text x="14" y="19" text-anchor="middle" font-size="14" font-weight="700" fill="#fff">S</text></svg>
      <span class="app-title">Semantic Model Explorer</span>
    </div>
    <div class="toolbar-center">
      <div style="position:relative">
        <input type="text" id="global-search" placeholder="Search measures, tables, reports...  ( / )" autocomplete="off" />
        <div id="search-results" class="search-results hidden"></div>
      </div>
    </div>
    <div class="toolbar-right">
      <button id="btn-theme-toggle" class="btn-icon" title="Toggle theme"><span id="theme-icon">&#9790;</span></button>
    </div>
  </header>
  <div class="app-layout">
    <aside class="sidebar">
      <div style="padding:8px;border-bottom:1px solid var(--border);flex-shrink:0"><input type="text" id="sidebar-search" placeholder="Filter sidebar..." style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-primary);color:var(--text-primary);font-size:12px;outline:none" /></div>
      <div class="tab-panel" id="sidebar-content"></div>
    </aside>
    <main class="main-content">
      <div id="view-home" class="view"></div>
      <div id="view-domain" class="view hidden"></div>
      <div id="view-report" class="view hidden"></div>
      <div id="view-measure" class="view hidden"></div>
      <div id="view-table" class="view hidden"></div>
      <div id="view-lineage" class="view hidden"></div>
      <div id="view-table-lineage" class="view hidden"></div>
      <div id="view-unused" class="view hidden"></div>
    </main>
  </div>
"""

def generate_html(data):
    bundle_js = json.dumps(data, ensure_ascii=True)
    return f'''<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Semantic Model Explorer</title>
<style>{CSS}</style>
</head>
<body>
{HTML_BODY}
<script>
const RAW_DATA = {bundle_js};
{JS_APP}
</script>
</body>
</html>'''

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Generate a self-contained HTML explorer from a Power BI PBIP project.'
    )
    parser.add_argument('project_path', help='Path to the PBIP project folder')
    parser.add_argument('-o', '--output', default='explorer.html', help='Output HTML file (default: explorer.html)')
    parser.add_argument('-n', '--name', default=None, help='Model name (default: derived from folder name)')
    args = parser.parse_args()

    project_path = os.path.abspath(args.project_path)
    if not os.path.isdir(project_path):
        print(f"Error: '{project_path}' is not a directory.")
        sys.exit(1)

    print(f"Scanning: {project_path}")

    # Find project structure
    model_dir, report_dirs = find_pbip_project(project_path)

    if not model_dir:
        print("Error: No .SemanticModel folder or .tmdl files found.")
        sys.exit(1)

    print(f"  Model: {model_dir}")
    for rd in report_dirs:
        print(f"  Report: {rd}")

    # Parse model
    tables = parse_model(model_dir)
    print(f"  Parsed {len(tables)} tables, {sum(len(t['measures']) for t in tables)} measures, {sum(len(t['columns']) for t in tables)} columns")

    # Parse reports
    reports = parse_reports(report_dirs)
    print(f"  Parsed {len(reports)} reports with {sum(len(r['pages']) for r in reports)} pages")

    # Detect domains
    domains = detect_domains(reports)
    print(f"  Detected {len(domains)} domains")

    # Model name
    model_name = args.name
    if not model_name:
        model_name = os.path.basename(project_path)
        if model_name.endswith('.SemanticModel'):
            model_name = model_name[:-14]

    # Build data bundle
    data = {
        'modelName': model_name,
        'tables': [
            {
                'name': t['name'],
                'type': t['type'],
                'columns': [{'name': c['name'], 'dataType': c.get('dataType', '')} for c in t['columns']],
                'measures': [{'name': m['name'], 'expression': m.get('expression', '')} for m in t['measures']]
            }
            for t in tables
        ],
        'reports': [
            {
                'name': r['name'],
                'domain': r.get('domain', 'Default'),
                'pages': r['pages']
            }
            for r in reports
        ],
        'domains': domains
    }

    # Generate HTML
    html = generate_html(data)

    output_path = os.path.abspath(args.output)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"\nGenerated: {output_path} ({len(html):,} bytes / {len(html)/1024:.0f} KB)")
    print("Open it in your browser — no server needed.")

if __name__ == '__main__':
    main()
