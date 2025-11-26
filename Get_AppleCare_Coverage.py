#!/usr/bin/env python3
"""
Get_AppleCare_Coverage.py

Fetch AppleCare coverage for devices listed in serial_numbers.txt.
Uses cached access token from Apple_AxM_OAuth.py.
Parallel requests via ThreadPoolExecutor speed up fetching for multiple devices.
Logs slow requests, retries, failures, and tracks summary of total devices attempted, successful, and failed.

Apple API documentation:
https://developer.apple.com/documentation/applebusinessmanagerapi/get-all-apple-care-coverage-for-an-orgdevice

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
output_file = os.path.abspath(f"AppleCoverage_{timestamp_str}.csv")

failure_serials = []

# ------------------------------
# Read serial numbers
# ------------------------------
with open("serial_numbers.txt", "r") as f:
    serial_numbers = [line.strip() for line in f if line.strip()]

# ------------------------------
# AppleCare fields + timestamp
# ------------------------------
fields = [
    "status", "paymentType", "description", "agreementNumber",
    "startDateTime", "endDateTime", "isRenewable", "isCanceled", "contractCancelDateTime",
    "timestamp"
]

# ------------------------------
# Requests session with retries
# ------------------------------
def make_session():
    """
    Create a requests session with retry/backoff for 429/5xx errors.
    Only HTTPS mounted for security.
    """
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
# Fetch AppleCare coverage for one serial
# ------------------------------
def fetch_applecare(serial, access_token):
    url = f"{api_base}/{serial}/appleCareCoverage?fields[appleCareCoverage]={','.join(fields[:-1])}"  # Exclude timestamp
    headers = {"Authorization": f"Bearer {access_token}"}

    for attempt in range(2):
        logger.info(f"Requesting AppleCare for {serial} (attempt {attempt+1})...")
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
                logger.warning(f"No AppleCare coverage found for {serial}")
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

    logger.info(f"Access token failed twice for {serial}. Regenerating JWT/token...")
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
            logger.warning(f"No AppleCare coverage found for {serial}")
            return None, access_token
        return data, access_token
    except Exception as e:
        failure_serials.append(serial)
        logger.error(f"Failed after regenerating JWT for {serial}: {e}")
        return None, access_token

# ------------------------------
# Convert JSON to CSV rows
# ------------------------------
def to_rows(serial, data):
    rows = []
    for entry in data.get("data", []):
        attrs = entry.get("attributes", {})
        row = {"serialNumber": serial}
        for f in fields:
            if f == "timestamp":
                row[f] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                row[f] = attrs.get(f, "")
        rows.append(row)
    return rows

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
        writer = csv.DictWriter(csvfile, fieldnames=["serialNumber"] + fields)
        writer.writeheader()

        MAX_WORKERS = 5
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_applecare, serial, access_token): serial for serial in serial_numbers}

            for future in as_completed(futures):
                serial = futures[future]
                try:
                    data, _ = future.result()
                    if data:
                        for row in to_rows(serial, data):
                            writer.writerow(row)
                            success += 1
                except Exception as e:
                    if serial not in failure_serials:
                        failure_serials.append(serial)
                    logger.error(f"Failed {serial}: {e}")

    logger.info(f"AppleCare CSV saved at: {output_file}")
    logger.info(f"Total devices attempted: {total_devices}")
    logger.info(f"Successful: {success}")
    logger.info(f"Failed: {len(failure_serials)}")
    if failure_serials:
        logger.info(f"Failed serial numbers: {failure_serials}")

if __name__ == "__main__":
    main()