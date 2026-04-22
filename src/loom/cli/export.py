from __future__ import annotations

import json
import webbrowser
from pathlib import Path

import typer
from rich.console import Console

from loom.cli._app import app
from loom.core.graph import LoomGraph

console = Console()

# ── colour palette per node kind ─────────────────────────────────────────────
_KIND_COLOURS: dict[str, str] = {
    "function": "#4f8ef7",
    "method": "#7c5cbf",
    "class": "#f0a500",
    "module": "#3aafa9",
    "interface": "#e07b54",
    "enum": "#c75d9d",
    "type": "#9ab87a",
    "file": "#8da9b4",
    "community": "#d4d4d4",
}
_DEFAULT_COLOUR = "#aaaaaa"

# ── edge colours ──────────────────────────────────────────────────────────────
_EDGE_COLOURS: dict[str, str] = {
    "calls": "#e74c3c",
    "imports": "#3498db",
    "extends": "#2ecc71",
    "child_of": "#f39c12",
    "contains": "#95a5a6",
    "coupled_with": "#9b59b6",
    "member_of": "#1abc9c",
}
_DEFAULT_EDGE_COLOUR = "#888888"


def _build_graph_data(g: LoomGraph) -> dict:
    conn = g._connect()
    node_rows = conn.execute("SELECT id, kind, name, path, language, is_dead_code FROM nodes").fetchall()
    edge_rows = conn.execute("SELECT from_id, to_id, kind FROM edges").fetchall()

    nodes = []
    for r in node_rows:
        colour = _KIND_COLOURS.get(r["kind"], _DEFAULT_COLOUR)
        label = r["name"]
        nodes.append({
            "data": {
                "id": r["id"],
                "label": label,
                "kind": r["kind"],
                "path": r["path"],
                "language": r["language"] or "",
                "is_dead_code": bool(r["is_dead_code"]),
                "colour": colour,
            }
        })

    edges = []
    seen: set[tuple[str, str, str]] = set()
    for r in edge_rows:
        key = (r["from_id"], r["to_id"], r["kind"])
        if key in seen:
            continue
        seen.add(key)
        colour = _EDGE_COLOURS.get(r["kind"], _DEFAULT_EDGE_COLOUR)
        edges.append({
            "data": {
                "id": f"{r['from_id']}__{r['to_id']}__{r['kind']}",
                "source": r["from_id"],
                "target": r["to_id"],
                "kind": r["kind"],
                "colour": colour,
            }
        })

    kinds = sorted({r["kind"] for r in node_rows})
    edge_kinds = sorted({r["kind"] for r in edge_rows})
    return {"nodes": nodes, "edges": edges, "kinds": kinds, "edge_kinds": edge_kinds}


def _render_html(data: dict, db_path: Path) -> str:
    graph_json = json.dumps(data, separators=(",", ":"))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Loom — {db_path.name}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0f1117; color: #e0e0e0; display: flex; height: 100vh; overflow: hidden; }}

  /* ── sidebar ── */
  #sidebar {{
    width: 280px; min-width: 240px; max-width: 400px;
    background: #181c24; border-right: 1px solid #2a2e3a;
    display: flex; flex-direction: column; overflow: hidden;
    resize: horizontal;
  }}
  #sidebar h1 {{ font-size: 14px; font-weight: 700; padding: 14px 16px;
                 border-bottom: 1px solid #2a2e3a; color: #fff; letter-spacing: .5px; }}
  #sidebar h1 span {{ color: #4f8ef7; }}
  .section-title {{ font-size: 11px; font-weight: 600; color: #888; text-transform: uppercase;
                    letter-spacing: .8px; padding: 12px 16px 6px; }}

  /* filters */
  #filters {{ padding: 0 16px 8px; display: flex; flex-direction: column; gap: 4px; }}
  .filter-row {{ display: flex; align-items: center; gap: 8px; cursor: pointer;
                 font-size: 12px; padding: 3px 0; }}
  .filter-row input {{ cursor: pointer; accent-color: #4f8ef7; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}

  /* search */
  #search-wrap {{ padding: 8px 16px; }}
  #search {{ width: 100%; background: #0f1117; border: 1px solid #2a2e3a; border-radius: 6px;
             color: #e0e0e0; padding: 6px 10px; font-size: 12px; outline: none; }}
  #search:focus {{ border-color: #4f8ef7; }}
  #match-count {{ font-size: 11px; color: #666; padding: 2px 16px 6px; }}

  /* detail panel */
  #detail {{
    flex: 1; overflow-y: auto; padding: 12px 16px;
    border-top: 1px solid #2a2e3a; font-size: 12px;
  }}
  #detail h2 {{ font-size: 13px; font-weight: 600; margin-bottom: 8px; color: #fff; word-break: break-all; }}
  .prop {{ display: grid; grid-template-columns: 80px 1fr; gap: 4px; margin-bottom: 4px; }}
  .prop-key {{ color: #888; font-size: 11px; padding-top: 1px; }}
  .prop-val {{ color: #d0d0d0; word-break: break-all; }}
  .badge {{ display: inline-block; background: #2a2e3a; border-radius: 4px;
            padding: 1px 7px; font-size: 10px; margin-bottom: 8px; }}
  #callers-list, #callees-list {{ list-style: none; margin-top: 4px; }}
  #callers-list li, #callees-list li {{
    font-size: 11px; color: #aaa; padding: 3px 0;
    cursor: pointer; border-bottom: 1px solid #1e2230;
  }}
  #callers-list li:hover, #callees-list li:hover {{ color: #4f8ef7; }}
  .empty {{ color: #555; font-style: italic; }}

  /* stats bar */
  #statsbar {{ padding: 8px 16px; border-top: 1px solid #2a2e3a;
               font-size: 11px; color: #666; line-height: 1.8; }}

  /* layout controls */
  #controls {{ padding: 8px 16px; border-top: 1px solid #2a2e3a; display: flex; gap: 6px; flex-wrap: wrap; }}
  button {{
    background: #252a36; border: 1px solid #2a2e3a; border-radius: 5px;
    color: #ccc; font-size: 11px; padding: 4px 10px; cursor: pointer;
  }}
  button:hover {{ background: #2f3548; color: #fff; }}
  button.active {{ background: #4f8ef7; border-color: #4f8ef7; color: #fff; }}

  /* main graph area */
  #cy {{ flex: 1; background: #0f1117; }}

  /* tooltip */
  #tooltip {{
    position: fixed; background: #1e2230; border: 1px solid #2a2e3a;
    border-radius: 6px; padding: 6px 10px; font-size: 11px; color: #ccc;
    pointer-events: none; display: none; z-index: 999; max-width: 260px;
    line-height: 1.5;
  }}
  .dead {{ opacity: 0.35; }}
</style>
</head>
<body>
<div id="sidebar">
  <h1>🧵 <span>Loom</span> Graph</h1>

  <div class="section-title">Node Kinds</div>
  <div id="filters"></div>

  <div id="search-wrap">
    <input id="search" type="text" placeholder="Search by name…">
  </div>
  <div id="match-count"></div>

  <div id="detail">
    <p class="empty">Click a node to inspect it.</p>
  </div>

  <div id="statsbar"></div>
  <div id="controls">
    <button id="btn-fit">Fit</button>
    <button id="btn-cose" class="active">CoSE</button>
    <button id="btn-dagre">Dagre</button>
    <button id="btn-dead">Dead code</button>
    <button id="btn-calls-only">Calls only</button>
  </div>
</div>

<div id="cy"></div>
<div id="tooltip"></div>

<script>
const RAW = {graph_json};

// ── build cytoscape elements ──────────────────────────────────────────────────
function buildElements(activeKinds, activeEdgeKinds) {{
  const nodeSet = new Set(
    RAW.nodes.filter(n => activeKinds.has(n.data.kind)).map(n => n.data.id)
  );
  const nodes = RAW.nodes.filter(n => nodeSet.has(n.data.id));
  const edges = RAW.edges.filter(
    e => nodeSet.has(e.data.source) && nodeSet.has(e.data.target)
         && activeEdgeKinds.has(e.data.kind)
  );
  return [...nodes, ...edges];
}}

// ── state ─────────────────────────────────────────────────────────────────────
const activeKinds = new Set(RAW.kinds);
const activeEdgeKinds = new Set(RAW.edge_kinds);

// ── init cytoscape ────────────────────────────────────────────────────────────
let cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: buildElements(activeKinds, activeEdgeKinds),
  style: [
    {{
      selector: 'node',
      style: {{
        'background-color': 'data(colour)',
        'label': 'data(label)',
        'color': '#ffffff',
        'font-size': '9px',
        'text-valign': 'bottom',
        'text-margin-y': '4px',
        'text-outline-color': '#0f1117',
        'text-outline-width': '1px',
        'width': 18,
        'height': 18,
        'border-width': 0,
      }}
    }},
    {{
      selector: 'node.highlighted',
      style: {{
        'border-width': 3,
        'border-color': '#fff',
        'width': 26,
        'height': 26,
        'z-index': 10,
      }}
    }},
    {{
      selector: 'node.dimmed',
      style: {{ 'opacity': 0.15 }}
    }},
    {{
      selector: 'node[?is_dead_code]',
      style: {{ 'border-width': 2, 'border-color': '#e74c3c', 'border-style': 'dashed' }}
    }},
    {{
      selector: 'edge',
      style: {{
        'line-color': 'data(colour)',
        'target-arrow-color': 'data(colour)',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'width': 1,
        'opacity': 0.5,
        'arrow-scale': 0.7,
      }}
    }},
    {{
      selector: 'edge.highlighted',
      style: {{ 'opacity': 1, 'width': 2, 'z-index': 5 }}
    }},
    {{
      selector: 'edge.dimmed',
      style: {{ 'opacity': 0.04 }}
    }},
  ],
  layout: {{ name: 'cose', animate: false, randomize: false, nodeRepulsion: 8000, idealEdgeLength: 80 }},
  wheelSensitivity: 0.3,
}});

// ── filters UI ────────────────────────────────────────────────────────────────
const filtersEl = document.getElementById('filters');
RAW.kinds.forEach(kind => {{
  const nodeColour = RAW.nodes.find(n => n.data.kind === kind)?.data.colour || '#aaa';
  const row = document.createElement('label');
  row.className = 'filter-row';
  row.innerHTML = `
    <input type="checkbox" checked data-kind="${{kind}}">
    <span class="dot" style="background:${{nodeColour}}"></span>
    ${{kind}}
  `;
  row.querySelector('input').addEventListener('change', rebuildGraph);
  filtersEl.appendChild(row);
}});

function rebuildGraph() {{
  activeKinds.clear();
  document.querySelectorAll('#filters input:checked').forEach(cb => {{
    activeKinds.add(cb.dataset.kind);
  }});
  cy.elements().remove();
  cy.add(buildElements(activeKinds, activeEdgeKinds));
  runLayout(currentLayout);
  updateStats();
}}

// ── stats bar ─────────────────────────────────────────────────────────────────
function updateStats() {{
  const statsEl = document.getElementById('statsbar');
  statsEl.innerHTML = `Nodes: ${{cy.nodes().length}} &nbsp;|&nbsp; Edges: ${{cy.edges().length}}`;
}}
updateStats();

// ── search ────────────────────────────────────────────────────────────────────
const searchEl = document.getElementById('search');
const matchCountEl = document.getElementById('match-count');

searchEl.addEventListener('input', () => {{
  const q = searchEl.value.trim().toLowerCase();
  cy.nodes().removeClass('highlighted dimmed');
  cy.edges().removeClass('highlighted dimmed');
  if (!q) {{ matchCountEl.textContent = ''; return; }}
  const matched = cy.nodes().filter(n => n.data('label').toLowerCase().includes(q));
  const unmatched = cy.nodes().not(matched);
  matched.addClass('highlighted');
  unmatched.addClass('dimmed');
  cy.edges().addClass('dimmed');
  matched.connectedEdges().addClass('highlighted').removeClass('dimmed');
  matchCountEl.textContent = `${{matched.length}} match${{matched.length !== 1 ? 'es' : ''}}`;
}});

// ── node click — detail panel ─────────────────────────────────────────────────
const detailEl = document.getElementById('detail');

cy.on('tap', 'node', evt => {{
  const n = evt.target;
  const d = n.data();

  // highlight neighbourhood
  cy.nodes().removeClass('highlighted dimmed');
  cy.edges().removeClass('highlighted dimmed');
  const hood = n.closedNeighborhood();
  cy.elements().not(hood).addClass('dimmed');
  hood.addClass('highlighted');
  hood.edges().removeClass('dimmed').addClass('highlighted');
  n.removeClass('dimmed');

  // callers / callees
  const callerNodes = n.incomers('node[kind="calls"], edge[kind="calls"]').sources();
  const calleeNodes = n.outgoers('node[kind="calls"], edge[kind="calls"]').targets();

  const callerItems = callerNodes.map(c =>
    `<li onclick="focusNode('${{c.id()}}')">${{c.data('label')}} <span style="color:#555">(${{c.data('path')}})</span></li>`
  ).join('') || '<li class="empty">none</li>';

  const calleeItems = calleeNodes.map(c =>
    `<li onclick="focusNode('${{c.id()}}')">${{c.data('label')}} <span style="color:#555">(${{c.data('path')}})</span></li>`
  ).join('') || '<li class="empty">none</li>';

  detailEl.innerHTML = `
    <h2>${{d.label}}</h2>
    <span class="badge" style="background:${{d.colour}};color:#fff">${{d.kind}}</span>
    ${{d.is_dead_code ? '<span class="badge" style="background:#e74c3c;color:#fff">dead code</span>' : ''}}
    <div class="prop"><span class="prop-key">Path</span><span class="prop-val">${{d.path}}</span></div>
    ${{d.language ? `<div class="prop"><span class="prop-key">Language</span><span class="prop-val">${{d.language}}</span></div>` : ''}}
    <div class="prop"><span class="prop-key">ID</span><span class="prop-val" style="font-size:10px;color:#666">${{d.id}}</span></div>
    <div class="section-title" style="padding:10px 0 4px">Callers (${{callerNodes.length}})</div>
    <ul id="callers-list">${{callerItems}}</ul>
    <div class="section-title" style="padding:10px 0 4px">Callees (${{calleeNodes.length}})</div>
    <ul id="callees-list">${{calleeItems}}</ul>
  `;
}});

cy.on('tap', evt => {{
  if (evt.target === cy) {{
    cy.nodes().removeClass('highlighted dimmed');
    cy.edges().removeClass('highlighted dimmed');
    detailEl.innerHTML = '<p class="empty">Click a node to inspect it.</p>';
  }}
}});

function focusNode(id) {{
  const n = cy.getElementById(id);
  if (!n.length) return;
  cy.animate({{ center: {{ eles: n }}, zoom: cy.zoom() }}, {{ duration: 300 }});
  n.trigger('tap');
}}

// ── tooltip on hover ──────────────────────────────────────────────────────────
const tooltip = document.getElementById('tooltip');
cy.on('mouseover', 'node', evt => {{
  const d = evt.target.data();
  tooltip.innerHTML = `<strong>${{d.label}}</strong><br>${{d.kind}} &nbsp;·&nbsp; ${{d.path}}`;
  tooltip.style.display = 'block';
}});
cy.on('mouseout', 'node', () => {{ tooltip.style.display = 'none'; }});
document.addEventListener('mousemove', e => {{
  tooltip.style.left = (e.clientX + 14) + 'px';
  tooltip.style.top = (e.clientY + 10) + 'px';
}});

// ── layout switching ──────────────────────────────────────────────────────────
let currentLayout = 'cose';

function runLayout(name) {{
  currentLayout = name;
  const opts = {{
    cose:  {{ name: 'cose', animate: false, nodeRepulsion: 8000, idealEdgeLength: 80 }},
    dagre: {{ name: 'dagre', animate: false, rankDir: 'LR', nodeSep: 30, rankSep: 80 }},
  }}[name] || {{ name }};
  cy.layout(opts).run();
}}

document.getElementById('btn-fit').addEventListener('click', () => cy.fit(undefined, 40));
document.getElementById('btn-cose').addEventListener('click', () => {{
  document.querySelectorAll('#controls button').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-cose').classList.add('active');
  runLayout('cose');
}});
document.getElementById('btn-dagre').addEventListener('click', () => {{
  // try dagre, fall back to breadthfirst if not available
  document.querySelectorAll('#controls button').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-dagre').classList.add('active');
  try {{ runLayout('dagre'); }} catch {{ runLayout('breadthfirst'); }}
}});

// toggle dead-code nodes
let showDead = true;
document.getElementById('btn-dead').addEventListener('click', e => {{
  showDead = !showDead;
  e.target.classList.toggle('active', !showDead);
  cy.nodes().filter(n => n.data('is_dead_code')).style('display', showDead ? 'element' : 'none');
}});

// toggle calls-only edges
let callsOnly = false;
document.getElementById('btn-calls-only').addEventListener('click', e => {{
  callsOnly = !callsOnly;
  e.target.classList.toggle('active', callsOnly);
  if (callsOnly) {{
    activeEdgeKinds.clear(); activeEdgeKinds.add('calls');
  }} else {{
    RAW.edge_kinds.forEach(k => activeEdgeKinds.add(k));
  }}
  rebuildGraph();
}});
</script>
</body>
</html>"""


@app.command(name="export")
def export_graph(
    output: Path = typer.Argument(Path("loom-graph.html"), help="Output HTML file path"),
    db: Path | None = typer.Option(None, "--db", help="Path to loom.db"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open in browser after export"),
) -> None:
    """Export the code graph as a self-contained interactive HTML file."""
    g = LoomGraph(db_path=db)
    data = _build_graph_data(g)
    html = _render_html(data, g.db_path)
    output.write_text(html, encoding="utf-8")
    console.print(
        f"[green]✓[/green] Exported {len(data['nodes'])} nodes, "
        f"{len(data['edges'])} edges → [bold]{output}[/bold]"
    )
    if open_browser:
        webbrowser.open(output.resolve().as_uri())
