"""Select concrete Python answer-consumption sites for semantic workflow review."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

ANSWER_FIELDS = {"noul", "choice", "score", "probabilities", "confidence"}


@dataclass(frozen=True)
class _Provenance:
    kind: str
    question_id: str | None = None


_UNKNOWN = _Provenance("unknown")
_ANSWERS = _Provenance("answers")
_RESPONSE = _Provenance("response")
_UNRESOLVED_ANSWER = _Provenance("unresolved_answer")


class _StoredNames(ast.NodeVisitor):
    """Collect one function's local bindings without entering nested scopes."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, _node: ast.Lambda) -> None:
        return


class _AnswerAccessCollector(ast.NodeVisitor):
    """Resolve typed-answer reads from an SDK ``answers`` root and its local aliases."""

    def __init__(self, question_ids: set[str]) -> None:
        self.question_ids = question_ids
        self.scopes: list[dict[str, _Provenance]] = [{}]
        self.resolved: dict[ast.Attribute, str] = {}
        self.unresolved: list[ast.Attribute] = []

    def _lookup(self, name: str) -> _Provenance:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        if name == "answers":
            return _ANSWERS
        if name == "response":
            return _RESPONSE
        return _UNKNOWN

    def _provenance(self, node: ast.AST) -> _Provenance:
        if isinstance(node, ast.Name):
            return self._lookup(node.id)
        if isinstance(node, ast.Attribute) and node.attr == "answers" and self._provenance(node.value) == _RESPONSE:
            return _ANSWERS
        if isinstance(node, ast.Subscript) and self._provenance(node.value) == _ANSWERS:
            index = node.slice
            if isinstance(index, ast.Constant) and isinstance(index.value, str):
                question_id = index.value
                if question_id in self.question_ids:
                    return _Provenance("answer", question_id)
            return _UNRESOLVED_ANSWER
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and self._provenance(node.func.value) == _ANSWERS
        ):
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                question_id = node.args[0].value
                if question_id in self.question_ids:
                    return _Provenance("answer", question_id)
            return _UNRESOLVED_ANSWER
        return _UNKNOWN

    def _bind(self, target: ast.AST, provenance: _Provenance) -> None:
        if isinstance(target, ast.Name):
            self.scopes[-1][target.id] = provenance
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._bind(item, _UNKNOWN)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.visit(node.value)
        if node.attr not in ANSWER_FIELDS:
            return
        provenance = self._provenance(node.value)
        if provenance.kind == "answer" and provenance.question_id is not None:
            self.resolved[node] = provenance.question_id
        elif provenance == _UNRESOLVED_ANSWER:
            self.unresolved.append(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        provenance = self._provenance(node.value)
        for target in node.targets:
            self._bind(target, provenance)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            provenance = self._provenance(node.value)
        else:
            provenance = _UNKNOWN
        self._bind(node.target, provenance)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._bind(node.target, self._provenance(node.value))

    @staticmethod
    def _merge_branches(*branches: Mapping[str, _Provenance]) -> dict[str, _Provenance]:
        merged: dict[str, _Provenance] = {}
        for name in {name for branch in branches for name in branch}:
            values = [branch.get(name, _UNKNOWN) for branch in branches]
            if all(value == values[0] for value in values[1:]):
                merged[name] = values[0]
            elif any(value.kind in {"answers", "response", "answer", "unresolved_answer"} for value in values):
                merged[name] = _UNRESOLVED_ANSWER
            else:
                merged[name] = _UNKNOWN
        return merged

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        original = dict(self.scopes[-1])

        self.scopes[-1] = dict(original)
        for statement in node.body:
            self.visit(statement)
        body = dict(self.scopes[-1])

        self.scopes[-1] = dict(original)
        for statement in node.orelse:
            self.visit(statement)
        orelse = dict(self.scopes[-1])

        self.scopes[-1] = self._merge_branches(body, orelse)

    def _visit_loop(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self.visit(node.iter)
        else:
            self.visit(node.test)
        original = dict(self.scopes[-1])

        self.scopes[-1] = dict(original)
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self._bind(node.target, _UNKNOWN)
        for statement in node.body:
            self.visit(statement)
        body = dict(self.scopes[-1])

        self.scopes[-1] = dict(original)
        for statement in node.orelse:
            self.visit(statement)
        orelse = dict(self.scopes[-1])

        self.scopes[-1] = self._merge_branches(original, body, orelse)

    def visit_For(self, node: ast.For) -> None:
        self._visit_loop(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_loop(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_loop(node)

    def _visit_unsupported_control_flow(self, node: ast.AST) -> None:
        original = dict(self.scopes[-1])
        previous_resolved = set(self.resolved)
        self.generic_visit(node)
        for access in set(self.resolved) - previous_resolved:
            self.resolved.pop(access)
            self.unresolved.append(access)
        current = self.scopes[-1]
        self.scopes[-1] = self._merge_branches(original, current)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_unsupported_control_flow(node)

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self._visit_unsupported_control_flow(node)

    def visit_Match(self, node: ast.Match) -> None:
        self._visit_unsupported_control_flow(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)

        stored = _StoredNames()
        for statement in node.body:
            stored.visit(statement)
        local = {name: _UNKNOWN for name in stored.names}
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        if node.args.kwarg is not None:
            arguments.append(node.args.kwarg)
        local.update(
            {
                argument.arg: _ANSWERS
                if argument.arg == "answers"
                else _RESPONSE
                if argument.arg == "response"
                else _UNKNOWN
                for argument in arguments
            }
        )

        self.scopes.append(local)
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scopes[-1][node.name] = _UNKNOWN
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scopes[-1][node.name] = _UNKNOWN
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        if node.args.kwarg is not None:
            arguments.append(node.args.kwarg)
        self.scopes.append(
            {
                argument.arg: _ANSWERS
                if argument.arg == "answers"
                else _RESPONSE
                if argument.arg == "response"
                else _UNKNOWN
                for argument in arguments
            }
        )
        self.visit(node.body)
        self.scopes.pop()


def _ancestor(
    node: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
    wanted: type[ast.AST] | tuple[type[ast.AST], ...],
) -> ast.AST | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, wanted):
            return current
        current = parents.get(current)
    return None


def _answer_accesses(node: ast.AST, resolved: Mapping[ast.Attribute, str]) -> list[tuple[ast.Attribute, str]]:
    return [
        (child, resolved[child]) for child in ast.walk(node) if isinstance(child, ast.Attribute) and child in resolved
    ]


def _lexical_scope(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> ast.AST:
    return _ancestor(node, parents, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) or _root(node, parents)


def _root(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> ast.AST:
    current = node
    while current in parents:
        current = parents[current]
    return current


def _downstream_uses(statement: ast.AST, tree: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> list[str]:
    if not isinstance(statement, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
        return []
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    assigned_names = {node.id for target in targets for node in ast.walk(target) if isinstance(node, ast.Name)}
    if not assigned_names:
        return []
    statement_line = getattr(statement, "lineno", 0)
    scope = _lexical_scope(statement, parents)
    downstream: list[str] = []
    for candidate in ast.walk(tree):
        if not isinstance(candidate, ast.stmt) or getattr(candidate, "lineno", 0) <= statement_line:
            continue
        if _lexical_scope(candidate, parents) is not scope:
            continue
        reads = {
            node.id for node in ast.walk(candidate) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        if assigned_names & reads:
            rendered = ast.unparse(candidate)
            if rendered not in downstream:
                downstream.append(rendered)
    return downstream


def inspect_python_consumer(code: str, questions: Mapping[str, Any]) -> dict[str, Any]:
    """Return exact typed-answer reads and arithmetic sites from parseable Python code."""
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return {
            "status": "not_reviewed",
            "reason": f"workflow.consumer_code is not parseable Python: line {error.lineno}",
            "sites": [],
        }

    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    known_question_ids = {str(question_id) for question_id in questions}
    collector = _AnswerAccessCollector(known_question_ids)
    collector.visit(tree)
    if collector.unresolved:
        lines = sorted({node.lineno for node in collector.unresolved})
        return {
            "status": "not_reviewed",
            "reason": f"workflow.consumer_code has unresolved typed-answer reads at lines {lines}",
            "sites": [],
        }
    all_accesses = _answer_accesses(tree, collector.resolved)
    if not all_accesses:
        return {
            "status": "not_reviewed",
            "reason": "workflow.consumer_code has no resolvable typed-answer reads",
            "sites": [],
        }

    sites: list[dict[str, Any]] = []
    seen_compositions: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp):
            continue
        accesses = _answer_accesses(node, collector.resolved)
        if not accesses:
            continue
        parent_composition = _ancestor(node, parents, ast.BinOp)
        if isinstance(parent_composition, ast.BinOp) and _answer_accesses(parent_composition, collector.resolved):
            continue
        identity = (node.lineno, node.col_offset)
        if identity in seen_compositions:
            continue
        seen_compositions.add(identity)
        statement = _ancestor(node, parents, ast.stmt) or node
        branches = [ast.unparse(parent.test) for parent in _parent_chain(node, parents) if isinstance(parent, ast.If)]
        sites.append(
            {
                "kind": "composition",
                "line": node.lineno,
                "expression": ast.unparse(node),
                "statement": ast.unparse(statement),
                "downstream_uses": _downstream_uses(statement, tree, parents),
                "branch_conditions": branches,
                "operation": type(node.op).__name__,
                "answer_fields": sorted({access.attr for access, _ in accesses}),
                "question_ids": sorted({question_id for _, question_id in accesses}),
            }
        )

    for access, question_id in all_accesses:
        statement = _ancestor(access, parents, ast.stmt) or access
        branches = [ast.unparse(parent.test) for parent in _parent_chain(access, parents) if isinstance(parent, ast.If)]
        sites.append(
            {
                "kind": "answer_read",
                "line": access.lineno,
                "expression": ast.unparse(access),
                "statement": ast.unparse(statement),
                "downstream_uses": _downstream_uses(statement, tree, parents),
                "branch_conditions": branches,
                "answer_fields": [access.attr],
                "question_ids": [question_id],
            }
        )

    for index, site in enumerate(sites):
        site["site_id"] = f"site_{index}"
        site["relevant_questions"] = {question_id: questions[question_id] for question_id in site.pop("question_ids")}
    return {
        "status": "reviewed",
        "language": "python",
        "site_count": len(sites),
        "sites": sites,
    }


def _parent_chain(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> list[ast.AST]:
    chain: list[ast.AST] = []
    current = parents.get(node)
    while current is not None:
        chain.append(current)
        current = parents.get(current)
    return chain
