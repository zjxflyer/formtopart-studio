# Shared drawing application, separate customer projects

Keep common code shared and customer launchers/assets inside registered project folders. Each project owns its manifest, seed/model identity, source/evidence, view configuration, database, history and exports. Resolve project paths within that registered directory; reject traversal and unknown keys instead of falling back to another customer. A new empty project must contain no previous customer's geometry and trigger no paid analysis automatically.

Scope scene, evidence, preview, commit, restore, imports and exports to the selected project. A browser tab or preview token from one project cannot mutate another. Keep project IDs, source paths and camera/visibility rules in project configuration rather than generic renderer conditions. Preserve required legacy behavior only through explicit compatibility aliases, not silent defaults.

## Ordinary Windows startup

Test the actual double-click entry from a normal shell without agent-injected paths. Separate the installed runtime and compiled application from explicit setup/rebuild dependencies. A packaged frontend served by the backend should not require Node, pnpm or a development server during normal use.

Resolve executable paths from local configuration and verified absolute fallbacks. Confirm executable identity and required imports before starting. Use process-local environment changes; do not permanently modify Windows PATH. Decode health/configuration data as UTF-8 when non-ASCII paths are involved. If inherited PowerShell module paths are incompatible, prefer the current shell's standard modules process-locally, not a machine-wide reset.

Before reusing a listener, verify application, workspace/project root and build identity. A responding port alone is insufficient. Report foreign or stale services without terminating unidentified processes. Restart only a verified in-scope service when necessary. Missing runtime, missing compiled assets and port conflicts need clear diagnostics; do not silently install packages.

## History migration

Copy active assets and make a consistent SQLite backup, checking source revisions before and after and comparing preserved IDs, revision numbers, timestamps, serialized data and geometry/binding provenance. If the source changes during migration, do not publish or overwrite either history. Explicitly close SQLite connections before moving files on Windows; a transaction context manager need not close a connection.

Leave originals and historical experiments untouched as rollback evidence. Archive obsolete launchers only after migration and new entries pass; record hashes and restoration steps. Keep test runs outside customer-facing roots. Use isolated synthetic projects for editing/migration tests, never the customer's live history.
