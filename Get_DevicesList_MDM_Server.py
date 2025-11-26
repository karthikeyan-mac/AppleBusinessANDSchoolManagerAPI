#!/usr/bin/env python3
"""
Get_DevicesList_MDM_Server.py

Fetch all device serial numbers assigned to a specific MDM server.
Uses cached access token from Apple_AxM_OAuth.py.
Handles pagination to fetch all devices (not just first 1000).
Logs slow requests, retries (429), unauthorized (401) and token refresh failures.

Apple API documentation:
https://developer.apple.com/documentation/applebusinessmanagerapi/get-all-device-ids-for-a-device-management-service

Author: Karthikeyan Marappan
"""

import csv
import os
import logging
import time
from datetime import datetime
import requests
from Apple_AxM_OAuth import get_access_token, scope

# ------------------------------
# Logging configuration
# ------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------
# CSV output with timestamp
# ------------------------------
timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = os.path.abspath(f"DeviceList_MDM_Server_{timestamp_str}.csv")

# ------------------------------
# CSV fields
# ------------------------------
fields = ["mdmServerId", "deviceType", "serialNumber", "timestamp"]

# ------------------------------
# Timed GET request
# ------------------------------
def timed_request(url, headers):
    start = time.time()
    resp = requests.get(url, headers=headers, timeout=90)
    duration = time.time() - start
    if duration > 2:
        logger.warning(f"Slow request ({duration:.2f}s) → {url}")
    return resp

# ------------------------------
# Main function
# ------------------------------
def main():
    mdm_server_id = input("Enter MDM Server ID: ").strip()
    if not mdm_server_id:
        logger.error("MDM Server ID is required")
        return

    try:
        access_token = get_access_token()
    except RuntimeError as e:
        logger.error(f"Failed to obtain access token. Verify team_id, key_id, and PEM in Apple_AxM_OAuth.py. Details: {e}")
        return

    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api-{scope.split('.')[0]}.apple.com/v1/mdmServers/{mdm_server_id}/relationships/devices?limit=1000"

    total_devices = 0
    success = 0

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fields)
        writer.writeheader()

        while url:
            resp = timed_request(url, headers)

            # Rate limiting
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                logger.warning(f"Rate limited (429). Retrying after {retry_after}s...")
                time.sleep(retry_after)
                continue

            # Unauthorized handling
            if resp.status_code == 401:
                logger.info("401 Unauthorized. Refreshing access token and retrying...")
                try:
                    access_token = get_access_token(force=True)
                    headers["Authorization"] = f"Bearer {access_token}"
                    continue
                except RuntimeError as e:
                    logger.error(f"Failed to refresh access token. Details: {e}")
                    break

            if resp.status_code != 200:
                logger.error(f"Failed to fetch devices: {resp.status_code} {resp.text}")
                break

            data_json = resp.json()
            devices = data_json.get("data", [])

            for device in devices:
                writer.writerow({
                    "mdmServerId": mdm_server_id,
                    "deviceType": device.get("type", ""),
                    "serialNumber": device.get("id", ""),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                success += 1

            total_devices += len(devices)
            url = data_json.get("links", {}).get("next")  # Pagination

    logger.info(f"Device list CSV saved at: {output_file}")
    logger.info(f"Total devices attempted: {total_devices}")
    logger.info(f"Successful: {success}")
    if total_devices != success:
        logger.info(f"Failed devices: {total_devices - success}")

if __name__ == "__main__":
    main()