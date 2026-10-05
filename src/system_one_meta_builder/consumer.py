"""Select concrete Python answer-consumption sites for semantic workflow review."""

from __future__ import annotations

import ast
import builtins
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from typesafe_sdk import ChoiceAnswer, NoulAnswer, ScoreAnswer

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

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.names.add(node.name)
        self.generic_visit(node)


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


@dataclass(frozen=True)
class _AnswerRead:
    question_ids: tuple[str, ...]
    field: str
    provenance: str


def _answer_accesses(node: ast.AST, resolved: Mapping[ast.expr, _AnswerRead]) -> list[tuple[ast.expr, _AnswerRead]]:
    return [(child, resolved[child]) for child in ast.walk(node) if child in resolved]


def _composition_operation(node: ast.AST, resolved: Mapping[ast.expr, _AnswerRead]) -> str | None:
    if isinstance(node, ast.BinOp):
        return type(node.op).__name__
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"min", "max"}
        and any(read.provenance == "host_declared" for _, read in _answer_accesses(node, resolved))
    ):
        return node.func.id
    return None


def _bind_declared_reads(
    tree: ast.AST, questions: Mapping[str, Any], bindings: Any, resolved: dict[ast.expr, _AnswerRead]
) -> None:
    """Validate host-declared joins; this does not infer runtime data flow."""
    if bindings is None:
        return
    if not isinstance(bindings, list):
        raise ValueError("must be a list")
    expressions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, ast.Load)
    ]
    declared: set[ast.expr] = set()
    for index, binding in enumerate(bindings):
        prefix = f"entry {index}"
        if not isinstance(binding, Mapping):
            raise ValueError(f"{prefix} must be an object")
        expression, line = binding.get("expression"), binding.get("line")
        if not isinstance(expression, str) or type(line) is not int:
            raise ValueError(f"{prefix} requires an expression and integer line")
        try:
            parsed = ast.parse(expression, mode="eval").body
        except SyntaxError as error:
            raise ValueError(f"{prefix} expression is not parseable Python") from error
        nodes = [node for node in expressions if node.lineno == line and ast.dump(node) == ast.dump(parsed)]
        if not nodes:
            raise ValueError(f"{prefix} does not select an actual attribute or subscript read")
        question_ids, field = binding.get("question_ids"), binding.get("answer_field")
        if not isinstance(question_ids, list) or not question_ids or not all(isinstance(q, str) for q in question_ids):
            raise ValueError(f"{prefix} requires nonempty question_ids")
        for question_id in question_ids:
            if question_id not in questions:
                raise ValueError(f"{prefix} has unknown question ID {question_id!r}")
            model = {"noul": NoulAnswer, "choice": ChoiceAnswer, "score": ScoreAnswer}[questions[question_id]["type"]]
            if not isinstance(field, str) or field not in ANSWER_FIELDS or field not in model.model_fields:
                raise ValueError(f"{prefix} field {field!r} is incompatible with question {question_id!r}")
        read = _AnswerRead(tuple(question_ids), field, "host_declared")
        for node in nodes:
            if isinstance(node, ast.Attribute) and node.attr in ANSWER_FIELDS and node.attr != field:
                raise ValueError(f"{prefix} field differs from the actual typed field read")
            existing = resolved.get(node)
            if node in declared or (
                existing is not None and (existing.question_ids, existing.field) != (read.question_ids, field)
            ):
                raise ValueError(f"{prefix} conflicts with another answer binding")
            resolved[node] = read
            declared.add(node)


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


def _declared_context(node: ast.AST, code: str, tree: ast.Module, parents: Mapping[ast.AST, ast.AST]) -> dict[str, Any]:
    scope = _ancestor(node, parents, (ast.FunctionDef, ast.AsyncFunctionDef)) or node
    stored = _StoredNames()
    body = scope.body if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) else [scope]
    for statement in body:
        stored.visit(statement)
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        stored.names.update(argument.arg for argument in ast.walk(scope.args) if isinstance(argument, ast.arg))
    referenced = {
        child.id
        for statement in body
        for child in ast.walk(statement)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    } - stored.names
    constants: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)) and statement.value is not None:
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            try:
                ast.literal_eval(statement.value)
            except (ValueError, TypeError):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in referenced:
                    constants[target.id] = ast.get_source_segment(code, statement) or ast.unparse(statement)
    return {
        "enclosing_function": ast.get_source_segment(code, scope) if scope is not node else None,
        "referenced_constants": constants,
        "unresolved_dependencies": sorted(referenced - constants.keys() - vars(builtins).keys()),
    }


def inspect_python_consumer(code: str, questions: Mapping[str, Any], answer_bindings: Any = None) -> dict[str, Any]:
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
    resolved = {
        node: _AnswerRead((question_id,), node.attr, "sdk_root") for node, question_id in collector.resolved.items()
    }
    try:
        _bind_declared_reads(tree, questions, answer_bindings, resolved)
    except ValueError as error:
        return {"status": "not_reviewed", "reason": f"workflow.answer_bindings {error}", "sites": []}
    unresolved = [node for node in collector.unresolved if node not in resolved]
    if unresolved:
        lines = sorted({node.lineno for node in unresolved})
        return {
            "status": "not_reviewed",
            "reason": f"workflow.consumer_code has unresolved typed-answer reads at lines {lines}",
            "sites": [],
        }
    all_accesses = _answer_accesses(tree, resolved)
    if not all_accesses:
        return {
            "status": "not_reviewed",
            "reason": "workflow.consumer_code has no resolvable typed-answer reads",
            "sites": [],
        }

    sites: list[dict[str, Any]] = []
    seen_compositions: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        operation = _composition_operation(node, resolved)
        if operation is None:
            continue
        accesses = _answer_accesses(node, resolved)
        if not accesses:
            continue
        if any(
            _composition_operation(parent, resolved) is not None and _answer_accesses(parent, resolved)
            for parent in _parent_chain(node, parents)
        ):
            continue
        identity = (node.lineno, node.col_offset)
        if identity in seen_compositions:
            continue
        seen_compositions.add(identity)
        statement = _ancestor(node, parents, ast.stmt) or node
        branches = [ast.unparse(parent.test) for parent in _parent_chain(node, parents) if isinstance(parent, ast.If)]
        sites.append(
            {
                "_node": node,
                "kind": "composition",
                "line": node.lineno,
                "expression": ast.unparse(node),
                "statement": ast.unparse(statement),
                "downstream_uses": _downstream_uses(statement, tree, parents),
                "branch_conditions": branches,
                "operation": operation,
                "answer_fields": sorted({read.field for _, read in accesses}),
                "question_ids": sorted({question_id for _, read in accesses for question_id in read.question_ids}),
                "binding_provenance": sorted({read.provenance for _, read in accesses}),
            }
        )

    for access, read in all_accesses:
        statement = _ancestor(access, parents, ast.stmt) or access
        branches = [ast.unparse(parent.test) for parent in _parent_chain(access, parents) if isinstance(parent, ast.If)]
        sites.append(
            {
                "_node": access,
                "kind": "answer_read",
                "line": access.lineno,
                "expression": ast.unparse(access),
                "statement": ast.unparse(statement),
                "downstream_uses": _downstream_uses(statement, tree, parents),
                "branch_conditions": branches,
                "answer_fields": [read.field],
                "question_ids": list(read.question_ids),
                "binding_provenance": read.provenance,
            }
        )

    contexts: list[dict[str, Any]] = []
    for index, site in enumerate(sites):
        node = site.pop("_node")
        if site["binding_provenance"] in ("sdk_root", ["sdk_root"]):
            del site["binding_provenance"]
        else:
            context = _declared_context(node, code, tree, parents)
            if context not in contexts:
                contexts.append(context)
            site["source_context_path"] = f"workflow_coverage.source_contexts[{contexts.index(context)}]"
        site["site_id"] = f"site_{index}"
        site["relevant_questions"] = {question_id: questions[question_id] for question_id in site.pop("question_ids")}
    analysis = {
        "status": "reviewed",
        "language": "python",
        "site_count": len(sites),
        "sites": sites,
    }
    if contexts:
        analysis["source_contexts"] = contexts
        analysis["coverage_scope"] = "declared_reads_and_direct_sdk_reads"
    return analysis


def _parent_chain(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> list[ast.AST]:
    chain: list[ast.AST] = []
    current = parents.get(node)
    while current is not None:
        chain.append(current)
        current = parents.get(current)
    return chain
