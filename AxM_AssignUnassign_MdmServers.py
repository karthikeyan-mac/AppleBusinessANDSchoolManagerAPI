#!/usr/bin/env python3
"""
AxM_AssignUnassign_MdmServers.py

Assign or unassign a list of devices (from serialnumbers.txt)
to/from a Device Management Service (MDM server) via:

  POST https://api-<scope>.apple.com/v1/orgDeviceActivities

Then waits 30 seconds and calls:

  GET  https://api-<scope>.apple.com/v1/orgDeviceActivities/{id}

If a downloadUrl is present and the activity is COMPLETED, it
downloads the CSV log file.

Configuration (edit these at the top of the file):

  MODE           -> "ASSIGN" or "UNASSIGN"
  MDM_SERVER_ID  -> your MDM Server ID string
"""

import os
import time
import json
from typing import Dict, Any, List, Tuple

import requests
from AxM_OAuth import get_access_token_and_scope


# -------------- CONFIG --------------

# "ASSIGN" or "UNASSIGN"
MODE = "ASSIGN"

# MDM Server ID to assign/unassign devices to/from
MDM_SERVER_ID = "<MDMSERVERID>"

# File with one device ID (serial) per line
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERIALS_FILE = os.path.join(BASE_DIR, "serialnumbers.txt")

# Token cache used by AxM_OAuth
TOKEN_CACHE_FILE = os.path.join(BASE_DIR, "AxM_Token.cache")

# How long to wait before checking activity status/downloadUrl
WAIT_SECONDS_BEFORE_STATUS = 30


# -------------- TOKEN / URL HELPERS --------------

def get_token_and_activities_url(force_new: bool = False) -> Tuple[str, str]:
    """
    Get an access token and the orgDeviceActivities base URL based on scope.

    If force_new=True, delete AxM_Token.cache so AxM_OAuth generates a fresh token.
    """
    if force_new and os.path.exists(TOKEN_CACHE_FILE):
        try:
            os.remove(TOKEN_CACHE_FILE)
            print("INFO: Deleted cached token file to force regeneration.")
        except OSError:
            print("WARN: Could not delete token cache; AxM_OAuth will handle it.")

    access_token, scope = get_access_token_and_scope()
    s = scope.lower()

    if "school" in s:
        base_url = "https://api-school.apple.com/v1/orgDeviceActivities"
    elif "business" in s:
        base_url = "https://api-business.apple.com/v1/orgDeviceActivities"
    else:
        raise RuntimeError(f"Invalid scope '{scope}'. Expected school.api or business.api")

    return access_token, base_url


def handle_429(response: requests.Response) -> None:
    """Handle Apple 429 with Retry-After if present."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            wait_seconds = int(retry_after)
            print(f"INFO: 429 Too Many Requests — waiting Retry-After: {wait_seconds} seconds...")
            time.sleep(wait_seconds)
            return
        except ValueError:
            pass

    print("INFO: 429 Too Many Requests — waiting 60 seconds...")
    time.sleep(60)


# -------------- SUPPORT FUNCTIONS --------------

def load_device_ids(path: str) -> List[str]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found")

    with open(path, "r") as f:
        ids = [line.strip() for line in f if line.strip()]

    if not ids:
        raise ValueError(f"{path} is empty")

    return ids


# -------------- API CALLS --------------

def post_org_device_activity(
    session: requests.Session,
    token_state: Dict[str, Any],
    activity_type: str,
    mdm_server_id: str,
    device_ids: List[str],
) -> Dict[str, Any]:
    """
    POST /v1/orgDeviceActivities with basic retry for 429 (once) and 401 (one refresh).
    """
    access_token = token_state["access_token"]
    base_url = token_state["base_url"]

    payload = {
        "data": {
            "type": "orgDeviceActivities",
            "attributes": {
                "activityType": activity_type,
            },
            "relationships": {
                "mdmServer": {
                    "data": {
                        "type": "mdmServers",
                        "id": mdm_server_id,
                    }
                },
                "devices": {
                    "data": [
                        {"type": "orgDevices", "id": d_id}
                        for d_id in device_ids
                    ]
                },
            },
        }
    }

    url = base_url
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    tried_429 = False
    tried_refresh = False

    while True:
        print(f"INFO: Sending orgDeviceActivities request for {len(device_ids)} device(s)...")
        response = session.post(url, headers=headers, data=json.dumps(payload))

        # 429
        if response.status_code == 429 and not tried_429:
            tried_429 = True
            handle_429(response)
            continue

        # 401
        if response.status_code == 401 and not tried_refresh:
            tried_refresh = True
            print("INFO: 401 Unauthorized — regenerating token once...")
            new_token, new_base = get_token_and_activities_url(force_new=True)
            token_state["access_token"] = new_token
            token_state["base_url"] = new_base
            headers["Authorization"] = f"Bearer {new_token}"
            continue

        # Other errors
        if response.status_code == 400:
            raise RuntimeError(f"ERROR: 400 Bad Request. Response: {response.text}")
        if response.status_code == 403:
            raise RuntimeError(f"ERROR: 403 Forbidden. Response: {response.text}")
        if response.status_code == 409:
            raise RuntimeError(f"ERROR: 409 Conflict. Response: {response.text}")
        if response.status_code == 422:
            raise RuntimeError(f"ERROR: 422 Unprocessable Entity. Response: {response.text}")
        if response.status_code != 201:
            raise RuntimeError(f"ERROR: HTTP {response.status_code}. Response: {response.text}")

        # Success
        try:
            return response.json()
        except json.JSONDecodeError as e:
            raise RuntimeError(f"ERROR: Failed to parse JSON from response: {response.text}") from e


def get_activity_status(
    session: requests.Session,
    token_state: Dict[str, Any],
    activity_id: str,
) -> Dict[str, Any]:
    """
    GET /v1/orgDeviceActivities/{id} with basic retry for 429 (once) and 401 (one refresh).
    """
    access_token = token_state["access_token"]
    base_url = token_state["base_url"]

    url = f"{base_url}/{activity_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    tried_429 = False
    tried_refresh = False

    while True:
        print(f"INFO: Fetching activity status for ID {activity_id} ...")
        response = session.get(url, headers=headers)

        # 429
        if response.status_code == 429 and not tried_429:
            tried_429 = True
            handle_429(response)
            continue

        # 401
        if response.status_code == 401 and not tried_refresh:
            tried_refresh = True
            print("INFO: 401 Unauthorized while checking activity — regenerating token once...")
            new_token, new_base = get_token_and_activities_url(force_new=True)
            token_state["access_token"] = new_token
            token_state["base_url"] = new_base
            headers["Authorization"] = f"Bearer {new_token}"
            continue

        if response.status_code == 404:
            raise RuntimeError(f"ERROR: 404 Not Found. Activity ID '{activity_id}' invalid or not visible.")
        if response.status_code == 403:
            raise RuntimeError(f"ERROR: 403 Forbidden while checking activity. Response: {response.text}")
        if response.status_code == 400:
            raise RuntimeError(f"ERROR: 400 Bad Request while checking activity. Response: {response.text}")
        if not response.ok:
            raise RuntimeError(f"ERROR: HTTP {response.status_code} while checking activity. Response: {response.text}")

        try:
            return response.json()
        except json.JSONDecodeError as e:
            raise RuntimeError(f"ERROR: Failed to parse JSON from activity status response: {response.text}") from e


def download_activity_csv(download_url: str, activity_id: str) -> str:
    """
    Download the CSV file from downloadUrl (signed URL) and save locally.
    """
    print("INFO: Downloading CSV from activity downloadUrl...")

    resp = requests.get(download_url, stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"ERROR: Failed to download CSV. HTTP {resp.status_code}: {resp.text}")

    # Try to infer filename from Content-Disposition
    filename = None
    content_disp = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition")
    if content_disp and "filename=" in content_disp:
        parts = content_disp.split("filename=")
        if len(parts) > 1:
            raw_name = parts[1].strip().strip(";").strip()
            if raw_name.startswith('"') and raw_name.endswith('"'):
                raw_name = raw_name[1:-1]
            filename = raw_name

    if not filename:
        filename = f"OrgDeviceActivity_{activity_id}.csv"

    local_path = os.path.join(BASE_DIR, filename)

    with open(local_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    print(f"INFO: CSV downloaded to {local_path}")
    return local_path


# -------------- MAIN --------------

def main():
    mode = MODE.upper().strip()
    if mode not in ("ASSIGN", "UNASSIGN"):
        print("ERROR: MODE must be 'ASSIGN' or 'UNASSIGN'.")
        return

    activity_type = "ASSIGN_DEVICES" if mode == "ASSIGN" else "UNASSIGN_DEVICES"

    if not MDM_SERVER_ID:
        print("ERROR: MDM_SERVER_ID is not configured.")
        return

    print(f"INFO: Mode: {mode} ({activity_type})")
    print(f"INFO: MDM Server ID: {MDM_SERVER_ID}")

    # Load device IDs
    try:
        device_ids = load_device_ids(SERIALS_FILE)
    except Exception as e:
        print("ERROR:", e)
        return

    print(f"INFO: Loaded {len(device_ids)} device ID(s) from {SERIALS_FILE}")

    # Get token + base URL
    try:
        access_token, base_url = get_token_and_activities_url()
    except Exception as e:
        print("ERROR obtaining token/base URL:", e)
        return

    token_state: Dict[str, Any] = {
        "access_token": access_token,
        "base_url": base_url,
    }

    session = requests.Session()

    # POST orgDeviceActivities
    try:
        resp = post_org_device_activity(
            session=session,
            token_state=token_state,
            activity_type=activity_type,
            mdm_server_id=MDM_SERVER_ID,
            device_ids=device_ids,
        )
    except Exception as e:
        print("ERROR while creating orgDeviceActivity:")
        print(e)
        return

    data = resp.get("data", {}) if isinstance(resp, dict) else {}
    attrs = data.get("attributes", {}) if isinstance(data, dict) else {}

    activity_id = data.get("id", "")
    status = attrs.get("status", "")
    sub_status = attrs.get("subStatus", "")
    created_dt = attrs.get("createdDateTime", "")

    print("\nINFO: Org Device Activity created.")
    print(f"  Activity ID:   {activity_id}")
    print(f"  Activity Type: {activity_type}")
    print(f"  MDM Server ID: {MDM_SERVER_ID}")
    print(f"  Devices Count: {len(device_ids)}")
    print(f"  Status:        {status}")
    print(f"  Sub-Status:    {sub_status}")
    print(f"  Created At:    {created_dt}")

    if not activity_id:
        print("WARN: No activity ID returned; cannot check status or download CSV.")
        return

    # Wait before checking status
    print(f"\nINFO: Waiting {WAIT_SECONDS_BEFORE_STATUS} seconds before checking activity status...")
    time.sleep(WAIT_SECONDS_BEFORE_STATUS)

    # GET activity status
    try:
        status_resp = get_activity_status(session, token_state, activity_id)
    except Exception as e:
        print("ERROR while fetching activity status:")
        print(e)
        return

    s_data = status_resp.get("data", {}) or {}
    s_attr = s_data.get("attributes", {}) or {}

    cur_status = s_attr.get("status", "")
    cur_sub_status = s_attr.get("subStatus", "")
    completed_dt = s_attr.get("completedDateTime", "")
    download_url = s_attr.get("downloadUrl")

    print("\nINFO: Activity Status Check:")
    print(f"  Activity ID:  {activity_id}")
    print(f"  Status:       {cur_status}")
    print(f"  Sub-Status:   {cur_sub_status}")
    print(f"  Completed At: {completed_dt}")
    print(f"  Has CSV URL:  {'YES' if download_url else 'NO'}")

    # Download CSV if available and completed
    if cur_status == "COMPLETED" and download_url:
        try:
            download_activity_csv(download_url, activity_id)
        except Exception as e:
            print("ERROR while downloading CSV:")
            print(e)
    else:
        print("INFO: CSV not downloaded. Activity not COMPLETED or downloadUrl missing.")


if __name__ == "__main__":
    main()