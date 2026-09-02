# SMAX Task "完成摘要" (CompletionSummary) Skill — Design

- Date: 2026-08-12
- Status: Approved (approach A; close-values: runtime auto-discover; image deferred)
- Target page: `https://serviceprod.capitaland.com.cn/home/task/{taskId}/general?TENANTID=820189321`
- HAR evidence: `serviceprod.capitaland.com.cn.har` (browsing only — **no save captured**)

## Goal

Fill the "完成摘要" field on a Capitaland SMAX Task and close the task, via REST API, packaged as a Claude Code skill. **Text only in v1**; image support deferred.

## Confirmed facts (from HAR + prior probe)

- Entity is **`Task`** (not Incident). Example id `12167079`; `PlatformTaskType=ManualTask` (har:49251).
- "完成摘要" = property **`CompletionSummary`**, `logical_type: RICH_TEXT`, `readOnly: false` (har:29436). HTML rich-text → can hold text and embedded images.
- **Auth for direct EMS REST = `SMAX_AUTH_TOKEN` cookie only; no XSRF.** Proven by the prior probe: `POST /rest/820189321/ems/bulk` with only the cookie returned `200` (no `x-xsrf-token`). The `x-xsrf-token` seen in the HAR (har:7735, 49163) is the browser app's CSRF protection for the `/rest/.../batch` endpoint — not needed for direct EMS calls.
- **Read contract**: `GET /rest/{tenant}/ems/Task/{id}?fields=...` →
  ```json
  {"entities":[{"entity_type":"Task","properties":{"LastUpdateTime":1785399519480,"Id":"12167079","PlatformTaskType":"ManualTask"},"related_properties":{}}],"meta":{"completion_status":"OK",...}}
  ```
  (har:49251). `LastUpdateTime` is a **millisecond epoch** and is the optimistic-lock token the UPDATE must echo back. The `layout=PlatformTaskType` only fetched 3 fields — that's why `CompletionSummary`/`Status` weren't visible; we request fields explicitly via `?fields=`.
- **Write contract**: `POST /rest/{tenant}/ems/bulk`, body `{"entities":[{"entity_type":"Task","properties":{...}}],"operation":"UPDATE"}`, UTF-8. Verify `meta.completion_status=="OK"` and per-entity `completion_status` ∈ {OK, SUCCESS, COMPLETED}. This is the colleague's Incident pattern, adapted (`Solution→CompletionSummary`, `Incident→Task`).
- **Token**: `POST /auth/authentication-endpoint/authenticate/token?TENANTID={tenant}`, body `{login, password}` → JWT as response body (`smax.md`). Validated by the 3-dot check.

## Approach

**A — Pure-REST Python skill.** A Claude Code skill embedding a Python script that logs in, reads the task, then `ems/bulk` UPDATEs `CompletionSummary` + close fields, and verifies. Reuses the colleague's proven `ems/bulk` pattern and the probe's success; no browser. (Rejected: B browser automation — heavy/brittle for a field write. Evolution path C: add image later via FRS REST or browser.)

## Skill structure

```
ces/.claude/skills/smax-complete-task/
  SKILL.md                       # when-to-use + flow + caveats
  scripts/complete_task.py       # standalone runnable
```

`SKILL.md` frontmatter `description` lists triggers ("填 SMAX 完成摘要", "完成/关闭 SMAX 任务", "complete task <id>", etc.). Body documents the flow and points to the script.

## `complete_task.py` flow

1. **Login**: `get_token(login="inc.integration", password=getpass())` → JWT.
2. **Read task**: `get_task(task_id, fields="Id,LastUpdateTime,Status,PhaseId,CompletionCode,CompletionSummary")` → capture `LastUpdateTime` (ms epoch) + current state. **Print current `Status`/`PhaseId`** (for close-value discovery).
3. **Build HTML**: if `summary` doesn't start with `<`, wrap `<p>{summary}</p>` (colleague's rule).
4. **Update**: `POST /rest/820189321/ems/bulk` with
   ```json
   {"entities":[{"entity_type":"Task","properties":{
      "Id":"<id>","LastUpdateTime":<ms>,
      "CompletionSummary":"<p>…</p>",
      "CompletionCode":"<code>","Status":"<closed>"}}],
    "operation":"UPDATE"}
   ```
   Body: `json.dumps(payload, ensure_ascii=False).encode("utf-8")` (Chinese safe).
5. **Verify**: assert `meta.completion_status == "OK"` and entity `completion_status` ∈ success set; else raise with server text.
6. **Re-GET** the task, print new `Status`/`PhaseId` so the user can see whether it actually closed.

## Close handling (runtime auto-discover — per user decision)

- Task closed `Status` / `CompletionCode` enum values are **NOT in the HAR** (no save was captured). The colleague's Incident values (`Resolvedbyfix` / `Resolved`) may not apply to Task.
- The script does **not** bake in a closed value as "correct". It exposes `--status` and `--completion-code` params (no default closed value — caller must supply, or run `--show-status` first to read current state). On each run it prints the **current** `Status`/`PhaseId` before updating and the **new** values after, so the correct closed value is confirmed at first run and then supplied every run.
- **Fallback**: if a direct `ems/bulk` `Status` set does **not** move `PhaseId` (task didn't actually close), fall back to a workflow transition via `POST /rest/{tenant}/workflow/Task` (this endpoint appears in the HAR URL list). Exact payload TBD at implementation — **TODO**.

## Auth details

- Login: `POST {BASE}/auth/authentication-endpoint/authenticate/token?TENANTID=820189321`, JSON `{login,password}`, headers `Content-Type: application/json`, `User-Agent: AutomationScript/1.0`. Token = `response.text.strip()`.
- All EMS calls: `Cookie: SMAX_AUTH_TOKEN=<token>`; `User-Agent: AutomationScript/1.0`. GET adds `Accept: application/json`. POST `ems/bulk` adds `Content-Type: application/json; charset=utf-8`.
- `x-client-tenant-version: v28` is optional (browser sends it; direct EMS probe omitted it and still 200'd).

## Verification

- Run against a **test Task**; assert `meta.completion_status == "OK"` and entity `completion_status` in success set.
- Re-GET confirms `CompletionSummary` persisted and `Status`/`PhaseId` changed.
- Error path: non-200 or `completion_status != OK` → raise with full server response text.

## Image (out of scope v1 — future)

`CompletionSummary` is RICH_TEXT and can embed `<img>`. Future flow: upload image to **FRS** → get uuid → embed `<img src="/rest/{tenant}/frs/image-list/{uuid}">` in the `CompletionSummary` HTML → same `ems/bulk` UPDATE. The FRS **upload** endpoint and exact `<img>` reference format are **NOT in the current HAR** (only FRS *reads* appear, and those are tenant branding images, not completion-summary images). Need a confirm-HAR where a user inserts an image into 完成摘要 and saves.

## Open items / TODO

- Confirm Task closed `Status` + `CompletionCode` enum (auto-discover on first run).
- Confirm whether `ems/bulk` `Status` set closes a Task, or whether `workflow/Task` transition is required (fallback path).
- Confirm `?fields=` is honored by `ems/Task/{id}`; if ignored, drop it and read the full entity.
- No git repo in `ces/` → this design doc is written but **not committed** (git init not done unprompted).

## File layout

```
ces/
  .claude/skills/smax-complete-task/SKILL.md
  .claude/skills/smax-complete-task/scripts/complete_task.py
  docs/superpowers/specs/2026-08-12-smax-completion-summary-skill-design.md   # this
  smax.md                              # existing — token acquisition (PS)
  test.md                              # existing — low-risk probe (PS)
  serviceprod.capitaland.com.cn.har    # existing — evidence
```
