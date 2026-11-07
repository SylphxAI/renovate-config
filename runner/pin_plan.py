"""Pure discovery and reporting for shared ``SylphxAI/.github`` pin rolls.

No clock, filesystem, network or mutation lives here. Offsets are Python string
indices in the supplied UTF-8-decoded text; ``text[start:end]`` is exactly the
existing SHA. ``match`` is an exact source fragment for Renovate, not rewritten
YAML. Findings are retained as pin records with ``sha=None``.

Change records have sha, merged_at (aware datetime or ISO-8601), files, and an
optional number. Ancestry must be supplied by the caller: ``behind_pins`` lists
pins proven strictly behind that change; ``included_by_pins`` lists pins proven
to contain it. Unequal SHAs never establish ancestry. Missing evidence is a
finding, not an urgent roll or a lag breach.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase
from itertools import product
import re
from typing import Any

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

SOURCE = "SylphxAI/.github"
FULL_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
REPOSITORY = re.compile(r"`([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)`")


def parse_active_portfolio(text: str) -> list[str]:
    """Read only Repository cells of Drive/Maintain Markdown tables.

    Foundation-support repositories and multiple current repositories in a cell
    count. Prose, Owns-cell references, historical sections and former names in
    parentheses do not. Explicit paused/parked/retired/archived/delivered rows
    are excluded, but frozen serving Maintain products are not.
    """
    active = False
    columns: list[str] = []
    repositories: set[str] = set()
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*#*\s*$", line)
        if heading:
            title = heading.group(1)
            active = bool(re.match(r"(?:Drive|Maintain)\b", title))
            columns = []
            continue
        if not active or not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if "Repository" in cells:
            columns = cells
            continue
        if not columns or len(cells) != len(columns):
            continue
        row = dict(zip(columns, cells))
        if not re.fullmatch(r"\d+", row.get("#", "")):
            continue
        status = " ".join(row.get(key, "") for key in ("Product", "State", "Repository"))
        if re.search(r"\b(paused|parked|retired|archived|delivered)\b", status, re.I):
            continue
        owns = row.get("Owns", "")
        plain_owns = re.sub(r"[*`]", "", owns).strip()
        if (re.match(r"(?:paused|parked|retired|archived|delivered)\b", plain_owns, re.I)
                or re.search(r"\b(?:paused|parked)\s*[:(]", plain_owns, re.I)
                or re.search(r"sylphx_delivery\s*=\s*delivered", plain_owns, re.I)):
            continue
        cell = row["Repository"]
        # Former names are parenthetical in portfolio.md; strip only those
        # annotations, not the current repositories outside the parentheses.
        while re.search(r"\([^()]*\)", cell):
            cell = re.sub(r"\([^()]*\)", "", cell)
        repositories.update(REPOSITORY.findall(cell))
    return sorted(repositories, key=str.casefold)


def _mapping(node: Any) -> dict[str, Any]:
    return {key.value: value for key, value in node.value if isinstance(key, ScalarNode)} if isinstance(node, MappingNode) else {}


def _scalar(node: Any, default: str = "") -> str:
    return node.value if isinstance(node, ScalarNode) else default


def _walk(node: Any, sequence: SequenceNode | None = None, seen: set[int] | None = None):
    seen = set() if seen is None else seen
    if node is None or id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, MappingNode):
        yield node, sequence
        for _, value in node.value:
            yield from _walk(value, None, seen)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            yield from _walk(value, node, seen)


def _scalar_values(node: Any, seen: set[int] | None = None):
    seen = set() if seen is None else seen
    if node is None or id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, ScalarNode):
        yield node.value
    elif isinstance(node, SequenceNode):
        for value in node.value:
            yield from _scalar_values(value, seen)
    elif isinstance(node, MappingNode):
        for _, value in node.value:
            yield from _scalar_values(value, seen)


def _root(path: str) -> str:
    path = path.removeprefix("./").rstrip("/")
    action = re.match(r"(\.github/actions/[^/]+)(?:/|$)", path)
    return action.group(1) if action else path


def _checkout_roots(step: MappingNode, sequence: SequenceNode | None, destination: str) -> list[str]:
    if not sequence or not destination or "${{" in destination:
        return [""]
    destination = destination.removeprefix("./").rstrip("/")
    pattern = re.compile(r"(?<![\w.-])(?:\./)?" + re.escape(destination) + r"/([\w.+/-]+)")
    roots = set()
    later = False
    for other in sequence.value:
        if other is step:
            later = True
            continue
        if not later:
            continue
        values = _mapping(other)
        with_values = _mapping(values.get("with"))
        if (_scalar(values.get("uses")).lower().startswith("actions/checkout@")
                and _scalar(with_values.get("path")).removeprefix("./").rstrip("/") == destination):
            break  # A later materialization owns this destination now.
        for value in _scalar_values(other):
            for match in pattern.finditer(value):
                relative = match.group(1).rstrip("/.")
                if relative and not any(part == ".." for part in relative.split("/")):
                    roots.add(_root(relative))
    return sorted(roots) or [""]


def _fragment(text: str, node: Any, multiline: bool) -> tuple[int, int, str]:
    begin = text.rfind("\n", 0, node.start_mark.index) + 1
    if multiline:
        end = node.end_mark.index
        # Mapping end marks may contain the next step's leading indentation.
        end = begin + len(text[begin:end].rstrip())
    else:
        end = text.find("\n", node.end_mark.index)
        if end < 0:
            end = len(text)
    return begin, end, text[begin:end]


def _pin(text: str, path: str, kind: str, ref: str, roots: list[str], value_node: Any, context_node: Any) -> dict:
    match_start, match_end, fragment = _fragment(text, context_node, kind == "checkout")
    immutable = bool(FULL_SHA.fullmatch(ref))
    start = text.find(ref, value_node.start_mark.index, value_node.end_mark.index) if ref else -1
    if immutable and start < 0:
        immutable = False  # Escaped YAML scalars need a different updater.
    return {
        "path": path, "kind": kind, "ref": ref,
        "sha": ref if immutable else None,
        "roots": roots, "consumed_roots": roots,
        "start": start if immutable else None,
        "end": start + len(ref) if immutable else None,
        "match_start": match_start, "match_end": match_end, "match": fragment,
        "finding": None if immutable else "non_immutable_ref",
    }


def parse_pins(files: dict[str, str]) -> list[dict]:
    """Find real YAML uses scalars and actions/checkout source materializations.

    Quoted/block/flow YAML, either checkout field order, optional # main,
    action.yml and reusable workflows are supported. Strings embedded in run
    scripts and comments are not declarations. A malformed YAML file containing
    the shared source is retained as ``invalid_yaml`` rather than disappearing.
    Checkout roots come from later references in the same steps sequence; an
    unresolved consumption conservatively has root ``''`` (whole source).
    """
    pins: list[dict] = []
    for path, text in sorted(files.items()):
        if not path.lower().endswith((".yaml", ".yml")) or SOURCE.lower() not in text.lower():
            continue
        try:
            documents = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
        except yaml.YAMLError as exc:
            pins.append({"path": path, "kind": "invalid_yaml", "sha": None, "ref": None,
                         "roots": [""], "consumed_roots": [""], "start": None, "end": None,
                         "match": None, "match_start": None, "match_end": None,
                         "finding": "invalid_yaml", "detail": str(exc)})
            continue
        seen_offsets = set()
        for document in documents:
            for node, sequence in _walk(document):
                fields = _mapping(node)
                uses_node = fields.get("uses")
                uses = _scalar(uses_node)
                match = re.match(r"^SylphxAI/\.github/([^@\s]+)(?:@(.+))?$", uses, re.I)
                if match:
                    pin = _pin(text, path, "uses", match.group(2) or "", [_root(match.group(1))], uses_node, uses_node)
                    identity = (pin["match_start"], uses_node.start_mark.index)
                    if identity not in seen_offsets:
                        pins.append(pin)
                        seen_offsets.add(identity)
                if not uses.lower().startswith("actions/checkout@"):
                    continue
                with_fields = _mapping(fields.get("with"))
                if _scalar(with_fields.get("repository")).lower() != SOURCE.lower():
                    continue
                ref_node = with_fields.get("ref") or with_fields["repository"]
                ref = _scalar(with_fields.get("ref"))
                roots = _checkout_roots(node, sequence, _scalar(with_fields.get("path")))
                pin = _pin(text, path, "checkout", ref, roots, ref_node, node)
                identity = (pin["match_start"], ref_node.start_mark.index)
                if identity not in seen_offsets:
                    pins.append(pin)
                    seen_offsets.add(identity)
    return sorted(pins, key=lambda pin: (pin["path"], pin["match_start"] or 0))


def _date(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _affected(pin: dict, changed_files: list) -> bool:
    paths = [item.get("filename", "") if isinstance(item, dict) else str(item) for item in changed_files]
    for path in paths:
        path = path.removeprefix("./")
        # Shared helpers are transitive inputs to actions and workflows. Without
        # a source dependency graph, narrowing these would silently omit callers.
        if path.startswith("scripts/"):
            return True
        for root in pin["roots"]:
            if root == "" or path == root or path.startswith(root.rstrip("/") + "/"):
                return True
    return False


def _ancestry(pin: dict, change: dict) -> str:
    sha = (pin.get("sha") or "").lower()
    if not sha:
        return "unknown"
    if sha == str(change.get("sha", "")).lower():
        return "included"
    behind = {item.lower() for item in change.get("behind_pins", [])}
    included = {item.lower() for item in change.get("included_by_pins", [])}
    if sha in behind and sha in included:
        return "conflict"
    if sha in behind:
        return "behind"
    if sha in included:
        return "included"
    return "unknown"


def _path_matches(path: str, pattern: str) -> bool:
    # GitHub's **/ also matches zero directories, unlike fnmatch's literal /.
    patterns = {pattern}
    while any("**/" in item for item in patterns):
        expanded = {item.replace("**/", "", 1) for item in patterns if "**/" in item}
        new = expanded - patterns
        if not new:
            break
        patterns.update(new)
    return any(fnmatchcase(path, item) for item in patterns)


def _selected_path(path: str, patterns: list[str]) -> bool:
    selected = False
    for pattern in patterns:
        negative = pattern.startswith("!")
        if _path_matches(path, pattern[1:] if negative else pattern):
            selected = not negative
    return selected


def _matrix_count(job: dict) -> int | None:
    matrix = job.get("strategy", {}).get("matrix") if isinstance(job.get("strategy", {}), dict) else None
    if matrix is None:
        return 1
    if not isinstance(matrix, dict):
        return None
    axes = {key: values for key, values in matrix.items() if key not in ("include", "exclude")}
    if any(not isinstance(values, list) for values in axes.values()):
        return None
    if any("${{" in str(value) for value in matrix.values()):
        return None
    if not all(isinstance(item, dict) for key in ("include", "exclude") for item in matrix.get(key, [])):
        return None
    combinations = [dict(zip(axes, values)) for values in product(*axes.values())] if axes else []
    combinations = [combo for combo in combinations if not any(
        all(combo.get(key) == value for key, value in exclusion.items())
        for exclusion in matrix.get("exclude", []))]
    extra = sum(not any(all(key not in axes or combo.get(key) == value for key, value in item.items())
                            for combo in combinations) for item in matrix.get("include", []))
    return len(combinations) + extra


def estimate_pr_ci_jobs(files: dict[str, str], changed_paths: list[str]) -> dict:
    """Estimate static PR job expansions, never claim actual runner usage.

    Known finite matrices and local reusable workflows are expanded. Dynamic
    matrices and unavailable reusable workflows make the upper bound unknown;
    job conditions and branch/event filters are explicitly uncertain. The
    ``known_jobs`` count excludes unknown expansions, not a guess of one job per
    reusable invocation. Exact means exact *static expansion*, not execution.
    """
    workflows: dict[str, dict] = {}
    uncertainties: set[str] = set()
    for path, text in sorted(files.items()):
        if not path.startswith(".github/workflows/") or not path.endswith((".yml", ".yaml")):
            continue
        try:
            data = yaml.safe_load(text)
            if isinstance(data, dict):
                workflows[path] = data
        except yaml.YAMLError:
            uncertainties.add(f"{path}: invalid YAML; PR job count unknown")
    reusable_calls = 0
    dynamic_matrices = 0
    unknown_expansion = bool(uncertainties)

    def count(path: str, chain: tuple[str, ...] = ()) -> int:
        nonlocal reusable_calls, dynamic_matrices, unknown_expansion
        if path in chain or path not in workflows:
            unknown_expansion = True
            uncertainties.add(f"{path}: unavailable or recursive reusable workflow")
            return 0
        data = workflows[path]
        total = 0
        jobs = data.get("jobs", {})
        if not isinstance(jobs, dict):
            unknown_expansion = True
            uncertainties.add(f"{path}: invalid jobs mapping")
            return 0
        for name, job in jobs.items():
            if not isinstance(job, dict):
                unknown_expansion = True
                uncertainties.add(f"{path}:{name}: invalid job")
                continue
            condition = job.get("if")
            if condition is False or str(condition).strip() in ("false", "${{ false }}"):
                continue
            if condition is not None:
                uncertainties.add(f"{path}:{name}: runtime job condition")
            size = _matrix_count(job)
            if size is None:
                dynamic_matrices += 1
                unknown_expansion = True
                uncertainties.add(f"{path}:{name}: dynamic matrix")
                continue
            uses = job.get("uses")
            if uses:
                reusable_calls += size
                if str(uses).startswith("./"):
                    total += size * count(str(uses)[2:], chain + (path,))
                else:
                    unknown_expansion = True
                    uncertainties.add(f"{path}:{name}: external reusable workflow {uses}")
            else:
                total += size
        return total

    reports = []
    known = 0
    for path, data in workflows.items():
        events = data.get("on", data.get(True, {}))  # PyYAML's YAML-1.1 'on'.
        if isinstance(events, str):
            events = {events: {}}
        elif isinstance(events, list):
            events = {str(event): {} for event in events}
        if not isinstance(events, dict):
            continue
        triggered = False
        for event in ("pull_request", "pull_request_target"):
            if event not in events:
                continue
            settings = events[event] or {}
            if not isinstance(settings, dict):
                uncertainties.add(f"{path}: dynamic PR trigger")
                triggered = True
                continue
            include = settings.get("paths")
            ignore = settings.get("paths-ignore")
            if isinstance(include, list) and not any(_selected_path(item, include) for item in changed_paths):
                continue
            if isinstance(ignore, list) and changed_paths and all(any(_path_matches(item, pattern) for pattern in ignore) for item in changed_paths):
                continue
            if any(key in settings for key in ("branches", "branches-ignore", "types")):
                uncertainties.add(f"{path}: PR branch/event filters not evaluated")
            triggered = True
        if triggered:
            jobs = count(path)
            known += jobs
            reports.append({"path": path, "known_jobs": jobs})
    return {"event": "pull_request", "known_jobs": known, "estimated_jobs": known,
            "jobs_upper_bound": None if unknown_expansion else known,
            "exact": not uncertainties, "reusable_calls": reusable_calls,
            "dynamic_matrices": dynamic_matrices, "workflows": reports,
            "uncertainties": sorted(uncertainties),
            "semantics": "Static expansions for a workflow-only pin PR; not actual executed jobs or runner minutes."}


def plan_repo(repo: str, files: dict[str, str], source_head: str, fixes: list[dict],
              changes: list[dict], now: datetime, existing_branches: list[str], regular: bool) -> dict:
    """Report a deterministic candidate without writing to GitHub.

    A regular batch gets an ISO-week key, urgent batches use the latest missing
    qualifying fix's complete merged SHA. Existing immutable keys are not opened
    again. Outdated means different from source_head, NOT proven behind it.
    Fix qualification and >24h marked / >8d general alerts require both consumed
    path relevance and explicit ancestry. Durations are strict greater-than.
    """
    now = _date(now)
    pins = parse_pins(files)
    outdated = [pin for pin in pins if pin.get("sha") and pin["sha"].lower() != source_head.lower()]
    findings = [{"kind": pin["finding"], "path": pin["path"], "ref": pin.get("ref")}
                for pin in pins if pin.get("finding")]
    qualifying = []
    alerts = []
    records = {str(change["sha"]).lower(): (change, False) for change in changes}
    records.update({str(fix["sha"]).lower(): (fix, True) for fix in fixes})
    for _, (record, marked) in sorted(records.items()):
        relevant = [pin for pin in pins if _affected(pin, record.get("files", []))]
        states = [(pin, _ancestry(pin, record)) for pin in relevant]
        behind = [pin for pin, state in states if state == "behind"]
        unknown = [pin for pin, state in states if state in ("unknown", "conflict")]
        if unknown:
            findings.append({"kind": "ancestry_unknown", "sha": record["sha"],
                             "pins": sorted({pin.get("sha") or pin.get("ref") or "<missing>" for pin in unknown}),
                             "paths": sorted({pin["path"] for pin in unknown})})
        if not behind:
            continue
        try:
            merged_at = _date(record.get("merged_at", record.get("date")))
        except (ValueError, TypeError):
            findings.append({"kind": "invalid_merged_at", "sha": record["sha"]})
            continue
        if merged_at > now:
            findings.append({"kind": "future_merged_at", "sha": record["sha"]})
            continue
        detail = dict(record)
        detail["merged_at"] = merged_at.isoformat()
        detail["behind_pins"] = sorted({pin["sha"] for pin in behind})
        detail["affected_paths"] = sorted({pin["path"] for pin in behind})
        detail["consumed_roots"] = sorted({root for pin in behind for root in pin["roots"]})
        if marked:
            qualifying.append(detail)
        age = now - merged_at
        threshold = timedelta(hours=24) if marked else timedelta(days=8)
        if age > threshold:
            alerts.append({"kind": "marked_fix" if marked else "general", "sha": record["sha"],
                           "number": record.get("number"), "merged_at": merged_at.isoformat(),
                           "age_hours": age.total_seconds() / 3600,
                           "threshold_hours": threshold.total_seconds() / 3600,
                           "paths": detail["affected_paths"], "pins": detail["behind_pins"],
                           "consumed_roots": detail["consumed_roots"]})
    qualifying.sort(key=lambda record: (record["merged_at"], record["sha"]))
    if qualifying:
        branch_key = f"fix-{qualifying[-1]['sha']}"
        reason = "marked_fix"
    elif regular:
        year, week, _ = now.isocalendar()
        branch_key = f"week-{year}-{week:02d}"
        reason = "regular"
    else:
        branch_key = None
        reason = None
    branches = {item.removeprefix("refs/heads/") for item in existing_branches}
    exists = branch_key is not None and (branch_key in branches or f"renovate/shared-ci-{branch_key}" in branches)
    ci_jobs = estimate_pr_ci_jobs(files, sorted({pin["path"] for pin in outdated}))
    return {"repo": repo, "source_head": source_head, "pins": pins,
            "pin_count": len(pins), "outdated_pins": outdated, "outdated_count": len(outdated),
            "outdated_semantics": "Full-SHA pins unequal to source_head; ancestry is not implied.",
            "qualifying_fixes": qualifying, "lag_alerts": alerts, "findings": findings,
            "branch_key": branch_key, "branch_exists": exists, "reason": reason,
            "should_open": bool(outdated and branch_key and not exists),
            "estimated_ci_jobs": ci_jobs}
