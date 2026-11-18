# Persistent coordinator TODO register
# 协调方持久化待办登记

Record every new authorized issue or task before dispatch, using a stable ID in `.drawing-workflow/state.json` under `todo`. Keep existing tasks when a new request arrives; reprioritize or explicitly defer them rather than replacing the list. Preserve the exact original request and its source reference. A task record can cover one sheet, several sheets, or the project. It does not grant new authorization or certify a drawing.

每项新授权问题或任务都应在分配前，以稳定编号写入 `.drawing-workflow/state.json` 的 `todo` 中。新请求到来时保留已有任务，通过调整优先级或明确暂缓处理，不能替换整个列表。保留准确原话及来源引用。一项待办可对应单张、多张图或整个项目；登记不扩大授权，也不代表图纸通过。

## Fields and status / 字段与状态

`todo-add` requires `id`, `title`, `original_request`. Optional fields are `source_ref`, `sheet_ids` (empty means all/project-wide), `stage` (`PROJECT` by default; also `PHASE1`, `INITIAL`, `DOCUMENT_ISSUES`, `FULL_REVIEW`, `DELIVERY`), `priority` (`P0` highest to `P3`, default `P2`), `owner` (default `Coordinate`), `depends_on`, `evidence` and `notes`. Dependencies reference existing stable task IDs; self-links, unknown dependencies and cycles are rejected. Sheet IDs must belong to the manifest. Equivalent original-request/source/scope/stage records are rejected as duplicates even if renamed.

`todo-add` 必需 `id`、`title`、`original_request`。可选字段为 `source_ref`、`sheet_ids`（空列表表示全部／项目级）、`stage`（默认 `PROJECT`，也支持 `PHASE1`、`INITIAL`、`DOCUMENT_ISSUES`、`FULL_REVIEW`、`DELIVERY`）、`priority`（`P0` 最高至 `P3`，默认 `P2`）、`owner`（默认 `Coordinate`）、`depends_on`、`evidence` 及 `notes`。依赖必须引用已有稳定编号；拒绝自依赖、未知依赖及依赖环。图号必须来自项目清单。同原话、来源、范围及阶段的记录即使改名，也会被判为重复。

Every new task starts `PENDING`. Updates may use `IN_PROGRESS`, `BLOCKED`, `DONE`, `DEFERRED`, `CANCELLED` or `SUPERSEDED`. Every update entering `BLOCKED` needs a fresh `blocker_reason`; every deferral, cancellation and supersession needs a fresh explicit `reason` in that update, never a reused prior reason. Cancellation/supersession also require fresh contextual evidence; supersession needs a different existing `superseded_by` ID. Closed tasks remain in history and are included with `todo-list --all`. Reopening a closed task requires a reason. No delete operation exists.

新任务初始为 `PENDING`。更新可使用 `IN_PROGRESS`、`BLOCKED`、`DONE`、`DEFERRED`、`CANCELLED` 或 `SUPERSEDED`。每次进入 `BLOCKED` 都须在本次更新提供新的 `blocker_reason`；每次暂缓、取消、替代都须在本次更新明确提供新的 `reason`，不能沿用旧原因。取消／替代还需新的上下文证据；替代须引用另一个已有 `superseded_by` 编号。已关闭任务仍保留历史，使用 `todo-list --all` 可查看。重新打开已关闭任务需要原因。不提供删除操作。

`DONE` requires fresh, nonempty completion `evidence` in that update and every explicit dependency already `DONE`. Evidence entries are nonempty reference strings or objects whose `ref`, `path` or `url` is a nonempty string; booleans and placeholder values do not establish a reference. The coordinator must actually verify the referenced outcome. Starting dependent `IN_PROGRESS` work also requires all explicit dependencies `DONE`. Worker termination or a worker’s claim alone never triggers completion. TODO completion is separate from independent drawing PASS, and changes no drawing cycle counters. Remaining core issues still use truthful drawing states.

`DONE` 更新必须附新的非空完成 `evidence`，且全部明确依赖都已 `DONE`。证据项可为非空引用字符串，或 `ref`、`path`、`url` 值为非空字符串的对象；布尔值或占位值不能构成引用。协调方须实际核验所引用的结果。依赖任务开始进入 `IN_PROGRESS` 前，也须全部明确依赖均已 `DONE`。worker 结束或其自述不会自动触发完成。待办完成与图纸独立检查通过分开，不改变绘图循环计数。核心问题仍须在图纸中保留真实状态。

Original request, source reference, ID, creation timestamp and audit history cannot be overwritten through updates. `notes` and `evidence` are append-only lists. Every change records timestamps, the previous/new statuses, requested changes and appended evidence/notes. Priorities, ownership, scope and dependencies may be explicitly revised with their history retained.

更新不能覆盖原话、来源引用、编号、创建时间或审计历史。`notes` 和 `evidence` 为只追加列表。每次变更记录时间、前后状态、请求变更及追加证据／说明。优先级、责任人、范围及依赖可明确调整，历史保留。

## Reassess against current context before dispatch / 分配前结合最新上下文重判

Before starting or resuming a task, compare its preserved intent with the latest user instructions, actual progress, dependencies and current outputs. Decide whether to **KEEP**, **REVISE** the authorized implementation, **SUPERSEDE**, **CANCEL**, **DEFER**, **BLOCK**, or mark **DONE** only with verified completion. Split a task only when its authorized scope warrants separately tracked subtasks; preserve the parent and relationships. Do not blindly execute obsolete tasks or broaden the request. A task that became unnecessary is cancelled or superseded with proof, never falsely marked DONE.

开始或恢复任务前，须结合最新用户要求、实际进度、依赖及当前成果，重新判断保留的原始意图。决定应当**保留**、**调整**已授权实现、**替代**、**取消**、**暂缓**、**受阻**，还是有已验证完成证据才记为 **DONE**。只有授权范围确有需要时才拆分子任务，并保留父项及关系。不能机械执行过时任务或扩大请求。已不再需要的任务应有证据地取消或替代，不能虚假标为完成。

Every update setting `status: "IN_PROGRESS"`—including resuming an already-running task—and every reassignment of an `IN_PROGRESS` task requires a new `context_review` with exactly `state_hash`, `decision: "PROCEED"`, a nonempty `reason`, and a nonempty list of nonempty `source_refs` strings. Use the exact current pre-write hash returned by `todo-list` both in `context_review.state_hash` and `--expected-state`. A newly recorded request changes the state hash and invalidates a prepared review. Reconsider its meaning, not merely substitute a fresh hash. Reviews are appended to `context_reviews` and retained in immutable update history. Ordinary new intake does not automatically cancel already-running work.

每次设置 `status: "IN_PROGRESS"`（包括恢复已进行的任务），以及每次重新分配 `IN_PROGRESS` 任务，都需要新的 `context_review`，包含且仅包含 `state_hash`、`decision: "PROCEED"`、非空 `reason`，以及由非空引用字符串组成的非空 `source_refs` 列表。将 `todo-list` 返回的准确写入前当前指纹，同时填入 `context_review.state_hash` 和 `--expected-state`。登记新请求会改变状态指纹，使此前准备的重判失效。应重新考虑其含义，不能只替换新指纹。重判会追加到 `context_reviews`，并保留在不可覆盖的更新历史中。新请求登记不会自动取消已运行工作。

The helper checks freshness and record completeness, not whether semantic reasoning truly occurred. For a non-PROCEED outcome, use the appropriate existing status update with fresh reason/evidence and a linked replacement when applicable. Original request text remains unchanged. No separate review engine or automatic cancellation policy is introduced.

工具仅核对新鲜度及记录完整性，不能证明真正进行了语义判断。如果不应继续，使用适当的既有状态更新，提供新的原因／证据，并在适用时关联替代任务。原始请求文本保持不变。不引入额外评审引擎或自动取消策略。

## CLI and API / 命令与接口

```text
python <skill>/scripts/workflow.py --root <project> todo-list
python <skill>/scripts/workflow.py --root <project> todo-add --file <task.json> --expected-state <state_sha256>
python <skill>/scripts/workflow.py --root <project> todo-update --id issue-17 --file <changes.json> --expected-state <state_sha256>
python <skill>/scripts/workflow.py --root <project> todo-list --all
```

`todo-list` returns the current `state_sha256` and tasks, ordered by priority and creation time. Default output includes pending, running, blocked and deferred tasks. Add/update share the exclusive writer lock and stale-state rejection used by workflow events. Python APIs are `todo_add(root, task, expected_hash)`, `todo_update(root, task_id, changes, expected_hash)` and `todo_list(root, include_closed=False)`; the list API returns task records directly.

`todo-list` 返回当前 `state_sha256` 及按优先级、创建时间排列的任务。默认包含待办、进行中、受阻及暂缓项。添加／更新与流程事件共用独占写锁及过期状态拒绝机制。Python 接口为 `todo_add(root, task, expected_hash)`、`todo_update(root, task_id, changes, expected_hash)` 及 `todo_list(root, include_closed=False)`；列表接口直接返回任务记录。

Example add file:

添加文件示例：

```json
{
  "id": "issue-17",
  "title": "Check the cabinet opening tip",
  "original_request": "Please correct the cabinet dashed-line tip and recheck it.",
  "source_ref": "user-message-17",
  "sheet_ids": ["K2"],
  "stage": "FULL_REVIEW",
  "priority": "P1",
  "owner": "Coordinate",
  "depends_on": [],
  "notes": ["Register before dispatching independent repair/check tasks."]
}
```

Example completion update after actual verification:

实际核验完成后的更新示例：

```json
{
  "status": "DONE",
  "evidence": [{"path": "results/K2/review-r02/check-report.json", "note": "Independent checker verified the actual PDF and PNG tip."}],
  "notes": ["Updated the own-sheet PDF SET and index link."]
}
```

Example start/resume update after reading the latest context; substitute the current hash and actual source references:

阅读最新上下文后的开始／恢复更新示例；须替换为当前指纹和实际来源引用：

```json
{
  "status": "IN_PROGRESS",
  "context_review": {
    "state_hash": "<current-state-sha256>",
    "decision": "PROCEED",
    "reason": "The latest instruction still requires this correction; the prerequisite review is complete.",
    "source_refs": ["latest-user-message", "current-independent-check-report"]
  }
}
```

TODO intake/listing deliberately remains available when source/artifact integrity checks fail, so a newly reported fault can still be registered. Its response is `TODO_RECORDED_NOT_A_DRAWING_VERDICT`; it does not claim that broken drawings became valid. Checkpoints and resume still require all pinned drawing files, and preserve the entire TODO register and history. Index generation shows an open-task summary alongside truthful sheet statuses; it still refuses stale drawing or packet links.

原图／成果完整性检查失败时，待办接收与查看仍可用，以免新问题无法登记。其响应为 `TODO_RECORDED_NOT_A_DRAWING_VERDICT`，不表示损坏图纸变为有效。检查点与恢复仍须核验全部绑定绘图文件，并保留完整待办及历史。index 在真实图纸状态旁显示未结待办摘要，仍拒绝过期图纸或套件链接。
