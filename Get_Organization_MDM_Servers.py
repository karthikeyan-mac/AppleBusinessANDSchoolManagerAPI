#!/usr/bin/env python3
"""
Get_Organization_MDM_Servers.py

Fetch all Device Management (MDM) servers in an organization.

- Uses cached access token from Apple_AxM_OAuth.py
- Fetches basic MDM server attributes: serverName, serverType, createdDateTime, updatedDateTime
- Includes devices relationship link separately
- Outputs data to Organization_MDM_Servers_<timestamp>.csv
- Improved error-handling: 401 retry, access token refresh, JWT regeneration
- Logs slow requests and HTTP errors
- Handles 429 Too Many Requests via Retry-After header only (no adapter retries)
- No session adapters / no make_session()

Apple API documentation:
https://developer.apple.com/documentation/applebusinessmanagerapi/get-device-management-services

Author: Karthikeyan Marappan
"""

import csv
import os
import logging
import time
from datetime import datetime
import requests
from typing import List, Dict
from Apple_AxM_OAuth import get_access_token, scope

# ------------------------------
# Logging configuration
# ------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------
# API base URL and timestamped CSV output
# ------------------------------
base_domain = scope.split('.')[0]
api_base = f"https://api-{base_domain}.apple.com/v1/mdmServers"

timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = os.path.abspath(f"Organization_MDM_Servers_{timestamp_str}.csv")

# ------------------------------
# Fields for API & CSV
# ------------------------------
fields_api = ["serverName", "serverType", "createdDateTime", "updatedDateTime"]
csv_fieldnames = ["id", "type"] + fields_api + ["devicesLink"]

# ------------------------------
# Simple session (no retry adapters)
# ------------------------------
session = requests.Session()

# ------------------------------
# Timed GET request
# ------------------------------
def timed_request(url: str, headers: Dict) -> requests.Response:
    start = time.time()
    resp = session.get(url, headers=headers, timeout=30)
    duration = time.time() - start
    if duration > 2:
        logger.warning(f"Slow request ({duration:.2f}s) → {url}")
    return resp

# ------------------------------
# Convert JSON to CSV row
# ------------------------------
def to_row(server: Dict) -> Dict:
    attrs = server.get("attributes", {}) or {}
    rels = server.get("relationships", {}) or {}
    return {
        "id": server.get("id", ""),
        "type": server.get("type", ""),
        "serverName": attrs.get("serverName", ""),
        "serverType": attrs.get("serverType", ""),
        "createdDateTime": attrs.get("createdDateTime", ""),
        "updatedDateTime": attrs.get("updatedDateTime", ""),
        "devicesLink": rels.get("devices", {}).get("links", {}).get("self", "")
    }

# ------------------------------
# Fetch MDM Servers with 401 + JWT handling and 429 Retry-After
# ------------------------------
def fetch_mdm_servers(token: str) -> List[Dict]:
    servers = []
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{api_base}?fields[mdmServers]={','.join(fields_api)}&limit=1000"

    retried_access = False
    retried_jwt = False

    while url:
        resp = timed_request(url, headers)

        # --- 429 Too Many Requests (Retry After only)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            logger.warning(f"Rate limited (429). Retrying after {retry_after}s…")
            time.sleep(retry_after)
            continue

        # --- 401 Unauthorized
        if resp.status_code == 401:
            if not retried_access:
                logger.info("401 Unauthorized. Regenerating access token...")
                try:
                    token = get_access_token(force=True)
                except RuntimeError as e:
                    logger.error(
                        f"Failed to refresh access token. Verify team_id, key_id, PEM in Apple_AxM_OAuth.py. Details: {e}"
                    )
                    raise
                headers["Authorization"] = f"Bearer {token}"
                retried_access = True
                continue

            elif not retried_jwt:
                logger.info("401 again. Regenerating JWT + access token...")
                try:
                    token = get_access_token(force=True)
                except TypeError:
                    token = get_access_token(force=True)
                except RuntimeError as e:
                    logger.error(
                        f"Failed to regenerate JWT. Verify team_id, key_id, PEM in Apple_AxM_OAuth.py. Details: {e}"
                    )
                    raise
                headers["Authorization"] = f"Bearer {token}"
                retried_jwt = True
                continue

            else:
                logger.error(
                    "Unauthorized even after JWT + token refresh. "
                    "Verify team_id, key_id, PEM file in Apple_AxM_OAuth.py."
                )
                raise RuntimeError("Unauthorized after multiple retries")

        # Other HTTP errors
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            logger.error(f"HTTPError fetching MDM servers: {resp.status_code} {resp.text}")
            raise

        # Process data
        data = resp.json()
        servers.extend(data.get("data", []))

        # Pagination
        url = data.get("links", {}).get("next")

    logger.info(f"Total MDM servers fetched: {len(servers)}")
    return servers

# ------------------------------
# Main
# ------------------------------
def main():
    logger.info("Starting fetch of organization MDM servers...")

    try:
        token = get_access_token()
    except RuntimeError as e:
        logger.error(
            f"Failed to obtain access token. Verify team_id, key_id, PEM in Apple_AxM_OAuth.py. Details: {e}"
        )
        return

    try:
        servers = fetch_mdm_servers(token)
    except Exception as e:
        logger.error(f"Failed to fetch MDM servers: {e}")
        return

    if not servers:
        logger.info("No MDM servers found.")
        return

    # Write CSV
    try:
        with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=csv_fieldnames)
            writer.writeheader()
            for s in servers:
                writer.writerow(to_row(s))
    except Exception as e:
        logger.error(f"Failed to write CSV: {e}")
        return

    logger.info(f"Organization MDM servers CSV saved at: {output_file}")

if __name__ == "__main__":
    main()