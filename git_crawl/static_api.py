from __future__ import annotations

import html
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CRAWLER_OUTPUT_FILES: tuple[str, ...] = (
    "crawl_runs.jsonl",
    "repositories.jsonl",
    "excluded_repositories.jsonl",
    "commits.jsonl",
    "file_changes.jsonl",
    "org_days.jsonl",
    "repo_days.jsonl",
    "contributor_days.jsonl",
    "repo_failures.jsonl",
    "summary.json",
    "summary.md",
    "output_manifest.json",
    "crawl_runs.csv",
    "repositories.csv",
    "excluded_repositories.csv",
    "commits.csv",
    "file_changes.csv",
    "org_days.csv",
    "repo_days.csv",
    "contributor_days.csv",
    "repo_failures.csv",
)

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class StaticApiPublishResult:
    dataset_dir: Path
    copied_files: list[Path]
    manifest_files: list[Path]
    dashboard_files: list[Path]


def publish_static_api(
    *,
    org: str,
    data_dir: str | Path,
    site_dir: str | Path,
    run_label: str = "latest",
    base_url: str | None = None,
    generated_at: datetime | None = None,
) -> StaticApiPublishResult:
    """Copy crawler outputs into a GitHub Pages-friendly static API tree."""

    _validate_path_segment(org, "org")
    _validate_path_segment(run_label, "run_label")
    data_dir = Path(data_dir)
    site_dir = Path(site_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"crawler output directory does not exist: {data_dir}")

    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    generated_at_text = generated_at.isoformat()
    normalized_base_url = base_url.rstrip("/") if base_url else None

    site_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir = site_dir / org / run_label
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)

    copied_files: list[Path] = []
    file_entries: dict[str, dict[str, Any]] = {}
    for file_name in CRAWLER_OUTPUT_FILES:
        source_path = data_dir / file_name
        if not source_path.is_file():
            continue
        target_path = dataset_dir / file_name
        shutil.copy2(source_path, target_path)
        copied_files.append(target_path)
        file_entries[file_name] = {
            "format": _file_format(file_name),
            **_endpoint(f"/{org}/{run_label}/{file_name}", normalized_base_url),
            "bytes": target_path.stat().st_size,
        }

    if not copied_files:
        raise ValueError(f"no known crawler output files found in {data_dir}")

    summary = _read_json_object(dataset_dir / "summary.json")
    output_manifest = _read_json_object(dataset_dir / "output_manifest.json")
    dashboard_endpoint = _endpoint(f"/{org}/{run_label}/dashboard.html", normalized_base_url)
    latest_manifest = {
        "api_version": 1,
        "output_schema_version": output_manifest.get("output_schema_version") or summary.get("output_schema_version"),
        "org": org,
        "run_label": run_label,
        "generated_at": generated_at_text,
        "run": _run_metadata(summary),
        "totals": summary.get("totals", {}) if summary else {},
        "calendar_span": summary.get("calendar_span", {}) if summary else {},
        "averages": summary.get("averages", {}) if summary else {},
        "dashboard": dashboard_endpoint,
        "summary": _endpoint(f"/{org}/{run_label}/summary.json", normalized_base_url)
        if "summary.json" in file_entries
        else None,
        "output_manifest": _endpoint(f"/{org}/{run_label}/output_manifest.json", normalized_base_url)
        if "output_manifest.json" in file_entries
        else None,
        "files": file_entries,
    }

    dataset_index = dataset_dir / "index.json"
    latest_manifest_path = site_dir / "api" / org / f"{run_label}.json"
    latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(dataset_index, latest_manifest)
    _write_json(latest_manifest_path, latest_manifest)

    root_index_path = site_dir / "index.json"
    root_index = _load_existing_index(root_index_path)
    root_index["api_version"] = 1
    root_index["generated_at"] = generated_at_text
    root_index.setdefault("orgs", {}).setdefault(org, {})[run_label] = _endpoint(
        f"/api/{org}/{run_label}.json",
        normalized_base_url,
    )
    _write_json(root_index_path, root_index)

    api_index_path = site_dir / "api" / "index.json"
    _write_json(api_index_path, root_index)

    dashboard_files = _write_dashboard_pages(
        org=org,
        run_label=run_label,
        site_dir=site_dir,
        dataset_dir=dataset_dir,
        summary=summary,
        generated_at=generated_at_text,
        base_url=normalized_base_url,
    )

    return StaticApiPublishResult(
        dataset_dir=dataset_dir,
        copied_files=copied_files,
        manifest_files=[dataset_index, latest_manifest_path, root_index_path, api_index_path],
        dashboard_files=dashboard_files,
    )


def _validate_path_segment(value: str, label: str) -> None:
    if value in {".", ".."}:
        raise ValueError(f"{label} must not be a dot path segment")
    if not value or not _SAFE_SEGMENT_RE.fullmatch(value):
        raise ValueError(f"{label} must contain only letters, numbers, dots, underscores, or hyphens")


def _endpoint(path: str, base_url: str | None) -> dict[str, str]:
    endpoint = {"path": path}
    if base_url:
        endpoint["url"] = f"{base_url}{path}"
    return endpoint


def _file_format(file_name: str) -> str:
    if file_name.endswith(".jsonl"):
        return "jsonl"
    suffix = Path(file_name).suffix.lstrip(".")
    return suffix or "binary"


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"expected JSON object in {path}")
    return loaded


def _run_metadata(summary: dict[str, Any]) -> dict[str, Any]:
    nested_run = summary.get("run")
    if isinstance(nested_run, dict):
        return nested_run
    return {
        field: summary[field]
        for field in (
            "run_id",
            "status",
            "ref_scope",
            "history_since",
            "history_until",
            "active_since",
        )
        if field in summary
    }


def _load_existing_index(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"api_version": 1, "orgs": {}}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return {"api_version": 1, "orgs": {}}
    orgs = loaded.get("orgs")
    if not isinstance(orgs, dict):
        loaded["orgs"] = {}
    return loaded


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_dashboard_pages(
    *,
    org: str,
    run_label: str,
    site_dir: Path,
    dataset_dir: Path,
    summary: dict[str, Any],
    generated_at: str,
    base_url: str | None,
) -> list[Path]:
    dataset_dashboard_path = dataset_dir / "dashboard.html"
    root_dashboard_path = site_dir / "index.html"

    dataset_dashboard_path.write_text(
        _render_dashboard_html(
            org=org,
            run_label=run_label,
            summary=summary,
            generated_at=generated_at,
            data_path_prefix="./",
            manifest_href=_manifest_href(org=org, run_label=run_label, base_url=base_url, relative_prefix="../../"),
            canonical_dashboard_href=None,
        ),
        encoding="utf-8",
    )
    root_dashboard_path.write_text(
        _render_dashboard_html(
            org=org,
            run_label=run_label,
            summary=summary,
            generated_at=generated_at,
            data_path_prefix=f"./{org}/{run_label}/",
            manifest_href=_manifest_href(org=org, run_label=run_label, base_url=base_url, relative_prefix="./"),
            canonical_dashboard_href=f"./{org}/{run_label}/dashboard.html",
        ),
        encoding="utf-8",
    )
    return [dataset_dashboard_path, root_dashboard_path]


def _manifest_href(*, org: str, run_label: str, base_url: str | None, relative_prefix: str) -> str:
    endpoint = _endpoint(f"/api/{org}/{run_label}.json", base_url)
    return endpoint.get("url", f"{relative_prefix}api/{org}/{run_label}.json")


def _render_dashboard_html(
    *,
    org: str,
    run_label: str,
    summary: dict[str, Any],
    generated_at: str,
    data_path_prefix: str,
    manifest_href: str,
    canonical_dashboard_href: str | None,
) -> str:
    repositories = _mapping(summary.get("repositories"))
    totals = _mapping(summary.get("totals"))
    calendar_span = _mapping(summary.get("calendar_span"))
    averages = _mapping(summary.get("averages"))
    source_like = _mapping(summary.get("source_like_totals"))
    generated_like = _mapping(summary.get("generated_like_totals"))
    run_metadata = _run_metadata(summary)

    status = str(summary.get("status") or run_metadata.get("status") or "unknown")
    run_id = summary.get("run_id") or run_metadata.get("run_id") or "unavailable"
    ref_scope = summary.get("ref_scope") or run_metadata.get("ref_scope") or "unavailable"
    history_since = summary.get("history_since") or run_metadata.get("history_since") or "beginning"
    history_until = summary.get("history_until") or run_metadata.get("history_until") or "latest"
    first_day = totals.get("first_day") or "unavailable"
    last_day = totals.get("last_day") or "unavailable"

    generated_display = _format_timestamp_display(generated_at)
    source_added = _number(source_like, "lines_added")
    generated_added = _number(generated_like, "lines_added")
    interpreted_added = source_added + generated_added
    source_percent = _percent(source_added, interpreted_added)
    generated_percent = _percent(generated_added, interpreted_added)

    kpi_cards = "\n".join(
        [
            _metric_card(
                "Total commits",
                _format_int(_number(totals, "commits")),
                "Parsed commit rows in the published crawl.",
            ),
            _metric_card(
                "File changes",
                _format_int(_number(totals, "file_changes")),
                "Git numstat file-change rows across selected repositories.",
            ),
            _metric_card(
                "Lines added",
                _format_signed_int(_number(totals, "lines_added")),
                "Raw additions from git history, not current source LOC.",
            ),
            _metric_card(
                "Lines deleted",
                _format_negative_int(_number(totals, "lines_deleted")),
                "Raw deletions from git history.",
            ),
            _metric_card(
                "Distinct contributors",
                _format_int(_number(totals, "distinct_contributor_keys")),
                "Deduplicated by GitHub login, email, or author name fallback.",
            ),
            _metric_card(
                "Active days",
                _format_int(_number(totals, "active_days")),
                f"Observed between {_h(first_day)} and {_h(last_day)}.",
                detail_is_html=True,
            ),
            _metric_card(
                "Repositories crawled",
                f"{_format_int(_number(repositories, 'crawled'))} / {_format_int(_number(repositories, 'selected'))}",
                "Selected public repositories successfully read.",
            ),
            _metric_card(
                "Repository failures",
                _format_int(_number(repositories, "failed")),
                "Investigate repo_failures when this value is non-zero.",
                tone="warning" if _number(repositories, "failed") else None,
            ),
        ]
    )

    canonical_action = ""
    if canonical_dashboard_href:
        canonical_action = (
            f'<a class="button secondary" href="{_attr(canonical_dashboard_href)}">Open run dashboard</a>'
        )

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(org)} KPI dashboard · git-crawl</title>
  <style>
{_DASHBOARD_CSS}
  </style>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div class="hero-copy">
        <p class="eyebrow">git-crawl metrics</p>
        <h1>KPI dashboard</h1>
        <p class="lede">
          Public GitHub organization activity for <strong>{_h(org)}</strong>, published as a static GitHub Pages report.
        </p>
        <div class="meta-grid" aria-label="Run metadata">
          <div><span>Status</span><strong class="meta-value status status-{_status_slug(status)}">{_h(status)}</strong></div>
          <div><span>Run label</span><strong class="meta-value">{_h(run_label)}</strong></div>
          <div><span>Ref scope</span><strong class="meta-value">{_h(ref_scope)}</strong></div>
          <div><span>Generated</span><strong class="meta-value">{_h(generated_display)}</strong></div>
        </div>
      </div>
      <aside class="run-card" aria-label="Run identity">
        <span class="card-label">Run ID</span>
        <code>{_h(run_id)}</code>
        <span class="card-label">History window</span>
        <strong>{_h(history_since)} to {_h(history_until)}</strong>
        <div class="hero-actions">
          <a class="button" href="{_attr(manifest_href)}">API manifest</a>
          {canonical_action}
        </div>
      </aside>
    </header>

    <section class="kpi-grid" aria-label="KPI metrics">
{kpi_cards}
    </section>

    <section class="two-column">
      <article class="panel span-wide">
        <div class="section-heading">
          <p class="eyebrow">Calendarized activity</p>
          <h2>Activity window</h2>
        </div>
        <div class="timeline-summary">
          <div><span>First active day</span><strong>{_h(first_day)}</strong></div>
          <div><span>Last active day</span><strong>{_h(last_day)}</strong></div>
          <div><span>Calendar span</span><strong>{_format_int(_number(calendar_span, 'days'))} days</strong></div>
          <div><span>Weeks</span><strong>{_format_int(_number(calendar_span, 'weeks'))}</strong></div>
          <div><span>Months</span><strong>{_format_int(_number(calendar_span, 'months'))}</strong></div>
        </div>
        {_render_average_grid(averages)}
      </article>

      <article class="panel">
        <div class="section-heading">
          <p class="eyebrow">Interpretation guardrail</p>
          <h2>Source mix</h2>
        </div>
        <div class="ratio-block">
          <div class="ratio-header">
            <strong>{_format_percent(source_percent)}</strong>
            <span>Source-like additions</span>
          </div>
          <div class="ratio-bar" aria-label="Source-like versus generated-like additions">
            <span class="ratio-source" style="width: {_attr(_format_percent(source_percent))}"></span>
            <span class="ratio-generated" style="width: {_attr(_format_percent(generated_percent))}"></span>
          </div>
          <dl class="compact-stats">
            <div><dt>Source-like</dt><dd>{_format_signed_int(source_added)}</dd></div>
            <div><dt>Generated-like</dt><dd>{_format_signed_int(generated_added)}</dd></div>
          </dl>
        </div>
      </article>
    </section>

    <section class="two-column">
      <article class="panel span-wide">
        <div class="section-heading">
          <p class="eyebrow">Repository focus</p>
          <h2>Top repos by commits</h2>
        </div>
        {_render_top_repositories(summary.get('top_repositories_by_commits'))}
      </article>

      <article class="panel">
        <div class="section-heading">
          <p class="eyebrow">Path mix</p>
          <h2>Path classes</h2>
        </div>
        {_render_path_classes(summary.get('path_classes'))}
      </article>
    </section>

    <section class="two-column">
      <article class="panel span-wide">
        <div class="section-heading">
          <p class="eyebrow">Churn concentration</p>
          <h2>Top paths by additions</h2>
        </div>
        {_render_top_paths(summary.get('top_paths_by_lines_added'))}
      </article>

      <article class="panel">
        <div class="section-heading">
          <p class="eyebrow">Raw data</p>
          <h2>Download endpoints</h2>
        </div>
        <div class="link-list">
          <a href="{_attr(data_path_prefix + 'summary.json')}">Summary JSON</a>
          <a href="{_attr(data_path_prefix + 'summary.md')}">Summary Markdown</a>
          <a href="{_attr(data_path_prefix + 'org_days.jsonl')}">Org days JSONL</a>
          <a href="{_attr(data_path_prefix + 'repo_days.jsonl')}">Repo days JSONL</a>
          <a href="{_attr(data_path_prefix + 'contributor_days.jsonl')}">Contributor days JSONL</a>
          <a href="{_attr(data_path_prefix + 'repositories.jsonl')}">Repositories JSONL</a>
          <a href="{_attr(data_path_prefix + 'repo_failures.jsonl')}">Repo failures JSONL</a>
        </div>
      </article>
    </section>

    <section class="panel caveats">
      <div class="section-heading">
        <p class="eyebrow">Read before comparing teams</p>
        <h2>Caveats</h2>
      </div>
      {_render_caveats(summary.get('caveats'))}
    </section>
  </main>
</body>
</html>
"""
    return html_text


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, dict)]


def _h(value: object) -> str:
    if value is None:
        return "—"
    return html.escape(str(value), quote=True)


def _attr(value: object) -> str:
    return _h(value)


def _number(mapping: dict[str, Any], key: str) -> float:
    value = mapping.get(key, 0)
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _format_int(value: float) -> str:
    return f"{int(round(value)):,}"


def _format_decimal(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _format_signed_int(value: float) -> str:
    if value > 0:
        return f"+{_format_int(value)}"
    if value < 0:
        return f"-{_format_int(abs(value))}"
    return "0"


def _format_negative_int(value: float) -> str:
    return f"-{_format_int(value)}" if value > 0 else _format_int(value)


def _percent(part: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (part / total) * 100.0))


def _format_percent(value: float) -> str:
    return f"{max(0.0, min(100.0, value)):.1f}%"


def _format_timestamp_display(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _status_slug(status: str) -> str:
    normalized = status.strip().lower()
    if normalized in {"success", "partial", "failed"}:
        return normalized
    return "unknown"


def _metric_card(
    label: str,
    value: str,
    detail: str,
    *,
    tone: str | None = None,
    detail_is_html: bool = False,
) -> str:
    tone_class = f" tone-{tone}" if tone in {"good", "warning"} else ""
    detail_text = detail if detail_is_html else _h(detail)
    return f"""      <article class="metric-card{tone_class}">
        <span>{_h(label)}</span>
        <strong class="metric-value">{_h(value)}</strong>
        <p>{detail_text}</p>
      </article>"""


def _render_average_grid(averages: dict[str, Any]) -> str:
    rows = [
        ("Per calendar day", _mapping(averages.get("per_calendar_day"))),
        ("Per calendar week", _mapping(averages.get("per_calendar_week"))),
        ("Per calendar month", _mapping(averages.get("per_calendar_month"))),
    ]
    rendered = []
    for label, rates in rows:
        rendered.append(
            f"""          <div>
            <span>{_h(label)}</span>
            <strong>{_format_decimal(_number(rates, 'commits'))} commits</strong>
            <p>{_format_signed_int(_number(rates, 'lines_added'))} / {_format_negative_int(_number(rates, 'lines_deleted'))} lines</p>
          </div>"""
        )
    return "<div class=\"average-grid\">\n" + "\n".join(rendered) + "\n        </div>"


def _render_top_repositories(value: object) -> str:
    rows = _dict_rows(value)
    if not rows:
        return '<p class="empty">No repository ranking is available for this run.</p>'
    max_commits = max((_number(row, "commits") for row in rows), default=0.0) or 1.0
    rendered_rows = []
    for row in rows:
        commits = _number(row, "commits")
        width = _format_percent(_percent(commits, max_commits))
        rendered_rows.append(
            f"""          <tr>
            <td class="repo-name">{_h(row.get('repo', 'unknown'))}</td>
            <td>{_format_int(commits)}</td>
            <td>{_format_int(_number(row, 'files_changed'))}</td>
            <td>{_format_signed_int(_number(row, 'lines_added'))}</td>
            <td>{_format_negative_int(_number(row, 'lines_deleted'))}</td>
            <td><span class="mini-bar"><span style="width: {_attr(width)}"></span></span></td>
          </tr>"""
        )
    return f"""        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Repository</th>
                <th>Commits</th>
                <th>Files</th>
                <th>Added</th>
                <th>Deleted</th>
                <th>Share</th>
              </tr>
            </thead>
            <tbody>
{chr(10).join(rendered_rows)}
            </tbody>
          </table>
        </div>"""


def _render_path_classes(value: object) -> str:
    path_classes = _mapping(value)
    rows = [
        (name, _mapping(metrics))
        for name, metrics in path_classes.items()
        if isinstance(name, str) and isinstance(metrics, dict)
    ]
    if not rows:
        return '<p class="empty">No path classification breakdown is available for this run.</p>'
    rows.sort(key=lambda item: (-_number(item[1], "lines_added"), item[0]))
    total_added = sum(_number(metrics, "lines_added") for _, metrics in rows) or 1.0
    rendered = []
    for name, metrics in rows:
        width = _format_percent(_percent(_number(metrics, "lines_added"), total_added))
        rendered.append(
            f"""          <li>
            <div><strong>{_h(name)}</strong><span>{_format_int(_number(metrics, 'files_changed'))} files</span></div>
            <span class="mini-bar"><span style="width: {_attr(width)}"></span></span>
            <small>{_format_signed_int(_number(metrics, 'lines_added'))} / {_format_negative_int(_number(metrics, 'lines_deleted'))} lines</small>
          </li>"""
        )
    return "<ul class=\"class-list\">\n" + "\n".join(rendered) + "\n        </ul>"


def _render_top_paths(value: object) -> str:
    rows = _dict_rows(value)
    if not rows:
        return '<p class="empty">No path-level churn ranking is available for this run.</p>'
    rendered = []
    for row in rows:
        rendered.append(
            f"""          <li>
            <div>
              <strong>{_h(row.get('path', 'unknown'))}</strong>
              <span>{_h(row.get('repo', 'unknown'))} · {_h(row.get('path_class', 'unknown'))}</span>
            </div>
            <p>{_format_signed_int(_number(row, 'lines_added'))} / {_format_negative_int(_number(row, 'lines_deleted'))} lines across {_format_int(_number(row, 'files_changed'))} files</p>
          </li>"""
        )
    return "<ol class=\"path-list\">\n" + "\n".join(rendered) + "\n        </ol>"


def _render_caveats(value: object) -> str:
    caveats = [item for item in value if isinstance(item, str)] if isinstance(value, list) else []
    if not caveats:
        caveats = [
            "Line counts are raw git churn from git log --numstat, not current source LOC.",
            "Generated-like totals include lockfiles, generated files, vendored artifacts, and specs.",
        ]
    rendered = "\n".join(f"        <li>{_h(caveat)}</li>" for caveat in caveats)
    return f"<ul>\n{rendered}\n      </ul>"


_DASHBOARD_CSS = """
    :root {
      color-scheme: light;
      --bg: #f8fafc;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #64748b;
      --line: #dbe4ef;
      --accent: #0f766e;
      --accent-soft: #ccfbf1;
      --warning: #b45309;
      --warning-soft: #fef3c7;
      --shadow: 0 24px 70px -38px rgba(15, 23, 42, 0.35);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.12), transparent 34rem),
        linear-gradient(180deg, #ffffff 0%, var(--bg) 42%, #eef3f8 100%);
      color: var(--ink);
      font-family: Geist, Satoshi, "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
    }

    a { color: inherit; }

    .shell {
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 48px 0;
    }

    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 420px);
      gap: 28px;
      align-items: stretch;
      margin-bottom: 28px;
    }

    .hero-copy,
    .run-card,
    .panel,
    .metric-card {
      min-width: 0;
      background: rgba(255, 255, 255, 0.86);
      border: 1px solid rgba(219, 228, 239, 0.92);
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }

    .hero-copy {
      border-radius: 34px;
      padding: clamp(28px, 5vw, 56px);
    }

    .eyebrow {
      margin: 0 0 12px;
      color: var(--accent);
      font-size: 0.76rem;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }

    h1,
    h2 {
      margin: 0;
      letter-spacing: -0.045em;
      line-height: 0.96;
    }

    h1 {
      max-width: 720px;
      font-size: clamp(2.85rem, 8vw, 5.8rem);
    }

    h2 { font-size: clamp(1.65rem, 4vw, 3rem); }

    .two-column .panel:not(.span-wide) h2 {
      font-size: clamp(1.45rem, 3vw, 2.15rem);
    }

    .lede {
      max-width: 62ch;
      margin: 22px 0 0;
      color: var(--muted);
      font-size: 1.08rem;
      line-height: 1.75;
    }

    .meta-grid,
    .timeline-summary,
    .average-grid,
    .compact-stats {
      display: grid;
      gap: 12px;
    }

    .meta-grid {
      grid-template-columns: repeat(auto-fit, minmax(min(160px, 100%), 1fr));
      margin-top: 32px;
    }

    .meta-grid div,
    .timeline-summary div,
    .average-grid div,
    .compact-stats div {
      min-width: 0;
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }

    .meta-grid span,
    .timeline-summary span,
    .average-grid span,
    .card-label,
    .metric-card span,
    dt {
      display: block;
      color: var(--muted);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .meta-value,
    .timeline-summary strong,
    .average-grid strong,
    dd {
      display: block;
      margin-top: 6px;
      max-width: 100%;
      overflow-wrap: anywhere;
      font-size: 1rem;
    }

    .meta-value {
      line-height: 1.35;
      font-variant-numeric: tabular-nums;
    }

    .status {
      width: fit-content;
      border-radius: 999px;
      padding: 5px 10px;
      background: #e2e8f0;
      color: #334155;
      white-space: nowrap;
      text-transform: capitalize;
    }

    .status-success,
    .tone-good strong { background: var(--accent-soft); color: var(--accent); }

    .status-partial,
    .status-failed,
    .tone-warning strong { background: var(--warning-soft); color: var(--warning); }

    .run-card {
      display: flex;
      flex-direction: column;
      gap: 14px;
      justify-content: space-between;
      border-radius: 30px;
      padding: 28px;
    }

    code {
      max-width: 100%;
      overflow-wrap: anywhere;
      color: #0f172a;
      font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
      font-size: 0.92rem;
    }

    .run-card strong {
      max-width: 100%;
      overflow-wrap: anywhere;
      line-height: 1.35;
    }

    .hero-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }

    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      max-width: 100%;
      min-height: 42px;
      border-radius: 999px;
      padding: 0 16px;
      background: #0f172a;
      color: #ffffff;
      font-weight: 800;
      text-decoration: none;
      transition: filter 160ms ease, transform 160ms ease;
    }

    .button.secondary {
      background: #e2e8f0;
      color: #172033;
    }

    .button:hover { filter: brightness(1.08); }
    .button:active { transform: translateY(1px); }

    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(235px, 100%), 1fr));
      gap: 16px;
      margin-bottom: 16px;
    }

    .metric-card {
      container-type: inline-size;
      overflow: hidden;
      min-height: 178px;
      border-radius: 28px;
      padding: 24px;
    }

    .metric-value {
      display: block;
      margin-top: 14px;
      max-width: 100%;
      overflow-wrap: anywhere;
      font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
      font-size: clamp(1.95rem, 3vw, 2.65rem);
      font-size: clamp(1.95rem, 16cqw, 2.65rem);
      font-variant-numeric: tabular-nums;
      letter-spacing: -0.06em;
      line-height: 0.98;
    }

    .metric-card p,
    .average-grid p,
    .path-list p,
    .empty {
      color: var(--muted);
      line-height: 1.58;
    }

    .two-column {
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.75fr);
      gap: 16px;
      margin-top: 16px;
    }

    .panel {
      border-radius: 30px;
      padding: 28px;
    }

    .section-heading {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 22px;
    }

    .timeline-summary {
      grid-template-columns: repeat(5, minmax(0, 1fr));
      margin-bottom: 18px;
    }

    .average-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .ratio-header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 20px;
    }

    .ratio-header strong {
      font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
      font-size: clamp(2.8rem, 7vw, 5rem);
      letter-spacing: -0.07em;
    }

    .ratio-header span { color: var(--muted); font-weight: 800; }

    .ratio-bar,
    .mini-bar {
      display: flex;
      overflow: hidden;
      width: 100%;
      height: 12px;
      border-radius: 999px;
      background: #e2e8f0;
    }

    .ratio-source,
    .mini-bar span { background: var(--accent); }
    .ratio-generated { background: #94a3b8; }

    .compact-stats {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin: 18px 0 0;
      padding: 0;
    }

    dd { margin: 6px 0 0; font-weight: 900; }

    .table-wrap { overflow-x: auto; }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 720px;
    }

    th,
    td {
      border-bottom: 1px solid var(--line);
      padding: 13px 10px;
      text-align: left;
      white-space: nowrap;
    }

    th {
      color: var(--muted);
      font-size: 0.76rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    td:not(.repo-name) {
      font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
      font-size: 0.94rem;
    }

    .repo-name { font-weight: 900; }

    .mini-bar { height: 8px; min-width: 90px; }

    .class-list,
    .path-list,
    .link-list,
    .caveats ul {
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .class-list li,
    .path-list li,
    .link-list a {
      border-top: 1px solid var(--line);
      padding: 14px 0;
    }

    .class-list li:first-child,
    .path-list li:first-child,
    .link-list a:first-child { border-top: 0; }

    .class-list div,
    .path-list div {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      min-width: 0;
    }

    .class-list strong,
    .class-list span,
    .path-list strong,
    .path-list span,
    .path-list p,
    .link-list a {
      min-width: 0;
      max-width: 100%;
      overflow-wrap: anywhere;
    }

    .class-list span,
    .class-list small,
    .path-list span {
      color: var(--muted);
    }

    .link-list {
      display: grid;
      gap: 0;
    }

    .link-list a {
      color: var(--accent);
      font-weight: 850;
      text-decoration: none;
    }

    .link-list a:hover { text-decoration: underline; }

    .caveats li {
      border-top: 1px solid var(--line);
      color: var(--muted);
      line-height: 1.65;
      padding: 12px 0;
    }

    .caveats li:first-child { border-top: 0; }

    @media (max-width: 980px) {
      .hero,
      .two-column,
      .kpi-grid,
      .timeline-summary,
      .average-grid {
        grid-template-columns: 1fr;
      }

      .meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }

    @media (max-width: 620px) {
      .shell { width: min(100% - 20px, 1180px); padding: 20px 0; }
      .hero-copy,
      .run-card,
      .panel,
      .metric-card { border-radius: 22px; padding: 20px; }
      .meta-grid { grid-template-columns: 1fr; }
      .section-heading { align-items: start; flex-direction: column; }
    }
""".strip()
