# Audit and Release Checklist

Use this checklist before merging, tagging, releasing, or updating a runtime host.

## Local audit

```bash
scripts/audit.sh
```

Optional Clawpatch smoke, using a local checkout of `openclaw/clawpatch`:

```bash
REQUIRE_CLAWPATCH=1 scripts/audit.sh
```

The Clawpatch smoke writes state outside the repo under `/tmp/noldo-memory-clawpatch-smoke-*`.

## Script safety checks

For scripts that write databases, vectors, state files or exports:

- prepare replacement data before touching live state;
- write output through a same-directory temp file and atomic replace when possible;
- commit database state and sync metadata in the same successful path;
- skip secondary side effects when primary storage fails;
- close pools/tasks on all return paths;
- never accept raw secrets through command-line arguments.

## Runtime alignment checks

After a release, verify:

- `pyproject.toml`, plugin package metadata and `plugin/openclaw.plugin.json` use the same version;
- OpenClaw install records and runtime plugin manifest report that exact version;
- Hermes Dorry and Hermes Dobby plugin copies report that exact version when they use the NoldoMem adapter;
- `/v1/health/deep` or the relevant runtime doctor succeeds without printing API keys, tokens or phone numbers.

NoldoMem releases are manual. Do not reintroduce semantic-release automation.
