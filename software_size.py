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
                              [--ai] [--ai-since WHEN] [--ai-metrics FILE]

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
    --ai                 Add an AI Development section: Lines Added/Deleted,
                         a refactor-ratio heuristic and an AI-coauthored-
                         commit ratio, all computed from git log across every
                         repo found under PATH.
    --ai-since WHEN      Limit --ai's git history (e.g. "90 days ago").
                         Recommended for large/vendored histories.
    --ai-metrics FILE    JSON with externally-measured AI metrics that git
                         cannot provide (AI Generated SLOC, assistant accept
                         rate, review/coding time, prompt count, test
                         generation ratio) -- see ai-metrics.example.json.
                         Never estimated; omitted from the report if not given.
                         If the file sets "ai_productivity_factor", it is
                         applied to Base PM (see Notes) whether or not --ai
                         is also passed.

Notes:
    - Person-months are estimated from a size-banded SLOC-productivity table
      (default: IPA's "ソフトウェア開発分析データ集2022" 表A1-2-4, 新規開発:
      全年度, n=1,246 -- IPA does not publish a per-language breakdown, so
      the same table is applied to Java SLOC and Node SLOC separately by
      default). Pass --productivity to plug in your own company's measured
      rates per language. Treat the result as a rough-order-of-magnitude
      estimate, not a committed estimate. This is the "Base PM" -- the
      estimation model, reproducible from SLOC + productivity table alone,
      meant for contracts/planning.
    - The estimation model (Base PM) and the AI diagnostic (--ai) are kept
      deliberately separate: a quality/readiness-style score is never used to
      adjust PM, because that would make the estimate hard to reproduce or
      explain ("why 16.8 PM?"). The only way AI affects PM is an explicit,
      user-supplied "ai_productivity_factor" in --ai-metrics (a plain
      multiplier: Adjusted PM = Base PM x APF) -- fully deterministic and
      auditable, and Base PM is always shown alongside it, unchanged.
    - --ai only reports what's verifiable from git (line churn, a refactor
      heuristic, and AI-coauthor commit trailers). It does not estimate
      "AI Generated Code %", "Copilot Accept Rate", "Prompt Count" or
      "Review Time" -- those need telemetry from your AI coding tool, which
      you supply via --ai-metrics.
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
# AI development metrics (git-derived, opt-in via --ai)
# ---------------------------------------------------------------------------
#
# What's actually measurable from git alone: Lines Added/Deleted (git log
# --numstat), a refactoring-ratio heuristic, and an AI-coauthored-commit ratio
# (via "Co-Authored-By: <tool>" trailers, which Claude Code and some other
# tools add automatically). There is no reliable local signal for "AI
# Generated SLOC %", "Copilot Accept Rate", "Prompt Count" or "Review Time" --
# those require telemetry from the AI tool itself (Copilot Metrics API,
# Cursor analytics, IDE plugin logs). Rather than estimate them, this tool
# only reports them if supplied via --ai-metrics FILE (see
# ai-metrics.example.json); otherwise they're shown as not available.

AI_COAUTHOR_PATTERN = re.compile(
    r"co-authored-by:.*(claude|copilot|codeium|cursor|chatgpt|gpt-|openai|gemini|"
    r"devin|windsurf|tabnine|codewhisperer|amazon\s*q|jules|replit)",
    re.IGNORECASE,
)
REFACTOR_KEYWORD_PATTERN = re.compile(r"\brefactor\w*\b", re.IGNORECASE)

# Metrics that require external AI-tool telemetry; only populated from
# --ai-metrics FILE, never estimated.
EXTERNAL_AI_FIELDS = [
    ("ai_generated_sloc", "AI Generated SLOC"),
    ("ai_generated_ratio_pct", "AI Generated Ratio (%)"),
    ("copilot_accept_rate_pct", "Assistant Accept Rate (%)"),
    ("estimated_review_hours", "Estimated Review Time (h)"),
    ("estimated_coding_hours", "Estimated Coding Time (h)"),
    ("prompt_count", "Prompt Count"),
    ("test_generation_ratio_pct", "Test Generation Ratio (%)"),
]

# Supporting context for a human-judged "ai_productivity_factor" -- purely
# informational (shown next to APF so the number is auditable). The tool
# never computes APF from these; the value in ai-metrics.json is entered by
# whoever is best placed to judge it (see README: "入力者の判断にまかせる").
AI_PRODUCTIVITY_BASIS_FIELDS = [
    ("ai_generated_ratio_pct", "AI Generated Ratio (%)"),
    ("copilot_accept_rate_pct", "AI Accept Rate (%)"),
    ("ai_test_generation_used", "AI Test Generation"),
    ("ai_review_used", "AI Review Used"),
    ("ai_refactoring_used", "AI Refactoring Used"),
]


def _fmt_basis_value(value):
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return value


def _run_git(repo_dir, args, timeout=90):
    try:
        out = subprocess.run(["git", "-C", repo_dir] + args, capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    return out.stdout if out.returncode == 0 else None


def find_git_repo_dirs(root):
    """Repo roots under `root` (just [root] if root itself is already a repo).

    This tool commonly scans a multi-repo workspace where every subproject
    has its own .git, so we discover and aggregate across all of them.
    """
    if _run_git(root, ["rev-parse", "--is-inside-work-tree"]) is not None:
        return [root]
    repo_dirs = []
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames or ".git" in filenames:
            repo_dirs.append(dirpath)
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
    return repo_dirs


def _parse_git_log(raw):
    commits = []
    for chunk in raw.split("\x01"):
        if not chunk.strip():
            continue
        try:
            commit_hash, rest = chunk.split("\x02", 1)
            body, numstat_block = rest.split("\x03", 1)
        except ValueError:
            continue
        added = deleted = 0
        for line in numstat_block.splitlines():
            parts = line.strip().split("\t")
            if len(parts) < 3 or parts[0] == "-" or parts[1] == "-":
                continue  # binary file or malformed line
            added += int(parts[0])
            deleted += int(parts[1])
        first_line = body.splitlines()[0] if body.strip() else ""
        commits.append({
            "hash": commit_hash.strip(),
            "added": added,
            "deleted": deleted,
            "is_ai_coauthored": bool(AI_COAUTHOR_PATTERN.search(body)),
            "is_refactor_keyword": bool(REFACTOR_KEYWORD_PATTERN.search(first_line)),
        })
    return commits


def git_ai_stats(root, since=None):
    """Aggregate Lines Added/Deleted, refactor ratio and AI-coauthor-commit
    ratio across every git repo found under `root`. Returns None if no git
    repo is found under the scanned path.
    """
    repo_dirs = find_git_repo_dirs(root)
    if not repo_dirs:
        return None

    all_commits = []
    skipped = 0
    log_args = ["log", "--no-merges", "--numstat", "--pretty=format:%x01%H%x02%B%x03"]
    if since:
        log_args += [f"--since={since}"]
    for repo_dir in repo_dirs:
        raw = _run_git(repo_dir, log_args)
        if raw is None:
            skipped += 1
            continue
        all_commits.extend(_parse_git_log(raw))

    if not all_commits:
        return {"repo_count": len(repo_dirs), "skipped_repos": skipped, "commit_count": 0}

    total_added = sum(c["added"] for c in all_commits)
    total_deleted = sum(c["deleted"] for c in all_commits)
    total_churn = total_added + total_deleted
    balanced_churn = sum(2 * min(c["added"], c["deleted"]) for c in all_commits)
    refactor_commits = [c for c in all_commits if c["is_refactor_keyword"]]
    ai_commits = [c for c in all_commits if c["is_ai_coauthored"]]
    ai_added = sum(c["added"] for c in ai_commits)

    return {
        "repo_count": len(repo_dirs),
        "skipped_repos": skipped,
        "commit_count": len(all_commits),
        "lines_added": total_added,
        "lines_deleted": total_deleted,
        "net_lines": total_added - total_deleted,
        "refactor_keyword_commits": len(refactor_commits),
        "refactor_keyword_ratio_pct": round(len(refactor_commits) / len(all_commits) * 100, 1),
        "balanced_churn_refactor_ratio_pct": round(balanced_churn / total_churn * 100, 1) if total_churn else 0.0,
        "ai_coauthored_commits": len(ai_commits),
        "ai_coauthored_commit_ratio_pct": round(len(ai_commits) / len(all_commits) * 100, 1),
        "ai_coauthored_lines_added": ai_added,
        "ai_coauthored_lines_ratio_pct": round(ai_added / total_added * 100, 1) if total_added else 0.0,
    }


def load_external_ai_metrics(path):
    if not path:
        return None
    with open(path) as f:
        return json.load(f)


def render_ai_section(git_stats, external_metrics, external_source):
    lines = []
    add = lines.append
    add("")
    add("AI Development (git-derived + optional external metrics)")
    add("-" * 60)
    if git_stats is None:
        add("No git repository found under the scanned path -- git-derived metrics")
        add("(Lines Added/Deleted, refactor ratio, AI-coauthor ratio) are unavailable.")
    elif git_stats.get("commit_count", 0) == 0:
        note = f" ({git_stats['skipped_repos']} skipped: timeout/error)" if git_stats.get("skipped_repos") else ""
        add(f"Found {git_stats['repo_count']} git repo(s){note} but no commits matched.")
    else:
        skipped_note = f" ({git_stats['skipped_repos']} skipped: timeout/error)" if git_stats.get("skipped_repos") else ""
        add(f"Repos analyzed    : {git_stats['repo_count']}{skipped_note}")
        add(f"Commits analyzed  : {git_stats['commit_count']:,}")
        add(f"Lines Added       : {git_stats['lines_added']:,}")
        add(f"Lines Deleted     : {git_stats['lines_deleted']:,}")
        add(f"Net Change        : {git_stats['net_lines']:+,}")
        add(f"Refactoring Ratio : {git_stats['balanced_churn_refactor_ratio_pct']}% "
            f"(balanced-churn heuristic: 2*min(added,deleted)/churn per commit)")
        add(f"                    {git_stats['refactor_keyword_ratio_pct']}% of commits mention "
            f"\"refactor\" in the message (keyword heuristic)")
        add(f"AI Co-authored    : {git_stats['ai_coauthored_commit_ratio_pct']}% of commits "
            f"({git_stats['ai_coauthored_commits']:,}/{git_stats['commit_count']:,}), "
            f"{git_stats['ai_coauthored_lines_ratio_pct']}% of lines added")
        add("  * Detected via 'Co-Authored-By: <tool>' commit trailers (Claude, Copilot,")
        add("    Cursor, etc.). Tools that don't add commit trailers (e.g. plain")
        add("    autocomplete) are undercounted -- this is a lower bound, not a")
        add("    precise measurement of AI involvement.")
    add("")
    if external_metrics:
        add(f"External AI metrics (source: {external_source})")
        for key, label in EXTERNAL_AI_FIELDS:
            if key in external_metrics and external_metrics[key] is not None:
                add(f"  {label:<28}: {external_metrics[key]}")
    else:
        add("External AI metrics: not provided.")
        add("  AI Generated SLOC/Ratio, Assistant Accept Rate, Review/Coding Time,")
        add("  Prompt Count and Test Generation Ratio require telemetry from your AI")
        add("  coding tool (e.g. GitHub Copilot Metrics API, Cursor analytics) -- pass")
        add("  --ai-metrics FILE to include them (see ai-metrics.example.json).")
    return "\n".join(lines)


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


def apply_ai_productivity_factor(effort, apf, apf_source):
    """Applies an explicit AI Productivity Factor (APF) multiplier to Base PM.

    APF is a plain, user-supplied number (via --ai-metrics), never derived from
    a quality/readiness score -- this keeps the estimation model (SLOC ->
    Base PM, used for contracts/planning) reproducible and explainable:
    Adjusted PM = Base PM x APF, full stop. The unadjusted Base PM fields are
    left untouched so both numbers remain visible.
    """
    adjusted = dict(effort)
    adjusted["ai_productivity_factor"] = apf
    adjusted["ai_productivity_factor_source"] = apf_source
    adjusted["java_person_months_adjusted"] = round(effort["java_person_months"] * apf, 1)
    adjusted["node_person_months_adjusted"] = round(effort["node_person_months"] * apf, 1)
    adjusted["total_person_months_adjusted"] = round(effort["total_person_months"] * apf, 1)
    return adjusted


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

def render_report(name, metrics, weights, score, classification, effort=None, productivity_source=None,
                  ai_external=None):
    """Renders the text report summary-first: headline Summary, then details."""
    lines = []
    add = lines.append
    add("Software Size Summary")
    add("=" * 21)
    add("")
    add("Summary")
    add("-------")
    add(f"Name           : {name}")
    add(f"Score          : {score} points -> {classification}")
    add(f"SLOC           : {metrics['total_sloc']:,}")
    add(f"Files          : {metrics['files']:,}")
    add("Size Bands     : Tiny(<100) / Small(100-300) / Medium(300-700) / Large(700-1500) / Enterprise(1500+)")
    if effort is not None:
        add("")
        add(f"Effort Estimate (productivity: {productivity_source})")
        add(f"  Java SLOC    : {effort['java_sloc']:,}  (rate {effort['java_rate']} SLOC/人時) "
            f"-> {effort['java_person_months']} 人月")
        add(f"  Node SLOC    : {effort['node_sloc']:,}  (TS+JS, rate {effort['node_rate']} SLOC/人時) "
            f"-> {effort['node_person_months']} 人月")
        add(f"  Total        : {effort['total_person_months']} 人月  <- Base PM (contract/planning figure)")
        add("  * Default rates are IPA's overall size-banded median (no official")
        add("    per-language split exists). Pass --productivity for your own rates.")
        if "ai_productivity_factor" in effort:
            apf = effort["ai_productivity_factor"]
            add("")
            add(f"  APF (AI Productivity Factor): {apf}  (source: {effort['ai_productivity_factor_source']})")
            add(f"  Estimated PM (AI-adjusted)  : {effort['total_person_months_adjusted']} 人月  "
                f"(= {effort['total_person_months']} base x {apf})")
            add(f"    Java: {effort['java_person_months_adjusted']} 人月, "
                f"Node: {effort['node_person_months_adjusted']} 人月")
            add("  * APF is a plain user-supplied multiplier, not derived from any quality/")
            add("    readiness score -- Base PM above is unchanged and remains the number to")
            add("    use for contracts; this adjusted figure is a separate, explicit estimate.")
            if ai_external:
                basis = [(label, ai_external[key]) for key, label in AI_PRODUCTIVITY_BASIS_FIELDS
                         if key in ai_external and ai_external[key] is not None]
                if basis:
                    add("  Basis (judged by whoever set APF, not computed by this tool):")
                    for label, value in basis:
                        add(f"    {label:<24}: {_fmt_basis_value(value)}")
                if ai_external.get("ai_productivity_factor_note"):
                    add(f"  Note: {ai_external['ai_productivity_factor_note']}")
    add("")
    add("Project")
    add("-------")
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


def render_html(name, metrics, weights, score, classification, breakdown, effort, productivity_source,
                ai_stats=None, ai_external=None, ai_external_source=None, apf_context=None):
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    badge_colors = {"Tiny": "#60a5fa", "Small": "#3b82f6", "Medium": "#2563eb",
                    "Large": "#f59e0b", "Enterprise": "#ef4444"}
    badge_color = badge_colors.get(classification, "#2563eb")

    sloc_items = sorted(metrics["sloc_by_lang"].items(), key=lambda kv: -kv[1])
    breakdown_items = list(breakdown.items())
    effort_items = [("Java", effort["java_person_months"]), ("Node (TS+JS)", effort["node_person_months"])]
    apf_block = ""
    if "ai_productivity_factor" in effort:
        apf = effort["ai_productivity_factor"]
        adjusted_items = [("Base PM", effort["total_person_months"]),
                           ("AI-adjusted PM", effort["total_person_months_adjusted"])]
        basis_html = ""
        if apf_context:
            basis_rows = [(label, _fmt_basis_value(apf_context[key])) for key, label in AI_PRODUCTIVITY_BASIS_FIELDS
                          if key in apf_context and apf_context[key] is not None]
            if basis_rows:
                basis_trs = "".join(f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in basis_rows)
                basis_html += f'<p class="note">Basis (judged by whoever set APF, not computed by this tool):</p><table>{basis_trs}</table>'
            if apf_context.get("ai_productivity_factor_note"):
                basis_html += f'<p class="note">Note: {_esc(apf_context["ai_productivity_factor_note"])}</p>'
        apf_block = f"""
    <h3>AI Productivity Factor (APF): {apf} (source: {_esc(effort['ai_productivity_factor_source'])})</h3>
    {_svg_bar_chart(adjusted_items, unit=" 人月", color="#059669")}
    <p class="note">
      Estimated PM (AI-adjusted) = {effort['total_person_months']} base &times; {apf} =
      {effort['total_person_months_adjusted']} 人月 (Java {effort['java_person_months_adjusted']},
      Node {effort['node_person_months_adjusted']}).<br>
      APF is a plain user-supplied multiplier, not derived from any quality/readiness score &mdash;
      Base PM above is unchanged and remains the contract/planning figure; this adjusted figure is
      a separate, explicit estimate.
    </p>
    {basis_html}"""
    show_ai = ai_stats is not None or ai_external is not None

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

    ai_panel_html = ""
    if show_ai:
        if ai_stats and ai_stats.get("commit_count"):
            churn_items = [("Lines Added", ai_stats["lines_added"]), ("Lines Deleted", ai_stats["lines_deleted"])]
            coauthor_items = [
                ("AI Co-authored", ai_stats["ai_coauthored_commits"]),
                ("Human-only", ai_stats["commit_count"] - ai_stats["ai_coauthored_commits"]),
            ]
            git_block = f"""
            <div class="grid-2">
              <div>
                <h3>Lines Added / Deleted ({ai_stats['commit_count']:,} commits, {ai_stats['repo_count']} repo(s))</h3>
                {_svg_bar_chart(churn_items, unit=" lines", color="#0891b2")}
              </div>
              <div>
                <h3>Commits by Co-authorship</h3>
                {_svg_bar_chart(coauthor_items, unit=" commits", color="#7c3aed")}
              </div>
            </div>
            <p class="note">
              Refactoring ratio: {ai_stats['balanced_churn_refactor_ratio_pct']}% (balanced-churn heuristic:
              2&times;min(added,deleted)/churn per commit) &middot;
              {ai_stats['refactor_keyword_ratio_pct']}% of commits mention "refactor" in the message.<br>
              AI co-authored: {ai_stats['ai_coauthored_commit_ratio_pct']}% of commits,
              {ai_stats['ai_coauthored_lines_ratio_pct']}% of lines added &mdash; detected via
              "Co-Authored-By: &lt;tool&gt;" commit trailers (Claude, Copilot, Cursor, etc.). Tools that
              don't add commit trailers (plain autocomplete) are undercounted; treat this as a lower bound,
              not a precise measurement.
            </p>"""
        else:
            git_block = '<p class="note">No git repository found under the scanned path, or no commits matched.</p>'

        if ai_external:
            ext_rows = [(label, ai_external[key]) for key, label in EXTERNAL_AI_FIELDS
                        if key in ai_external and ai_external[key] is not None]
            ext_block = (table_section(f"External AI Metrics (source: {ai_external_source})", ext_rows)
                         if ext_rows else "")
        else:
            ext_block = ("""<p class="note">
              External AI metrics not provided. AI Generated SLOC/Ratio, Assistant Accept Rate,
              Review/Coding Time, Prompt Count and Test Generation Ratio require telemetry from your
              AI coding tool (e.g. GitHub Copilot Metrics API, Cursor analytics) &mdash; pass
              --ai-metrics FILE to include them (see ai-metrics.example.json).
            </p>""")

        ai_panel_html = f"""
  <div class="panel">
    <h2>AI Development</h2>
    {git_block}
    {ext_block}
  </div>"""

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
    {apf_block}
  </div>
  {ai_panel_html}
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
    parser.add_argument("--ai", action="store_true",
                         help="Add an AI Development section (git-derived Lines Added/Deleted, "
                              "refactor ratio, AI-coauthored-commit ratio, plus --ai-metrics if given)")
    parser.add_argument("--ai-since", help='Limit git history for --ai, e.g. "90 days ago" '
                                            "(recommended for large/vendored histories -- full history "
                                            "on a big repo can take a minute or more)")
    parser.add_argument("--ai-metrics", help="JSON file with externally-measured AI metrics "
                                              "(see ai-metrics.example.json); not estimated if omitted")
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

    # --ai-metrics is independent of --ai: an explicit AI Productivity Factor
    # adjusts the estimation model (Base PM -> Adjusted PM) whether or not the
    # --ai diagnostic section (git-derived churn/refactor/coauthor stats) is
    # requested. The two are kept deliberately separate -- see README.
    ai_external = load_external_ai_metrics(args.ai_metrics)
    if ai_external and ai_external.get("ai_productivity_factor") is not None:
        effort = apply_ai_productivity_factor(effort, ai_external["ai_productivity_factor"], args.ai_metrics)

    print(render_report(name, metrics, weights, score, classification,
                        effort if args.effort else None, productivity_source, ai_external))

    ai_stats = None
    if args.ai:
        ai_stats = git_ai_stats(root, since=args.ai_since)
        print(render_ai_section(ai_stats, ai_external, args.ai_metrics))

    if args.html:
        # The AI Development panel (git churn/refactor/coauthor stats) only
        # shows when --ai was requested; an APF-only run (--ai-metrics without
        # --ai) still adjusts the Effort panel above via `effort` itself.
        html = render_html(name, metrics, weights, score, classification, breakdown, effort, productivity_source,
                            ai_stats=ai_stats if args.ai else None,
                            ai_external=ai_external if args.ai else None,
                            ai_external_source=args.ai_metrics,
                            apf_context=ai_external)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nHTML report written to {args.html}")

    if args.json:
        print()
        print(json.dumps({
            "name": name, "metrics": metrics, "weights": weights,
            "breakdown": breakdown, "score": score, "classification": classification,
            "effort": effort,
            "ai": {"git_stats": ai_stats, "external_metrics": ai_external} if (args.ai or ai_external) else None,
        }, indent=2, default=str))


if __name__ == "__main__":
    main()
