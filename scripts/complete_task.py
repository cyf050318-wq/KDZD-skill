"""Fill a Capitaland SMAX Task's CompletionSummary field and close it via EMS REST."""
import argparse
import getpass
import json
import mimetypes
import re
import sys
from html import escape
from pathlib import Path

import requests

BASE = "https://serviceprod.capitaland.com.cn"
TENANT = "820189321"
UA = "AutomationScript/1.0"
SUCCESS_STATUSES = {"OK", "SUCCESS", "COMPLETED"}
GUID_RE = re.compile(r"(?i)\b[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}\b")


def wrap_html(text):
    """Return HTML for the CompletionSummary field.

    Plain text is wrapped in <p>...</p>; strings that already start with '<'
    are passed through. None/empty -> ''.
    """
    if not text:
        return ""
    s = text.strip()
    if s.startswith("<"):
        return s
    return f"<p>{s}</p>"


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


def verify_response(data):
    """Validate an ems/bulk response.

    SMAX may return either the older ``entities`` shape or the observed
    ``entity_result_list`` shape. Returns the first entity/result dict on
    success; raises RuntimeError if meta or entity indicates failure.
    """
    meta = (data or {}).get("meta", {})
    if meta.get("completion_status") != "OK":
        raise RuntimeError(
            f"bulk update failed: meta.completion_status={meta.get('completion_status')!r} "
            f"errors={meta.get('errorDetailsList')}"
        )
    entities = data.get("entities") or data.get("entity_result_list") or []
    if not entities:
        raise RuntimeError("bulk update returned no entities/entity_result_list")
    ent = entities[0]
    if str(ent.get("completion_status", "")).upper() not in SUCCESS_STATUSES:
        raise RuntimeError(f"entity update failed: completion_status={ent.get('completion_status')!r} entity={ent}")
    return ent


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


def _ems_headers(token, json_body=False):
    h = {"Cookie": f"SMAX_AUTH_TOKEN={token}", "User-Agent": UA, "Accept": "application/json"}
    if json_body:
        h["Content-Type"] = "application/json; charset=utf-8"
    return h


def get_task(token, task_id, layout="PlatformTaskType", base=BASE, tenant=TENANT):
    """GET a Task's properties. Returns the properties dict (includes LastUpdateTime)."""
    url = f"{base}/rest/{tenant}/ems/Task/{task_id}"
    params = {"layout": layout} if layout else None
    r = requests.get(
        url,
        params=params,
        headers=_ems_headers(token, json_body=False),
        timeout=30,
    )
    if not r.ok:
        body = r.text
        raise RuntimeError(f"GET Task failed: {r.status_code} url={r.url} body={body[:500]}")
    data = r.json()
    if not data.get("entities"):
        raise RuntimeError(f"task not found or no access: {task_id}")
    return data["entities"][0]["properties"]


def _extract_guid(value):
    """Extract a GUID from nested JSON, text, or headers."""
    if value is None:
        return None
    if isinstance(value, str):
        match = GUID_RE.search(value)
        return match.group(0) if match else None
    if isinstance(value, dict):
        for key in ("fileId", "FileId", "guid", "Guid", "id", "Id", "value"):
            if key in value:
                found = _extract_guid(value[key])
                if found:
                    return found
        for nested in value.values():
            found = _extract_guid(nested)
            if found:
                return found
        return None
    if isinstance(value, list):
        for item in value:
            found = _extract_guid(item)
            if found:
                return found
    return None


def upload_screenshot(token, image_path, base=BASE, tenant=TENANT):
    """Upload one local image file to FRS and return a dict with its guid/name."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"screenshot file not found: {path}")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    r = requests.post(
        f"{base}/rest/{tenant}/frs/file-list/",
        headers={
            "Cookie": f"SMAX_AUTH_TOKEN={token}",
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "fs_filename": path.name,
            "Content-Type": content_type,
        },
        data=path.read_bytes(),
        timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"FRS upload failed: {r.status_code} url={r.url} body={r.text[:500]}")

    guid = None
    for header_name in ("Location", "Content-Location", "X-Resource-Id", "x-resource-id"):
        guid = _extract_guid(r.headers.get(header_name))
        if guid:
            break
    if not guid:
        try:
            guid = _extract_guid(r.json())
        except ValueError:
            guid = None
    if not guid:
        guid = _extract_guid(r.text.strip())
    if not guid:
        raise RuntimeError(f"FRS upload succeeded but no file guid was returned: status={r.status_code} body={r.text[:500]}")
    return {"guid": guid, "filename": path.name, "content_type": content_type}


def build_file_src(file_guid, tenant=TENANT):
    return f"../rest/{tenant}/frs/file-list/{file_guid}"


def build_image_html(file_guid, alt=None, tenant=TENANT):
    alt_attr = f' alt="{escape(alt, quote=True)}"' if alt else ""
    return (
        f'<p><img src="{build_file_src(file_guid, tenant=tenant)}"'
        f'{alt_attr} style="max-width: 100%; height: auto;" /></p>'
    )


def build_completion_summary_html(summary, screenshot_refs=None, tenant=TENANT):
    """Combine text summary and uploaded screenshot references into HTML."""
    html = wrap_html(summary)
    images = ""
    for ref in screenshot_refs or []:
        images += build_image_html(ref["guid"], alt=ref.get("filename"), tenant=tenant)
    return f"{html}{images}" if html else images


def complete_task(token, task_id, summary, status=None, completion_code=None,
                  comments=None, screenshots=None, base=BASE, tenant=TENANT):
    """Read the task, then UPDATE its CompletionSummary (+ optional Status/CompletionCode)."""
    screenshot_refs = []
    for screenshot in screenshots or []:
        ref = upload_screenshot(token, screenshot, base=base, tenant=tenant)
        screenshot_refs.append(ref)
        print(f"UPLOADED: {screenshot} -> {ref['guid']}")

    props = get_task(token, task_id, base=base, tenant=tenant)
    last = int(props["LastUpdateTime"])
    completion_html = build_completion_summary_html(summary, screenshot_refs, tenant=tenant)
    payload = build_update_payload(
        task_id, last, completion_html,
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
    print("DEBUG raw ems/bulk response:", json.dumps(data, ensure_ascii=False, indent=2))
    verify_response(data)
    return data


def _summarize(props):
    keys = ("Id", "LastUpdateTime", "Status", "PhaseId", "CompletionCode",
            "CompletionSummary", "PlatformTaskType")
    return {k: props.get(k) for k in keys}


def main():
    p = argparse.ArgumentParser(description="Fill a SMAX Task CompletionSummary and optionally close it.")
    p.add_argument("--task-id", required=True)
    p.add_argument("--summary", help="Completion summary text (plain or HTML). Can be omitted when only using --screenshot.")
    p.add_argument("--screenshot", action="append", default=[], metavar="PATH",
                   help="Local screenshot image file to upload and embed. Repeatable.")
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

    if not args.summary and not args.screenshot:
        print("--summary or --screenshot is required (or use --show-status).", file=sys.stderr)
        return 2
    if not (args.status or args.completion_code):
        print("WARNING: no --status/--completion-code given — writing CompletionSummary only (not closing).",
              file=sys.stderr)

    data = complete_task(token, args.task_id, args.summary,
                         status=args.status, completion_code=args.completion_code, comments=args.comments,
                         screenshots=args.screenshot)
    print("UPDATE OK:", json.dumps(data.get("meta", {}), ensure_ascii=False))

    after = get_task(token, args.task_id)
    print("AFTER:", json.dumps(_summarize(after), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())


