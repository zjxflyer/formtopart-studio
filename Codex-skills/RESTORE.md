# Portable installation and restoration / 通用安装与恢复

1. Discover Python 3.10+ and the host's shared skill discovery root. Keep the full package at a stable location. Read its manifest, handbook and package-tools/README.md. Bookkeeping uses only the standard library; PDF packets/merging additionally use `pypdf`. Renderers and source-inspection tools are selected for each real project.
   发现 Python 3.10+ 及主机共享技能发现根目录。完整套件保存在稳定位置，阅读清单、手册及 package-tools/README.md。记录功能仅需标准库，PDF 套件／合并另需 `pypdf`；实际项目另选绘图及原图检查工具。

2. Verify the package, preferably with an externally retained bundle fingerprint. Capture current installed fingerprints into a separate file; inspect differences before replacing anything. Missing skills require expected `null`, existing skills an exact matching fingerprint. A stale fingerprint or active lock is a conflict to resolve, not permission to replace it.
   核验套件，优先使用外部另存的套件指纹。将当前安装指纹写到独立文件，替换前检查差异。不存在技能须预期 `null`，已有技能须准确匹配。过期指纹或活动锁代表须处理的冲突，不代表可以强行替换。

```text
python -B <package>/package-tools/bundle_tool.py verify --snapshot <package> --expected-bundle-fingerprint <pinned-hash>
python -B <package>/package-tools/bundle_tool.py current --snapshot <package> --target-root <skills-root> --output <expected.json>
python -B <package>/package-tools/bundle_tool.py apply --snapshot <package> --target-root <skills-root> --expected <expected.json> --backup-root <new-external-backup> --expected-bundle-fingerprint <pinned-hash>
```

3. Package, target and backup must be disjoint: none may contain another. If restoring canonical files to a workspace that contains the snapshot, first copy the complete package outside that target, verify the relocated copy and use a separate backup. The helper refuses path traversal, redirected paths, damaged snapshots, concurrent transactions and stale current files. It makes a verified complete backup before replacing existing skills. Unrelated skills remain untouched.
   套件、目标及备份路径不能重叠或互相包含。若恢复正式文件的工作区包含该快照，先将完整套件复制到目标之外，核验迁移副本，并使用独立备份。工具拒绝路径穿越、路径跳转、损坏快照、并发事务及过期文件。替换已有技能前完整备份并核验，无关技能不变。

4. `restore` is guarded `apply`, not an unverified overwrite. Existing candidate/version histories remain active; managed records match the chosen snapshot while prior records remain in the full backup. Verify installed fingerprints, open a fresh chat and invoke `$drawing-workflow`. Preserve in-flight task bindings; do not migrate customer data as a side effect.
   `restore` 即受保护的 `apply`，不是无核验覆盖。保留已有活动候选／版本历史；受管理记录匹配所选快照，旧记录仍在完整备份中。核验安装指纹，打开新聊天调用 `$drawing-workflow`。保留在途任务绑定，不附带迁移客户数据。

5. If an installation process actually ended but left a journal, inspect ownership and run `recover --target-root <skills-root>` with this tool. Live owners are rejected. Pre-commit interruption restores originals; committed transactions finish cleanup. Never delete locks to force progress. Preserve backups and later receipts outside the frozen package.
   安装进程确已结束而留有记录时，核对所有权，用本工具执行 `recover --target-root <skills-root>`。活动所有者会被拒绝；提交前中断则恢复原件，已提交则补做清理。不删锁强行推进。备份及后续凭据保存在冻结套件之外。

No old chat, absolute user path, historical customer source or coordinator script is required. This restores skills only; project manifests, state/TODO history and all pinned source/artifact binaries have separate retention and recovery requirements.

无需旧聊天、固定用户绝对路径、历史客户原图或旧协调脚本。本操作只恢复技能；项目清单、状态／TODO 历史及全部绑定原图／成果二进制文件须另行保留和恢复。
