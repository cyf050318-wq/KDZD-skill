# SMAX Task CompletionSummary Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill (Python) that fills a Capitaland SMAX Task's "完成摘要" (`CompletionSummary`) field and closes the task via the EMS REST API.

**Architecture:** Pure-REST Python. Login → GET task (read `LastUpdateTime` + current state) → `POST /rest/{tenant}/ems/bulk` UPDATE with `CompletionSummary`(HTML) + `Status` + `CompletionCode` → verify `completion_status` → re-GET. Auth = `SMAX_AUTH_TOKEN` cookie only (no XSRF — proven by prior probe). TDD for pure helpers; integration verification against the live tenant for HTTP functions.

**Tech Stack:** Python 3, `requests`, stdlib `unittest`/`argparse`/`getpass`.

**Spec:** `docs/superpowers/specs/2026-08-12-smax-completion-summary-skill-design.md`

**Prerequisites:**
- `pip install requests`
- A designated **TEST Task id you own**. Do **NOT** write against `12167079` (it may be a real production task). Create a throwaway test Task in the SMAX UI first and use its id.
- SMAX login `inc.integration` + its password (prompted at runtime via `getpass`).
- This project is **not** a git repo and you haven't asked for git. "Commit" steps below are **OPTIONAL** checkpoints — run the verification command in each step regardless. If you want version control, run `git init` first and then the commit lines will work.

---

## File Structure

```
ces/.claude/skills/smax-complete-task/
  SKILL.md                         # skill frontmatter + flow + caveats
  scripts/
    complete_task.py               # the runnable script (built incrementally)
    test_complete_task.py          # unit tests for pure helpers (stdlib unittest)
```

- `SKILL.md` — when-to-use triggers, the run flow, caveats (close-value discovery, image not supported, workflow fallback TODO, don't write to prod tasks).
- `complete_task.py` — one file, focused responsibilities grouped: pure helpers (`wrap_html`, `build_update_payload`, `verify_response`), HTTP layer (`get_token`, `get_task`, `complete_task`), CLI (`main`).
- `test_complete_task.py` — unit tests for the three pure helpers only (HTTP layer is verified by live integration commands, not mocks — the whole point is to verify the real REST contract).

Final function signatures (used consistently across all tasks):
- `wrap_html(text) -> str`
- `build_update_payload(task_id, last_update_time, completion_summary_html, status=None, completion_code=None, comments=None) -> dict`
- `verify_response(data) -> dict`
- `get_token(login, password=None, base=BASE, tenant=TENANT) -> str`
- `get_task(token, task_id, fields=DEFAULT_FIELDS, base=BASE, tenant=TENANT) -> dict`
- `complete_task(token, task_id, summary, status=None, completion_code=None, comments=None, base=BASE, tenant=TENANT) -> dict`
- `main() -> int`

Module constants: `BASE`, `TENANT`, `UA`, `DEFAULT_FIELDS`, `SUCCESS_STATUSES`.

---

### Task 1: Scaffold skill directory + SKILL.md skeleton

**Files:**
- Create: `ces/.claude/skills/smax-complete-task/SKILL.md`
- Create: `ces/.claude/skills/smax-complete-task/scripts/complete_task.py` (constants only)
- (`test_complete_task.py` is created fresh in Task 2)

- [ ] **Step 1: Create the directory tree and empty files**

Run (from `C:\Users\42011\Desktop\ces`):
```bash
mkdir -p .claude/skills/smax-complete-task/scripts
```
Then create `scripts/complete_task.py` with just the module constants:
```python
"""Fill a Capitaland SMAX Task's CompletionSummary field and close it via EMS REST."""
import argparse, json, sys, getpass
import requests

BASE = "https://serviceprod.capitaland.com.cn"
TENANT = "820189321"
UA = "AutomationScript/1.0"
DEFAULT_FIELDS = "Id,LastUpdateTime,Status,PhaseId,CompletionCode,CompletionSummary"
SUCCESS_STATUSES = {"OK", "SUCCESS", "COMPLETED"}
```

- [ ] **Step 2: Write SKILL.md with frontmatter + flow**

Create `SKILL.md`:
```markdown
---
name: smax-complete-task
description: Fill the "完成摘要" (CompletionSummary) field of a Capitaland SMAX Task and optionally close the task, via the EMS REST API. Use when the user says things like "填 SMAX 完成摘要", "完成/关闭 SMAX 任务", "complete SMAX task <id>", "set task completion summary", or references the SMAX task page at serviceprod.capitaland.com.cn/home/task/<id>/general.
---

# SMAX Complete Task

Fills a Task's **CompletionSummary** ("完成摘要") field with text and optionally closes the task, via the SMAX EMS REST API. No browser, no XSRF — uses the `SMAX_AUTH_TOKEN` cookie obtained by logging in as `inc.integration`.

## Run

```bash
# 1) Read-only: see current Status/PhaseId/LastUpdateTime (do this first to discover close values)
python .claude/skills/smax-complete-task/scripts/complete_task.py --task-id <TASK_ID> --show-status

# 2) Write completion summary only (no close)
python .claude/skills/smax-complete-task/scripts/complete_task.py --task-id <TASK_ID> --summary "处理完成"

# 3) Write summary AND close the task (supply the closed Status + CompletionCode discovered in step 1)
python .claude/skills/smax-complete-task/scripts/complete_task.py --task-id <TASK_ID> \
  --summary "处理完成" --status <CLOSED_STATUS> --completion-code <CODE>
```

Password for `inc.integration` is prompted via `getpass` (hidden input).

## How it works
1. `POST /auth/.../authenticate/token` → JWT (cookie value).
2. `GET /rest/{tenant}/ems/Task/{id}?fields=...` → read `LastUpdateTime` (ms-epoch, optimistic-lock token) + current `Status`/`PhaseId`.
3. Wrap summary text as HTML `<p>…</p>` if it isn't already HTML.
4. `POST /rest/{tenant}/ems/bulk` with `{"entities":[{"entity_type":"Task","properties":{"Id","LastUpdateTime","CompletionSummary","Status","CompletionCode"}}],"operation":"UPDATE"}`.
5. Verify `meta.completion_status == "OK"` and per-entity `completion_status` ∈ {OK, SUCCESS, COMPLETED}.
6. Re-GET and print new `Status`/`PhaseId`.

## Caveats
- **Close values:** the Task's closed `Status` and `CompletionCode` enum are not pre-known. Run `--show-status` first; after a close, confirm `PhaseId` moved. If `PhaseId` did **not** change, a direct `Status` set didn't close it — fall back to `POST /rest/{tenant}/workflow/Task` (NOT YET IMPLEMENTED — see TODO).
- **Do not run the write against production tasks** (`12167079`). Use a test task you own.
- **Image upload not supported** in v1. `CompletionSummary` is RICH_TEXT and can embed `<img src="/rest/{tenant}/frs/image-list/{uuid}">`, but the FRS upload endpoint is unconfirmed. Add later with a confirm-HAR.
- No XSRF token needed for direct EMS REST (the prior probe returned 200 without it).
```

- [ ] **Step 3: Verify scaffold**

Run:
```bash
test -f .claude/skills/smax-complete-task/SKILL.md && test -f .claude/skills/smax-complete-task/scripts/complete_task.py && echo OK
```
Expected: `OK`

- [ ] **Step 4 (optional): Commit**
```bash
git add .claude/skills/smax-complete-task
git commit -m "scaffold smax-complete-task skill"
```

---

### Task 2: TDD `wrap_html` (pure helper)

**Files:**
- Modify: `ces/.claude/skills/smax-complete-task/scripts/test_complete_task.py`
- Modify: `ces/.claude/skills/smax-complete-task/scripts/complete_task.py`

- [ ] **Step 1: Write the failing test**

Create `test_complete_task.py` with:
```python
import unittest
from complete_task import wrap_html

class TestWrapHtml(unittest.TestCase):
    def test_plain_text_wrapped_in_p(self):
        self.assertEqual(wrap_html("处理完成"), "<p>处理完成</p>")

    def test_html_passthrough(self):
        self.assertEqual(wrap_html("<p>x</p>"), "<p>x</p>")

    def test_html_list_passthrough(self):
        self.assertEqual(wrap_html("<ul><li>a</li></ul>"), "<ul><li>a</li></ul>")

    def test_strips_outer_whitespace_then_wraps(self):
        self.assertEqual(wrap_html("  hello  "), "<p>hello</p>")

    def test_none_returns_empty(self):
        self.assertEqual(wrap_html(None), "")

    def test_empty_returns_empty(self):
        self.assertEqual(wrap_html(""), "")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run (cwd = `scripts/`):
```bash
cd .claude/skills/smax-complete-task/scripts && python -m unittest test_complete_task -v
```
Expected: FAIL — `ImportError: cannot import name 'wrap_html'` (function not defined yet).

- [ ] **Step 3: Implement `wrap_html`**

Append to `complete_task.py`:
```python
def wrap_html(text):
    """Return HTML for the CompletionSummary field. Plain text is wrapped in <p>...</p>;
    strings that already start with '<' are passed through. None/empty -> ''."""
    if not text:
        return ""
    s = text.strip()
    if s.startswith("<"):
        return s
    return f"<p>{s}</p>"
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd .claude/skills/smax-complete-task/scripts && python -m unittest test_complete_task -v
```
Expected: PASS — 6 tests, OK.

- [ ] **Step 5 (optional): Commit**
```bash
git add .claude/skills/smax-complete-task/scripts
git commit -m "add wrap_html helper with tests"
```

---

### Task 3: TDD `build_update_payload` (pure helper)

**Files:**
- Modify: `test_complete_task.py`
- Modify: `complete_task.py`

- [ ] **Step 1: Add the failing test**

Add this import and class to `test_complete_task.py` (keep the existing `TestWrapHtml`):
```python
from complete_task import wrap_html, build_update_payload

class TestBuildUpdatePayload(unittest.TestCase):
    def test_minimal_payload_has_required_fields(self):
        p = build_update_payload("12167079", 1785399519480, "<p>x</p>")
        self.assertEqual(p["operation"], "UPDATE")
        self.assertEqual(p["entities"][0]["entity_type"], "Task")
        props = p["entities"][0]["properties"]
        self.assertEqual(props["Id"], "12167079")
        self.assertEqual(props["LastUpdateTime"], 1785399519480)
        self.assertEqual(props["CompletionSummary"], "<p>x</p>")
        self.assertNotIn("Status", props)
        self.assertNotIn("CompletionCode", props)
        self.assertNotIn("Comments", props)

    def test_last_update_time_coerced_to_int(self):
        p = build_update_payload("1", "1700000000000", "<p>x</p>")
        self.assertEqual(p["entities"][0]["properties"]["LastUpdateTime"], 1700000000000)
        self.assertIsInstance(p["entities"][0]["properties"]["LastUpdateTime"], int)

    def test_id_stripped(self):
        p = build_update_payload("  12167079  ", 1, "<p>x</p>")
        self.assertEqual(p["entities"][0]["properties"]["Id"], "12167079")

    def test_optional_close_fields_when_provided(self):
        p = build_update_payload("1", 1, "<p>x</p>",
                                 status="Closed", completion_code="Resolvedbyfix",
                                 comments="done")
        props = p["entities"][0]["properties"]
        self.assertEqual(props["Status"], "Closed")
        self.assertEqual(props["CompletionCode"], "Resolvedbyfix")
        self.assertEqual(props["Comments"], "done")
```
(Update the existing import line to `from complete_task import wrap_html, build_update_payload`.)

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd .claude/skills/smax-complete-task/scripts && python -m unittest test_complete_task -v
```
Expected: FAIL — `ImportError: cannot import name 'build_update_payload'`.

- [ ] **Step 3: Implement `build_update_payload`**

Append to `complete_task.py`:
```python
def build_update_payload(task_id, last_update_time, completion_summary_html,
                         status=None, completion_code=None, comments=None):
    """Build the ems/bulk UPDATE body for one Task."""
    props = {
        "Id": str(task_id).strip(),
        "LastUpdateTime": int(last_update_time),
        "CompletionSummary": completion_summary_html,
    }
    if status:
        props["Status"] = status
    if completion_code:
        props["CompletionCode"] = completion_code
    if comments:
        props["Comments"] = comments
    return {"entities": [{"entity_type": "Task", "properties": props}], "operation": "UPDATE"}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd .claude/skills/smax-complete-task/scripts && python -m unittest test_complete_task -v
```
Expected: PASS — all tests OK.

- [ ] **Step 5 (optional): Commit**
```bash
git add .claude/skills/smax-complete-task/scripts
git commit -m "add build_update_payload helper with tests"
```

---

### Task 4: TDD `verify_response` (pure helper)

**Files:**
- Modify: `test_complete_task.py`
- Modify: `complete_task.py`

- [ ] **Step 1: Add the failing test**

Update the import line in `test_complete_task.py`:
```python
from complete_task import wrap_html, build_update_payload, verify_response
```
Add this class:
```python
class TestVerifyResponse(unittest.TestCase):
    def test_ok_returns_entity(self):
        data = {"meta": {"completion_status": "OK"},
                "entities": [{"completion_status": "OK", "properties": {"Id": "1"}}]}
        ent = verify_response(data)
        self.assertEqual(ent["properties"]["Id"], "1")

    def test_success_and_completed_accepted(self):
        for cs in ("SUCCESS", "COMPLETED"):
            data = {"meta": {"completion_status": "OK"},
                    "entities": [{"completion_status": cs}]}
            verify_response(data)  # no raise

    def test_meta_not_ok_raises(self):
        data = {"meta": {"completion_status": "FAIL", "errorDetailsList": [{"msg": "boom"}]},
                "entities": []}
        with self.assertRaises(RuntimeError):
            verify_response(data)

    def test_entity_failure_raises(self):
        data = {"meta": {"completion_status": "OK"},
                "entities": [{"completion_status": "FAIL"}]}
        with self.assertRaises(RuntimeError):
            verify_response(data)

    def test_missing_entities_raises(self):
        data = {"meta": {"completion_status": "OK"}, "entities": []}
        with self.assertRaises(RuntimeError):
            verify_response(data)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd .claude/skills/smax-complete-task/scripts && python -m unittest test_complete_task -v
```
Expected: FAIL — `ImportError: cannot import name 'verify_response'`.

- [ ] **Step 3: Implement `verify_response`**

Append to `complete_task.py`:
```python
def verify_response(data):
    """Validate an ems/bulk response. Returns the first entity dict on success;
    raises RuntimeError if meta or entity indicates failure."""
    meta = (data or {}).get("meta", {})
    if meta.get("completion_status") != "OK":
        raise RuntimeError(
            f"bulk update failed: meta.completion_status={meta.get('completion_status')!r} "
            f"errors={meta.get('errorDetailsList')}"
        )
    entities = data.get("entities", [])
    if not entities:
        raise RuntimeError("bulk update returned no entities")
    ent = entities[0]
    if str(ent.get("completion_status", "")).upper() not in SUCCESS_STATUSES:
        raise RuntimeError(f"entity update failed: completion_status={ent.get('completion_status')!r} entity={ent}")
    return ent
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd .claude/skills/smax-complete-task/scripts && python -m unittest test_complete_task -v
```
Expected: PASS — all tests OK.

- [ ] **Step 5 (optional): Commit**
```bash
git add .claude/skills/smax-complete-task/scripts
git commit -m "add verify_response helper with tests"
```

---

### Task 5: Implement `get_token` (HTTP login) + integration verify

**Files:**
- Modify: `complete_task.py`

No unit test — this calls the live auth endpoint. A mock would test the mock, not the real contract (which is exactly what we debugged in the 401 saga). Verify by running it against the real tenant.

- [ ] **Step 1: Implement `get_token`**

Append to `complete_task.py`:
```python
def get_token(login, password=None, base=BASE, tenant=TENANT):
    """Log in to SMAX and return the SMAX_AUTH_TOKEN JWT (cookie value)."""
    if password is None:
        password = getpass.getpass(f"SMAX password for {login}: ")
    r = requests.post(
        f"{base}/auth/authentication-endpoint/authenticate/token?TENANTID={tenant}",
        json={"login": login, "password": password},
        headers={"Content-Type": "application/json", "User-Agent": UA},
        timeout=30,
    )
    r.raise_for_status()
    token = r.text.strip()
    if len(token.split(".")) != 3:
        raise RuntimeError(f"response doesn't look like a JWT: {token[:60]!r}")
    return token
```

- [ ] **Step 2: Verify against the live tenant (read-only — login only)**

Run (you'll be prompted for the `inc.integration` password):
```bash
cd .claude/skills/smax-complete-task/scripts && python -c "from complete_task import get_token; t=get_token('inc.integration'); print('parts=', len(t.split('.')), 'len=', len(t))"
```
Expected: prints `parts= 3 len= <some number>` and no exception. If you see 401, recheck the password; if the response isn't a JWT, the auth endpoint shape changed.

- [ ] **Step 3 (optional): Commit**
```bash
git add .claude/skills/smax-complete-task/scripts/complete_task.py
git commit -m "add get_token login"
```

---

### Task 6: Implement `get_task` (HTTP GET) + integration verify (read-only)

**Files:**
- Modify: `complete_task.py`

- [ ] **Step 1: Implement `_ems_headers` and `get_task`**

Append to `complete_task.py`:
```python
def _ems_headers(token, json_body=False):
    h = {"Cookie": f"SMAX_AUTH_TOKEN={token}", "User-Agent": UA, "Accept": "application/json"}
    if json_body:
        h["Content-Type"] = "application/json; charset=utf-8"
    return h

def get_task(token, task_id, fields=DEFAULT_FIELDS, base=BASE, tenant=TENANT):
    """GET a Task's properties. Returns the properties dict (includes LastUpdateTime)."""
    r = requests.get(
        f"{base}/rest/{tenant}/ems/Task/{task_id}",
        params={"fields": fields},
        headers=_ems_headers(token, json_body=False),
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("entities"):
        raise RuntimeError(f"task not found or no access: {task_id}")
    return data["entities"][0]["properties"]
```

- [ ] **Step 2: Verify against the live tenant (read-only — safe)**

Run:
```bash
cd .claude/skills/smax-complete-task/scripts && python -c "from complete_task import get_token, get_task; t=get_token('inc.integration'); p=get_task(t,'12167079'); print({k: p.get(k) for k in ('Id','Status','PhaseId','CompletionCode','LastUpdateTime','PlatformTaskType')})"
```
Expected: a dict like `{'Id': '12167079', 'Status': <current>, 'PhaseId': <current>, 'CompletionCode': <current or None>, 'LastUpdateTime': <ms-epoch>, 'PlatformTaskType': 'ManualTask'}`. If `Status`/`PhaseId` come back as `None`, the `?fields=` param was ignored — harmless (we only read what exists); proceed.

- [ ] **Step 3 (optional): Commit**
```bash
git add .claude/skills/smax-complete-task/scripts/complete_task.py
git commit -m "add get_task read"
```

---

### Task 7: Implement `complete_task` (the mutation) + integration verify against a TEST task

**Files:**
- Modify: `complete_task.py`

This is the mutating call. Verify against a **TEST task you own**, never `12167079`.

- [ ] **Step 1: Implement `complete_task`**

Append to `complete_task.py`:
```python
def complete_task(token, task_id, summary, status=None, completion_code=None,
                  comments=None, base=BASE, tenant=TENANT):
    """Read the task, then UPDATE its CompletionSummary (+ optional Status/CompletionCode).
    Returns the raw ems/bulk response dict after verification."""
    props = get_task(token, task_id)
    last = int(props["LastUpdateTime"])
    payload = build_update_payload(
        task_id, last, wrap_html(summary),
        status=status, completion_code=completion_code, comments=comments,
    )
    r = requests.post(
        f"{base}/rest/{tenant}/ems/bulk",
        headers=_ems_headers(token, json_body=True),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    verify_response(data)
    return data
```

- [ ] **Step 2: Verify against a TEST task (write summary only — no close yet)**

Replace `<TEST_TASK_ID>` with your test task's id. Run:
```bash
cd .claude/skills/smax-complete-task/scripts && python -c "from complete_task import get_token, complete_task; t=get_token('inc.integration'); d=complete_task(t,'<TEST_TASK_ID>','测试完成摘要-自动写入'); print('meta=', d.get('meta',{}).get('completion_status')); print('entity=', d.get('entities',[{}])[0].get('completion_status'))"
```
Expected: `meta= OK` and `entity= OK`. Then confirm visually in the SMAX UI (open the test task's 完成摘要) that the text landed. If `meta` is not `OK`, read `errorDetailsList` from the response — a wrong field name or stale `LastUpdateTime` shows up there.

- [ ] **Step 3 (optional): Commit**
```bash
git add .claude/skills/smax-complete-task/scripts/complete_task.py
git commit -m "add complete_task ems/bulk UPDATE"
```

---

### Task 8: Wire CLI (`main`) + end-to-end via the script

**Files:**
- Modify: `complete_task.py`

- [ ] **Step 1: Implement `main`**

Append to `complete_task.py`:
```python
def _summarize(props):
    keys = ("Id", "LastUpdateTime", "Status", "PhaseId", "CompletionCode",
            "CompletionSummary", "PlatformTaskType")
    return {k: props.get(k) for k in keys}

def main():
    p = argparse.ArgumentParser(description="Fill a SMAX Task CompletionSummary and optionally close it.")
    p.add_argument("--task-id", required=True)
    p.add_argument("--summary", help="Completion summary text (plain or HTML). Omit with --show-status.")
    p.add_argument("--status", help="Closed Status value (discover via --show-status first).")
    p.add_argument("--completion-code", help="CompletionCode value.")
    p.add_argument("--comments", help="Optional Comments text.")
    p.add_argument("--login", default="inc.integration")
    p.add_argument("--password", help="Omit to prompt via getpass.")
    p.add_argument("--show-status", action="store_true",
                   help="Read-only: print current Status/PhaseId/LastUpdateTime and exit.")
    args = p.parse_args()

    token = get_token(args.login, args.password)

    if args.show_status:
        props = get_task(token, args.task_id)
        print(json.dumps(_summarize(props), ensure_ascii=False, indent=2))
        return 0

    if not args.summary:
        print("--summary is required (or use --show-status).", file=sys.stderr)
        return 2
    if not (args.status or args.completion_code):
        print("WARNING: no --status/--completion-code given — writing CompletionSummary only (not closing).",
              file=sys.stderr)

    data = complete_task(token, args.task_id, args.summary,
                         status=args.status, completion_code=args.completion_code, comments=args.comments)
    print("UPDATE OK:", json.dumps(data.get("meta", {}), ensure_ascii=False))

    after = get_task(token, args.task_id)
    print("AFTER:", json.dumps(_summarize(after), ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify read-only CLI (safe)**

Run:
```bash
cd .claude/skills/smax-complete-task/scripts && python complete_task.py --task-id <TEST_TASK_ID> --show-status
```
Expected: a JSON block with `Id`, `Status`, `PhaseId`, `LastUpdateTime`, etc. No exception.

- [ ] **Step 3: Verify end-to-end write (summary only) on a TEST task**

Run:
```bash
cd .claude/skills/smax-complete-task/scripts && python complete_task.py --task-id <TEST_TASK_ID> --summary "测试-CLI写入"
```
Expected: `UPDATE OK: {"completion_status": "OK", ...}` then an `AFTER:` block where `CompletionSummary` now contains `<p>测试-CLI写入</p>`. Confirm the `WARNING` line about not closing appears (expected — we didn't pass `--status`).

- [ ] **Step 4 (optional): Commit**
```bash
git add .claude/skills/smax-complete-task/scripts/complete_task.py
git commit -m "add CLI main"
```

---

### Task 9: Discover close values + finalize SKILL.md

**Files:**
- Modify: `SKILL.md` (fill in the confirmed close values + the discovery result)

This task executes the close-value auto-discovery loop and records the result in `SKILL.md`.

- [ ] **Step 1: Read the test task's current state**

Run:
```bash
cd .claude/skills/smax-complete-task/scripts && python complete_task.py --task-id <TEST_TASK_ID> --show-status
```
Record the `Status` and `PhaseId` values printed (these are the **open** values). The closed `Status` is typically the terminal value in that Status enum (commonly `Closed`, but confirm from the UI dropdown on the test task's 完成/close action).

- [ ] **Step 2: Attempt a close with a candidate Status + CompletionCode**

Run (substitute the candidate closed `Status` and a `CompletionCode`; if you don't know the code, omit `--completion-code` for the first try):
```bash
cd .claude/skills/smax-complete-task/scripts && python complete_task.py --task-id <TEST_TASK_ID> \
  --summary "测试-关闭" --status <CANDIDATE_CLOSED_STATUS> --completion-code <CANDIDATE_CODE>
```
Expected: `UPDATE OK: {"completion_status": "OK", ...}` and an `AFTER:` block. **Check whether `PhaseId` changed** from the value recorded in Step 1.

- [ ] **Step 3: Interpret the result and record it in SKILL.md**

- If `PhaseId` **changed** (and `Status` is now the closed value): the direct `ems/bulk` `Status` set closes the Task. In `SKILL.md`, under **Caveats**, replace the close-values bullet with:
  ```
  - **Close values (confirmed on <DATE>):** Status=`<CONFIRMED>`, CompletionCode=`<CONFIRMED or None>`. Direct ems/bulk UPDATE closes the task (PhaseId moves to <CLOSED_PHASE>).
  ```
- If `PhaseId` did **not** change: direct `Status` set doesn't close the Task. Leave the workflow-fallback TODO in place and update the bullet:
  ```
  - **Close:** direct ems/bulk Status set does NOT move PhaseId (confirmed on <DATE>). Closing requires a workflow transition via `POST /rest/{tenant}/workflow/Task` — NOT YET IMPLEMENTED. Until then, this skill writes CompletionSummary + sets Status but does not fully close the Task.
  ```

- [ ] **Step 4: Re-run the unit tests to confirm nothing regressed**

Run:
```bash
cd .claude/skills/smax-complete-task/scripts && python -m unittest test_complete_task -v
```
Expected: PASS — all tests OK.

- [ ] **Step 5 (optional): Commit**
```bash
git add .claude/skills/smax-complete-task
git commit -m "confirm close values; finalize SKILL.md"
```

---

## Done criteria

- `python -m unittest test_complete_task -v` passes (pure helpers covered).
- `complete_task.py --task-id <TEST> --show-status` works (read-only).
- `complete_task.py --task-id <TEST> --summary "..."` writes `CompletionSummary` (verified in UI + via `AFTER:` block).
- Close-value discovery executed on a test task; result recorded in `SKILL.md`.
- No write was run against `12167079` or any production task.
