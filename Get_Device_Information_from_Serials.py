#!/usr/bin/env python3
"""
Get_Device_Information_from_Serials.py

Fetch detailed device information for serials listed in serial_numbers.txt.
Uses cached access token from Apple_AxM_OAuth.py.
Parallel requests via ThreadPoolExecutor speed up fetching for multiple devices.
Logs slow requests, retries, failures, and provides summary of total devices attempted, successful, and failed.

Apple API documentation:
https://developer.apple.com/documentation/applebusinessmanagerapi/get-orgdevice-information

Author: Karthikeyan Marappan
"""

import csv
import os
import logging
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Add timestamp to CSV filename
timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = os.path.abspath(f"Devices_Information_{timestamp_str}.csv")

failure_serials = []

# ------------------------------
# Read serial numbers
# ------------------------------
with open("serial_numbers.txt", "r") as f:
    serial_numbers = [line.strip() for line in f if line.strip()]

# ------------------------------
# Device fields to fetch + timestamp
# ------------------------------
fields = [
    "serialNumber", "addedToOrgDateTime", "releasedFromOrgDateTime", "updatedDateTime",
    "deviceModel", "productFamily", "productType", "deviceCapacity", "partNumber",
    "orderNumber", "color", "status", "orderDateTime", "imei", "meid", "eid",
    "wifiMacAddress", "bluetoothMacAddress", "purchaseSourceId", "purchaseSourceType",
    "assignedServer", "appleCareCoverage", "timestamp"
]

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
    session.mount("https://", adapter)  # Only HTTPS

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
    resp = session.get(url, headers=headers, timeout=30)
    duration = time.time() - start
    if duration > 2:
        logger.warning(f"Slow request ({duration:.2f}s) → {url}")
    return resp

# ------------------------------
# Fetch device information for one serial
# ------------------------------
def fetch_device(serial, access_token):
    url = f"{api_base}/{serial}?fields[orgDevices]={','.join(fields[:-1])}"  # Exclude timestamp for API
    headers = {"Authorization": f"Bearer {access_token}"}

    for attempt in range(2):
        logger.info(f"Requesting serial {serial} (attempt {attempt+1})...")
        resp = timed_request(url, headers)

        if resp.status_code == 401 and attempt == 0:
            logger.warning(f"Unauthorized (401) for {serial} → refreshing access token...")
            try:
                access_token = get_access_token(force=True)
            except RuntimeError as e:
                logger.error(
                    f"Failed to generate/refresh access token for {serial}. "
                    f"Verify team_id, key_id, and PEM in Apple_AxM_OAuth.py. Details: {e}"
                )
                failure_serials.append(serial)
                return None, access_token
            headers["Authorization"] = f"Bearer {access_token}"
            continue

        try:
            resp.raise_for_status()
            data = resp.json()
            if not data.get("data"):
                failure_serials.append(serial)
                logger.warning(f"No device information found for {serial}")
                return None, access_token
            return data, access_token

        except requests.HTTPError:
            failure_serials.append(serial)
            logger.error(f"HTTPError for {serial}: {resp.status_code} {resp.text}")
            return None, access_token
        except requests.RequestException as e:
            failure_serials.append(serial)
            logger.error(f"RequestException for {serial}: {e}")
            return None, access_token

    # If both attempts failed with 401
    try:
        access_token = get_access_token(force=True)
    except RuntimeError as e:
        logger.error(
            f"Failed to regenerate JWT + token for {serial}. "
            f"Verify team_id, key_id, and PEM in Apple_AxM_OAuth.py. Details: {e}"
        )
        failure_serials.append(serial)
        return None, access_token

    headers["Authorization"] = f"Bearer {access_token}"
    try:
        resp = timed_request(url, headers)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("data"):
            failure_serials.append(serial)
            logger.warning(f"No device information found for {serial}")
            return None, access_token
        return data, access_token
    except Exception as e:
        failure_serials.append(serial)
        logger.error(f"Failed after regenerating JWT for {serial}: {e}")
        return None, access_token

# ------------------------------
# Convert JSON to CSV row
# ------------------------------
def to_row(data):
    attrs = data.get("data", {}).get("attributes", {}) or {}
    rels = data.get("data", {}).get("relationships", {}) or {}
    row = {}
    for f in fields:
        if f == "assignedServer":
            row[f] = rels.get("assignedServer", {}).get("links", {}).get("related", "")
        elif f == "appleCareCoverage":
            row[f] = rels.get("appleCareCoverage", {}).get("links", {}).get("related", "")
        elif f == "timestamp":
            row[f] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            v = attrs.get(f)
            if isinstance(v, (list, tuple)):
                v = ", ".join(map(str, v))
            row[f] = v if v is not None else ""
    return row

# ------------------------------
# Main function
# ------------------------------
def main():
    try:
        access_token = get_access_token()
    except RuntimeError as e:
        logger.error(
            f"Failed to obtain access token. Verify team_id, key_id, and PEM in Apple_AxM_OAuth.py. Details: {e}"
        )
        return

    success = 0
    total_devices = len(serial_numbers)

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fields)
        writer.writeheader()

        MAX_WORKERS = 5
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_device, serial, access_token): serial for serial in serial_numbers}

            for future in as_completed(futures):
                serial = futures[future]
                try:
                    data, _ = future.result()
                    if data:
                        writer.writerow(to_row(data))
                        success += 1
                except Exception as e:
                    if serial not in failure_serials:
                        failure_serials.append(serial)
                    logger.error(f"Failed {serial}: {e}")

    logger.info(f"Device info CSV saved at: {output_file}")
    logger.info(f"Total devices attempted: {total_devices}")
    logger.info(f"Successful: {success}")
    logger.info(f"Failed: {len(failure_serials)}")
    if failure_serials:
        logger.info(f"Failed serial numbers: {failure_serials}")

if __name__ == "__main__":
    main()