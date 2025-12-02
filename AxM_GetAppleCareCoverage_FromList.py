#!/usr/bin/env python3
"""
AxM_GetAppleCareCoverage_FromList.py

Reads SERIAL NUMBERS from serialnumbers.txt in the SAME directory,
fetches AppleCare coverage information for each device via:

    GET https://api-<scope>.apple.com/v1/orgDevices/{id}/appleCareCoverage

and exports the results to appleCareCoverage_details.csv.

Features:
- Uses AxM_OAuth.get_access_token_and_scope() for token + scope
- Scope determines base URL:
    - school.api   -> https://api-school.apple.com/v1/orgDevices
    - business.api -> https://api-business.apple.com/v1/orgDevices
- 429 Too Many Requests -> uses Retry-After header if present, else waits 60 seconds
- 401 Unauthorized -> regenerates token ONCE for the whole run; if still 401, records error
- 200 with empty "data": [] is treated as a failure:
      "Serial number does not exist in AxM or AppleCare coverage information does not exist."
- Uses requests.Session for connection reuse
- Never prints the access token
- At the end, prints a JSON summary of failures and errors
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
CSV_FILENAME = "appleCareCoverage_details.csv"


# -------------------- TOKEN HELPERS -------------------- #

def get_token_and_base_url(force_new: bool = False) -> tuple[str, str]:
    """Get token + base URL for orgDevices based on scope."""
    if force_new and os.path.exists(TOKEN_CACHE_FILE):
        try:
            os.remove(TOKEN_CACHE_FILE)
            print("INFO: Deleted cached token file to force regeneration.")
        except OSError:
            print("WARN: Could not delete token cache; AxM_OAuth will handle it.")

    access_token, scope = get_access_token_and_scope()

    s = scope.lower()
    if "school" in s:
        base_url = "https://api-school.apple.com/v1/orgDevices"
    elif "business" in s:
        base_url = "https://api-business.apple.com/v1/orgDevices"
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

    # fallback if Retry-After missing or invalid
    print("INFO: 429 received — Retry-After not provided, waiting 60 seconds...")
    time.sleep(60)


# -------------------- APPLECARE FETCH -------------------- #

def fetch_applecare_coverage(
    session: requests.Session,
    device_id: str,
    token_state: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Fetch AppleCare coverage for a single device.

    Endpoint:
      GET {base_url}/{device_id}/appleCareCoverage

    token_state:
        {
          "access_token": str,
          "base_url": str,   # base orgDevices URL
          "refreshed_once": bool
        }

    Returns:
        (data, error_message)
        - data: dict with JSON payload (if success and non-empty coverage), or None
        - error_message:
            * None            -> success with coverage
            * "NO_DATA"       -> 200 OK but data: [] (no coverage / not in AxM)
            * "NOT_FOUND"     -> 404
            * other string    -> description of error
    """
    access_token = token_state["access_token"]
    base_url = token_state["base_url"]

    url = f"{base_url}/{device_id}/appleCareCoverage"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    response = session.get(url, headers=headers)

    # 429 - Too Many Requests
    if response.status_code == 429:
        handle_429(response)
        return fetch_applecare_coverage(session, device_id, token_state)

    # 401 - Unauthorized
    if response.status_code == 401:
        if not token_state["refreshed_once"]:
            print("INFO: 401 Unauthorized — regenerating token once for this run...")
            new_token, new_base = get_token_and_base_url(force_new=True)
            token_state["access_token"] = new_token
            token_state["base_url"] = new_base
            token_state["refreshed_once"] = True
            return fetch_applecare_coverage(session, device_id, token_state)
        else:
            return None, "401 Unauthorized even after regenerating token once"

    # 403 - Forbidden
    if response.status_code == 403:
        return None, f"403 Forbidden — {response.text}"

    # 400 - Bad Request
    if response.status_code == 400:
        return None, f"400 Bad Request — {response.text}"

    # 404 - Not Found (not in doc for this endpoint, but we handle just in case)
    if response.status_code == 404:
        print(f"INFO: Device '{device_id}' not found (404) for AppleCare coverage.")
        return None, "NOT_FOUND"

    # Other non-OK
    if not response.ok:
        return None, f"HTTP {response.status_code} — {response.text}"

    # 200 OK – parse JSON
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return None, f"Failed to parse JSON — {response.text}"

    data_list = payload.get("data", [])
    if isinstance(data_list, list) and len(data_list) == 0:
        # No AppleCare coverage OR device not in AxM (Apple returns empty list)
        return None, "NO_DATA"

    return payload, None


# -------------------- CSV BUILD -------------------- #

def build_csv_from_results(results: Dict[str, Any]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Flatten AppleCare coverage data into CSV rows.

    Each row = one AppleCare coverage record for one serial.

    results structure:
        {
          "SERIAL1": { "data": [ {...}, {...} ], ... } or None,
          "SERIAL2": { "data": [ ... ], ... } or None,
        }
    """
    # Collect all coverage entries with their serials
    coverage_entries: List[Tuple[str, Dict[str, Any]]] = []

    for serial, payload in results.items():
        if not payload:
            continue
        data_list = payload.get("data", [])
        if not isinstance(data_list, list):
            continue
        for coverage in data_list:
            coverage_entries.append((serial, coverage))

    if not coverage_entries:
        return [], []

    # Collect all attribute keys across all coverage entries
    attribute_keys = set()
    for _, cov in coverage_entries:
        attrs = cov.get("attributes", {}) or {}
        attribute_keys.update(attrs.keys())

    attribute_keys = sorted(attribute_keys)

    # CSV columns
    fieldnames = ["inputSerial", "coverageId", "type"] + attribute_keys
    rows: List[Dict[str, Any]] = []

    for serial, cov in coverage_entries:
        row: Dict[str, Any] = {
            "inputSerial": serial,
            "coverageId": cov.get("id", ""),
            "type": cov.get("type", ""),
        }
        attrs = cov.get("attributes", {}) or {}
        for key in attribute_keys:
            val = attrs.get(key, "")
            if isinstance(val, list):
                val = ",".join(str(v) for v in val)
            row[key] = val
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
        print(f"ERROR: serialnumbers.txt not found in {BASE_DIR}")
        return

    with open(SERIALS_FILE, "r") as f:
        serials = [s.strip() for s in f if s.strip()]

    if not serials:
        print("ERROR: serialnumbers.txt is empty.")
        return

    print(f"INFO: Loaded {len(serials)} serial numbers.")

    access_token, base_url = get_token_and_base_url()

    # Shared token state for the whole script
    token_state: Dict[str, Any] = {
        "access_token": access_token,
        "base_url": base_url,
        "refreshed_once": False,
    }

    session = requests.Session()
    results: Dict[str, Any] = {}

    no_data_serials: List[str] = []         # 200 OK but data: []
    not_found_serials: List[str] = []       # 404 (if ever returned)
    error_serials: Dict[str, str] = {}      # other errors (401-after-refresh, 403, 400, etc.)

    for serial in serials:
        print(f"INFO: Fetching AppleCare coverage for {serial} ...")
        data, error_msg = fetch_applecare_coverage(session, serial, token_state)
        results[serial] = data

        if error_msg == "NO_DATA":
            no_data_serials.append(serial)
        elif error_msg == "NOT_FOUND":
            print(f"INFO for {serial}: Device not found (404).")
            not_found_serials.append(serial)
        elif error_msg:
            print(f"ERROR for {serial}: {error_msg}")
            error_serials[serial] = error_msg

    print("\nINFO: Summary:")
    total_success = len([s for s, d in results.items() if d is not None])
    print(f"  Successful responses (with coverage data): {total_success}")
    print(f"  No coverage / not in AxM (empty data):    {len(no_data_serials)}")
    print(f"  Not found (404):                          {len(not_found_serials)}")
    print(f"  With other errors:                        {len(error_serials)}")

    # JSON-style summary
    summary = {
        "no_applecare_or_not_in_axm": sorted(no_data_serials),
        "not_found_404": sorted(not_found_serials),
        "error_serials": error_serials,
    }

    print("\n---- FINAL RESULT (JSON SUMMARY) ----")
    print("These devices do not have the required information")
    print(json.dumps(summary, indent=2))
    print("-------------------------------------\n")

    # CSV export (only serials with actual coverage entries)
    fieldnames, rows = build_csv_from_results(results)
    if rows:
        write_csv(fieldnames, rows)
        print(f"INFO: CSV created: {CSV_FILENAME}")
    else:
        print("INFO: No AppleCare coverage data available to write to CSV.")


if __name__ == "__main__":
    main()