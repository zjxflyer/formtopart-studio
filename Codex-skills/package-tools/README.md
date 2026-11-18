# Portable bundle tool / 通用套件工具

`bundle_tool.py` uses Python 3.10+ and the standard library. It never edits a registry or assumes a fixed skill list. Run it from any working directory with absolute paths. The examples below are templates: substitute real paths, and keep each backup location unique.

`bundle_tool.py` 使用 Python 3.10+ 和标准库，不编辑版本登记，也不预设技能名单。可从任意目录使用绝对路径运行。下面是指令模板：请替换为实际路径，每次使用新的备份位置。

## 1. Freeze once / 一次冻结

Before freezing, put the handbook, restore/keep instructions, verification evidence and this tool in the destination package. The manifest hashes those files and all managed skill files. Declare skills in a separate JSON specification; do not hardcode project or installed-skill paths inside the tool.

冻结前，将手册、恢复与保留说明、验证证据及本工具放入目标套件。清单会对这些文件及全部受管理技能文件计算哈希。通过独立 JSON 指定技能名单，不在工具中硬编码项目路径或安装路径。

```json
{
  "name": "Effective Version N",
  "created": "2026-10-22",
  "canonical_skill_names": ["drawing-workflow", "example-audit"]
}
```

```text
python -B bundle_tool.py freeze --snapshot PACKAGE --source-root CANONICAL_SKILLS --spec SPEC.json
python -B bundle_tool.py verify --snapshot PACKAGE
```

A package with root `manifest.json` or reserved `skills/` already present is never overwritten. Documentation can exist before freezing. Only the root manifest is omitted from its own file list: nested `manifest.json` files are included. `__pycache__` and `.git` are ignored. Treat the resulting package as immutable; put later execution receipts outside it. Keep the returned bundle fingerprint separately when possible, and use `--expected-bundle-fingerprint HASH` during verification/application to pin it.

套件根目录已有 `manifest.json` 或保留目录 `skills/` 时，拒绝覆盖。冻结前可以预放文档。文件清单只排除根清单本身，内层同名 `manifest.json` 仍计入；忽略 `__pycache__` 和 `.git`。冻结后不要改动套件，后续运行凭据保存在外面。尽量另存返回的套件指纹，验证及应用时可通过 `--expected-bundle-fingerprint HASH` 固定它。

## 2. Inspect then apply / 先查看，再应用

```text
python -B bundle_tool.py current --snapshot PACKAGE --target-root INSTALLED_SKILLS --output EXPECTED.json
python -B bundle_tool.py apply --snapshot PACKAGE --target-root INSTALLED_SKILLS --expected EXPECTED.json --backup-root NEW_BACKUP
```

`current` returns a direct map of every declared skill to its managed fingerprint or `null` when absent. A fresh skill can be installed only when the expected value is `null`; an existing skill can be changed only when its current fingerprint still matches the captured value. `restore` is an alias of `apply` with exactly the same guards. Never manufacture expected fingerprints to bypass a stale-state failure: inspect the changed files and capture a new baseline only when authorized.

`current` 返回每个声明技能的受管理指纹；不存在则为 `null`。仅预期值为 `null` 时才可首次安装，已有技能则必须与捕获指纹保持一致。`restore` 是 `apply` 的同义命令，保护条件相同。不得伪造预期值绕过过期状态：应先查看变动，得到授权后才重新捕获基线。

The snapshot, target and backup directories must not overlap. The backup must be a new location outside the installed-skill root. Every existing skill is fully backed up and the copy is verified, including caches and all learning history. Symlinks, junctions, reparse-point redirects, path traversal, duplicate names and unsupported filesystem objects are rejected. Unrelated installed skills are untouched.

套件、安装目录和备份目录不能互相包含。备份必须位于安装根目录之外，且是新位置。已有技能全部完整备份并核验，包含缓存和所有学习历史。拒绝符号链接、目录联接、重解析跳转、路径穿越、重复名称及不支持的文件对象。不涉及的已安装技能不受影响。

## 3. Learning-history policy / 学习历史规则

Managed fingerprints exclude `.git`, `__pycache__`, `learning/candidates/`, `learning/versions/` and `learning/**/update.lock`. They retain `learning/records/`. The algorithm is the established sorted relative path + NUL + content SHA256 digest algorithm.

受管理指纹排除 `.git`、`__pycache__`、`learning/candidates/`、`learning/versions/` 和 `learning/**/update.lock`；保留 `learning/records/`。算法沿用既有方式：按相对路径排序，对路径、NUL 及内容 SHA256 摘要汇总。

During application, existing candidates and historical versions stay in the active installation. Managed learning records match the selected frozen snapshot; earlier records remain in the complete backup. Records are not silently merged, because that would invalidate the selected version's fingerprint. A skill's `learning/update.lock` blocks an update.

应用时，已有候选经验和历史版本保留在活动安装中。受管理学习记录以选定快照为准，原记录仍保存在完整备份中。不静默合并记录，避免破坏所选版本的指纹。技能的 `learning/update.lock` 会阻止更新。

## 4. Transactions and interrupted recovery / 事务及中断恢复

All declared skills share one exclusive transaction lock beside the installed-skill root. Before replacement, the tool verifies the snapshot, expected state, update locks, backups and staged fingerprints again. A failed replacement rolls all replaced skills back. A verified commit is not rolled back merely because temporary-directory cleanup fails.

所有声明技能共用安装根目录旁的一个独占事务锁。替换前再次核验套件、预期状态、更新锁、备份及暂存指纹。替换失败时回滚全部已替换技能；已经验证提交成功时，不会仅因临时目录清理失败而倒退。

If the tool process has actually ended with a journal remaining, run:

如果工具进程确已退出但仍留有事务记录，运行：

```text
python -B bundle_tool.py recover --target-root INSTALLED_SKILLS
```

Recovery refuses a still-active owner process. A pre-commit interruption restores original states; a committed transaction only finishes cleanup. Unexpectedly changed files, invalid journals or unavailable originals stop recovery and preserve the journal and full backup for inspection. Do not delete locks just to force installation. These locks coordinate this tool and cooperating skill updaters; they are not an operating-system security boundary against arbitrary external writes.

恢复会拒绝仍在运行的事务所有者进程。提交前中断则恢复原状态，已提交事务只补做清理。出现意外改动、无效记录或原件缺失时停止恢复，保留记录和完整备份供检查。不要删除锁来强行安装。这些锁协调本工具及遵守锁的技能更新程序，不是阻止任意外部写入的操作系统安全边界。

## 5. Meaningful verification / 有效验证

```text
python -B test_bundle_tool.py
```

Tests exercise fresh and mixed installation, full-history preservation, stale expected hashes, active update and transaction locks, package tampering (including nested manifests), path traversal, forced multi-skill swap failures, interrupted recovery, live-owner refusal and reparse defenses. Tests use temporary folders beside the test file and do not change installed skills or registries. Actual file-symlink/junction integration may be skipped only if the platform permits neither; the reparse-rejection branch is separately exercised without elevated privileges.

测试覆盖首次及混合安装、完整历史保留、过期指纹、活动更新与事务锁、套件篡改（含内层清单）、路径穿越、强制多技能替换失败、中断恢复、拒绝活动所有者及重解析防护。测试只使用测试文件旁的临时目录，不修改安装技能或版本登记。仅当平台既不允许符号链接也不允许目录联接时，跳过真实链接集成检查；另有无需提权的重解析拒绝分支测试。
