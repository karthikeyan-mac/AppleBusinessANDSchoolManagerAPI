#!/usr/bin/env python3
"""
Assign_Unassign_MDM_Server_Devices.py

Assign or unassign devices to/from a Device Management Server in ABM/ASM.

Apple API documentation:
https://developer.apple.com/documentation/applebusinessmanagerapi/create-an-orgdeviceactivity

Reads serial numbers from serial_numbers.txt.
Uses get_access_token() from Apple_AxM_OAuth.py for JWT/token handling.

Author: Karthikeyan Marappan
"""

import os
import time
import logging
import requests
from Apple_AxM_OAuth import get_access_token, scope

# ------------------------------
# Logging configuration
# ------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------
# Settings
# ------------------------------
DEVICE_LIST_FILE = "serial_numbers.txt"
# Options: "ASSIGN_DEVICES" | "UNASSIGN_DEVICES"
ACTIVITY_TYPE = "ASSIGN_DEVICES"
MDM_SERVER_ID = "B996D182CC0C4295AFF7992033EA8FE6"
BASE_DOMAIN = scope.split('.')[0]
APPLE_API = f"https://api-{BASE_DOMAIN}.apple.com/v1/orgDeviceActivities"

RESPONSE_CODES = {
    200: "OK",
    201: "Created",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    409: "Conflict",
    422: "Unprocessable Entity",
    429: "Too Many Requests"
}

# ------------------------------
# Helpers
# ------------------------------
def log_response(resp):
    msg = RESPONSE_CODES.get(resp.status_code, f"Unexpected {resp.status_code}")
    logger.info(f"Response {resp.status_code}: {msg}")
    return resp.status_code

def submit_activity(serials, token):
    """
    Initiates the assignment/unassignment activity.
    Handles 401, 429 rate-limits, and exits if Retry-After > 60s.
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    relationships = {"devices": {"data": [{"type": "orgDevices", "id": s} for s in serials]}}
    if ACTIVITY_TYPE == "ASSIGN_DEVICES":
        relationships["mdmServer"] = {"data": {"type": "mdmServers", "id": MDM_SERVER_ID}}

    payload = {
        "data": {
            "type": "orgDeviceActivities",
            "attributes": {"activityType": ACTIVITY_TYPE},
            "relationships": relationships
        }
    }

    while True:
        try:
            resp = requests.post(APPLE_API, headers=headers, json=payload, timeout=60)
        except requests.RequestException as e:
            logger.error(f"Network error submitting activity: {e}")
            return None, None

        code = log_response(resp)

        # Handle rate limiting
        if code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            if retry_after > 60:
                logger.error(f"Retry-After header too high ({retry_after}s). Exiting script.")
                return None, None
            logger.warning(f"Rate limited. Retrying after {retry_after}s...")
            time.sleep(retry_after)
            continue

        # Handle 401 unauthorized
        if code == 401:
            logger.warning("Unauthorized (401). Refreshing token...")
            try:
                token = get_access_token(force=True)
            except RuntimeError as e:
                logger.error(f"Token refresh failed: {e}")
                return None, None
            headers["Authorization"] = f"Bearer {token}"
            continue

        if code == 201:
            body = resp.json()
            return body["data"]["id"], body["links"]["self"]

        logger.error(resp.text)
        return None, None

def check_status(activity_id, token):
    """
    Polls orgDeviceActivities/<id> for status.
    """
    url = f"{APPLE_API}/{activity_id}"
    headers = {"Authorization": f"Bearer {token}"}

    time.sleep(5)
    try:
        resp = requests.get(url, headers=headers, timeout=90)
    except requests.RequestException as e:
        logger.error(f"Network error checking activity: {e}")
        return None

    code = log_response(resp)
    if code == 401:
        logger.warning("401 while checking status. Refreshing token...")
        token = get_access_token(force=True)
        return check_status(activity_id, token)

    if code != 200:
        logger.error(resp.text)
        return None

    return resp.json().get("data", {})

def download_csv(url):
    """
    Downloads the Apple-generated CSV.
    """
    try:
        resp = requests.get(url, timeout=90)
    except requests.RequestException as e:
        logger.error(f"Network error downloading CSV: {e}")
        return

    if resp.status_code != 200:
        logger.error("Failed to download CSV")
        return

    cd_header = resp.headers.get("Content-Disposition", "")
    filename = "activity_log.csv"
    if "filename=" in cd_header:
        filename = cd_header.split("filename=")[-1].strip('"')

    with open(filename, "wb") as f:
        f.write(resp.content)
    logger.info(f"CSV downloaded successfully: {filename}")

# ------------------------------
# Main
# ------------------------------
def main():
    if not os.path.exists(DEVICE_LIST_FILE):
        logger.error(f"{DEVICE_LIST_FILE} not found")
        return

    with open(DEVICE_LIST_FILE) as f:
        serials = [line.strip() for line in f if line.strip()]

    if not serials:
        logger.error("No serial numbers found in file.")
        return

    logger.info(f"Submitting {ACTIVITY_TYPE} request for {len(serials)} devices")

    try:
        token = get_access_token()
    except RuntimeError as e:
        logger.error(f"Failed to generate access token: {e}")
        return

    activity_id, _ = submit_activity(serials, token)
    if not activity_id:
        return

    data = check_status(activity_id, token)
    if not data:
        return

    attrs = data.get("attributes", {})
    logger.info(f"Activity Status: {attrs.get('status')} - SubStatus: {attrs.get('subStatus')}")

    if attrs.get("downloadUrl"):
        download_csv(attrs["downloadUrl"])

if __name__ == "__main__":
    main()