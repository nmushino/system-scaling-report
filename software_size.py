#!/usr/bin/env python3
"""
software_size.py - Software size / scale scoring tool.

Scans a directory tree (single repo or a whole multi-repo workspace) and
reports SLOC, architecture, data, cloud-native and complexity metrics, then
computes a weighted "Software Size Score" and classifies the project into
a size band (Tiny / Small / Medium / Large / Enterprise).

Usage:
    python3 software_size.py [PATH] [--name NAME] [--json] [--weights FILE] [--effort]
                              [--productivity FILE] [--html FILE]

    PATH                Directory to scan (default: current directory)
    --name NAME         Project name shown in the report (default: dir name)
    --json              Also dump the raw metrics + score as JSON
    --weights FILE      JSON file overriding the default weight table
    --effort            Print the Java/Node person-months estimate in the
                         text report (the HTML report always includes it).
    --productivity FILE JSON file overriding the default person-months
                         productivity table (see productivity.json /
                         productivity.example.json).
    --html FILE          Write a self-contained HTML report (with charts)
                         to this path.

Notes:
    - Person-months are estimated from a size-banded SLOC-productivity table
      (default: IPA's "ソフトウェア開発分析データ集2022" 表A1-2-4, 新規開発:
      全年度, n=1,246 -- IPA does not publish a per-language breakdown, so
      the same table is applied to Java SLOC and Node SLOC separately by
      default). Pass --productivity to plug in your own company's measured
      rates per language. Treat the result as a rough-order-of-magnitude
      estimate, not a committed estimate.
    - Uses `cloc` for SLOC counting when available (accurate comment/blank
      stripping across languages), otherwise falls back to a built-in
      counter.
    - Complexity (Average/Maximum CC) and topic/table/API detection are
      regex-based heuristics, not a certified static analyzer. They are
      good enough for relative size comparisons, not for code quality
      audits.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EXCLUDE_DIRS = {
    ".git", "node_modules", "target", "dist", "build", "out", ".venv", "venv",
    "__pycache__", ".yarn", ".next", "coverage", ".m2", "vendor", ".gradle",
    ".idea", ".vscode", ".claude", ".pytest_cache", ".cache", "bin", "obj",
    ".terraform", ".husky", ".changeset", ".storybook",
}

LANGUAGE_EXTENSIONS = {
    ".java": "Java",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".py": "Python",
    ".go": "Go",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".sql": "SQL",
    ".sh": "Shell",
    ".md": "Markdown",
}

# Weight table (as specified) applied to raw metric counts.
DEFAULT_WEIGHTS = {
    "kloc": 1,
    "api": 5,
    "camel_route": 3,
    "kafka_topic": 2,
    "db_table": 2,
    "deployment": 2,
    "module": 4,
    "complexity": 10,  # applied to Average CC
}

# Default person-months productivity table (ships as productivity.json).
# Source: IPA "ソフトウェア開発分析データ集2022" 表A1-2-4 (新規開発:全年度,
# n=1,246), SLOC生産性の中央値 [SLOC/人時]、全言語混在・SLOC規模帯別。
# IPA publishes no per-language breakdown, so by default the same table is
# applied to Java SLOC and Node SLOC independently. Override with
# --productivity FILE to plug in your own company's measured rates per
# language (see productivity.example.json). "max_sloc": null means the band
# has no upper bound.
DEFAULT_PRODUCTIVITY = {
    "hours_per_person_month": 160,
    "java": {"bands": [
        {"max_sloc": 40000, "rate_sloc_per_hour": 3.94},
        {"max_sloc": 100000, "rate_sloc_per_hour": 5.15},
        {"max_sloc": 300000, "rate_sloc_per_hour": 5.76},
        {"max_sloc": None, "rate_sloc_per_hour": 5.92},
    ]},
    "node": {"bands": [
        {"max_sloc": 40000, "rate_sloc_per_hour": 3.94},
        {"max_sloc": 100000, "rate_sloc_per_hour": 5.15},
        {"max_sloc": 300000, "rate_sloc_per_hour": 5.76},
        {"max_sloc": None, "rate_sloc_per_hour": 5.92},
    ]},
}


def load_productivity(path):
    config = json.loads(json.dumps(DEFAULT_PRODUCTIVITY))  # deep copy
    if path:
        with open(path) as f:
            config.update(json.load(f))
    return config

# Upper bound is exclusive; last band is open-ended.
SIZE_BANDS = [
    (100, "Tiny"),
    (300, "Small"),
    (700, "Medium"),
    (1500, "Large"),
    (float("inf"), "Enterprise"),
]


# ---------------------------------------------------------------------------
# File walking helpers
# ---------------------------------------------------------------------------

def walk_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".git")]
        for fname in filenames:
            yield os.path.join(dirpath, fname)


def read_text(path, limit=None):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(limit) if limit else f.read()
    except (OSError, IsADirectoryError):
        return ""


# ---------------------------------------------------------------------------
# SLOC counting
# ---------------------------------------------------------------------------

def count_sloc_cloc(root):
    """Use `cloc` if available. Returns {language: sloc} or None on failure."""
    if not shutil.which("cloc"):
        return None
    try:
        out = subprocess.run(
            ["cloc", "--json", "--quiet",
             "--exclude-dir=" + ",".join(EXCLUDE_DIRS), root],
            capture_output=True, text=True, timeout=300,
        )
        data = json.loads(out.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return None
    result = {}
    for lang, stats in data.items():
        if lang in ("header", "SUM"):
            continue
        result[lang] = stats.get("code", 0)
    return result


LINE_COMMENT = {"Java": "//", "TypeScript": "//", "JavaScript": "//",
                "Go": "//", "Shell": "#", "Python": "#", "YAML": "#"}
BLOCK_COMMENT = {"Java": ("/*", "*/"), "TypeScript": ("/*", "*/"),
                 "JavaScript": ("/*", "*/"), "Go": ("/*", "*/")}


def count_sloc_manual(root):
    """Fallback SLOC counter: strips block/line comments and blank lines."""
    totals = defaultdict(int)
    for path in walk_files(root):
        ext = os.path.splitext(path)[1].lower()
        lang = LANGUAGE_EXTENSIONS.get(ext)
        if not lang:
            continue
        text = read_text(path)
        if not text:
            continue
        if lang in BLOCK_COMMENT:
            start, end = BLOCK_COMMENT[lang]
            text = re.sub(re.escape(start) + r".*?" + re.escape(end), "", text, flags=re.S)
        line_marker = LINE_COMMENT.get(lang)
        count = 0
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if line_marker and stripped.startswith(line_marker):
                continue
            count += 1
        totals[lang] += count
    return dict(totals)


def count_sloc(root):
    sloc = count_sloc_cloc(root)
    if sloc is None:
        sloc = count_sloc_manual(root)
    return {k: v for k, v in sloc.items() if v > 0}


# ---------------------------------------------------------------------------
# Regex-based metric scanners
# ---------------------------------------------------------------------------

def iter_source(root, exts):
    for path in walk_files(root):
        if os.path.splitext(path)[1].lower() in exts:
            yield path


def scan_pattern_count(root, exts, pattern):
    regex = re.compile(pattern)
    total = 0
    for path in iter_source(root, exts):
        total += len(regex.findall(read_text(path)))
    return total


def scan_pattern_unique(root, exts, pattern, group=1):
    regex = re.compile(pattern)
    names = set()
    for path in iter_source(root, exts):
        for m in regex.finditer(read_text(path)):
            names.add(m.group(group))
    return names


def count_rest_apis(root):
    total = 0
    # JAX-RS (Java, Quarkus/Spring Boot @Path style)
    total += scan_pattern_count(root, {".java"}, r"@Path\s*\(")
    # NestJS-style decorators
    total += scan_pattern_count(root, {".ts", ".tsx"}, r"@(?:Get|Post|Put|Delete|Patch)\s*\(")
    # Express-style routers
    total += scan_pattern_count(root, {".ts", ".tsx", ".js", ".jsx"},
                                 r"\brouter\.(?:get|post|put|delete|patch)\s*\(")
    # FastAPI / Flask decorators
    total += scan_pattern_count(root, {".py"}, r"@(?:app|router)\.(?:get|post|put|delete|patch)\s*\(")
    return total


def count_graphql_apis(root):
    total = 0
    for path in walk_files(root):
        if path.endswith((".graphql", ".graphqls")):
            total += 1
    total += scan_pattern_count(root, {".java"}, r"@GraphQLApi\b")
    total += scan_pattern_count(root, {".ts", ".tsx"}, r"@Resolver\s*\(")
    return total


def count_camel_routes(root):
    total = 0
    for path in iter_source(root, {".java"}):
        text = read_text(path)
        if "org.apache.camel" in text or "RouteBuilder" in text:
            total += len(re.findall(r"\bfrom\s*\(\s*[\"']", text))
    total += scan_pattern_count(root, {".yaml", ".yml"}, r"^\s*-?\s*from:\s*[\"']")
    return total


def count_kafka_topics(root):
    names = set()
    # MicroProfile Reactive Messaging config: mp.messaging.<in|out>.<channel>.topic=<name>
    for path in walk_files(root):
        if os.path.basename(path) not in ("application.properties", "application.yaml", "application.yml"):
            continue
        text = read_text(path)
        names |= set(re.findall(r"mp\.messaging\.[\w.\-]+\.topic\s*=\s*(\S+)", text))
        names |= set(re.findall(r"topic:\s*[\"']?([\w.\-]+)[\"']?", text))
    # Strimzi KafkaTopic custom resources
    for path in iter_source(root, {".yaml", ".yml"}):
        text = read_text(path)
        if "kind: KafkaTopic" in text:
            for m in re.finditer(r"kind:\s*KafkaTopic.*?name:\s*([\w.\-]+)", text, re.S):
                names.add(m.group(1))
    if names:
        return len(names)
    # Fallback: annotation occurrence count if no concrete topic names were found
    return scan_pattern_count(root, {".java"}, r"@(?:Channel|Topic)\s*\(\s*\"[^\"]+\"\s*\)")


def count_db_tables(root):
    names = set()
    names |= scan_pattern_unique(root, {".java"}, r"@Table\s*\(\s*name\s*=\s*\"([^\"]+)\"")
    names |= scan_pattern_unique(root, {".sql"},
                                  r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?",
                                  )
    return len(names)


def count_entities(root):
    total = scan_pattern_count(root, {".java"}, r"@Entity\b")
    total += scan_pattern_count(root, {".ts", ".tsx"}, r"@Entity\s*\(")
    return total


def _has_top_level_key(text, key):
    for line in text.splitlines()[:30]:
        if re.match(rf"^{key}\s*:", line.strip()):
            return True
    return False


def count_api_specs(root):
    openapi, asyncapi = 0, 0
    for path in iter_source(root, {".yaml", ".yml", ".json"}):
        base = os.path.basename(path).lower()
        text = read_text(path, limit=4000)
        if "openapi" in base or _has_top_level_key(text, "openapi") or '"openapi"' in text[:200]:
            openapi += 1
        elif "asyncapi" in base or _has_top_level_key(text, "asyncapi") or '"asyncapi"' in text[:200]:
            asyncapi += 1
    return openapi, asyncapi


def count_k8s_kinds(root):
    kinds = defaultdict(int)
    for path in iter_source(root, {".yaml", ".yml"}):
        text = read_text(path)
        for m in re.finditer(r"^kind:\s*(\w+)", text, re.M):
            kinds[m.group(1)] += 1
        if os.path.basename(path) == "Chart.yaml":
            kinds["_HelmChart"] += 1
    return kinds


def count_helm_charts(root):
    return sum(1 for path in walk_files(root) if os.path.basename(path) == "Chart.yaml")


def count_operators(root):
    return scan_pattern_count(root, {".yaml", ".yml"}, r"^kind:\s*ClusterServiceVersion")


def find_module_dirs(root):
    markers = {"pom.xml", "package.json", "build.gradle", "build.gradle.kts",
               "go.mod", "pyproject.toml", "setup.py"}
    dirs = set()
    for path in walk_files(root):
        if os.path.basename(path) in markers:
            dirs.add(os.path.dirname(path))
    return dirs


def find_microservice_dirs(root):
    dirs = set()
    for path in walk_files(root):
        if os.path.basename(path) in ("Dockerfile", "Containerfile") or path.endswith(".Dockerfile"):
            dirs.add(os.path.dirname(path))
    return dirs


def count_maven_modules(root):
    return sum(1 for path in walk_files(root) if os.path.basename(path) == "pom.xml")


def count_node_packages(root):
    names = set()
    for path in walk_files(root):
        if os.path.basename(path) != "package.json" or "/node_modules/" in path.replace(os.sep, "/"):
            continue
        try:
            data = json.loads(read_text(path))
        except (ValueError, TypeError):
            continue
        for section in ("dependencies", "devDependencies"):
            names.update((data.get(section) or {}).keys())
    return len(names)


def count_container_images(root):
    return len(find_microservice_dirs(root))


# ---------------------------------------------------------------------------
# Complexity (heuristic cyclomatic complexity)
# ---------------------------------------------------------------------------

JAVA_TS_FUNC = re.compile(
    r"(?:public|private|protected|static|final|synchronized|async|export|function|def)"
    r"[^\n;{}=]*?\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{"
)
DECISION_POINTS = re.compile(
    r"\b(?:if|else\s+if|for|foreach|while|case|catch)\b|&&|\|\||\?[^:]*:"
)


def _extract_braced_bodies(text):
    """Yield function bodies for each JAVA_TS_FUNC match via brace matching."""
    for m in JAVA_TS_FUNC.finditer(text):
        start = m.end() - 1  # position of the opening '{'
        depth = 0
        i = start
        for i in range(start, min(len(text), start + 20000)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
        yield text[start:i + 1]


def compute_complexity(root):
    """Approximate average/maximum cyclomatic complexity across functions."""
    ccs = []
    for path in iter_source(root, {".java", ".ts", ".tsx", ".js", ".jsx"}):
        text = read_text(path)
        if not text:
            continue
        for body in _extract_braced_bodies(text):
            cc = 1 + len(DECISION_POINTS.findall(body))
            ccs.append(cc)
    if not ccs:
        return None, None
    avg = sum(ccs) / len(ccs)
    return round(avg, 1), max(ccs)


def find_coverage(root):
    """Best-effort test coverage percentage lookup from common report formats."""
    candidates = []
    for path in walk_files(root):
        base = os.path.basename(path)
        if base == "jacoco.xml":
            text = read_text(path)
            m = re.search(r'<counter type="INSTRUCTION"[^>]*missed="(\d+)"[^>]*covered="(\d+)"', text)
            if m:
                missed, covered = int(m.group(1)), int(m.group(2))
                total = missed + covered
                if total:
                    candidates.append(100.0 * covered / total)
        elif base == "coverage-summary.json":
            try:
                data = json.loads(read_text(path))
                pct = data.get("total", {}).get("lines", {}).get("pct")
                if pct is not None:
                    candidates.append(float(pct))
            except (ValueError, TypeError):
                pass
    if not candidates:
        return None
    return round(sum(candidates) / len(candidates), 1)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def estimate_person_months(sloc, bands, hours_per_month):
    """Person-months for `sloc` lines, via a size-banded productivity table."""
    if sloc <= 0:
        return 0.0, None
    rate_per_hour = bands[-1]["rate_sloc_per_hour"]
    for band in bands:
        max_sloc = band.get("max_sloc")
        if max_sloc is None or sloc < max_sloc:
            rate_per_hour = band["rate_sloc_per_hour"]
            break
    rate_per_month = rate_per_hour * hours_per_month
    return round(sloc / rate_per_month, 1), rate_per_hour


def compute_effort(metrics, productivity):
    java_sloc = metrics["sloc_by_lang"].get("Java", 0)
    node_sloc = metrics["sloc_by_lang"].get("TypeScript", 0) + metrics["sloc_by_lang"].get("JavaScript", 0)
    hours = productivity["hours_per_person_month"]
    java_months, java_rate = estimate_person_months(java_sloc, productivity["java"]["bands"], hours)
    node_months, node_rate = estimate_person_months(node_sloc, productivity["node"]["bands"], hours)
    return {
        "hours_per_person_month": hours,
        "java_sloc": java_sloc, "java_rate": java_rate, "java_person_months": java_months,
        "node_sloc": node_sloc, "node_rate": node_rate, "node_person_months": node_months,
        "total_person_months": round(java_months + node_months, 1),
    }


def classify(score):
    for upper, label in SIZE_BANDS:
        if score < upper:
            return label
    return SIZE_BANDS[-1][1]


def compute_score(metrics, weights):
    kloc = metrics["total_sloc"] / 1000.0
    apis = metrics["rest_apis"] + metrics["graphql_apis"]
    avg_cc = metrics["avg_cc"] or 0
    breakdown = {
        "kloc": kloc * weights["kloc"],
        "api": apis * weights["api"],
        "camel_route": metrics["camel_routes"] * weights["camel_route"],
        "kafka_topic": metrics["kafka_topics"] * weights["kafka_topic"],
        "db_table": metrics["db_tables"] * weights["db_table"],
        "deployment": metrics["deployments"] * weights["deployment"],
        "module": metrics["modules"] * weights["module"],
        "complexity": avg_cc * weights["complexity"],
    }
    return round(sum(breakdown.values())), breakdown


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def render_effort_section(effort, productivity_source):
    lines = []
    add = lines.append
    add("")
    add(f"Effort Estimate (productivity: {productivity_source})")
    add("-" * 60)
    add(f"Java SLOC       : {effort['java_sloc']:,}  (rate {effort['java_rate']} SLOC/人時) "
        f"-> {effort['java_person_months']} 人月")
    add(f"Node SLOC       : {effort['node_sloc']:,}  (TS+JS, rate {effort['node_rate']} SLOC/人時) "
        f"-> {effort['node_person_months']} 人月")
    add(f"Total           : {effort['total_person_months']} 人月")
    add("* Default rates are IPA's overall size-banded median (no official")
    add("  per-language split exists). Pass --productivity for your own rates.")
    return "\n".join(lines)


def render_report(name, metrics, weights, score, classification):
    lines = []
    add = lines.append
    add("Software Size Summary")
    add("=" * 21)
    add("")
    add("Project")
    add("-------")
    add(f"Name            : {name}")
    langs = ", ".join(sorted(metrics["sloc_by_lang"], key=lambda l: -metrics["sloc_by_lang"][l]))
    add(f"Languages       : {langs or 'N/A'}")
    add("")
    add("Code")
    add("----")
    for lang, count in sorted(metrics["sloc_by_lang"].items(), key=lambda kv: -kv[1]):
        add(f"{lang + ' SLOC':<16}: {count:,}")
    add(f"{'Total SLOC':<16}: {metrics['total_sloc']:,}")
    add(f"{'Files':<16}: {metrics['files']:,}")
    add("")
    add("Architecture")
    add("------------")
    add(f"Modules         : {metrics['modules']}")
    add(f"Microservices   : {metrics['microservices']}")
    add(f"REST APIs       : {metrics['rest_apis']}")
    add(f"GraphQL APIs    : {metrics['graphql_apis']}")
    add(f"Camel Routes    : {metrics['camel_routes']}")
    add(f"Kafka Topics    : {metrics['kafka_topics']}")
    add("")
    add("Data")
    add("----")
    add(f"Database Tables : {metrics['db_tables']}")
    add(f"Entities        : {metrics['entities']}")
    add(f"OpenAPI Specs   : {metrics['openapi_specs']}")
    add(f"AsyncAPI Specs  : {metrics['asyncapi_specs']}")
    add("")
    add("Cloud Native")
    add("------------")
    add(f"Deployments     : {metrics['deployments']}")
    add(f"StatefulSets    : {metrics['statefulsets']}")
    add(f"CronJobs        : {metrics['cronjobs']}")
    add(f"Helm Charts     : {metrics['helm_charts']}")
    add(f"Operators       : {metrics['operators']}")
    add("")
    add("Complexity")
    add("----------")
    add(f"Average CC      : {metrics['avg_cc'] if metrics['avg_cc'] is not None else 'N/A'}")
    add(f"Maximum CC      : {metrics['max_cc'] if metrics['max_cc'] is not None else 'N/A'}")
    add(f"Coverage        : {str(metrics['coverage']) + '%' if metrics['coverage'] is not None else 'N/A'}")
    add("")
    add("Dependencies")
    add("------------")
    add(f"Maven Modules   : {metrics['maven_modules']}")
    add(f"Node Packages   : {metrics['node_packages']}")
    add(f"Container Images: {metrics['container_images']}")
    add("")
    add("Overall Size")
    add("------------")
    add("Tiny / Small / Medium / Large / Enterprise")
    add("")
    add("Software Size Score")
    add("-" * 20)
    add(f"{score} points -> {classification}")
    add("")
    add("Summary")
    add("-------")
    add(f"Score          : {score}")
    add(f"SLOC           : {metrics['total_sloc']:,}")
    add(f"ApplicationType: {classification}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML report (self-contained, inline SVG charts, no external dependencies)
# ---------------------------------------------------------------------------

def _esc(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return _esc(value)
    return f"{int(f):,}" if f.is_integer() else f"{f:,.1f}"


def _svg_bar_chart(items, unit="", width=620, bar_h=26, gap=10, color="#2563eb"):
    """items: list of (label, value). Renders a horizontal bar chart as inline SVG."""
    items = [(label, value) for label, value in items if value is not None]
    if not items:
        return '<p class="note">No data</p>'
    max_v = max(value for _, value in items) or 1
    label_w = 150
    value_margin = 140
    chart_w = width - label_w - value_margin
    height = len(items) * (bar_h + gap) + gap
    rows = []
    y = gap
    for label, value in items:
        bar_len = max((value / max_v) * chart_w, 0) if max_v else 0
        rows.append(f'<text x="{label_w - 8}" y="{y + bar_h * 0.7:.1f}" text-anchor="end" '
                     f'class="chart-label">{_esc(label)}</text>')
        rows.append(f'<rect x="{label_w}" y="{y}" width="{bar_len:.1f}" height="{bar_h}" '
                     f'rx="4" fill="{color}"/>')
        rows.append(f'<text x="{label_w + bar_len + 8:.1f}" y="{y + bar_h * 0.7:.1f}" '
                     f'class="chart-value">{_fmt_num(value)}{unit}</text>')
        y += bar_h + gap
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
            f'xmlns="http://www.w3.org/2000/svg">{"".join(rows)}</svg>')


def _svg_gauge(score, bands, width=680):
    """Horizontal segmented gauge showing where `score` lands across SIZE_BANDS.

    Band labels are rendered as an evenly-spaced legend row (not centered inside
    each segment), because narrow bands next to a dominant open-ended band would
    otherwise overlap.
    """
    colors = ["#93c5fd", "#60a5fa", "#3b82f6", "#f59e0b", "#ef4444"]
    finite_bounds = [upper for upper, _ in bands if upper != float("inf")]
    display_max = max(finite_bounds[-1] * 1.3, score * 1.15, 100)
    bar_h, y = 28, 34
    legend_y = y + bar_h + 28
    height = legend_y + 14
    segments = []
    prev = 0.0
    x = 0.0
    for (upper, _label), color in zip(bands, colors):
        seg_upper = min(upper, display_max)
        seg_w = max((seg_upper - prev) / display_max * width, 0)
        segments.append(f'<rect x="{x:.1f}" y="{y}" width="{seg_w:.1f}" height="{bar_h}" fill="{color}"/>')
        x += seg_w
        prev = upper
        if seg_upper >= display_max:
            break
    marker_x = min(max(score / display_max * width, 8), width - 8)
    segments.append(f'<polygon points="{marker_x - 7:.1f},{y - 10} {marker_x + 7:.1f},{y - 10} '
                     f'{marker_x:.1f},{y + 2}" fill="#111827"/>')
    segments.append(f'<text x="{marker_x:.1f}" y="{y - 14}" text-anchor="middle" '
                     f'class="chart-marker">Score {score}</text>')
    legend_col_w = width / len(bands)
    for i, ((_upper, label), color) in enumerate(zip(bands, colors)):
        lx = i * legend_col_w
        segments.append(f'<rect x="{lx:.1f}" y="{legend_y}" width="10" height="10" rx="2" fill="{color}"/>')
        segments.append(f'<text x="{lx + 14:.1f}" y="{legend_y + 9}" class="chart-label">{_esc(label)}</text>')
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
            f'xmlns="http://www.w3.org/2000/svg">{"".join(segments)}</svg>')


def render_html(name, metrics, weights, score, classification, breakdown, effort, productivity_source):
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    badge_colors = {"Tiny": "#60a5fa", "Small": "#3b82f6", "Medium": "#2563eb",
                    "Large": "#f59e0b", "Enterprise": "#ef4444"}
    badge_color = badge_colors.get(classification, "#2563eb")

    sloc_items = sorted(metrics["sloc_by_lang"].items(), key=lambda kv: -kv[1])
    breakdown_items = list(breakdown.items())
    effort_items = [("Java", effort["java_person_months"]), ("Node (TS+JS)", effort["node_person_months"])]

    def stat_card(label, value, sub="", accent=False):
        cls = "card accent" if accent else "card"
        return (f'<div class="{cls}"><div class="card-label">{_esc(label)}</div>'
                f'<div class="card-value">{_esc(value)}</div>'
                f'<div class="card-sub">{_esc(sub)}</div></div>')

    def table_section(title, rows):
        trs = "".join(f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in rows)
        return f'<div class="panel"><h3>{_esc(title)}</h3><table>{trs}</table></div>'

    architecture_rows = [
        ("Modules", metrics["modules"]), ("Microservices", metrics["microservices"]),
        ("REST APIs", metrics["rest_apis"]), ("GraphQL APIs", metrics["graphql_apis"]),
        ("Camel Routes", metrics["camel_routes"]), ("Kafka Topics", metrics["kafka_topics"]),
    ]
    data_rows = [
        ("Database Tables", metrics["db_tables"]), ("Entities", metrics["entities"]),
        ("OpenAPI Specs", metrics["openapi_specs"]), ("AsyncAPI Specs", metrics["asyncapi_specs"]),
    ]
    cloud_rows = [
        ("Deployments", metrics["deployments"]), ("StatefulSets", metrics["statefulsets"]),
        ("CronJobs", metrics["cronjobs"]), ("Helm Charts", metrics["helm_charts"]),
        ("Operators", metrics["operators"]),
    ]
    complexity_rows = [
        ("Average CC", metrics["avg_cc"] if metrics["avg_cc"] is not None else "N/A"),
        ("Maximum CC", metrics["max_cc"] if metrics["max_cc"] is not None else "N/A"),
        ("Coverage", f"{metrics['coverage']}%" if metrics["coverage"] is not None else "N/A"),
    ]
    dependency_rows = [
        ("Maven Modules", metrics["maven_modules"]), ("Node Packages", metrics["node_packages"]),
        ("Container Images", metrics["container_images"]),
    ]

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Software Size Report - {_esc(name)}</title>
<style>
  :root {{ --accent: {badge_color}; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Hiragino Sans", "Yu Gothic", "Segoe UI", sans-serif;
          margin: 0; background: #f3f4f6; color: #111827; }}
  header {{ background: #111827; color: #fff; padding: 28px 32px; }}
  header h1 {{ margin: 0 0 4px; font-size: 22px; }}
  header .meta {{ opacity: .65; font-size: 13px; }}
  main {{ max-width: 1080px; margin: 0 auto; padding: 24px 32px 60px; }}
  .hero {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 24px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 16px 20px; flex: 1 1 150px;
           box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .card-label {{ font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: .04em; }}
  .card-value {{ font-size: 26px; font-weight: 700; margin-top: 4px; }}
  .card-sub {{ font-size: 12px; color: #9ca3af; margin-top: 2px; }}
  .card.accent .card-value {{ color: var(--accent); }}
  .panel {{ background: #fff; border-radius: 12px; padding: 20px 24px; margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .panel h2 {{ margin-top: 0; font-size: 16px; }}
  .panel h3 {{ margin-top: 0; font-size: 14px; color: #374151; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ text-align: left; padding: 6px 4px; border-bottom: 1px solid #f3f4f6; }}
  th {{ font-weight: 500; color: #6b7280; width: 60%; }}
  .chart-label {{ font-size: 12px; fill: #374151; }}
  .chart-value {{ font-size: 12px; fill: #111827; }}
  .chart-marker {{ font-size: 12px; fill: #111827; font-weight: 600; }}
  .note {{ font-size: 12px; color: #9ca3af; margin-top: 10px; line-height: 1.7; }}
  @media (max-width: 720px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<header>
  <h1>Software Size Report - {_esc(name)}</h1>
  <div class="meta">Generated {generated}</div>
</header>
<main>
  <section class="hero">
    {stat_card("Software Size Score", score, "weighted score", accent=True)}
    {stat_card("Classification", classification, "Tiny / Small / Medium / Large / Enterprise", accent=True)}
    {stat_card("Total SLOC", f"{metrics['total_sloc']:,}", f"{metrics['files']:,} files")}
    {stat_card("Effort: Java", f"{effort['java_person_months']} 人月", f"{effort['java_sloc']:,} SLOC")}
    {stat_card("Effort: Node", f"{effort['node_person_months']} 人月", f"{effort['node_sloc']:,} SLOC (TS+JS)")}
    {stat_card("Effort: Total", f"{effort['total_person_months']} 人月", "Java + Node", accent=True)}
  </section>

  <div class="panel">
    <h2>Size Classification</h2>
    {_svg_gauge(score, SIZE_BANDS)}
  </div>

  <div class="grid-2">
    <div class="panel">
      <h2>SLOC by Language</h2>
      {_svg_bar_chart(sloc_items, unit=" SLOC")}
    </div>
    <div class="panel">
      <h2>Score Breakdown by Weight Category</h2>
      {_svg_bar_chart(breakdown_items, unit=" pt", color="#10b981")}
    </div>
  </div>

  <div class="panel">
    <h2>Effort Estimate (Person-Months)</h2>
    {_svg_bar_chart(effort_items, unit=" 人月", color="#8b5cf6")}
    <p class="note">
      Productivity source: {_esc(productivity_source)} &middot;
      hours per person-month: {effort['hours_per_person_month']}<br>
      Default rates come from IPA's overall, mixed-language SLOC productivity table
      (no official per-language Java/Node split exists) &mdash; pass --productivity to
      plug in your own company's measured rates. Treat as a rough-order-of-magnitude estimate.
    </p>
  </div>

  <div class="grid-2">
    {table_section("Architecture", architecture_rows)}
    {table_section("Data", data_rows)}
    {table_section("Cloud Native", cloud_rows)}
    {table_section("Complexity", complexity_rows)}
  </div>
  {table_section("Dependencies", dependency_rows)}

  <p class="note">
    Metrics are collected via regex-based heuristics, not a certified static analyzer &mdash;
    use for relative size comparison, not code-quality audits. Vendored/third-party code
    inflates SLOC and effort if not excluded before scanning.
  </p>
</main>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def collect_metrics(root):
    sloc_by_lang = {k: v for k, v in count_sloc(root).items()
                     if k in ("Java", "TypeScript", "JavaScript", "Python", "Go", "YAML", "SQL", "Shell", "Markdown")}
    total_sloc = sum(sloc_by_lang.values())
    files = sum(1 for _ in walk_files(root))

    module_dirs = find_module_dirs(root)
    microservice_dirs = find_microservice_dirs(root)
    rest_apis = count_rest_apis(root)
    graphql_apis = count_graphql_apis(root)
    camel_routes = count_camel_routes(root)
    kafka_topics = count_kafka_topics(root)
    db_tables = count_db_tables(root)
    entities = count_entities(root)
    openapi_specs, asyncapi_specs = count_api_specs(root)
    kinds = count_k8s_kinds(root)
    helm_charts = count_helm_charts(root)
    operators = count_operators(root)
    avg_cc, max_cc = compute_complexity(root)
    coverage = find_coverage(root)
    maven_modules = count_maven_modules(root)
    node_packages = count_node_packages(root)
    container_images = count_container_images(root)

    return {
        "sloc_by_lang": sloc_by_lang,
        "total_sloc": total_sloc,
        "files": files,
        "modules": len(module_dirs),
        "microservices": len(microservice_dirs),
        "rest_apis": rest_apis,
        "graphql_apis": graphql_apis,
        "camel_routes": camel_routes,
        "kafka_topics": kafka_topics,
        "db_tables": db_tables,
        "entities": entities,
        "openapi_specs": openapi_specs,
        "asyncapi_specs": asyncapi_specs,
        "deployments": kinds.get("Deployment", 0),
        "statefulsets": kinds.get("StatefulSet", 0),
        "cronjobs": kinds.get("CronJob", 0),
        "helm_charts": helm_charts,
        "operators": operators,
        "avg_cc": avg_cc,
        "max_cc": max_cc,
        "coverage": coverage,
        "maven_modules": maven_modules,
        "node_packages": node_packages,
        "container_images": container_images,
    }


def main():
    parser = argparse.ArgumentParser(description="Measure software size and compute a weighted size score.")
    parser.add_argument("path", nargs="?", default=".", help="Directory to scan (default: current directory)")
    parser.add_argument("--name", help="Project name shown in the report (default: directory name)")
    parser.add_argument("--json", action="store_true", help="Also print raw metrics + score as JSON")
    parser.add_argument("--weights", help="JSON file overriding the default weight table")
    parser.add_argument("--effort", action="store_true",
                         help="Print the Java/Node person-months estimate in the text report")
    parser.add_argument("--productivity", help="JSON file overriding the default person-months productivity table")
    parser.add_argument("--html", help="Write a self-contained HTML report (with charts) to this path")
    args = parser.parse_args()

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        sys.exit(f"error: no such directory: {root}")
    name = args.name or os.path.basename(root.rstrip("/"))

    weights = dict(DEFAULT_WEIGHTS)
    if args.weights:
        with open(args.weights) as f:
            weights.update(json.load(f))

    productivity = load_productivity(args.productivity)
    productivity_source = args.productivity or "built-in default (IPA 表A1-2-4)"

    metrics = collect_metrics(root)
    score, breakdown = compute_score(metrics, weights)
    classification = classify(score)
    effort = compute_effort(metrics, productivity)

    print(render_report(name, metrics, weights, score, classification))

    if args.effort:
        print(render_effort_section(effort, productivity_source))

    if args.html:
        html = render_html(name, metrics, weights, score, classification, breakdown, effort, productivity_source)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nHTML report written to {args.html}")

    if args.json:
        print()
        print(json.dumps({
            "name": name, "metrics": metrics, "weights": weights,
            "breakdown": breakdown, "score": score, "classification": classification,
            "effort": effort,
        }, indent=2, default=str))


if __name__ == "__main__":
    main()
