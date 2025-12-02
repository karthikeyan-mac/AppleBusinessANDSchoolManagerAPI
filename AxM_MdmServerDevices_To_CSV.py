#!/usr/bin/env python3
"""
AxM_MdmServerDevices_To_CSV.py

Prompts for an MDM Server ID and fetches all device serial numbers (orgDevices)
assigned to that Device Management Service via:

    GET https://api-<scope>.apple.com/v1/mdmServers/{id}/relationships/devices

Then exports the results to:
    mdmServerDevices_<MDM_SERVER_ID>.csv

Features:
- Uses AxM_OAuth.get_access_token_and_scope() for token + scope
- Scope determines base URL:
    - school.api   -> https://api-school.apple.com/v1/mdmServers
    - business.api -> https://api-business.apple.com/v1/mdmServers
- Handles pagination via meta.paging.nextCursor
- 429 Too Many Requests -> uses Retry-After header if present, else waits 60 seconds
- 401 Unauthorized -> regenerates token ONCE for the whole run; if still 401, raises clear error
- 400 / 403 / 404 / other non-OK codes -> clear exceptions
- Uses requests.Session for connection reuse
- Never prints the access token
"""

import os
import time
import json
from typing import List, Dict, Any, Tuple

import requests
from AxM_OAuth import get_access_token_and_scope


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(BASE_DIR, "AxM_Token.cache")
PAGE_LIMIT = 1000  # Apple max


# -------------------- TOKEN / URL HELPERS -------------------- #

def get_token_and_mdm_base_url(force_new: bool = False) -> tuple[str, str]:
    """
    Get an access token and the base mdmServers URL based on scope.

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
        base_url = "https://api-school.apple.com/v1/mdmServers"
    elif "business" in s:
        base_url = "https://api-business.apple.com/v1/mdmServers"
    else:
        raise RuntimeError(f"Invalid scope '{scope}'. Expected school.api or business.api")

    return access_token, base_url


# -------------------- 429 HANDLER -------------------- #

def handle_429(response: requests.Response) -> None:
    """Handle Apple 429 with Retry-After if present."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            wait_seconds = int(retry_after)
            print(f"INFO: 429 received — waiting Retry-After: {wait_seconds} seconds...")
            time.sleep(wait_seconds)
            return
        except ValueError:
            pass  # fall through to default

    print("INFO: 429 received — Retry-After not provided, waiting 60 seconds...")
    time.sleep(60)


# -------------------- FETCH DEVICES FOR ONE MDM SERVER -------------------- #

def fetch_all_devices_for_mdm_server(mdm_id: str) -> List[Dict[str, Any]]:
    """
    Fetch all orgDevices IDs assigned to a specific MDM server, handling
    pagination, 429, and one 401 refresh.

    Returns:
        List of linkage objects (each looks like: {"type": "orgDevices", "id": "SERIAL"}).
    """
    access_token, base_url = get_token_and_mdm_base_url()
    session = requests.Session()

    devices: List[Dict[str, Any]] = []
    cursor: str | None = None
    token_refreshed_once = False

    while True:
        params = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor

        url = f"{base_url}/{mdm_id}/relationships/devices"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        print(f"INFO: Fetching devices for MDM server {mdm_id} (cursor={cursor}) ...")
        response = session.get(url, headers=headers, params=params)

        # 429 Too Many Requests
        if response.status_code == 429:
            handle_429(response)
            continue

        # 401 Unauthorized
        if response.status_code == 401:
            if not token_refreshed_once:
                print("INFO: 401 Unauthorized — regenerating token once for this run...")
                access_token, base_url = get_token_and_mdm_base_url(force_new=True)
                token_refreshed_once = True
                continue
            else:
                raise RuntimeError(
                    "ERROR: 401 Unauthorized even after regenerating token once.\n"
                    "Please check values in AxM_Variables.env "
                    "(APPLE_CLIENT_ID / APPLE_KEY_ID / APPLE_SCOPE / PRIVATE KEY)."
                )

        # 404 Not Found
        if response.status_code == 404:
            raise RuntimeError(
                f"ERROR: 404 Not Found. MDM Server ID '{mdm_id}' does not exist "
                "or is not accessible with this token/scope."
            )

        # 403 Forbidden
        if response.status_code == 403:
            raise RuntimeError("ERROR: 403 Forbidden. Check API permissions / scope.")

        # 400 Bad Request
        if response.status_code == 400:
            raise RuntimeError(f"ERROR: 400 Bad Request. Response: {response.text}")

        # Other non-OK
        if not response.ok:
            raise RuntimeError(f"ERROR: HTTP {response.status_code}. Response: {response.text}")

        # Success
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise RuntimeError(f"ERROR: Failed to parse JSON from response: {response.text}") from e

        page_devices = data.get("data", []) or []
        print(f"INFO: Retrieved {len(page_devices)} device link(s) in this page.")
        devices.extend(page_devices)

        # Pagination
        meta = data.get("meta", {}) or {}
        paging = meta.get("paging", {}) or {}
        cursor = paging.get("nextCursor")
        if not cursor:
            print("INFO: No further pages. Finished fetching devices for this MDM server.")
            break

    print(f"INFO: Total devices linked to MDM server {mdm_id}: {len(devices)}")
    return devices


# -------------------- CSV BUILD -------------------- #

def flatten_devices(mdm_id: str, devices: List[Dict[str, Any]]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Flatten linkage objects into CSV rows.

    Each input object is expected to look like:
        {
          "type": "orgDevices",
          "id": "SERIAL_OR_DEVICE_ID"
        }

    We output:
        mdmServerId, type, deviceId
    """
    if not devices:
        return ["mdmServerId", "type", "deviceId"], []

    fieldnames = ["mdmServerId", "type", "deviceId"]
    rows: List[Dict[str, Any]] = []

    for d in devices:
        row = {
            "mdmServerId": mdm_id,
            "type": d.get("type", ""),
            "deviceId": d.get("id", ""),
        }
        rows.append(row)

    return fieldnames, rows


def write_csv(fieldnames: List[str], rows: List[Dict[str, Any]], filename: str) -> None:
    print(f"INFO: Writing {len(rows)} records to {filename} ...")
    import csv
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print("INFO: CSV writing completed.")


# -------------------- MAIN -------------------- #

def main():
    mdm_id = input("Enter MDM Server ID: ").strip()
    if not mdm_id:
        print("ERROR: MDM Server ID cannot be empty.")
        return

    # Build a safe filename (your IDs are typically hex, so this is mostly for safety)
    safe_id = "".join(ch for ch in mdm_id if ch.isalnum() or ch in ("-", "_"))
    csv_filename = f"mdmServerDevices_{safe_id}.csv"

    print(f"INFO: Starting device export for MDM server: {mdm_id}")

    try:
        devices = fetch_all_devices_for_mdm_server(mdm_id)
    except Exception as e:
        print("ERROR:", e)
        return

    if not devices:
        print("INFO: No devices linked to this MDM server. Creating empty CSV with header.")
        fieldnames, rows = flatten_devices(mdm_id, devices)
        write_csv(fieldnames, rows, csv_filename)
        print(f"INFO: Done. File created: {csv_filename}")
        return

    fieldnames, rows = flatten_devices(mdm_id, devices)
    write_csv(fieldnames, rows, csv_filename)
    print(f"INFO: Device export completed. File: {csv_filename}")


if __name__ == "__main__":
    main()