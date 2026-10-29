"""Score a model response against the checks declared in behavior.yaml.

Used by build_dataset.py (to filter generated data) and by
eval/run_behavior_eval.py (to measure adherence). Stdlib + PyYAML only.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CODE_BLOCK_RE = re.compile(r"```([\w+#.-]*)[ \t]*\n(.*?)```", re.DOTALL)
PYTHON_LANGS = {"python", "py", "python3"}


@dataclass
class CheckResult:
    id: str
    applicable: bool
    passed: bool
    detail: str = ""


@dataclass
class Score:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def applicable(self) -> list[CheckResult]:
        return [c for c in self.checks if c.applicable]

    @property
    def passed(self) -> bool:
        """An example passes when every applicable check passes."""
        return all(c.passed for c in self.applicable)

    @property
    def failures(self) -> list[str]:
        return [f"{c.id}: {c.detail}" if c.detail else c.id for c in self.applicable if not c.passed]


def load_behavior(path: str | Path) -> dict:
    with open(path) as f:
        spec = yaml.safe_load(f)
    for key in ("name", "teacher_system_prompt", "checks"):
        if key not in spec:
            raise ValueError(f"{path}: missing required key {key!r}")
    for check in spec["checks"]:
        if check.get("type") not in CHECKS:
            raise ValueError(f"{path}: unknown check type {check.get('type')!r} (known: {sorted(CHECKS)})")
        if check.get("applies_when", "always") not in CONDITIONS:
            raise ValueError(f"{path}: unknown applies_when {check['applies_when']!r} (known: {sorted(CONDITIONS)})")
    return spec


def code_blocks(text: str) -> list[tuple[str, str]]:
    return [(lang.lower(), body) for lang, body in CODE_BLOCK_RE.findall(text)]


def python_blocks(text: str) -> list[str]:
    return [body for lang, body in code_blocks(text) if lang in PYTHON_LANGS]


# --- applicability conditions -------------------------------------------------

CONDITIONS = {
    "always": lambda text: True,
    "has_code": lambda text: bool(code_blocks(text)),
    "no_code": lambda text: not code_blocks(text),
    "has_python_code": lambda text: bool(python_blocks(text)),
}


# --- check implementations ----------------------------------------------------

def _regex_present(text: str, check: dict) -> tuple[bool, str]:
    ok = re.search(check["pattern"], text) is not None
    return ok, "" if ok else f"pattern not found: {check['pattern']}"


def _regex_absent(text: str, check: dict) -> tuple[bool, str]:
    m = re.search(check["pattern"], text)
    return m is None, "" if m is None else f"forbidden pattern found: {m.group(0)[:60]!r}"


def _python_all_functions_annotated(text: str, check: dict) -> tuple[bool, str]:
    exempt = re.compile(check["exempt_function_pattern"]) if check.get("exempt_function_pattern") else None
    missing: list[str] = []
    for body in python_blocks(text):
        try:
            tree = ast.parse(body)
        except SyntaxError as e:
            return False, f"python block does not parse: {e.msg} (line {e.lineno})"
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if exempt and exempt.search(node.name):
                continue
            args = node.args
            params = args.posonlyargs + args.args + args.kwonlyargs
            params += [a for a in (args.vararg, args.kwarg) if a is not None]
            unannotated = [a.arg for a in params if a.annotation is None and a.arg not in ("self", "cls")]
            if unannotated:
                missing.append(f"{node.name}({', '.join(unannotated)})")
            if node.returns is None:
                missing.append(f"{node.name} -> ?")
    return not missing, "" if not missing else "missing hints: " + "; ".join(missing[:5])


def _section_is_last(text: str, check: dict) -> tuple[bool, str]:
    heading = check["heading"]
    lines = text.rstrip().splitlines()
    idx = [i for i, line in enumerate(lines) if line.strip() == heading]
    if not idx:
        return False, f"no {heading!r} heading"
    later_headings = [line for line in lines[idx[-1] + 1:] if re.match(r"^#{1,6} ", line)]
    return not later_headings, "" if not later_headings else f"content after {heading!r}: {later_headings[0]!r}"


CHECKS = {
    "regex_present": _regex_present,
    "regex_absent": _regex_absent,
    "python_all_functions_annotated": _python_all_functions_annotated,
    "section_is_last": _section_is_last,
}


def score_response(text: str, spec: dict) -> Score:
    score = Score()
    for check in spec["checks"]:
        applicable = CONDITIONS[check.get("applies_when", "always")](text)
        if not applicable:
            score.checks.append(CheckResult(check["id"], False, True))
            continue
        ok, detail = CHECKS[check["type"]](text, check)
        score.checks.append(CheckResult(check["id"], True, ok, detail))
    return score
