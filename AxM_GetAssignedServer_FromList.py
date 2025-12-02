#!/usr/bin/env python3
"""
AxM_GetAssignedServer_FromList.py

Reads SERIAL NUMBERS from serialnumbers.txt in the SAME directory
and fetches the assigned MDM server for each device via:

    GET https://api-<scope>.apple.com/v1/orgDevices/{id}/assignedServer

Exports results to assignedServer_details.csv.

Features:
- Uses AxM_OAuth.get_access_token_and_scope() for token + scope
- Scope determines:
      school.api   -> https://api-school.apple.com/v1/orgDevices
      business.api -> https://api-business.apple.com/v1/orgDevices
- Handles:
      429 Too Many Requests -> Retry-After or 60 sec
      401 Unauthorized -> refresh token ONCE per run
      404 device not found
      400 / 403 / other errors
- No NO_DATA logic (API 404 is sufficient)
- Writes clean CSV
- Prints JSON summary at the end
"""

import os
import time
import json
from typing import Dict, Any, List, Tuple, Optional

import requests
from AxM_OAuth import get_access_token_and_scope

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERIALS_FILE = os.path.join(BASE_DIR, "serialnumbers.txt")
TOKEN_CACHE_FILE = os.path.join(BASE_DIR, "AxM_Token.cache")
CSV_FILENAME = "assignedServer_details.csv"


# -------------------- TOKEN HELPERS -------------------- #

def get_token_and_base_url(force_new: bool = False) -> tuple[str, str]:
    """Get token + base URL for orgDevices based on Apple API scope."""
    if force_new and os.path.exists(TOKEN_CACHE_FILE):
        try:
            os.remove(TOKEN_CACHE_FILE)
            print("INFO: Deleted cached token file to force regeneration.")
        except Exception:
            pass

    access_token, scope = get_access_token_and_scope()

    if "school" in scope.lower():
        base_url = "https://api-school.apple.com/v1/orgDevices"
    elif "business" in scope.lower():
        base_url = "https://api-business.apple.com/v1/orgDevices"
    else:
        raise RuntimeError(f"Invalid scope '{scope}'. Expected school.api or business.api")

    return access_token, base_url


# -------------------- 429 HANDLER -------------------- #

def handle_429(response: requests.Response) -> None:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            wait = int(retry_after)
            print(f"INFO: 429 Too Many Requests — waiting {wait} seconds...")
            time.sleep(wait)
            return
        except ValueError:
            pass

    print("INFO: 429 Too Many Requests — waiting 60 seconds...")
    time.sleep(60)


# -------------------- FETCH ASSIGNED MDM SERVER -------------------- #

def fetch_assigned_server(
    session: requests.Session,
    serial: str,
    token_state: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Returns: (data, error_message)
    data: Dict when successful
    error_message: string for error, or None on success
    """
    access_token = token_state["access_token"]
    base_url = token_state["base_url"]

    url = f"{base_url}/{serial}/assignedServer"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    response = session.get(url, headers=headers)

    # 429 Too Many Requests
    if response.status_code == 429:
        handle_429(response)
        return fetch_assigned_server(session, serial, token_state)

    # 401 Unauthorized
    if response.status_code == 401:
        if not token_state["refreshed_once"]:
            print("INFO: 401 Unauthorized — refreshing token once...")
            new_token, new_base = get_token_and_base_url(force_new=True)
            token_state["access_token"] = new_token
            token_state["base_url"] = new_base
            token_state["refreshed_once"] = True
            return fetch_assigned_server(session, serial, token_state)
        else:
            return None, "401 Unauthorized even after token refresh"

    # 404 Device Not Found
    if response.status_code == 404:
        print(f"INFO: Device '{serial}' not found (404).")
        return None, "NOT_FOUND"

    # 403 Forbidden
    if response.status_code == 403:
        return None, "403 Forbidden"

    # 400 Bad Request
    if response.status_code == 400:
        return None, f"400 Bad Request — {response.text}"

    # Other error
    if not response.ok:
        return None, f"HTTP {response.status_code} — {response.text}"

    # Parse JSON
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return None, f"Invalid JSON — {response.text}"

    data_obj = payload.get("data")
    if not data_obj:
        # API guarantees structured data or 404 — so missing data means API anomaly
        return None, "Unexpected empty data from API"

    return payload, None


# -------------------- CSV BUILD -------------------- #

def build_csv_from_results(results: Dict[str, Any]) -> Tuple[List[str], List[Dict[str, Any]]]:
    rows = []
    attribute_keys = set()

    # Collect all attribute keys
    for payload in results.values():
        if not payload:
            continue
        attrs = payload["data"].get("attributes", {}) or {}
        attribute_keys.update(attrs.keys())

    attribute_keys = sorted(attribute_keys)
    fieldnames = ["inputSerial", "mdmServerId", "type"] + attribute_keys

    # Build rows
    for serial, payload in results.items():
        if not payload:
            continue

        data = payload["data"]
        attrs = data.get("attributes", {}) or {}

        row = {
            "inputSerial": serial,
            "mdmServerId": data.get("id", ""),
            "type": data.get("type", ""),
        }

        for key in attribute_keys:
            value = attrs.get(key, "")
            if isinstance(value, list):
                value = ",".join(value)
            row[key] = value

        rows.append(row)

    return fieldnames, rows


def write_csv(fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    print(f"INFO: Writing {len(rows)} records to {CSV_FILENAME} ...")
    import csv
    with open(CSV_FILENAME, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print("INFO: CSV writing complete.")


# -------------------- MAIN -------------------- #

def main():
    print("INFO: Loading serial numbers from serialnumbers.txt...")

    if not os.path.exists(SERIALS_FILE):
        print("ERROR: serialnumbers.txt not found.")
        return

    with open(SERIALS_FILE, "r") as f:
        serials = [line.strip() for line in f if line.strip()]

    print(f"INFO: Loaded {len(serials)} serials.")

    access_token, base_url = get_token_and_base_url()

    token_state = {
        "access_token": access_token,
        "base_url": base_url,
        "refreshed_once": False,
    }

    session = requests.Session()
    results = {}
    not_found = []
    errors = {}

    # Process each serial
    for serial in serials:
        print(f"INFO: Fetching assigned MDM server for {serial} ...")

        data, error_msg = fetch_assigned_server(session, serial, token_state)
        results[serial] = data

        if error_msg == "NOT_FOUND":
            not_found.append(serial)
        elif error_msg:
            errors[serial] = error_msg

    # Summary
    good = len([d for d in results.values() if d is not None])

    print("\nINFO: Summary:")
    print("  Successful:", good)
    print("  Not found (404):", len(not_found))
    print("  Errors:", len(errors))

    summary = {
        "not_found_404": sorted(not_found),
        "error_serials": errors,
    }

    print("\n---- FINAL RESULT (JSON SUMMARY) ----")
    print(json.dumps(summary, indent=2))
    print("--------------------------------------\n")

    # Write CSV
    fieldnames, rows = build_csv_from_results(results)
    if rows:
        write_csv(fieldnames, rows)
        print(f"INFO: CSV created: {CSV_FILENAME}")
    else:
        print("INFO: No assigned MDM data available; CSV not created.")


if __name__ == "__main__":
    main() 