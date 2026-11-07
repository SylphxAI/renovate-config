"""Declared source dependency closure for action/workflow consumption.

Only literal shared script paths, local uses and Python imports are followed.
Unknown checkouts remain unknown; unrelated script churn cannot enroll callers.
"""
from __future__ import annotations

import re


def dependency_paths(roots, source_paths, read):
    paths = set(source_paths)
    selected = set()
    pending = [p for p in paths for root in roots if root and
               (p == root or p.startswith(root.rstrip('/') + '/'))]
    while pending:
        path = pending.pop()
        if path in selected:
            continue
        selected.add(path)
        if not path.endswith(('.yml', '.yaml', '.py', '.sh', '.js', '.mjs', '.ts')):
            continue
        text = read(path)
        references = set(re.findall(r'(?<![\w.-])(scripts/[\w./-]+)', text))
        references.update(re.findall(r'uses:\s*[\'"]?\./(\.github/(?:actions|workflows)/[\w./-]+)', text))
        # Python's declared same-directory imports are shared helper inputs too.
        for module in re.findall(r'^\s*(?:from|import)\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)', text, re.M):
            references.add(path.rsplit('/', 1)[0] + '/' + module.replace('.', '/') + '.py')
        for reference in references:
            pending.extend(p for p in paths if p == reference or p.startswith(reference.rstrip('/') + '/'))
    return sorted(selected)


def touches(pin, changed):
    """Positive relevance only: roots and explicitly resolved helper paths."""
    roots = [r for r in pin.get('roots', []) if r]
    declared = set(pin.get('dependency_paths', []))
    return any(path in declared or any(path == root or path.startswith(root.rstrip('/') + '/')
                                      for root in roots) for path in changed)
