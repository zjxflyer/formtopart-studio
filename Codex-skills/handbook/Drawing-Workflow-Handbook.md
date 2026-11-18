# Drawing Workflow Handbook / 绘图工作流程使用手册

**Effective Version 7 · Reusable agents and skills · 2026-10-22**

**Effective Version 7 · 通用 agents 与 skills · 2026-10-22**

Use this handbook to start and manage source-based Plan/elevation projects in a new chat. The workflow operates from your current sources, project manifest and saved state. No historical chat name or previous customer folder is required.

使用本手册，可在新聊天中启动和管理依据原图绘制平面图／立面图的项目。流程根据当前原图、项目清单及保存状态运行，不要求提供历史聊天名称或旧客户文件夹。

The frozen version is a recovery baseline. The installation and validation receipts identify the files actually activated and the checks actually performed. Later learning may improve the active working copy without changing this frozen version.

冻结版本是恢复基线。安装和验证凭据说明实际启用的文件及实际完成的检查。后续学习可以改进活动工作副本，但不能改变这个冻结版本。

## 1. Start in a new chat / 在新聊天中开始

Invoke `$drawing-workflow`, give the project root and original source files, and identify the desired sheet order. State whether you are starting new drawings, submitting manual issues or requesting a fresh full review. Supply the requested model and presentation preferences when relevant.

调用 `$drawing-workflow`，提供项目根目录和原始资料，并说明图号顺序。明确本次是首次绘制、提交人工问题，还是要求全量复查；需要时说明模型及表达偏好。

> Use $drawing-workflow for this project. Read the current sources and state first. Create separate Plan/elevation results for each sheet, save progress, and update the index after every sheet. Use the task-tested 2 + 1 + 2 baseline and normal independent checking.
>
> 使用 $drawing-workflow 处理本项目。先读取当前原图和状态。每张图分别生成平面及立面成果，保存进度，每张更新后立即同步 index。采用经过本任务测试的 2＋1＋2 基线，并保持正常独立检查。

Codex should discover available skills and tools, inspect existing records, and ask only for essential missing inputs. The workflow skill coordinates work; `elevation-create-and-audit` supplies technical drawing rules. Specialized object-change, extraction, standards or 3D skills are used only when the request needs them.

Codex 应发现可用技能和工具、查看已有记录，只询问必要且缺失的信息。流程 skill 负责协调，`elevation-create-and-audit` 提供技术绘图规则。只有请求确有需要时，才调用对象修改、提取、标准解释或三维专用技能。

A model name or Fast preference written in a manifest records the request. It does not prove that the runtime used it. Unsupported or unverifiable settings must be reported honestly, without silently reducing the chosen model or checking standard.

清单中的模型名称或 Fast 偏好只是请求记录，并不能证明实际运行采用了该设置。对不支持或无法验证的设置，应如实说明，不能悄悄降低所选模型或检查标准。

## 2. Understand the phases and 2 + 1 + 2 / 理解阶段与 2＋1＋2

**Phase 1: correspondence.** Identify source pages, actual view IDs, locations, directions and Plan/elevation relationships. Use readable mappings and targeted thumbnails. Detailed component extraction and dimension solving belong later. Each sheet must pass this correspondence gate before detailed drawing. Phase 1 is counted separately; its configurable default budget is two rounds.

**Phase 1：对应关系。** 识别原图页、真实视图编号、位置、方向及平立面关系，提供可读映射和必要局部图。详细组件提取、尺寸求解放在后续。每张图通过对应门控后才能进入详细绘制。Phase 1 单独计数，可配置预算默认两轮。

**Initial Phase 2: two total creation/check rounds.** Round 1 includes first creation, self-check and independent Check. Summarize the result. If necessary, round 2 contains a consolidated corrective creation and independent recheck, followed by another summary. Correct work can pass after round 1.

**首次 Phase 2：总共两轮创建检查。** 第 1 轮包含首次创建、自检及独立 Check，之后总结。必要时，第 2 轮集中修复，并独立复核、再次总结。正确成果可以第 1 轮就通过。

**Manual issue repair: one pass.** You inspect the results and provide issues. Codex resolves them individually in the listed order and transfers verified lessons before moving on. One pass may contain many issues and multiple recorded edits/checks; it does not mean one edit, one agent call or exactly one repair for each issue.

**人工问题修复：一遍。** 你查看成果并反馈问题，Codex 按顺序逐项处理，并在进入下一项前传递已验证经验。一遍可以包含多个问题及多次有记录的修改／检查，不代表一次编辑、一次 agent 调用或每个问题只能修一次。

**Full review: two corrective review rounds per sheet.** Round 1 begins with fresh independent checking of the entire current sheet. After Summary/SKIP, it may include the first correction and recheck, then another summary. If core findings remain, round 2 allows the second correction/recheck and summary. Each major round permits at most one corrective creation; there is no hidden unlimited loop inside it.

**全量复查：每张图两轮修复复查。** 第 1 轮先独立检查整张当前成果，总结或 SKIP 后，必要时进行首次修复及复核，再总结。仍有核心问题时，第 2 轮允许第二次修复／复核及总结。每个主要轮次最多一次修复创建，不能在一轮内隐藏无限循环。

The owner's practical **2 + 1 + 2** baseline comes from task/test experience with GPT-6.1 Sol Medium or higher. “Approximately five” is a planning shorthand, not the exact number of checks or calls, a universal optimum, or a guarantee of correctness. Initial work, manual issues and full review have separate records and budgets.

用户的 **2＋1＋2** 实践基线来自 GPT-6.1 Sol Medium 或以上的任务／测试经验。“大约五轮”是计划简称，不是检查或调用次数的精确总和，也不是普遍最优值或正确性保证。首次制作、人工问题和全量复查分别记录、分别计算预算。

One exceptional additional round requires the latest independent checker’s evidence of substantial remaining position, shape or dimension error. Cosmetic issues alone do not qualify. Unresolved core errors remain REVISE or HOLD; a budget limit never creates PASS. A fourth round is rejected by the helper.

特殊追加一轮，需要最新独立检查方证明仍有重大位置、形状或尺寸错误。仅有美观问题不适用。核心错误未解决时保留 REVISE 或 HOLD；不能因轮数用完就改为 PASS。工具会拒绝第四轮。

## 3. Four roles and their boundaries / 四类角色及边界

- **Create:** Reconstruct the assigned sheet, prevent known errors, inspect the actual exports and submit an immutable revision. It cannot independently accept its own work.
  **Create：** 重建分配的图纸、提前拦截已知错误、检查实际导出成果并提交不可变修订，不能独立批准自己的成果。
- **Check:** Establish requirements independently from original evidence and inspect the exact candidate revision. Write findings and review evidence, never repair the creator’s files.
  **Check：** 独立根据原始证据建立要求，检查准确候选版本；编写问题和检查证据，不修补创建方文件。
- **Summarize:** Run after every completed independent check. Extract a useful verified lesson or quickly record SKIP; prepare the next creator’s prevention instructions.
  **Summarize：** 每次独立检查完成后执行，提炼有用且已验证的经验，或快速记录 SKIP，并为下一次创建准备防错要求。
- **Coordinate:** Control scope, order, assignments, counters, dependencies, shared records, publication and recovery. Maintain the mandatory persistent coordinator TODO register described in section 14. Worker completion is not drawing acceptance.
  **Coordinate：** 负责范围、顺序、分配、计数、依赖、共享记录、发布及恢复，必须维护第 14 节说明的持久协调 TODO 登记。工作 agent 完成不等于图纸通过。

Name working tasks by role, exact sheet and stage, for example `Create-K2-INITIAL` and `Check-K2-INITIAL`. Separate sheets require separate names and ownership. Independence is substantive: giving the same author another name does not create an independent checker.

工作任务按角色、准确图号及阶段命名，例如 `Create-K2-INITIAL`、`Check-K2-INITIAL`。不同图纸分别命名并明确归属。独立性是实质要求：给同一个作者换个名称，不会变成独立检查方。

The coordinator is the single writer for shared state, index, queues and release references. Other roles work inside their assigned revision or review areas. Their reports are inputs to the coordinator, not permission to overwrite shared records.

协调方是共享状态、index、队列及发布引用的唯一写入方。其它角色在分配的修订或检查区域内工作，其报告交给协调方处理，不能据此覆盖共享记录。

## 4. Create: prevent errors before handoff / Create：交接前预防错误

Use a short to-do record with step, principle, evidence, result and scope. Mark DONE, PENDING, BLOCKED or NA; explain NA. Complete the common steps first, then add only checks triggered by the sheet’s special features.

使用简短 to-do 记录步骤、原则、证据、结果及范围，标注 DONE、PENDING、BLOCKED 或 NA，并说明 NA。先完成通用步骤，再增加图纸特征实际触发的专项检查。

- Establish required components, connected profiles, operation marks, dimensions and material associations directly from the original source. A renderer’s selected IDs or generated inventory cannot certify original completeness.
  直接从原图确认必要组件、连接轮廓、开启标记、尺寸及材料关联。绘图程序选出的 IDs 或自身生成清单不能证明原图完整覆盖。
- For a new or risky method, finish and compare one recognizable whole-view pilot before batching. Derive the current mapping from independent physical references; do not reuse a historical export transform blindly.
  新方法或有风险的方法先完成一幅可辨认的完整试绘，并比较后再批量处理。根据独立实体参照求出当前映射，不盲用历史导出变换。
- Preserve real physical parts, boundaries, junctions and openings. Read fill, stroke, clipping and paint order; white space may be a genuine opening or knockout, not missing wall ink.
  保留真实实体、边界、连接及洞口，读取填充、描边、裁剪和绘制顺序；白色区域可能是真实洞口或遮挡，不能直接当作缺失墙体。
- Keep printed values, units, qualifiers, witnesses and object ownership. Supported estimates require authorization, method and uncertainty; distinguish them visually. Nearby dimensions may belong to another space.
  保留原尺寸数值、单位、限定符、界线及对象归属。有依据的推断须有授权、方法和不确定性，并在视觉上区别；附近标尺可能属于其它空间。
- Omit evidenced decoration while retaining functional fixtures and real cabinet parts. Preserve each door panel’s source-supported dashed arms, direction, pattern and tips; never dash existing dash fragments again.
  去除有证据支持的装饰，保留功能设备及真实柜体构件。保留各门板有原图依据的虚线臂、方向、模式和尖端，不对已有虚线碎段再次虚线化。
- Inspect actual PDFs and rendered details, not only model data or text extraction. Save source/before/after evidence, changed scope and exact artifact hashes, then request independent checking.
  检查实际 PDF 及渲染细部，不只看模型数据或提取文字。保存原图／修改前／修改后证据、修改范围及准确成果指纹，再提交独立检查。

## 5. Check: verify the actual result independently / Check：独立核验实际成果

Start from the original source, phase mapping, user amendments and exact candidate files. Separate source fidelity, physical geometry, dimensions, symbols, readability, reproducibility and file integrity; success in one category does not prove the others.

从原图、阶段映射、用户修订及准确候选文件开始。分别检查原图忠实度、实体几何、尺寸、符号、可读性、可重复性和文件完整性；一类通过不证明其它类别通过。

- Compare the whole physical footprint, connected parts, positions and genuine openings. Verify overlay registration independently before using differences as evidence.
  比较完整实体范围、连接构件、位置及真实洞口；用叠图差异作证据前，先独立核验配准。
- Verify actual dimension ownership and witness endpoints as well as printed numbers. Confirm visible glyph ink, complete words and material target associations.
  除数值外，还须核验尺寸真实归属和界线端点；确认实际字形墨迹、完整文字及材料目标关联。
- Inspect relevant cabinet tips using operation-only ink or identical-frame subtraction. A visible frame border cannot prove that a missing operation tip was drawn.
  柜门尖端应检查独立开启墨迹，或扣除相同框线；可见边框不能证明缺失开启尖端已经画出。
- Return all material findings in one finite batch, each with region, source/output evidence, core/cosmetic classification and corrective scope. Withdraw wrong interpretations when original evidence disproves them, preserving an erratum.
  集中一次返回所有实质问题，逐项给出区域、原图／输出证据、核心／美观分类及修复范围。原始证据推翻检查解释时，应撤回误判并保留更正记录。

A complete full-review first inspection covers all of that sheet’s own views. Later bounded repairs may reuse unchanged evidence only when hashes, dependencies and source remain valid and no contrary evidence exists. Fast mode does not shorten normal verification.

全量复查的首次检查覆盖该图全部自身视图。后续局部修复仅在指纹、依赖、原图均有效且没有相反证据时，才可复用未改区域证据。Fast 模式不缩短正常核验。

Role conclusions map to helper statuses: CORE_PASS → PASS; cosmetic-only CORE_PASS_WITH_NOTES → PASS_WITH_NOTES; NOT_PASSED → REVISE; unresolved controlling evidence → HOLD or bounded PROVISIONAL where specifically justified. A helper status records evidence; it does not establish fabrication approval.

角色结论与工具状态对应：CORE_PASS → PASS；仅有美观备注的 CORE_PASS_WITH_NOTES → PASS_WITH_NOTES；NOT_PASSED → REVISE；关键证据未明时采用 HOLD，或在具体理由充分时采用有边界的 PROVISIONAL。工具状态记录证据，不代表加工批准。

## 6. Summarize and improve safely / Summarize 与安全迭代

The required sequence is **Create/self-check → independent Check → main-chat evidence → Summarize or SKIP → next dependent repair or release**. The initial full-review check also requires summary. Other independent sheets can continue while one sheet’s summary is being prepared.

必需顺序为 **Create／自检 → 独立 Check → 主聊天证据 → Summarize 或 SKIP → 下一次依赖修复或发布**。全量复查首次检查同样要总结。某图总结时，其它独立图纸可以继续。

Record SKIP quickly when there is no useful new transferable lesson. A repeated application of an existing rule needs a short closure receipt, not another duplicated rule or a global version bump.

没有有用的新可迁移经验时，快速记录 SKIP。现有规则再次应用，只需简短闭环凭据，不新增重复规则，也不必升级全局版本。

For a useful lesson, retain observation, source/output evidence, actual cause, precise creator prevention, checker verification, positive and meaningful defect examples, scope, independent confirmation and any superseded rule. Separate reusable principles, user preferences and project facts; customer dimensions remain local.

有用经验应保存现象、原图／输出证据、实际根因、准确创建方防错、检查方核验、正确及有效缺陷案例、范围、独立确认及被替代规则。区分通用原则、用户偏好和项目事实，客户尺寸留在项目内部。

Adopt through **candidate → scoped validation → independent confirmation → guarded update**. Instruction changes can receive decision-case validation within that scope. Claimed rendering improvements need actual rendered evidence and independent visual checking. A passing rule test does not certify a customer drawing.

采用 **候选 → 范围内验证 → 独立确认 → 受保护更新**。指令改进可以在相应范围用决策案例验证；若声称改善绘图，须有实际渲染证据及独立视觉检查。规则测试通过，不等于客户图纸通过。

The summary agent proposes changes; the designated coordinator applies reviewed updates with fresh fingerprints and backups. Keep running tasks pinned unless explicitly changed. New learning applies forward unless retrospective review is authorized. These are instruction/tool improvements, not model-weight fine-tuning or an autonomous background service.

总结 agent 提出改进，由指定协调方用新鲜指纹及备份应用已审查更新。除非明确变更，运行任务继续绑定原版本。新经验默认用于后续工作；回查旧图需要授权。这些是指令／工具改进，不是模型权重微调，也不是自动后台服务。

## 7. Separate sheets, parallel work and clean pages / 分图、并行及清晰版面

Each sheet owns a focused Plan, only its own elevations, an individual delivery row and independent revision folders. Repeat necessary Plan context rather than sharing one Plan across multiple sheets. Preserve original view IDs, directions and actual view counts; do not force every sheet into a four-view template.

每张图拥有局部聚焦平面图、仅属于该图的立面图、独立交付行及修订目录。宁可重复必要平面背景，也不要多张图共用一张平面。保留原视图编号、方向及真实数量，不强行统一为四视图。

Owner presentation defaults are white surfaces, black physical outlines, blue dimensions and pale-yellow supported estimates. Remove decorative floor patterns, wood grain, furniture, tint clutter and internal diagnostics when evidenced and irrelevant. Keep functional fixtures, physical shape, required dimensions and meaningful wall/grid IDs.

用户表达默认采用白底、黑色实体轮廓、蓝色尺寸及浅黄色有依据推断。对有证据且无关的地板纹理、木纹、家具、色块及内部诊断内容予以去除；保留功能设备、实体形状、必要尺寸及有意义墙／轴编号。

Place compact split-circle view clusters outside the object, with actual source IDs and outward direction tips, without blue view leaders or residual stubs. Keep genuine short wall/grid axes separate. Dimension lanes should sit near the object with a readable gap. Direct current instructions can change these preferences.

将紧凑分隔圆视图组放在对象外侧，使用真实原图编号及向外方向尖端，不保留蓝色视图引线或残留短线。真实短墙／轴线另行处理。尺寸带靠近对象，并留可读空隙。当前直接要求可以修改这些偏好。

Independent reached-sheet work can overlap within actual available capacity. Keep dependent actions sequential and exclusive file areas separate. Do not reorganize unrelated later sheets ahead of the reached work, overwrite frozen history or silently migrate an in-flight task.

已进入处理范围且互不依赖的图纸，可在实际容量内并行；依赖动作仍顺序执行，独占文件区域分开。不要提前跳去整理无关后续图纸、覆盖冻结历史或悄悄迁移在途任务。

## 8. Project manifest and portable helpers / 项目清单与通用工具

Copy the skill’s `templates/project.json` into a new project and replace the example values. Source, output and artifact paths are relative to the project root passed at runtime. Sources must stay outside the output tree. Do not embed an old customer root in reusable instructions.

将 skill 的 `templates/project.json` 复制到新项目，并替换示例值。原图、输出、成果路径相对于运行时传入的项目根目录；原图必须在输出树之外。通用指令不得嵌入旧客户根目录。

```json
{
  "schema_version": 1,
  "project_id": "customer-example",
  "workflow_version": "Effective Version 7",
  "sources": [{"path": "sources/customer.pdf"}],
  "sheets": ["K10", "K2", "R7"],
  "order": "natural",
  "output_dir": "results",
  "model": {"name": "gpt-6.1-sol", "effort": "medium", "fast_requested": false},
  "policy": {"phase1_rounds": 2, "initial_rounds": 2, "manual_issue_passes": 1, "full_review_rounds": 2}
}
```

`natural` orders this example as K2, K10, R7; `manifest` preserves the supplied order. Sheets require safe, unique identifiers. At initialization, missing source hashes are calculated; supplied mismatches are rejected. The manifest records requested settings and binds the workflow version.

`natural` 会把本例排序为 K2、K10、R7；`manifest` 保留清单顺序。图号须安全且唯一。初始化会计算缺省原图指纹；已提供但不匹配的指纹会被拒绝。清单记录请求设置并绑定流程版本。

The helper needs Python 3.10+ for records; `pypdf` is additionally required for PDF packets and merging. Substitute discovered real paths for the placeholders below. Commands do not draw, launch agents or change model settings.

记录工具需要 Python 3.10+；生成 PDF 套件及合并另需 `pypdf`。将下列占位符替换为实际发现路径。命令不会绘图、启动 agents 或修改模型设置。

```text
python <skill>/scripts/workflow.py --root <project> init --manifest <project>/project.json
python <skill>/scripts/workflow.py --root <project> validate
python <skill>/scripts/workflow.py --root <project> artifact-hash --sheet K2 --stage INITIAL
python <skill>/scripts/workflow.py --root <project> checkpoint
```

Active records live under `.drawing-workflow/`. Preserve the manifest, state, source files and every submitted historical/current artifact. Validation binds checks to exact artifact hashes; changing an old pinned revision fails validation even when a newer version has passed.

活动记录保存在 `.drawing-workflow/`。保留清单、状态、原图及每个已提交的历史／当前成果。验证将检查绑定到准确成果指纹；即使新版已通过，修改旧绑定修订仍会导致验证失败。

## 9. Record events, findings and HOLD / 记录事件、问题及 HOLD

The coordinator validates state and submits each event with its exact current `state_sha256`. All events identify `action`, `sheet` and `stage`; manual issues additionally identify `issue`. Use the documented helper contract rather than editing counters manually.

协调方先验证状态，每次事件使用当前准确 `state_sha256`。所有事件指定 `action`、`sheet`、`stage`；人工问题另带 `issue`。按照工具契约操作，不手改计数。

```text
python <skill>/scripts/workflow.py --root <project> event --file <event.json> --expected-state <state_sha256>
```

- `create`: submit the named creator’s new revision; Phase 1 uses a mapping file, detailed stages use own Plan plus elevations. `review`: begin full review with the unchanged current artifacts and their original creator identity.
  `create`：提交具名创建者的新修订；Phase 1 为映射文件，详细阶段为自身平面及立面。`review`：以当前未改成果及原创建者身份开始全量复查。
- `check`: submit an independent checker, exact artifact-set hash, verdict and nonempty evidence; non-PASS also requires findings. `summarize`: record ADOPT, CANDIDATE or SKIP with a note; ADOPT needs verification.
  `check`：提交独立检查者、准确成果集指纹、结论及非空证据；非 PASS 另须问题。`summarize`：记录 ADOPT、CANDIDATE 或 SKIP 及说明；ADOPT 需要验证。
- `hold`: after a completed REVISE and summary, preserve an unresolved issue with the latest checker, reason and evidence. This allows other authorized work to continue without inventing another repair or changing the old verdict to PASS.
  `hold`：已完成 REVISE 及总结后，用最新检查者、原因及证据保留未解决问题。这样可继续其它已授权工作，不虚构修复，也不把旧结论改为 PASS。
- `exception`: record the qualifying third-round basis before extra creation. `release`: publish only an eligible, exactly checked current revision after summary.
  `exception`：追加创建前记录符合条件的第三轮依据。`release`：总结后，只发布已准确检查且符合条件的当前版本。

PASS has no unresolved findings. PASS_WITH_NOTES permits only documented cosmetic findings and is normally deliverable. PROVISIONAL retains explicit bounds or unresolved conditions and needs explicit inclusion for packets/merge. HOLD cannot be released. Evidence fields are references, not automatic proof that an inspection occurred.

PASS 不带未解决问题；PASS_WITH_NOTES 只允许有记录的美观问题，可正常交付；PROVISIONAL 保留明确边界或未决条件，加入套件／合并须明确选择；HOLD 不能发布。证据字段只是引用，不会自动证明检查实际完成。

State updates reject stale hashes, changed pinned files and competing writers. Reconcile real ownership before dealing with a lock. Elapsed time alone does not prove that a worker or transaction has ended.

状态更新拒绝过期指纹、变化的绑定文件及竞争写入。处理锁前应核对真实所有者；仅凭经过时间，不能证明 worker 或事务已经结束。

## 10. Progress, checkpoints and interruption / 进度、检查点及中断

Before every repair, the main chat should announce the exact sheet, stage, major round N/2, correction number and scope. After each completed check, show what changed, the actual source/before/after comparison where applicable, the verdict, current PDF and index links, and Summary/SKIP. Save progress immediately.

每次修复前，主聊天说明准确图号、阶段、主要轮次 N/2、修订次数及范围。每次检查完成后，显示修改内容、适用时的实际原图／前后对比、结论、当前 PDF 与 index 链接，以及 Summary／SKIP，并立即保存进度。

If output or status changes, refresh the sheet’s index entry promptly with truthful labels. A candidate is not an accepted result. Keep useful correction evidence and a short next-step handoff so that resuming does not depend on remembering a chat.

成果或状态变化后，及时用真实标签更新该图 index。候选不等于已验收。保留有用修改证据及简短后续交接，使恢复不依赖聊天记忆。

A checkpoint saves hash-checked records, not source/PDF binaries. To move a project, copy all pinned sources and every historical/current artifact with the same relative paths. Resume into an uninitialized root, then reconcile actual worker activity, summaries, counters and the next authorized action.

检查点保存带指纹验证的记录，不包含原图／PDF 二进制。迁移项目时，应保持相对路径复制全部绑定原图及每个历史／当前成果。恢复到尚未初始化的根目录，再核对实际 worker 活动、总结、计数及下一授权动作。

```text
python <skill>/scripts/workflow.py --root <project> checkpoint
python <skill>/scripts/workflow.py --root <new-project> resume --checkpoint <checkpoint.json>
```

Missing old artifacts, changed sources, damaged snapshots or an existing active state are reasons to stop the restore and preserve evidence. A hash cannot reconstruct a lost drawing. This workflow does not promise a permanent application-health fix, a background watchdog or automatic work after the app exits.

旧成果缺失、原图变化、快照损坏或已有活动状态时，应停止恢复并保留证据。指纹不能重建丢失图纸。本流程不保证永久修复应用故障，不提供后台监控，也不保证应用退出后自动继续工作。

## 11. Per-sheet packets, index and final PDF / 逐图套件、index 及总 PDF

Release the checked revision, build that sheet’s PDF packet, then regenerate the index. A packet contains all of that sheet’s Plan pages followed by only its own elevation pages. Its receipt pins ordered inputs, input artifact hash, page count and output hash.

发布已检查版本后，生成该图 PDF 套件，再更新 index。套件顺序为该图全部平面页，再加仅属于该图的立面页。凭据绑定输入顺序、输入成果指纹、页数及输出指纹。

```text
python <skill>/scripts/workflow.py --root <project> packets --sheet K2
python <skill>/scripts/workflow.py --root <project> index
python <skill>/scripts/workflow.py --root <project> merge --output combined.pdf
```

The index has one row per sheet. **PDF SET—Plan + own elevations** must link to a current valid packet; a Plan-only PDF is labelled **Plan only**. Missing releases remain visibly NOT_RELEASED. Stale packet receipts require regeneration, not silently reused links.

index 每张图一行。**PDF SET—平面＋自身立面整套** 必须链接当前有效套件；只有平面的 PDF 标为 **仅平面**。未发布项明确显示 NOT_RELEASED。套件凭据过期时重新生成，不悄悄复用旧链接。

Final merge follows manifest order: first sheet Plan, its elevations, next sheet Plan, its elevations. Every sheet needs an eligible checked release. PROVISIONAL inclusion requires `--allow-provisional` and disclosed limits. A `.merge.json` receipt records order and hashes; input files are never overwritten.

最终合并按清单顺序：第一张平面、该图立面、下一张平面、该图立面。所有图纸都要有符合条件的核验发布项。包含 PROVISIONAL 时须使用 `--allow-provisional` 并披露边界。`.merge.json` 凭据记录顺序及指纹，不覆盖输入文件。

The compact merge helper does not add a contents page. When requested, add a compact linked contents page and bookmarks as a separate delivery step. Extra proposal/detail pages need explicit placement and scope. Recalculate page numbers after insertion and check every actual link destination, page count, nonempty decoded content and page box.

精简合并工具不添加目录。需要时，另行添加紧凑可点击目录页及书签。额外方案／详图页须明确插入位置及范围。插页后重算页码，检查每个实际跳转目标、总页数、非空解码内容及页面边界。

Static link/file validation and real browser clicking are different checks. Record whichever was actually performed; browser restrictions do not justify claiming a click test passed.

静态链接／文件验证与真实浏览器点击是不同检查。只记录实际完成的检查；浏览器受限不能声称点击测试通过。

## 12. Final delivery acceptance checklist / 最终交付验收清单

For each applicable item, record principle, evidence, status and scope. Mark inapplicable checks with a reason and add sheet-specific checks only when triggered.

每个适用项记录原则、证据、状态及范围；不适用须说明原因，仅在触发时增加图纸专项检查。

- **Physical fidelity:** Required components, placement, connected shapes, real openings and operation marks agree with the source; decorative omissions are justified.
  **实体忠实度：** 必要组件、位置、连接形状、真实洞口和开启标记符合原图，装饰删减有依据。
- **Dimensions:** Numbers, units, qualifiers, endpoints and ownership are correct. Source conflicts remain visible as needed; authorized estimates retain method and uncertainty.
  **尺寸：** 数值、单位、限定符、端点及归属正确；必要原图冲突保留，有授权推断保留方法及不确定性。
- **Actual readability:** All needed glyphs, thin contours, cabinet tips, material words and leaders paint legibly in exported files; no necessary content is hidden by cleanup.
  **实际可读性：** 导出文件中的必要字形、薄轮廓、柜门尖端、材料文字和引线清楚可见，清理不隐藏必要内容。
- **Individual ownership:** Every sheet has its focused Plan and own elevations, correct view references and current presentation; no unrelated shared-plan substitution.
  **独立归属：** 每张图有自身聚焦平面及立面、正确视图引用和当前表达，不用无关共用平面替代。
- **Exact acceptance:** Delivered files and controlling inputs match the independent check’s hashes and scope. Changed artifacts invalidate affected acceptance.
  **准确验收绑定：** 交付文件及控制输入符合独立检查的指纹和范围；成果变化会使相关验收失效。
- **Navigation and order:** Index labels/targets are accurate, packets and total PDF have correct order, contents/bookmark destinations resolve, and decoded pages are nonempty.
  **导航及顺序：** index 标签／目标正确，套件与总 PDF 页序正确，目录／书签能跳转，解码页面非空。
- **Completion and recovery:** Disclose missing, omitted, provisional or held work; save current release references, evidence and checkpoint before declaring completion.
  **完成与恢复：** 披露缺失、删减、暂定或待定工作；宣布完成前保存当前发布引用、证据及检查点。

Layout-review acceptance is not fabrication readiness, site measurement or engineering certification. A proven instruction or test case is not proof that every future drawing will be correct on its first attempt.

布局审阅通过不等于加工就绪、现场量尺或工程认证。指令或测试案例有效，不证明以后每张图首次尝试都一定正确。

## 13. Version use, restoration and safe cleanup / 版本使用、恢复及安全清理

Canonical reusable skills live under the workspace’s `skill-packages/`; the frozen package is `skill-packages/effective-version-7`. A matching shared installed copy enables discovery in other chats. Keep the canonical copies and frozen package even when a temporary staging area is no longer needed.

通用技能正式文件位于工作区 `skill-packages/`；冻结套件为 `skill-packages/effective-version-7`。匹配的共享安装副本使其它聊天能发现技能。即使临时暂存区不再需要，仍保留正式副本及冻结套件。

The package supplies `package-tools/bundle_tool.py`, its instructions, skill snapshots, handbook and compact validation evidence. Discover the target skill root rather than assuming an old user path. Fresh installation and restoration both use a verified package, fresh expected fingerprints and a unique external backup location.

套件提供 `package-tools/bundle_tool.py`、工具说明、技能快照、手册及精简验证证据。应发现目标技能根目录，不假设旧用户路径。首次安装和恢复均使用已验证套件、新鲜预期指纹及独立且不重复的外部备份位置。

```text
python -B <package>/package-tools/bundle_tool.py verify --snapshot <package>
python -B <package>/package-tools/bundle_tool.py current --snapshot <package> --target-root <skills-root> --output <expected.json>
python -B <package>/package-tools/bundle_tool.py apply --snapshot <package> --target-root <skills-root> --expected <expected.json> --backup-root <new-backup>
```

`restore` is an alias for guarded `apply`. Missing new skills require an expected `null`; existing skills require an exact current fingerprint. Snapshot, installation and backup paths must not overlap. Conflicts, active locks, damaged packages and redirected paths are rejected. Never manufacture fingerprints or delete locks to force installation.

`restore` 是受保护 `apply` 的同义操作。新技能不存在时预期值须为 `null`；已有技能须准确匹配当前指纹。套件、安装与备份路径不能重叠。冲突、活动锁、损坏套件及重定向路径会被拒绝。不得伪造指纹或删锁强行安装。

Existing candidates and historical versions are preserved in the installation; existing skills also receive complete verified backups. Managed learning records match the selected snapshot, while earlier records remain in the backup. If a transaction was interrupted, inspect actual process ownership and follow the tool’s recovery instructions; do not restore customer drawings as a side effect.

安装中保留已有候选和历史版本，已有技能另有完整核验备份。受管理学习记录与所选快照一致，原记录保存在备份中。事务中断时核对实际进程所有权，并按工具恢复说明处理；不能附带恢复或覆盖客户图纸。

Before any deletion, archive, move or reorganization, read the workspace-root `KEEP-MANIFEST.json` and cleanup instruction. Protect active canonical skills, the current frozen version, required dependencies, receipts, pinned recovery anchors and all active project source/state/artifact pins. Checkpoints do not replace those binaries. Unknown files require inspection; regenerable-looking previews or staging files are only cleanup candidates, not permission to delete.

删除、归档、移动或整理前，读取工作区根目录的 `KEEP-MANIFEST.json` 及清理指引。保护活动正式技能、当前冻结版本、必要依赖、凭据、指定恢复锚点，以及全部活动项目原图／状态／成果绑定。检查点不能代替这些二进制文件。未知文件须检查；看似可再生成的预览或暂存文件仅是候选，不代表获准删除。

Frozen packages remain immutable; write later receipts outside them. Do not change an old version to make it appear current. A new named Effective Version is a deliberately validated recovery point, not a mandatory outcome of every cycle.

冻结套件保持不可变，后续凭据写在套件外。不能修改旧版，让它看起来像当前版。命名 Effective Version 是有意验证的恢复点，不是每个循环的必需产物。

### Copyable continuation prompts / 可复制的后续指令

> Use $drawing-workflow. Resolve my listed issues one by one, independently check each correction and summarize useful prevention before the next issue. Preserve this manual pass separately from the later full review.
>
> 使用 $drawing-workflow。按顺序逐个处理我列出的问题，独立检查每次修改，并在下一问题前总结有用防错。本次人工问题遍次与之后全量复查分开记录。

> Use the latest verified $drawing-workflow procedures to independently inspect every sheet in manifest order. Apply the two-round full-review baseline, announce each repair count, update that sheet’s index immediately, and save a checkpoint. Do not reopen unrelated work.
>
> 使用最新已验证的 $drawing-workflow 流程，按清单顺序独立检查每张图。采用全量复查两轮基线，通报每次修复计数，立即更新该图 index，并保存检查点。不重新打开无关工作。

> Resume this project with $drawing-workflow. Verify the checkpoint, source and all artifact pins first; reconcile actual worker state, previous summaries and the persistent TODO register. Reassess pending tasks against the latest instructions and verified results, then continue the next authorized step. Keep existing counters and truthful unresolved statuses.
>
> 使用 $drawing-workflow 恢复本项目。先核验检查点、原图及全部成果绑定，核对实际 worker 状态、既有总结及持久 TODO 登记。根据最新指令和已验证成果重估待办，再继续下一授权步骤。保留现有计数及真实未决状态。

> Use Effective Version 7 for a new project. Verify the frozen package and installed-copy match before starting; if they differ, report the difference and use guarded installation or restoration. Preserve other tasks and customer files.
>
> 新项目使用 Effective Version 7。开始前核验冻结套件与安装副本一致；如有差异，说明差异并使用受保护安装或恢复。保留其它任务及客户文件。

### Where to verify details / 详细规则核对位置

Within the selected skill, use `references/workflow.md` for counting, `references/roles/` for responsibilities, `references/project-state.md` for the current event contract, and `references/learning.md`, `delivery.md`, `preservation.md` for adoption, delivery and recovery. The technical skill’s `references/source-fidelity-gates.md` explains the targeted source/export safeguards. Prefer these shipped resources and release receipts over remembered historical claims.

在所选技能内，计数查 `references/workflow.md`，角色职责查 `references/roles/`，当前事件契约查 `references/project-state.md`；经验采纳、交付及恢复分别查 `references/learning.md`、`delivery.md`、`preservation.md`。技术技能的 `references/source-fidelity-gates.md` 说明针对性原图／导出防护。以套件实际资源及发布凭据为准，不依赖历史记忆声明。

## 14. Coordinator TODO register / 协调方 TODO 登记

The coordinator must keep a persistent project TODO register, rather than relying on the current chat or an agent’s short-term notes. Capture every new user issue or authorized task before assigning work. New feedback supplements or explicitly supersedes existing entries; it must not silently erase older pending work.

协调方必须维护持久化的项目 TODO 登记，不能只依赖当前聊天或 agent 临时笔记。每个新用户问题或已授权任务，都须先记录再分配。新反馈是补充或明确替代现有条目，不能悄悄抹去此前未完成工作。

Each entry preserves a stable ID, original request or traceable source, concise intended result, affected sheet and stage, priority, owner, dependencies, status, and completion evidence. Keep the original intent when refining wording. If an instruction changes, retain the predecessor, successor and reason instead of rewriting the old request as though it never existed.

每项保存稳定编号、原始要求或可追溯来源、简明预期结果、涉及图号与阶段、优先级、负责人、依赖、状态及完成证据。整理措辞时保留原意；指令变化时保存前项、后继及原因，不把旧要求改写成仿佛从未存在。

### Reassess context before execution / 执行前重新评估上下文

Before starting or redispatching a TODO, the coordinator must compare its original intent against the latest user instructions, current artifact/check status, completed progress and dependencies. Repeat this review when relevant feedback or results arrive during execution. A preserved TODO is not an instruction to carry out an obsolete action mechanically.

开始或重新分配 TODO 前，协调方必须将原意与最新用户指令、当前成果／检查状态、已完成进度和依赖对照。执行中出现相关反馈或成果时，再次复核。保留 TODO 不意味着机械执行已经过时的动作。

- **Proceed:** The request still applies, its prerequisites are complete and current evidence supports the intended action. Record why it remains necessary before assigning it.
  **继续：** 要求仍有效、前置条件已完成、当前证据支持预期动作。分配前记录仍须执行的理由。
- **Refine or split:** Clarify execution details or create linked subtasks while retaining the original request and sufficient traceable coverage. Record scope changes explicitly; do not silently narrow away requested work.
  **细化或拆分：** 在保留原始要求及充分可追溯覆盖的前提下，明确执行细节或创建关联子任务。明确记录范围变化，不能悄悄缩小而遗漏要求。
- **Replace:** A newer authorized requirement changes the intended result. Create and link its successor, then mark the predecessor SUPERSEDED with the reason and source. Preserve both instructions.
  **替代：** 新的已授权要求改变预期结果时，创建并关联后继任务，再以原因和来源将前项标为 SUPERSEDED；两条指令都保留。
- **Defer or block:** Record the actual priority/dependency or evidence limitation and the next condition for resuming. Continue unrelated authorized work without erasing the pending item.
  **暂缓或受阻：** 记录实际优先级／依赖或证据限制，以及恢复所需条件。继续无关的已授权工作，保留待办项。
- **Cancel:** Require explicit user authorization or an unambiguous contradiction with a newer authorized instruction, and record the supporting source/evidence. The coordinator’s preference or lack of urgency is not cancellation authority.
  **取消：** 须有用户明确授权，或与更新已授权指令存在无歧义冲突，并记录支持来源／证据。协调方个人偏好或不紧急，不构成取消授权。
- **Already evidenced complete:** Verify that existing work actually satisfies the original intent and applicable dependencies, with current artifact/check evidence. Record DONE without unnecessary duplicate work. “No longer needed” alone is not completion and must not be labelled DONE.
  **已有证据证明完成：** 核验已有工作确实满足原意及适用依赖，并有当前成果／检查证据，再记 DONE，避免无意义重复。“不再需要”本身不是完成，不能标为 DONE。

These decisions preserve current authorization and ongoing unrelated work. New feedback, reassessment, reassignment or a successor task never resets drawing rounds. An explicit change of scope must retain the original request and its supersession or split links.

这些决策须保留当前授权及无关在途工作。新反馈、重估、转派或后继任务都不能重置绘图轮次。范围明确变化时，应保留原始要求及其替代或拆分关联。

- **Capture and plan:** Reconcile new requests with the register, identify duplicates or supersessions, set dependencies and assign an eligible owner. Urgent work may change priority without losing the remaining queue.
  **记录及安排：** 将新要求与登记对照，识别重复或替代关系，设置依赖并分配可执行负责人。紧急工作可调整优先级，但不能丢失剩余队列。
- **Track actual work:** Update the item when work starts, is blocked, awaits review or finishes. An owner’s “finished” message is not sufficient completion evidence; bind the applicable review result, exact deliverable or justified administrative closure.
  **跟踪实际工作：** 工作开始、受阻、待检查及完成时更新条目。负责人说“完成”不足以作为完成证据；应绑定适用检查结果、准确交付物或有理由的管理闭环。
- **Keep counters separate:** A TODO item tracks responsibility and intent, not a fresh repair allowance. Splitting, reopening, renaming or reassigning a TODO cannot reset sheet/stage rounds or remove unresolved findings.
  **计数另行管理：** TODO 跟踪责任及意图，不提供新的修复预算。拆分、重开、改名或转派 TODO，不能重置图号／阶段轮数，也不能删除未解决问题。
- **Report and recover:** Briefly show what is being done, what comes next and what is blocked. Save the register with checkpoints and reconcile it on resume. Refresh the index’s task summary without confusing task completion with drawing acceptance.
  **汇报及恢复：** 简要显示正在做什么、下一步及阻碍项。随检查点保存登记，恢复时核对。更新 index 的任务摘要，不能把任务完成混同于图纸通过。

Unresolved work remains visible until completed, explicitly deferred, cancelled or superseded with a reason. A deferral is not PASS. An already authorized independent task may continue while another item is blocked; dependent work must wait for its prerequisites.

未解决工作保持可见，直到完成，或有理由地明确延期、取消、被替代。延期不是 PASS。某项受阻时，已授权的独立任务可以继续；依赖任务必须等待前置条件。

The helper stores the register in project state. `todo-list` returns open tasks and the current state hash; `--all` includes closed items. Use that fresh hash for `todo-add` or `todo-update`, then obtain the new hash before another change. The index shows a task summary; checkpoints and relocation preserve the register. See the shipped `references/todo-list.md` for the complete contract.

工具将登记保存在项目状态中。`todo-list` 返回未闭环任务及当前状态指纹；`--all` 包含已闭环项。`todo-add` 或 `todo-update` 使用新鲜指纹，下一次修改前再获取新指纹。index 显示任务摘要，检查点及迁移保留登记。完整契约查套件内 `references/todo-list.md`。

```text
python <skill>/scripts/workflow.py --root <project> todo-list --all
python <skill>/scripts/workflow.py --root <project> todo-add --file <task.json> --expected-state <state_sha256>
python <skill>/scripts/workflow.py --root <project> todo-update --id T-001 --file <changes.json> --expected-state <fresh_state_sha256>
```

For example, a new `task.json` records the original request and its scope. The priority default is P2; available priorities are P0–P3. Empty `sheet_ids` means project-wide rather than an unknown sheet.

例如，新 `task.json` 记录原始要求及范围。优先级默认 P2，可选 P0–P3。空 `sheet_ids` 表示项目级任务，而不是未知图号。

```json
{
  "id": "T-001",
  "title": "Check the cabinet opening tips",
  "original_request": "Please check and correct the cabinet opening tips on K2.",
  "source_ref": "user-message-001",
  "sheet_ids": ["K2"],
  "stage": "FULL_REVIEW",
  "priority": "P1",
  "owner": "Check-K2-FULL_REVIEW",
  "depends_on": []
}
```

New tasks start PENDING. Other statuses are IN_PROGRESS, BLOCKED, DONE, DEFERRED, CANCELLED and SUPERSEDED. DONE requires new nonempty completion `evidence` and every explicit dependency DONE. BLOCKED needs `blocker_reason`; deferral, cancellation and supersession need a `reason`, and supersession also identifies an existing `superseded_by` task. Record an awaiting-check detail in notes rather than inventing a new status.

新任务从 PENDING 开始。其它状态为 IN_PROGRESS、BLOCKED、DONE、DEFERRED、CANCELLED、SUPERSEDED。DONE 需要新增非空完成 `evidence`，且全部明确依赖均为 DONE。BLOCKED 需要 `blocker_reason`；延期、取消及替代需要 `reason`，替代另须指出已存在的 `superseded_by` 任务。待检查细节写入 notes，不自行新增状态。

Starting, resuming or reassigning an IN_PROGRESS task requires a fresh `context_review`. Its `state_hash` must match the current pre-update hash passed to `--expected-state`; `decision` must be PROCEED, `reason` must explain the current context, and `source_refs` must contain nonempty reference strings. All explicit dependencies must already be DONE. Use actual current references in this example rather than copying invented evidence.

开始、恢复或转派 IN_PROGRESS 任务时，必须提供新鲜 `context_review`。其中 `state_hash` 须与传给 `--expected-state` 的当前修改前指纹相同；`decision` 必须为 PROCEED，`reason` 解释当前上下文，`source_refs` 包含非空引用字符串。全部明确依赖须已 DONE。本例应替换为真实当前引用，不能复制虚构证据。

```json
{
  "status": "IN_PROGRESS",
  "context_review": {
    "state_hash": "<fresh_state_sha256>",
    "decision": "PROCEED",
    "reason": "The latest instruction still requires this correction; current checked artifacts retain the defect and all prerequisites are complete.",
    "source_refs": ["user-message-001", "results/K2/current-check.json"]
  }
}
```

If the correct contextual decision is to defer, block, cancel or replace, record that justified status instead of submitting PROCEED. A context record makes the decision auditable; the helper cannot itself understand user intent or prove that the cited sources support the decision. The coordinator must perform that assessment.

若上下文决定应暂缓、受阻、取消或替代，就记录有理由的相应状态，不提交 PROCEED。上下文记录让决策可审计；工具本身不会理解用户意图，也不能证明引用来源支持该决策，仍须协调方实际评估。

The stable ID, original request and source reference are immutable. Evidence and notes are append-only; changes are audit-logged. Reopening a closed item requires a reason. These administrative updates cannot grant drawing PASS, change the original check history or reset repair rounds.

稳定编号、原始要求及来源引用不可改写。证据与笔记只能追加，变化留审计记录；重开已闭环项须说明原因。这些管理更新不能授予图纸 PASS、改变原检查历史或重置修复轮次。

> Keep a persistent coordinator TODO register for this project. Record new issues before assignment and preserve earlier pending work. Before executing each item, reassess its original intent against my latest instructions, current results and dependencies; proceed, refine, link a replacement or explain a justified defer/block/cancel decision. Do not treat obsolete work as completed. Show current work, next steps and blockers, close only with evidence, and keep repair counters unchanged.
>
> 为本项目维护持久协调 TODO 登记。分配前记录新问题，保留旧待办。每项执行前，根据我的最新指令、当前成果和依赖重估原意，决定继续、细化、关联替代，或说明有依据的暂缓／受阻／取消。不要把过时任务当作已完成。显示当前工作、下一步和阻碍，有证据才闭环，修复计数不变。
