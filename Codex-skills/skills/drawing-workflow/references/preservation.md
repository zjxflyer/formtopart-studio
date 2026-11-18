# Preservation, cleanup and relocation

Keep active canonical skill folders, the current frozen Effective Version, its manifest/restore helper, installed-version receipt, handbook and required dependencies. In the workspace, consult the root KEEP-MANIFEST.json before cleanup or reorganization. Unknown paths are review-required, not automatically disposable.

Historical project files are not runtime dependencies of this skill. Their paths may remain optional provenance; deletion does not turn their old claims into freshly verified evidence. Preserve the compact source-independent cases and adoption records shipped with the version. Customer sources and active project state have their own retention requirements.

A frozen version is immutable. Old protected recovery anchors remain unchanged unless the user authorizes their archival/removal. Regenerable previews/caches may be classified for a later cleanup, but this skill's creation does not authorize deleting them. Do not protect every historical intermediate indefinitely or guess that all old skill files are useless.

Canonical reusable files and version packages may live inside the owner's workspace. The shared installed copy enables other chats to discover the skill, but is not the only backup. Never replace canonical files with symlinks into a temporary or deletable old-task folder. Use relative package resources and a caller-supplied project root.

To relocate: copy the complete package, verify its manifest, discover a working Python runtime and the target skill root, capture fresh expected fingerprints (including null for a missing new skill), and use the bundled guarded restore helper with an external new backup directory. Verify installed fingerprints and preserve local histories. Do not restore customer outputs as a side effect.

On resume, verify project source/artifact hashes and reconcile claims separately from actual worker activity. If runtime/library capabilities are unavailable, report the limitation and preserve files; do not fake a successful fresh-chat invocation or visual review.
