# Portable project records and helper contract
# 通用项目记录与辅助工具契约

Use `scripts/workflow.py` for deterministic gates, counters, file fingerprints, checkpoints and delivery links. It does not draw, run agents, choose a service tier or establish that a visual review truly occurred. The coordinator supplies evidence and must inspect the resulting artifacts. Python 3.10+ is sufficient for bookkeeping; only PDF merging and per-sheet packets require the optional `pypdf` package.

使用 `scripts/workflow.py` 确定性地管理门控、计数、文件指纹、检查点及交付链接。它不会绘图、运行 agents、选择服务速度，也不会证明视觉核验实际发生。协调方负责提供证据，并检查实际成果。记录功能仅需 Python 3.10+；只有 PDF 合并及逐图套件需要可选的 `pypdf`。

For new user requests, register persistent tasks before dispatch using [the TODO contract](todo-list.md). Before starting/resuming or reassigning running work, record a fresh state-bound context review against the latest instructions and progress; cancel or supersede obsolete work with proof rather than marking it completed. TODO state, context reviews, evidence and history survive checkpoints and relocation, and remain separate from drawing counters and independent quality verdicts.

新用户请求分配前，按[待办契约](todo-list.md)登记持久化任务。开始／恢复或重新分配运行中工作前，须结合最新要求及进度，记录绑定当前状态的新重判；过时任务有证据地取消或替代，不能称为完成。待办状态、上下文重判、证据及历史随检查点及迁移保留，与绘图计数及独立质量结论分开。

## 1. Project manifest / 项目清单

Copy `templates/project.json` into a new project and supply its real sources and sheet IDs. The runtime root is passed using `--root`; it is never embedded as an absolute path. Source paths, output paths and artifact paths are relative to that root. Sources must be outside the output tree. Sources lacking a `sha256` are hashed at initialization; a supplied mismatch is rejected.

将 `templates/project.json` 复制到新项目，填写真实原图及图号。运行时用 `--root` 传入根目录，不嵌入绝对路径。原图、输出及成果路径均相对于根目录。原图须位于输出目录之外。初始化时计算未提供 `sha256` 的原图指纹；已提供但不匹配的指纹会被拒绝。

| Field / 字段 | Meaning / 含义 |
|---|---|
| `project_id` | Safe identifier, independent of a historical chat. / 独立于历史聊天的安全标识。 |
| `sources` | Nonempty list of `{path, sha256?}`; paths use `/`, never `..` or absolute paths. / 非空原图清单；路径用 `/`，不得使用 `..` 或绝对路径。 |
| `sheets` | Nonempty, case-insensitively unique safe sheet IDs. / 非空且大小写不敏感唯一的安全图号。 |
| `order` | `natural` sorts numeric portions; `manifest` preserves explicitly requested order. / `natural` 按数字自然排序；`manifest` 保留明确指定的清单顺序。 |
| `output_dir` | Dedicated relative subdirectory, default `results`. / 独立相对子目录，默认 `results`。 |
| `model` | Requested `name`, `effort`, optional `fast_requested`; a record, not proof of runtime model or speed. / 请求的名称、推理档位及可选 Fast 意向；仅为记录，不证明实际运行配置。 |
| `policy` | Separate `phase1_rounds`, `initial_rounds`, `manual_issue_passes`, `full_review_rounds`. / 分别记录映射阶段、首次制作、人工问题遍次、全量复查预算。 |
| `workflow_version` | Bound workflow version; initialization does not change another task’s binding. / 绑定流程版本；初始化不更改其它任务的版本绑定。 |

Safe IDs contain letters, digits, dots, underscores or hyphens, begin with a letter or digit, are at most 80 characters and exclude Windows reserved names. Each sheet owns artifacts below `<output_dir>/<sheet>/`; combined sheet names and shared Plan files are not required or generated.

安全标识由字母、数字、点、下划线或连字符组成，以字母或数字开头，最多 80 字符，并排除 Windows 保留名称。每张图的成果位于 `<output_dir>/<sheet>/` 下；不要求也不生成合并图号或共用平面图。

## 2. Stages, counters and statuses / 阶段、计数及状态

The ordinary practical baseline is **2 + 1 + 2**, for the user’s tested GPT-6.1 Sol Medium-or-higher setup: `INITIAL` allows two total submitted creation/check rounds, including the first creation; `DOCUMENT_ISSUES` is one manual pass containing multiple issue IDs; `FULL_REVIEW` allows two corrective review rounds. Full-review round 1 contains initial inspection/check, summary, necessary first corrective creation/recheck and summary. Round 2 permits the second corrective creation/recheck if a finding remains. `PHASE1` correspondence is tracked separately, with a configurable budget defaulting to two; its budget is not counted inside 2 + 1 + 2. These are task policies, not universal model guarantees.

通常实践基线为 **2＋1＋2**，适用于用户已测试的 GPT-6.1 Sol Medium 或以上配置：`INITIAL` 包含首次创建在内，共两轮提交及检查；`DOCUMENT_ISSUES` 是包含多个问题编号的一遍人工问题修复；`FULL_REVIEW` 共两轮修复复查。全量复查第 1 轮包含首次检查、总结、必要的首次修复及复核、总结；仍有问题时，第 2 轮再进行第二次修复及复核。`PHASE1` 对应关系另行计数，预算可配置、默认两轮，不计入 2＋1＋2。它们是任务策略，不是模型效果的普遍保证。

Each job is keyed by sheet and stage; manual jobs additionally include the issue ID. `major_round`, `repair_revision`, `check_events` and the event sequence remain distinct. First initial creation is round 1 and repair revision 0; corrective creation is round 2 and revision 1. An unchanged first full review is round 1/revision 0; the first corrective creation/check remains round 1/revision 1; a second corrective creation/check is round 2/revision 2. Each full-review major round therefore allows at most one corrective creation, while round 1 may contain two completed check events. Each manual issue stays in manual pass 1 while its repair revisions are recorded. Renaming folders or agent names cannot reset counters.

每项任务由图号和阶段定位；人工问题另带问题编号。`major_round`、`repair_revision`、`check_events` 和事件顺序分别记录。首次制作是第 1 轮、修订 0；修复版是第 2 轮、修订 1。全量复查先检查当前成果，记第 1 轮、修订 0；首次修复及复核仍为第 1 轮、修订 1；第二次修复及复核才是第 2 轮、修订 2。因此全量复查每个主要轮次最多允许一次修复创建，第 1 轮可包含两次完成检查事件。各人工问题保持在人工第 1 遍中，同时分别记录修订次数。修改目录或 agent 名称不能重置计数。

One exceptional additional round may be recorded after an exhausted independently checked `REVISE`, supported by the latest independent checker, substantial `position`, `shape` or `dimension` cause and source/output evidence. Cosmetic reasons do not qualify. A fourth round is rejected. Budget exhaustion never changes an unresolved result to `PASS`.

正常预算耗尽并由独立检查给出 `REVISE` 后，可记录一轮特殊追加修复。必须由最新独立检查方提供重大 `position`、`shape` 或 `dimension` 原因及原图／输出证据。美观问题不适用。第四轮会被拒绝。预算耗尽不会把未解决问题改为 `PASS`。

Statuses are `NOT_STARTED`, `AWAITING_CHECK`, `PASS`, `PASS_WITH_NOTES`, `PROVISIONAL`, `REVISE`, `HOLD`. The role-level term `CORE_PASS_WITH_NOTES` maps to helper status `PASS_WITH_NOTES`: positions, shapes and dimensions are correct; each finding must be an object with `classification: "cosmetic"` and a nonempty `note`, and must not mark `unresolved_core`. It is eligible for release and merge without provisional opt-in. `PROVISIONAL` always retains explicit bounds or unresolved conditions; `PASS` rejects unresolved findings. All completed checks require evidence references. A status is an auditable record, not fabrication approval.

状态包括 `NOT_STARTED`、`AWAITING_CHECK`、`PASS`、`PASS_WITH_NOTES`、`PROVISIONAL`、`REVISE`、`HOLD`。角色规则中的 `CORE_PASS_WITH_NOTES` 对应工具状态 `PASS_WITH_NOTES`：位置、形状及尺寸正确，每个问题须为包含 `classification: "cosmetic"` 及非空 `note` 的对象，且不得标记 `unresolved_core`。它可正常发布及合并，无需待定项确认选项。`PROVISIONAL` 必须保留明确边界或未决条件；`PASS` 不接受未解决问题。每次完成检查必须记录证据引用。状态用于可追溯记录，不代表加工审批。

## 3. CLI and events / 命令及事件

Use the Python interpreter and skill location available in the current environment. The following examples use placeholders; they do not select or install a model.

使用当前环境中的 Python 和 skill 路径。以下示例包含占位符，不会选择或安装模型。

```text
python <skill>/scripts/workflow.py --root <project> init --manifest <project>/project.json
python <skill>/scripts/workflow.py --root <project> validate
python <skill>/scripts/workflow.py --root <project> event --file <event.json> --expected-state <state_sha256>
python <skill>/scripts/workflow.py --root <project> artifact-hash --sheet K2 --stage INITIAL
python <skill>/scripts/workflow.py --root <project> checkpoint
python <skill>/scripts/workflow.py --root <project> packets --sheet K2
python <skill>/scripts/workflow.py --root <project> index
python <skill>/scripts/workflow.py --root <relocated-project> resume --checkpoint <checkpoint.json>
python <skill>/scripts/workflow.py --root <project> merge --output combined.pdf
```

`validate` returns `state_sha256`, sequence, ordered sheets and published sheets. Pass its exact current state hash to each event. Events acquire an exclusive writer lock; stale hashes, changed source/artifact files and competing writers fail rather than overwrite records. Reconcile a lock’s actual owner before removing an orphaned lock; time alone is not evidence that an agent stopped.

`validate` 返回 `state_sha256`、顺序号、排序图号及已发布图号。每次事件须传入当前准确状态指纹。事件使用独占写锁；过期状态、变化的原图／成果、竞争写入都会失败，避免覆盖记录。清理遗留锁前须核对实际持有者；仅凭时间不能判断 agent 已停止。

All events require `action`, `sheet`, `stage`; `DOCUMENT_ISSUES` additionally requires `issue`. Event-specific fields:

所有事件都需要 `action`、`sheet`、`stage`；`DOCUMENT_ISSUES` 另需 `issue`。各类事件字段如下：

| Action / 操作 | Required fields and gate / 必需字段与门控 |
|---|---|
| `create` | `creator`, `artifacts`; new submitted revision. Phase 1 uses `{"mapping":"..."}`; other stages use `{"plan":"...","elevations":["..."]}`. / 创建者及成果；提交新版本。Phase 1 使用映射文件，其它阶段为独立平面及立面列表。 |
| `review` | First `FULL_REVIEW` only; same `creator` and exact artifacts as the current job. / 仅用于首次全量复查；创建者及成果须与当前任务完全一致。 |
| `check` | Independent `checker`, `artifact_sha256`, `verdict`, nonempty `evidence`, `findings` for non-PASS. / 独立检查者、准确成果集指纹、结论、非空证据，非通过时须列问题。 |
| `summarize` | `decision` = `ADOPT`, `CANDIDATE` or `SKIP`; `note`; adoption also needs `verification`. / 采纳、候选或跳过，附原因；采纳另需验证证据。 |
| `hold` | After completed `REVISE` and summary: latest independent `checker`, nonempty `reason` and `evidence`; records HOLD without another create/check or changed verdict history. / 已完成 `REVISE` 并总结后：最新独立检查者、非空原因及证据；不新增创建／检查、不改写历史结论，单独记录待定。 |
| `exception` | Latest `checker`, core `category`, substantial `reason`, nonempty `evidence`. / 最新检查者、核心类别、重大原因及非空证据。 |
| `release` | Publishes the current independently checked `PASS`, cosmetic-only `PASS_WITH_NOTES` or explicitly bounded `PROVISIONAL`, after summary. / 总结后发布当前已独立核验通过、仅有美观备注或有明确边界的成果。 |

Example first creation event after Phase 1 has passed and been summarized:

Phase 1 已通过并总结后，首次创建事件示例：

```json
{
  "action": "create", "sheet": "K2", "stage": "INITIAL",
  "creator": "Create-K2",
  "artifacts": {
    "plan": "results/K2/r01/Plan.pdf",
    "elevations": ["results/K2/r01/Elevation-1.pdf", "results/K2/r01/Elevation-2.pdf"]
  }
}
```

Before checking, obtain the exact set hash with `artifact-hash`; put it in `artifact_sha256`. A checker ID matching the creator is rejected. After **every** completed check, `summarize` or `SKIP` is mandatory before dependent creation, a new issue on that sheet, full review or release. A full review starts with unchanged current-artifact review before corrective creation. `REVISE` manual issues must be resolved or explicitly held before moving to another issue.

检查前用 `artifact-hash` 获取准确成果集指纹，写入 `artifact_sha256`。检查者与创建者同名时会被拒绝。**每次**检查完成后，依赖创建、同张图新问题、全量复查或发布前必须先总结或 `SKIP`。全量复查先检查当前未改成果，再按需修复。人工 `REVISE` 问题须解决或明确保留待定后，才能进入其它问题。

Check evidence and summary verification are references supplied by the responsible agents; the helper validates that they exist as fields, not the truth of an assertion. Independent source comparison, rendering and defect-specific positive/negative checks remain the agents’ responsibility.

检查证据及总结验证是责任 agent 提供的引用；工具核对字段存在，不证明声明真实。独立原图比较、渲染、针对缺陷的正反检查仍由 agents 执行。

To defer an unresolved independently checked issue, submit `hold` after its summary with the latest checker identity, a concrete reason and evidence. It preserves the original REVISE check, repair count and check count; the HOLD is a separate state decision, never a PASS. This permits the next authorized manual issue or full review to proceed, while the held issue remains visible in state. A HOLD itself cannot be released. A job without a summarized REVISE basis cannot be held through this action.

需要暂缓独立检查确认的未解决问题时，先完成总结，再提交 `hold`，填写最新检查者、具体原因及证据。它保留原 REVISE 检查及修复、检查计数；HOLD 是独立的状态决定，不是通过。这允许继续已授权的下一人工问题或全量复查，待定问题仍保留在状态中。HOLD 本身不能发布。没有已总结 REVISE 依据的任务不能使用此操作。

## 4. Files, publication and recovery / 文件、发布与恢复

Initialization creates `.drawing-workflow/project.json` and `state.json`. State keeps the manifest hash, all event records, latest artifacts by stage/issue, checks, current releases and **immutable `artifact_history` for every submitted create/review**. Each historical submission records the job, sequence, creator, counters, source-manifest hash and exact artifact-set hash. Validation checks every historical file and retains exact check-to-submission bindings, even after a later revision passes. Keep these files plus all pinned source and artifact files. Always write new revisions into new directories; changing or deleting a pinned old artifact fails validation and checkpoint creation, even when it is no longer the published revision. States lacking `artifact_history_version: 1` and the history list are explicitly rejected; no silent reconstruction or old-state compatibility is claimed.

初始化生成 `.drawing-workflow/project.json` 及 `state.json`。状态保存清单指纹、全部事件、分阶段／问题的最新成果、检查、当前发布项，以及**每次创建／复查提交的不可变 `artifact_history`**。每条历史提交保存任务、顺序号、创建者、计数、原图清单指纹及准确成果集指纹。验证检查全部历史文件，即使新版已通过，也保留检查与准确提交版本的绑定。应保留这些文件及全部绑定原图、成果。修订始终写入新目录；更改或删除已绑定旧成果会导致验证及创建检查点失败，即使它不再是发布版本。缺少 `artifact_history_version: 1` 及历史列表的旧状态会被明确拒绝；不声称可以静默重建或兼容旧状态。

`packets` creates `<output_dir>/<sheet>/<sheet>-SET.pdf` and `packet.json`: each sheet's complete Plan pages followed by only that sheet's own elevations. Use `--sheet` for the just-updated sheet, or omit it to build all released sheets. `PROVISIONAL` packet inclusion needs `--allow-provisional`; `PASS_WITH_NOTES` does not. The receipt pins the exact input artifact-set hash, ordered inputs, page count and output hash. A packet never overwrites an input. After changed source artifacts are checked and released, regenerate that sheet's packet before publishing its index entry.

`packets` 生成 `<output_dir>/<sheet>/<sheet>-SET.pdf` 及 `packet.json`：每张图全部平面页在前，然后仅为该图自身立面。刚更新一张图时使用 `--sheet`，不指定时处理全部已发布图纸。`PROVISIONAL` 套件需要 `--allow-provisional`；`PASS_WITH_NOTES` 不需要。凭据绑定准确输入成果集指纹、输入顺序、页数及输出指纹。不会覆盖输入。成果变化并检查发布后，应先重新生成该图套件，再发布 index 入口。

`index` creates `<output_dir>/index.html`: one row per sheet, truthful status, a **PDF SET—Plan + own elevations** link only when a current hash-pinned packet exists, plus accurately labelled **Plan only** and individual elevation links. Without a packet, it never labels the Plan as a combined set. Stale or damaged existing packet receipts are rejected and must be regenerated. Unreleased sheets remain visible as `NOT_RELEASED`; they do not silently link to old work. Run it immediately after a sheet changes. `merge` requires every sheet to have a checked release; `PROVISIONAL` inclusion requires explicit `--allow-provisional`. It preserves all pages of each Plan followed by that sheet’s elevations, then the next sheet. It refuses to overwrite an input and emits a `.merge.json` order/hash receipt. These compact helpers do not add a PDF contents page or perform visual certification; use the delivery procedure for linked contents and final visual audit when required.

`index` 生成 `<output_dir>/index.html`：每张图一行，显示真实状态；只有存在当前指纹绑定套件时，才提供 **PDF SET—平面＋自身立面整套** 链接，同时提供准确标为 **仅平面** 及各立面的链接。没有套件时，绝不将平面文件称为整套。已存在但过期或损坏的套件凭据会被拒绝，必须重新生成。未发布图纸显示 `NOT_RELEASED`，不会悄悄链接旧成果。每张图更新后立即执行。`merge` 要求每张图都已有核验发布；包含 `PROVISIONAL` 须显式加 `--allow-provisional`。顺序为每张图的全部平面页、该图立面、下一张图。拒绝覆盖输入，另输出 `.merge.json` 顺序及指纹凭据。这些精简工具不添加 PDF 目录，也不完成视觉认证；需要时按交付流程添加可点击目录并进行最终视觉核验。

`checkpoint` saves a hash-checked record snapshot including immutable submission history. To relocate, copy all pinned sources and historical/current artifacts preserving relative paths, then `resume` the checkpoint into an otherwise uninitialized project root. Resume validates the complete historical pin set and exact check bindings before writing new active records. It refuses active-state overwrite and damaged snapshots; any missing or changed old revision fails. Checkpoints do not embed the PDF binaries. A lost source or old artifact cannot be reconstructed from its hash.

`checkpoint` 保存包含不可变提交历史的指纹检查记录快照。迁移时，保持相对路径复制全部绑定原图、历史及当前成果，然后在尚未初始化的新项目根目录中 `resume` 检查点。恢复前会先验证完整历史指纹及准确检查绑定，再写入新活动记录。禁止覆盖活动状态或使用损坏快照；任意旧版本缺失或变化都会失败。检查点不包含 PDF 二进制文件，不能根据指纹恢复丢失原图或旧成果。

## 5. Tests / 测试

```text
python -m unittest discover -s <skill>/scripts -p test_workflow.py -v
```

Tests create unrelated temporary projects with arbitrary sheet IDs, exercise legal/illegal transitions, distinct counters, summary gates, independent checks, stale fingerprints, writer conflicts, relocation, truthful provisional states, index link targets and real PDF page order. If a sandbox prohibits its default temporary directory, point `DRAWING_WORKFLOW_TEST_TMP` at an explicitly writable temporary parent. No historical project scripts or source files are imported.

测试建立使用任意图号的无关临时项目，覆盖合法／非法状态迁移、独立计数、总结门控、独立检查、过期指纹、写入冲突、迁移、有条件状态、index 链接及真实 PDF 页序。如果沙盒禁止默认临时目录，可将 `DRAWING_WORKFLOW_TEST_TMP` 指向明确可写的临时父目录。不会导入历史项目脚本或原图。
