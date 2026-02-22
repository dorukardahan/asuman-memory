# CHANGELOG

<!-- version list -->

## v1.0.0 (2026-02-22)

### Bug Fixes

- Remove build_command and changelog section causing semantic-release errors
  ([`2a68007`](https://github.com/dorukardahan/asuman-memory/commit/2a68007d0ebb44d67f42334b3a5a31d9f14fb0a9))

- Temporal parsing review fixes + single-word patterns
  ([`031a005`](https://github.com/dorukardahan/asuman-memory/commit/031a005dd08a407f75a62c48d7ae699cddc58c35))

- Unset AGENT_MEMORY_API_KEY in test conftest to prevent auth failures in CI
  ([`a03044f`](https://github.com/dorukardahan/asuman-memory/commit/a03044f1d32f8b69d2e1ec2f752743fed7a54d83))

- Use empty string instead of bool for semantic-release config
  ([`3cfdfef`](https://github.com/dorukardahan/asuman-memory/commit/3cfdfefd260928d40a5a049c859e9ba7c89577e7))

### Chores

- Generic rescore script with CLI args, add requirements-dev.txt, CI timeout
  ([`0a888ed`](https://github.com/dorukardahan/asuman-memory/commit/0a888ed7ce90913db8013869ce7147bc2657dbe3))

### Continuous Integration

- Add python-semantic-release for automated versioning
  ([`619ffef`](https://github.com/dorukardahan/asuman-memory/commit/619ffefbb690a6a929ad7ef3f7fa6b300a41b92c))

- Trigger release after CI completes to satisfy branch protection
  ([`122d12d`](https://github.com/dorukardahan/asuman-memory/commit/122d12d088eec45ce115503c8c696163fffa019b))

### Features

- Sync with production — reranker, resilient embedding, backfill, generic cleanup
  ([`fbf29b8`](https://github.com/dorukardahan/asuman-memory/commit/fbf29b886e969b2bceaee002bafed239cce0d056))


## v0.3.0 (2026-02-18)

- Initial Release
