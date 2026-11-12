"""The license gate (section 13.3), including the Phase 0 planted-GPL acceptance test."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edaforge_devtools.license_gate.classify import (
    Decision,
    SpdxError,
    classifier_to_spdx,
    classify_expression,
    fingerprint_text,
    parse_spdx,
    synonym_to_spdx,
)
from edaforge_devtools.license_gate.cli import main
from edaforge_devtools.license_gate.npm import check_npm_lockfile
from edaforge_devtools.license_gate.policy import load_policy
from edaforge_devtools.license_gate.python_env import check_distributions, closure
from edaforge_devtools.license_gate.weights import check_weights_manifest

ROOT = Path(__file__).resolve().parents[2]
POLICY = load_policy(ROOT / "license-policy.toml")
PLANTED = Path(__file__).parent / "fixtures" / "planted_gpl_site"


def test_planted_gpl_dependency_is_blocked(capsys: pytest.CaptureFixture[str]) -> None:
    """Phase 0 acceptance: the gate blocks a planted GPL test dependency."""
    code = main(
        [
            "--policy",
            str(ROOT / "license-policy.toml"),
            "python",
            "--root",
            "rootpkg",
            "--path",
            str(PLANTED),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "DENIED" in out
    assert "fakegpl==1.0" in out


def test_closure_follows_requirements() -> None:
    dists, missing = closure(["rootpkg"], paths=[PLANTED])
    assert sorted(d.metadata["Name"] for d in dists) == ["fakegpl", "rootpkg"]
    assert missing == []
    verdicts = {v.package: v for v in check_distributions(dists, POLICY)}
    assert verdicts["fakegpl"].verdict.decision == Decision.DENIED
    assert verdicts["rootpkg"].verdict.decision == Decision.ALLOWED


def test_core_closure_of_the_real_environment_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(["--policy", str(ROOT / "license-policy.toml"), "python", "--root", "edaforge"]) == 0
    )
    assert "0 violations" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("expression", "decision", "elected"),
    [
        ("MIT", Decision.ALLOWED, "MIT"),
        ("Apache-2.0 WITH LLVM-exception", Decision.ALLOWED, "Apache-2.0 WITH LLVM-exception"),
        ("MIT OR GPL-3.0-or-later", Decision.ALLOWED, "MIT"),
        ("EPL-2.0 OR GPL-3.0-or-later", Decision.ALLOWED_UNMODIFIED, "EPL-2.0"),  # elkjs
        ("MIT AND GPL-2.0-only", Decision.DENIED, "MIT AND GPL-2.0-only"),
        ("(MIT AND BSD-3-Clause) OR AGPL-3.0-only", Decision.ALLOWED, "MIT AND BSD-3-Clause"),
        ("LGPL-3.0-or-later", Decision.DENIED, "LGPL-3.0-or-later"),
        (
            "GPL-2.0-only WITH Classpath-exception-2.0",
            Decision.DENIED,
            "GPL-2.0-only WITH Classpath-exception-2.0",
        ),
        ("BUSL-1.1", Decision.DENIED, "BUSL-1.1"),
        ("CC-BY-NC-4.0", Decision.DENIED, "CC-BY-NC-4.0"),
        ("MPL-2.0", Decision.ALLOWED_UNMODIFIED, "MPL-2.0"),
        ("LicenseRef-Custom", Decision.UNKNOWN, "LicenseRef-Custom"),
        ("BSL-1.0", Decision.ALLOWED, "BSL-1.0"),
    ],
)
def test_expression_classification(expression: str, decision: Decision, elected: str) -> None:
    verdict = classify_expression(expression, POLICY)
    assert (verdict.decision, verdict.elected) == (decision, elected)


@pytest.mark.parametrize("bad", ["", "MIT AND", "(MIT", "MIT OR OR BSD-3-Clause", "MIT )"])
def test_malformed_expressions(bad: str) -> None:
    with pytest.raises(SpdxError):
        parse_spdx(bad)
    assert classify_expression(bad, POLICY).decision == Decision.UNKNOWN


def test_free_text_classifiers_and_fingerprints() -> None:
    assert synonym_to_spdx("The MIT License") == "MIT"
    assert synonym_to_spdx("Apache License, Version 2.0") == "Apache-2.0"
    assert classifier_to_spdx("License :: OSI Approved :: BSD License") == "BSD-3-Clause"
    assert (
        classifier_to_spdx("License :: OSI Approved :: GNU General Public License v3 (GPLv3)")
        == "GPL-3.0-only"
    )
    assert (
        classifier_to_spdx("License :: Free for non-commercial use") == "LicenseRef-NonCommercial"
    )
    assert fingerprint_text("Permission is hereby granted, free of charge, to any person") == "MIT"
    bsd3 = (
        "Redistribution and use in source and binary forms ... Neither the name of the "
        "copyright holder"
    )
    assert fingerprint_text(bsd3) == "BSD-3-Clause"
    assert fingerprint_text("GNU GENERAL PUBLIC LICENSE Version 3") == "GPL-2.0-or-later"
    assert (
        fingerprint_text("This software is free for non-commercial use only")
        == "LicenseRef-NonCommercial"
    )


def test_npm_lockfile(tmp_path: Path) -> None:
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "web"},
            "node_modules/vega-lite": {"version": "6.0.0", "license": "BSD-3-Clause"},
            "node_modules/elkjs": {"version": "0.12.0", "license": "EPL-2.0 OR GPL-3.0-or-later"},
            "node_modules/evil": {"version": "1.0.0", "license": "AGPL-3.0-only"},
            "node_modules/mystery": {"version": "1.0.0"},
        },
    }
    path = tmp_path / "package-lock.json"
    path.write_text(json.dumps(lock), "utf-8")
    verdicts = {v.package: v.verdict.decision for v in check_npm_lockfile(path, POLICY)}
    assert verdicts == {
        "vega-lite": Decision.ALLOWED,
        "elkjs": Decision.ALLOWED_UNMODIFIED,
        "evil": Decision.DENIED,
        "mystery": Decision.UNKNOWN,
    }


def test_model_weight_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "weights.toml"
    manifest.write_text(
        """
[[model]]
name = "timesfm"
version = "2.5"
license = "Apache-2.0"
scope = "core"

[[model]]
name = "timesfm"
version = "3.0"
license = "LicenseRef-NonCommercial"
scope = "core"

[[model]]
name = "timesfm"
version = "3.0-plugin"
license = "LicenseRef-NonCommercial"
scope = "plugin:edaforge-plugin-timesfm3"
""",
        "utf-8",
    )
    decisions = [v.verdict.decision for v in check_weights_manifest(manifest, POLICY)]
    assert decisions == [Decision.ALLOWED, Decision.DENIED, Decision.ALLOWED]
    assert check_weights_manifest(ROOT / "model-weights.toml", POLICY) == []


def test_policy_exceptions_need_a_reason(tmp_path: Path) -> None:
    policy = tmp_path / "policy.toml"
    policy.write_text(
        (ROOT / "license-policy.toml").read_text("utf-8")
        + '\n[[exception]]\npackage = "fakegpl"\nlicense = "MIT"\nreason = ""\n',
        "utf-8",
    )
    with pytest.raises(ValueError, match="reason"):
        load_policy(policy)
