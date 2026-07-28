"""Cross-manifest version consistency guard.

Ensures the release version stays aligned across all runtime manifests
so a partial bump cannot leave surfaces reporting different versions.
Run automatically as part of the normal pytest suite and therefore in CI.

Regression for issue #22.
"""

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read_pyproject_version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def _read_json_version(rel: str) -> str:
    with open(ROOT / rel, encoding="utf-8") as fh:
        return json.load(fh)["version"]


def _read_init_version() -> str:
    text = (ROOT / "agent_memory" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    assert match, "__version__ not found in agent_memory/__init__.py"
    return match.group(1)


def _read_plugin_index_version() -> str:
    text = (ROOT / "plugin" / "index.js").read_text(encoding="utf-8")
    match = re.search(r'NOLDOMEM_PLUGIN_VERSION\s*=\s*"([^"]+)"', text)
    assert match, "NOLDOMEM_PLUGIN_VERSION not found in plugin/index.js"
    return match.group(1)


def _collect_versions() -> dict[str, str]:
    return {
        "pyproject.toml": _read_pyproject_version(),
        "agent_memory/__init__.py": _read_init_version(),
        "hooks/package.json": _read_json_version("hooks/package.json"),
        "plugin/package.json": _read_json_version("plugin/package.json"),
        "plugin/index.js": _read_plugin_index_version(),
    }


def test_cross_manifest_version_consistency():
    """All runtime manifests must report the same version string."""
    versions = _collect_versions()
    unique = set(versions.values())
    if len(unique) > 1:
        detail = ", ".join(f"{p}={v}" for p, v in sorted(versions.items()))
        pytest.fail(f"Manifest version mismatch — {detail}")
    # Sanity: the version is a non-empty SemVer-ish string.
    version = unique.pop()
    assert version, "version string is empty"
    assert re.match(r"^\d+\.\d+\.\d+", version), f"unexpected version format: {version}"


def test_version_consistency_detects_mismatch(tmp_path, monkeypatch):
    """The guard must fail when one manifest is out of sync.

    Proves the check is not a constant-true no-op by running it against
    a tree with a deliberately mismatched manifest.
    """
    import tests.test_version_invariants as mod

    # Shadow ROOT with a temp copy that has a mismatched pyproject version.
    fake_root = tmp_path / "fake-root"
    fake_root.mkdir()
    for rel in [
        "pyproject.toml",
        "hooks/package.json",
        "plugin/package.json",
        "agent_memory/__init__.py",
        "plugin/index.js",
    ]:
        dst = fake_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((ROOT / rel).read_bytes())

    # Bump pyproject version only.
    pp = (fake_root / "pyproject.toml").read_text(encoding="utf-8")
    pp = pp.replace('version = "1.27.16"', 'version = "99.99.99"', 1)
    (fake_root / "pyproject.toml").write_text(pp, encoding="utf-8")

    # Point the module at the fake root and verify the guard catches the mismatch.
    monkeypatch.setattr(mod, "ROOT", fake_root)
    try:
        mod.test_cross_manifest_version_consistency()
    except pytest.fail.Exception as exc:
        assert "Manifest version mismatch" in str(exc)
    else:
        pytest.fail("Expected mismatch detection but test passed")
