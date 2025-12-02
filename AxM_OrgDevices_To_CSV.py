#!/usr/bin/env python3
"""
AxM_OrgDevices_To_CSV.py

Simplified script:
- Uses AxM_OAuth.get_access_token_and_scope() to get token + scope
- Chooses base URL based on scope ('school.api' or 'business.api')
- Fetches all orgDevices (with pagination)
- Handles 429 and 401 (with one token refresh)
- Exports devices to orgDevices.csv

Karthikeyan Marappan

"""

import os
import csv
import time
from typing import List, Dict, Any, Tuple

import requests
from AxM_OAuth import get_access_token_and_scope  # adjust name if needed


CSV_FILENAME = "orgDevices.csv"
PAGE_LIMIT = 1000  # Apple max

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(BASE_DIR, "AxM_Token.cache")


def get_token_and_url(force_new: bool = False) -> tuple[str, str]:
    """
    Get an access token and base orgDevices URL based on scope.
    If force_new=True, delete cache so AxM_OAuth generates a fresh token.
    """
    if force_new and os.path.exists(TOKEN_CACHE_FILE):
        try:
            os.remove(TOKEN_CACHE_FILE)
            print("INFO: Deleted cached token file to force regeneration.")
        except OSError:
            print("WARN: Could not delete token cache file; AxM_OAuth will handle it.")

    access_token, scope = get_access_token_and_scope()

    s = (scope or "").lower()
    if "school" in s:
        base_url = "https://api-school.apple.com/v1/orgDevices"
    elif "business" in s:
        base_url = "https://api-business.apple.com/v1/orgDevices"
    else:
        raise RuntimeError(f"Unrecognized scope '{scope}'. Expected 'school.api' or 'business.api'.")

    return access_token, base_url


def fetch_all_devices() -> List[Dict[str, Any]]:
    """
    Fetch all orgDevices, handling 429 and 401 with a single token refresh.
    """
    access_token, org_devices_url = get_token_and_url()
    devices: List[Dict[str, Any]] = []
    cursor = None
    token_refreshed_once = False

    while True:
        params = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        print(f"INFO: Fetching orgDevices page (cursor={cursor})")
        response = requests.get(org_devices_url, headers=headers, params=params)

        # 429 Too Many Requests
        if response.status_code == 429:
            print("INFO: HTTP 429 Too Many Requests. Waiting 60 seconds before retry...")
            time.sleep(60)
            continue

        # 401 Unauthorized: try one refresh
        if response.status_code == 401:
            if not token_refreshed_once:
                print("INFO: HTTP 401 Unauthorized. Regenerating access token and retrying once...")
                access_token, org_devices_url = get_token_and_url(force_new=True)
                token_refreshed_once = True
                # Retry same page with new token
                continue
            else:
                raise RuntimeError(
                    "ERROR: HTTP 401 Unauthorized even after regenerating token. "
                    "Please check variables in AxM_Variables.env."
                )

        # Other known errors
        if response.status_code == 403:
            raise RuntimeError("ERROR: HTTP 403 Forbidden. Check API permissions / scope.")
        if response.status_code == 400:
            raise RuntimeError(f"ERROR: HTTP 400 Bad Request. Response: {response.text}")
        if not response.ok:
            raise RuntimeError(f"ERROR: HTTP {response.status_code}. Response: {response.text}")

        # Success
        data = response.json()
        page_devices = data.get("data", []) or []
        print(f"INFO: Retrieved {len(page_devices)} devices in this page.")
        devices.extend(page_devices)

        # Pagination
        meta = data.get("meta", {}) or {}
        paging = meta.get("paging", {}) or {}
        cursor = paging.get("nextCursor")
        if not cursor:
            print("INFO: No further pages. Finished fetching devices.")
            break

    print(f"INFO: Total devices fetched: {len(devices)}")
    return devices


def flatten_devices(devices: List[Dict[str, Any]]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Flatten orgDevices JSON objects into rows ready for CSV.
    """
    # Collect all attribute keys
    attribute_keys = set()
    for d in devices:
        attrs = d.get("attributes", {}) or {}
        attribute_keys.update(attrs.keys())

    attribute_keys = sorted(attribute_keys)
    fieldnames = ["id", "type"] + attribute_keys
    rows: List[Dict[str, Any]] = []

    for d in devices:
        row: Dict[str, Any] = {
            "id": d.get("id", ""),
            "type": d.get("type", ""),
        }
        attrs = d.get("attributes", {}) or {}

        for key in attribute_keys:
            value = attrs.get(key, "")
            if isinstance(value, list):
                value = ",".join(str(v) for v in value)
            row[key] = value

        rows.append(row)

    return fieldnames, rows


def write_csv(fieldnames: List[str], rows: List[Dict[str, Any]], filename: str) -> None:
    print(f"INFO: Writing {len(rows)} records to {filename} ...")
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print("INFO: CSV writing completed.")


def main():
    print("INFO: Starting orgDevices export...")
    devices = fetch_all_devices()

    if not devices:
        print("INFO: No devices returned from API. Exiting.")
        return

    fieldnames, rows = flatten_devices(devices)
    write_csv(fieldnames, rows, CSV_FILENAME)
    print(f"INFO: orgDevices export completed. File: {CSV_FILENAME}")


if __name__ == "__main__":
    main()