#!/usr/bin/env python3
"""
Get_Assigned_MDM_forSerialNumber.py

Fetch assigned Device Management (MDM) service ID for devices listed in serial_numbers.txt.
Uses cached access token from Apple_AxM_OAuth.py.
Parallel requests via ThreadPoolExecutor speed up fetching for multiple devices.
Logs slow requests, retries, failures, and tracks summary of total devices attempted, successful, and failed.

Apple API documentation:
https://developer.apple.com/documentation/applebusinessmanagerapi/get-the-assigned-device-management-service-id-for-an-orgdevice

Author: Karthikeyan Marappan
"""

import csv
import os
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter, Retry
from Apple_AxM_OAuth import get_access_token, scope

# ------------------------------
# Logging configuration
# ------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------
# API base & CSV setup
# ------------------------------
base_domain = scope.split('.')[0]  # 'business' or 'school'
api_base = f"https://api-{base_domain}.apple.com/v1/orgDevices"

# CSV filename with timestamp
timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = os.path.abspath(f"AssignedMDM_forSerial_{timestamp_str}.csv")

failure_serials = []

# ------------------------------
# Read serial numbers
# ------------------------------
with open("serial_numbers.txt", "r") as f:
    serial_numbers = [line.strip() for line in f if line.strip()]

# ------------------------------
# CSV fields
# ------------------------------
fields = ["serialNumber", "type", "id", "serverName", "serverType", "createdDateTime", "updatedDateTime", "devicesLink", "timestamp"]

# ------------------------------
# Requests session with retries
# ------------------------------
def make_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)

    def _resp_hook(r, *args, **kwargs):
        if r.status_code in {429, 500, 502, 503, 504}:
            ra = r.headers.get("Retry-After")
            if ra:
                logger.warning(f"Retry due to {r.status_code} — server requested wait of {ra}s")
            else:
                logger.warning(f"Retry due to {r.status_code} — backoff factor applies")
        return r

    session.hooks["response"] = [_resp_hook]
    return session

session = make_session()

# ------------------------------
# Timed request
# ------------------------------
def timed_request(url, headers):
    start = time.time()
    resp = session.get(url, headers=headers, timeout=90)
    duration = time.time() - start
    if duration > 2:
        logger.warning(f"Slow request ({duration:.2f}s) → {url}")
    return resp

# ------------------------------
# Fetch assigned MDM for a single serial
# ------------------------------
def fetch_assigned_mdm(serial, access_token):
    url = f"{api_base}/{serial}/assignedServer"
    headers = {"Authorization": f"Bearer {access_token}"}

    for attempt in range(2):
        logger.info(f"Requesting assigned MDM for {serial} (attempt {attempt+1})...")
        resp = timed_request(url, headers)

        # Unauthorized → refresh token
        if resp.status_code == 401 and attempt == 0:
            logger.warning(f"Unauthorized (401) for {serial} → refreshing access token...")
            try:
                access_token = get_access_token(force=True)
            except RuntimeError as e:
                logger.error(f"Failed to refresh token for {serial}: {e}")
                failure_serials.append(serial)
                return None, access_token
            headers["Authorization"] = f"Bearer {access_token}"
            continue

        # No assigned MDM server → log and mark failure
        if resp.status_code == 404 or not resp.json().get("data"):
            logger.info(f"No assigned MDM server for {serial}")
            failure_serials.append(serial)
            return None, access_token

        try:
            resp.raise_for_status()
            data = resp.json().get("data")
            if not data:
                logger.info(f"No assigned MDM server for {serial}")
                failure_serials.append(serial)
                return None, access_token
            return data, access_token

        except requests.HTTPError:
            logger.error(f"HTTPError for {serial}: {resp.status_code} {resp.text}")
            failure_serials.append(serial)
            return None, access_token
        except requests.RequestException as e:
            logger.error(f"RequestException for {serial}: {e}")
            failure_serials.append(serial)
            return None, access_token

    # If both attempts failed → regenerate JWT/token
    logger.info(f"Access token failed twice for {serial}. Regenerating JWT/token...")
    try:
        access_token = get_access_token(force=True)
    except RuntimeError as e:
        logger.error(f"Failed to regenerate JWT/token for {serial}: {e}")
        failure_serials.append(serial)
        return None, access_token

    headers["Authorization"] = f"Bearer {access_token}"
    try:
        resp = timed_request(url, headers)
        resp.raise_for_status()
        data = resp.json().get("data")
        if not data:
            logger.info(f"No assigned MDM server for {serial}")
            failure_serials.append(serial)
            return None, access_token
        return data, access_token
    except Exception as e:
        logger.error(f"Failed after regenerating JWT for {serial}: {e}")
        failure_serials.append(serial)
        return None, access_token

# ------------------------------
# Convert JSON to CSV row
# ------------------------------
def to_row(serial, data):
    attrs = data.get("attributes", {}) or {}
    rels = data.get("relationships", {}) or {}
    row = {
        "serialNumber": serial,
        "type": data.get("type", ""),
        "id": data.get("id", ""),
        "serverName": attrs.get("serverName", ""),
        "serverType": attrs.get("serverType", ""),
        "createdDateTime": attrs.get("createdDateTime", ""),
        "updatedDateTime": attrs.get("updatedDateTime", ""),
        "devicesLink": rels.get("devices", {}).get("links", {}).get("self", ""),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return row

# ------------------------------
# Main function
# ------------------------------
def main():
    try:
        access_token = get_access_token()
    except RuntimeError as e:
        logger.error(f"Failed to obtain access token: {e}")
        return

    success = 0
    total_devices = len(serial_numbers)

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fields)
        writer.writeheader()

        MAX_WORKERS = 5
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_assigned_mdm, serial, access_token): serial for serial in serial_numbers}

            for future in as_completed(futures):
                serial = futures[future]
                try:
                    data, _ = future.result()
                    if data:
                        writer.writerow(to_row(serial, data))
                        success += 1
                except Exception as e:
                    if serial not in failure_serials:
                        failure_serials.append(serial)
                    logger.error(f"Failed {serial}: {e}")

    logger.info(f"Assigned MDM CSV saved at: {output_file}")
    logger.info(f"Total devices attempted: {total_devices}")
    logger.info(f"Successful: {success}")
    logger.info(f"Failed: {len(failure_serials)}")
    if failure_serials:
        logger.info(f"Failed serial numbers: {failure_serials}")

if __name__ == "__main__":
    main()