#!/usr/bin/env python3
"""
AxM_MdmServers_To_CSV.py

Fetches all Device Management Services (MDM servers) for the organization via:

    GET https://api-<scope>.apple.com/v1/mdmServers

and exports them to appleMdmServers.csv.

Features:
- Uses AxM_OAuth.get_access_token_and_scope() for token + scope
- Scope determines base URL:
    - school.api   -> https://api-school.apple.com/v1/mdmServers
    - business.api -> https://api-business.apple.com/v1/mdmServers
- Handles pagination via meta.paging.nextCursor (if present)
- 429 Too Many Requests -> uses Retry-After header if present, else waits 60 seconds
- 401 Unauthorized -> regenerates token ONCE for the whole run; if still 401, raises clear error
- 400 / 403 / other non-OK codes -> clear exceptions
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
CSV_FILENAME = "appleMdmServers.csv"
PAGE_LIMIT = 1000  # Apple max


# -------------------- TOKEN / URL HELPERS -------------------- #

def get_token_and_mdm_url(force_new: bool = False) -> tuple[str, str]:
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


# -------------------- FETCH ALL MDM SERVERS -------------------- #

def fetch_all_mdm_servers() -> List[Dict[str, Any]]:
    """
    Fetch all MDM servers, handling pagination, 429, and one 401 refresh.

    Returns:
        List of mdmServers objects (as JSON dictionaries).
    """
    access_token, base_url = get_token_and_mdm_url()
    session = requests.Session()

    servers: List[Dict[str, Any]] = []
    cursor: str | None = None
    token_refreshed_once = False

    while True:
        params = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        print(f"INFO: Fetching mdmServers page (cursor={cursor}) ...")
        response = session.get(base_url, headers=headers, params=params)

        # 429 Too Many Requests
        if response.status_code == 429:
            handle_429(response)
            continue

        # 401 Unauthorized
        if response.status_code == 401:
            if not token_refreshed_once:
                print("INFO: 401 Unauthorized — regenerating token once for this run...")
                access_token, base_url = get_token_and_mdm_url(force_new=True)
                token_refreshed_once = True
                continue
            else:
                raise RuntimeError(
                    "ERROR: 401 Unauthorized even after regenerating token once.\n"
                    "Please check values in AxM_Variables.env "
                    "(APPLE_CLIENT_ID / APPLE_KEY_ID / APPLE_SCOPE / PRIVATE KEY)."
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

        page_servers = data.get("data", []) or []
        print(f"INFO: Retrieved {len(page_servers)} MDM server(s) in this page.")
        servers.extend(page_servers)

        # Pagination
        meta = data.get("meta", {}) or {}
        paging = meta.get("paging", {}) or {}
        cursor = paging.get("nextCursor")
        if not cursor:
            print("INFO: No further pages. Finished fetching MDM servers.")
            break

    print(f"INFO: Total MDM servers fetched: {len(servers)}")
    return servers


# -------------------- CSV BUILD -------------------- #

def flatten_mdm_servers(servers: List[Dict[str, Any]]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Flatten mdmServers JSON objects into rows ready for CSV.

    Each server object has:
        - id
        - type
        - attributes: serverName, serverType, createdDateTime, updatedDateTime, ...
    """
    if not servers:
        return [], []

    attribute_keys = set()
    for s in servers:
        attrs = s.get("attributes", {}) or {}
        attribute_keys.update(attrs.keys())

    attribute_keys = sorted(attribute_keys)
    fieldnames = ["id", "type"] + attribute_keys
    rows: List[Dict[str, Any]] = []

    for s in servers:
        row: Dict[str, Any] = {
            "id": s.get("id", ""),
            "type": s.get("type", ""),
        }
        attrs = s.get("attributes", {}) or {}
        for key in attribute_keys:
            val = attrs.get(key, "")
            if isinstance(val, list):
                val = ",".join(str(v) for v in val)
            row[key] = val
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
    print("INFO: Starting MDM servers export...")

    try:
        servers = fetch_all_mdm_servers()
    except Exception as e:
        print("ERROR:", e)
        return

    if not servers:
        print("INFO: No MDM servers returned from API. Exiting.")
        return

    fieldnames, rows = flatten_mdm_servers(servers)
    if not rows:
        print("INFO: No data to write to CSV.")
        return

    write_csv(fieldnames, rows, CSV_FILENAME)
    print(f"INFO: MDM servers export completed. File: {CSV_FILENAME}")


if __name__ == "__main__":
    main()