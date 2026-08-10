"""
Heuristic classifier for v1. Deliberately NOT a trained model — regex/keyword
rules are fast, free, and (crucially) explainable: every routing decision can
say exactly *why* it fired. A learned classifier (e.g. embeddings + a small
sklearn model, like RouteLLM's approach) is a natural upgrade once you have
labeled traffic to train on — swap this function's internals without
touching anything that calls it.
"""
import re
from dataclasses import dataclass
from enum import Enum


class QueryType(str, Enum):
    CODE = "code"
    LONG_CONTEXT = "long_context"
    COMPLEX = "complex"
    SIMPLE = "simple"


@dataclass
class Classification:
    query_type: QueryType
    reason: str


_CODE_MARKERS = re.compile(
    r"```|\bdef \w+\(|\bclass \w+[:\(]|\bfunction\s+\w*\(|\bimport \w+|\bconsole\.log\(|"
    r"\b(bug|stack trace|traceback|compile error|exception)\b",
    re.IGNORECASE,
)
_COMPLEX_MARKERS = re.compile(
    r"\b(analy[sz]e|architecture|trade-?offs?|design|strategy|compare and contrast|"
    r"step by step|reason through|prove|derive)\b",
    re.IGNORECASE,
)

LONG_CONTEXT_CHAR_THRESHOLD = 6000  # ~1500 tokens; tune against real traffic


def classify(prompt: str) -> Classification:
    if len(prompt) > LONG_CONTEXT_CHAR_THRESHOLD:
        return Classification(QueryType.LONG_CONTEXT, f"prompt is {len(prompt)} chars (> {LONG_CONTEXT_CHAR_THRESHOLD})")

    if _CODE_MARKERS.search(prompt):
        return Classification(QueryType.CODE, "matched code-related pattern (syntax, error, code fence)")

    if _COMPLEX_MARKERS.search(prompt) or len(prompt.split()) > 80:
        return Classification(QueryType.COMPLEX, "matched reasoning/analysis language or long prompt")

    return Classification(QueryType.SIMPLE, "no complexity signals found — short, factual-style query")
