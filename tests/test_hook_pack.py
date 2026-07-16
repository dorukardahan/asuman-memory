import json
import os
import re
import subprocess
from pathlib import Path

VALID_MEMORY_TYPES = {"fact", "preference", "rule", "conversation", "lesson", "other"}


def test_hook_pack_entries_are_installable():
    repo_root = Path(__file__).resolve().parent.parent
    hooks_root = repo_root / "hooks"
    manifest = json.loads((hooks_root / "package.json").read_text())
    hook_entries = manifest["openclaw"]["hooks"]

    assert hook_entries, "openclaw.hooks must declare at least one hook"

    for entry in hook_entries:
        hook_dir = (hooks_root / entry).resolve()
        assert hook_dir.is_dir(), f"hook directory missing: {entry}"
        assert (hook_dir / "HOOK.md").is_file(), f"HOOK.md missing: {entry}"
        assert (hook_dir / "handler.js").is_file(), f"handler.js missing: {entry}"

        example_path = hook_dir / "handler.js.example"
        if example_path.is_file():
            assert (hook_dir / "handler.js").read_text() == example_path.read_text(), (
                f"handler.js drifted from handler.js.example: {entry}"
            )


def test_hook_pack_only_sends_public_memory_types():
    repo_root = Path(__file__).resolve().parent.parent
    hooks_root = repo_root / "hooks"
    hook_sources = list(hooks_root.glob("*/handler.js")) + list(
        hooks_root.glob("*/handler.js.example")
    )

    assert hook_sources

    for source in hook_sources:
        for match in re.finditer(r'memory_type:\s*"([^"]+)"', source.read_text()):
            assert match.group(1) in VALID_MEMORY_TYPES, (
                f"{source} sends invalid memory_type={match.group(1)!r}"
            )


def test_after_tool_call_redacts_secrets_before_memory_capture():
    repo_root = Path(__file__).resolve().parent.parent
    source = (repo_root / "hooks" / "after-tool-call" / "handler.js").read_text()

    assert "function redactSecrets" in source
    assert "redactSecrets(toolOutput)" in source
    assert "redactSecrets(toolInput.command || toolName)" in source
    assert "Secret sanitizer removed" not in source
    assert "Storing secrets in memory is intentional" not in source


def test_post_response_memory_writes_use_bounded_background_queue():
    repo_root = Path(__file__).resolve().parent.parent
    helper = (repo_root / "hooks" / "lib" / "memory-api.js").read_text()
    hook_sources = {
        path.name: (path / "handler.js").read_text()
        for path in (repo_root / "hooks").iterdir()
        if path.is_dir() and (path / "handler.js").is_file()
    }

    assert "maxInFlight = 8" in helper
    assert "postBackground" in helper
    assert "memory write queue full" in helper
    for name in ("after-tool-call", "claim-scanner", "realtime-capture", "session-end-capture"):
        assert "createMemoryPoster" in hook_sources[name]
    for source in hook_sources.values():
        assert "await fetch(`${MEMORY_API}/store`" not in source
    assert "Promise.allSettled(storePromises)" not in hook_sources["claim-scanner"]


def test_session_end_todo_scanner_requires_structural_markers(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    script = """
import { extractUnfinishedWork } from "./hooks/session-end-capture/handler.js";

const ordinaryProse = extractUnfinishedWork([
  { role: "assistant", text: "Kalan işleri bitirdim; başka bir işlem gerekmiyor." },
  { role: "assistant", text: "Bu yanıt hâlâ onay bekliyor ama bir görev listesi değil." },
  { role: "assistant", text: "The remaining time is short, so the explanation is concise." },
  { role: "assistant", text: "The unfinished sentence is quoted only as an example." },
]);
if (ordinaryProse.length !== 0) {
  throw new Error(`ordinary prose was captured: ${JSON.stringify(ordinaryProse)}`);
}

const actionableItems = extractUnfinishedWork([
  {
    role: "assistant",
    text: "Tamamlananları özetledim.\\n- [ ] bu işi yap\\nTODO: refactor search\\nTODO implement search\\nFIXME tighten timeout",
  },
]);
const expected = [
  "- [ ] bu işi yap",
  "TODO: refactor search",
  "TODO implement search",
  "FIXME tighten timeout",
];
if (JSON.stringify(actionableItems) !== JSON.stringify(expected)) {
  throw new Error(`actionable items were not captured: ${JSON.stringify(actionableItems)}`);
}
"""

    subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=repo_root,
        env={"HOME": str(tmp_path), "PATH": os.environ.get("PATH", "")},
        check=True,
        capture_output=True,
        text=True,
    )
