"""SPDX expression parsing and license classification.

Decisions, from best to worst: ``allowed``, ``allowed_unmodified`` (MPL-2.0, EPL-2.0: allowed
only as unmodified dependencies), ``unknown`` and ``denied``. ``OR`` takes the best branch
(the project elects that license), ``AND`` the worst, and ``WITH`` keeps the base license's
decision (an exception never makes a copyleft license acceptable in the core).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

from edaforge_devtools.license_gate.policy import Policy

__all__ = [
    "Decision",
    "SpdxError",
    "Verdict",
    "classifier_to_spdx",
    "classify_expression",
    "fingerprint_text",
    "parse_spdx",
    "synonym_to_spdx",
]


class Decision(IntEnum):
    """Ordered so that ``max`` is the worst outcome."""

    ALLOWED = 0
    ALLOWED_UNMODIFIED = 1
    UNKNOWN = 2
    DENIED = 3


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    expression: str
    elected: str  # the license the project uses (for OR expressions)
    detail: str


class SpdxError(ValueError):
    pass


# ---------------------------------------------------------------- parsing

_TOKEN = re.compile(r"\s*(\(|\)|[A-Za-z0-9.+:\-]+)")


@dataclass(frozen=True)
class _Id:
    license: str


@dataclass(frozen=True)
class _With:
    license: str
    exception: str


@dataclass(frozen=True)
class _And:
    parts: tuple[_Node, ...]


@dataclass(frozen=True)
class _Or:
    parts: tuple[_Node, ...]


_Node = _Id | _With | _And | _Or


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    stripped = text.strip()
    while pos < len(stripped):
        match = _TOKEN.match(stripped, pos)
        if match is None:
            msg = f"invalid character in SPDX expression {text!r} at {pos}"
            raise SpdxError(msg)
        tokens.append(match.group(1))
        pos = match.end()
    return tokens


def parse_spdx(text: str) -> _Node:
    tokens = _tokens(text)
    if not tokens:
        msg = "empty SPDX expression"
        raise SpdxError(msg)
    position = 0

    def peek() -> str | None:
        return tokens[position] if position < len(tokens) else None

    def take() -> str:
        nonlocal position
        if position >= len(tokens):
            msg = f"unexpected end of SPDX expression {text!r}"
            raise SpdxError(msg)
        token = tokens[position]
        position += 1
        return token

    def atom() -> _Node:
        item = take()
        if item == "(":
            node = or_expr()
            if take() != ")":
                msg = f"unbalanced parentheses in {text!r}"
                raise SpdxError(msg)
            return node
        if item == ")" or item.upper() in {"AND", "OR", "WITH"}:
            msg = f"unexpected {item!r} in {text!r}"
            raise SpdxError(msg)
        nxt = peek()
        if nxt is not None and nxt.upper() == "WITH":
            take()
            return _With(item, take())
        return _Id(item)

    def and_expr() -> _Node:
        parts = [atom()]
        while (nxt := peek()) is not None and nxt.upper() == "AND":
            take()
            parts.append(atom())
        return parts[0] if len(parts) == 1 else _And(tuple(parts))

    def or_expr() -> _Node:
        parts = [and_expr()]
        while (nxt := peek()) is not None and nxt.upper() == "OR":
            take()
            parts.append(and_expr())
        return parts[0] if len(parts) == 1 else _Or(tuple(parts))

    node = or_expr()
    if position != len(tokens):
        msg = f"trailing tokens in SPDX expression {text!r}"
        raise SpdxError(msg)
    return node


# ---------------------------------------------------------------- classification


def _classify_id(license_id: str, policy: Policy) -> Decision:
    base = license_id.removesuffix("+")
    if base in policy.allowed:
        return Decision.ALLOWED
    if base in policy.allowed_unmodified:
        return Decision.ALLOWED_UNMODIFIED
    upper = base.upper()
    if any(upper.startswith(p.upper()) for p in policy.denied_prefixes):
        return Decision.DENIED
    lowered = base.lower()
    if any(t in lowered for t in policy.denied_text):
        return Decision.DENIED
    return Decision.UNKNOWN


def _evaluate(node: _Node, policy: Policy) -> tuple[Decision, str]:
    if isinstance(node, _Id):
        return _classify_id(node.license, policy), node.license
    if isinstance(node, _With):
        return _classify_id(node.license, policy), f"{node.license} WITH {node.exception}"
    if isinstance(node, _And):
        results = [_evaluate(p, policy) for p in node.parts]
        worst = max(d for d, _ in results)
        return worst, " AND ".join(e for _, e in results)
    results = [_evaluate(p, policy) for p in node.parts]
    return min(results, key=lambda r: r[0])


def classify_expression(expression: str, policy: Policy) -> Verdict:
    try:
        node = parse_spdx(expression)
    except SpdxError as exc:
        return Verdict(Decision.UNKNOWN, expression, "", f"not an SPDX expression: {exc}")
    decision, elected = _evaluate(node, policy)
    detail = {
        Decision.ALLOWED: "allowed",
        Decision.ALLOWED_UNMODIFIED: "allowed as an unmodified dependency only",
        Decision.UNKNOWN: "license not in the policy; needs review",
        Decision.DENIED: "license not allowed in the core",
    }[decision]
    return Verdict(decision, expression, elected, detail)


# ---------------------------------------------------------------- normalization

_SYNONYMS: dict[str, str] = {
    "mit": "MIT",
    "mit license": "MIT",
    "the mit license": "MIT",
    "mit-license": "MIT",
    "expat": "MIT",
    "mit-0": "MIT-0",
    "bsd": "BSD-3-Clause",
    "bsd license": "BSD-3-Clause",
    "new bsd": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "modified bsd": "BSD-3-Clause",
    "bsd-3": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "3-clause bsd": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause",
    "bsd-2": "BSD-2-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd 2-clause": "BSD-2-Clause",
    "2-clause bsd": "BSD-2-Clause",
    "simplified bsd": "BSD-2-Clause",
    "freebsd": "BSD-2-Clause",
    "apache": "Apache-2.0",
    "apache 2": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache-2": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache license version 2.0": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "apache software license 2.0": "Apache-2.0",
    "asl 2.0": "Apache-2.0",
    "isc": "ISC",
    "isc license": "ISC",
    "iscl": "ISC",
    "psf": "PSF-2.0",
    "psfl": "PSF-2.0",
    "psf license": "PSF-2.0",
    "psf-2.0": "PSF-2.0",
    "python software foundation license": "PSF-2.0",
    "mpl 2.0": "MPL-2.0",
    "mpl-2.0": "MPL-2.0",
    "mozilla public license 2.0": "MPL-2.0",
    "unlicense": "Unlicense",
    "the unlicense": "Unlicense",
    "zlib": "Zlib",
    "cc0": "CC0-1.0",
    "cc0 1.0": "CC0-1.0",
    "gpl": "GPL-3.0-or-later",
    "gplv2": "GPL-2.0-only",
    "gplv3": "GPL-3.0-only",
    "lgpl": "LGPL-3.0-or-later",
    "agpl": "AGPL-3.0-only",
}

_CLASSIFIERS: dict[str, str] = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: MIT No Attribution License (MIT-0)": "MIT-0",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Eclipse Public License 2.0 (EPL-2.0)": "EPL-2.0",
    "License :: OSI Approved :: The Unlicense (Unlicense)": "Unlicense",
    "License :: OSI Approved :: zlib/libpng License": "Zlib",
    "License :: OSI Approved :: Boost Software License 1.0 (BSL-1.0)": "BSL-1.0",
    "License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication": "CC0-1.0",
    "License :: OSI Approved :: GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)": (
        "GPL-2.0-or-later"
    ),
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)": (
        "GPL-3.0-or-later"
    ),
    "License :: OSI Approved :: GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)": (
        "LGPL-2.0-or-later"
    ),
    "License :: OSI Approved :: GNU Affero General Public License v3": "AGPL-3.0-only",
    "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)": (
        "AGPL-3.0-or-later"
    ),
    "License :: Other/Proprietary License": "LicenseRef-Proprietary",
    "License :: Free for non-commercial use": "LicenseRef-NonCommercial",
}


def synonym_to_spdx(text: str) -> str | None:
    """Map a short, free-text license name to an SPDX ID."""
    key = " ".join(text.strip().lower().split()).strip('"').rstrip(".")
    return _SYNONYMS.get(key)


def classifier_to_spdx(classifier: str) -> str | None:
    if classifier in _CLASSIFIERS:
        return _CLASSIFIERS[classifier]
    if not classifier.startswith("License ::"):
        return None
    lowered = classifier.lower()
    if "affero" in lowered:
        return "AGPL-3.0-or-later"
    if "lesser general public" in lowered or "library general public" in lowered:
        return "LGPL-2.0-or-later"
    if "general public license" in lowered:
        return "GPL-2.0-or-later"
    return "LicenseRef-Unrecognized-Classifier"


def fingerprint_text(text: str) -> str | None:
    """Identify a license from the start of its text (copyleft checked first)."""
    head = " ".join(text[:4000].lower().split())
    if "gnu affero general public license" in head:
        return "AGPL-3.0-or-later"
    if "gnu lesser general public license" in head or "gnu library general public" in head:
        return "LGPL-2.0-or-later"
    if "gnu general public license" in head:
        return "GPL-2.0-or-later"
    if "business source license" in head:
        return "BUSL-1.1"
    if "commons clause" in head:
        return "LicenseRef-Commons-Clause"
    if "non-commercial" in head or "noncommercial" in head:
        return "LicenseRef-NonCommercial"
    if "mozilla public license" in head and "2.0" in head:
        return "MPL-2.0"
    if "apache license" in head and "version 2.0" in head:
        return "Apache-2.0"
    if "permission is hereby granted, free of charge" in head:
        return "MIT"
    if "redistribution and use in source and binary forms" in head:
        return "BSD-3-Clause" if "neither the name" in head else "BSD-2-Clause"
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in head:
        return "ISC" if "provided that the above copyright notice" in head else "0BSD"
    if "this is free and unencumbered software released into the public domain" in head:
        return "Unlicense"
    if "python software foundation license" in head:
        return "PSF-2.0"
    return None
