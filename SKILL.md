---
name: smax-complete-task
description: Fill the "完成摘要" (CompletionSummary) field of a Capitaland SMAX Task and optionally close the task, via the EMS REST API. Use when the user says things like "填 SMAX 完成摘要", "完成/关闭 SMAX 任务", "complete SMAX task <id>", "set task completion summary", or references the SMAX task page at serviceprod.capitaland.com.cn/home/task/<id>/general.
---

# SMAX Complete Task

Fills a Task's **CompletionSummary** field with text and optionally embeds one or more screenshots, then optionally closes the task, via the SMAX EMS REST API. No browser, no XSRF — uses the `SMAX_AUTH_TOKEN` cookie obtained by logging in as `inc.integration`.

## Run

```bash
# 1) Read-only: see current Status/PhaseId/LastUpdateTime (do this first to discover close values)
python .claude/skills/smax-complete-task/scripts/complete_task.py --task-id <TASK_ID> --show-status

# 2) Write completion summary only (no close)
python .claude/skills/smax-complete-task/scripts/complete_task.py --task-id <TASK_ID> --summary "处理完成"

# 3) Write summary + screenshot(s)
python .claude/skills/smax-complete-task/scripts/complete_task.py --task-id <TASK_ID> \
  --summary "处理完成" --screenshot C:\path\to\webpage-screenshot.png

# 4) Write summary, screenshot(s), AND close the task (supply the closed Status + CompletionCode discovered in step 1)
python .claude/skills/smax-complete-task/scripts/complete_task.py --task-id <TASK_ID> \
  --summary "处理完成" --screenshot C:\path\to\webpage-screenshot.png \
  --status <CLOSED_STATUS> --completion-code <CODE>
```

Password for `inc.integration` is prompted via `getpass` (hidden input).

## How it works
1. `POST /auth/.../authenticate/token` → JWT (cookie value).
2. Optional screenshot files are uploaded to FRS `POST /rest/{tenant}/frs/file-list/` and returned as file GUIDs.
3. `GET /rest/{tenant}/ems/Task/{id}` → read `LastUpdateTime` (ms-epoch, optimistic-lock token) + current state.
4. Build HTML: plain text becomes `<p>...</p>`, screenshots are appended as `<img src="../rest/{tenant}/frs/file-list/{guid}">` blocks.
5. `POST /rest/{tenant}/ems/bulk` with `{"entities":[{"entity_type":"Task","properties":{...}}],"operation":"UPDATE"}`.
6. Verify `meta.completion_status == "OK"` and per-entity `completion_status` ∈ {`OK`, `SUCCESS`, `COMPLETED`}.
7. Re-GET and print new `Status`/`PhaseId`.

## Caveats
- **Close values:** the Task's closed `Status` and `CompletionCode` enum are not pre-known. Run `--show-status` first; after a close, confirm `PhaseId` moved. If `PhaseId` did **not** change, a direct `Status` set didn't close it — fall back to `POST /rest/{tenant}/workflow/Task` (not implemented yet).
- **Screenshots:** provide a local image file path. The script uploads it to FRS and embeds the returned file GUID into `CompletionSummary`.
- **Do not run the write against production tasks** (`12167079`). Use a test task you own.
- No XSRF token needed for direct EMS REST (the prior probe returned 200 without it).
