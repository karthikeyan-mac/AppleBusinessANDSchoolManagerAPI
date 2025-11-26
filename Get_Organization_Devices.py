"""
get_Organization_Devices.py

Get a list of devices in an organization that enroll using Automated Device Enrollment.
Documentation: https://developer.apple.com/documentation/applebusinessmanagerapi/get-org-devices
"""

import csv
import time
import logging
import os
from typing import List, Dict, Set
import requests
from Apple_AxM_OAuth import get_access_token, scope

# ------------------------------
# Logging configuration
# ------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------
# Dynamic API URL based on scope
# ------------------------------
base_domain = scope.split('.')[0]  # 'business' or 'school'
api_url = f"https://api-{base_domain}.apple.com/v1/orgDevices"
limit = 1000

# ------------------------------
# Generate timestamped CSV filename
# ------------------------------
timestamp = time.strftime("%Y%m%d_%H%M%S")
csv_file = f"All_Organization_Devices_{timestamp}.csv"

# ------------------------------
# Flatten device attributes for CSV
# ------------------------------
def flatten_device(device: Dict) -> Dict:
    """
    Extracts device attributes and relationships into a flat dictionary.
    """
    attrs = device.get("attributes", {})
    rel = device.get("relationships", {})
    attrs["assignedServer"] = rel.get("assignedServer", {}).get("links", {}).get("related", "")
    attrs["appleCareCoverage"] = rel.get("appleCareCoverage", {}).get("links", {}).get("related", "")
    return attrs

# ------------------------------
# Fetch devices with pagination and retry handling
# ------------------------------
def fetch_devices(token: str) -> List[Dict]:
    """
    Fetch all orgDevices from Apple API.
    Handles pagination, 401 unauthorized, and 429 rate limiting.
    """
    devices = []
    session = requests.Session()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{api_url}?limit={limit}"

    retried_access = False
    retried_jwt = False

    while url:
        resp = session.get(url, headers=headers)

        # Rate limit handling
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            logger.warning(f"Rate limited (429). Retrying after {retry_after}s...")
            time.sleep(retry_after)
            continue

        # Unauthorized handling
        if resp.status_code == 401:
            if not retried_access:
                logger.info("401 Unauthorized. Regenerating access token...")
                token = get_access_token(force=True)
                headers["Authorization"] = f"Bearer {token}"
                retried_access = True
                continue
            elif not retried_jwt:
                logger.info("401 Unauthorized again. Regenerating JWT + access token...")
                token = get_access_token(force=True)
                headers["Authorization"] = f"Bearer {token}"
                retried_jwt = True
                continue
            else:
                raise RuntimeError(
                    "Unauthorized even after JWT + token regeneration. "
                    "Please verify team_id, key_id, and PEM file in Apple_AxM_OAuth.py"
                )

        resp.raise_for_status()
        data = resp.json()
        devices.extend(flatten_device(d) for d in data.get("data", []))
        url = data.get("links", {}).get("next")

    logger.info(f"Total devices fetched: {len(devices)}")
    return devices

# ------------------------------
# Write devices to CSV with uniform fields
# ------------------------------
def write_csv(devices: List[Dict], file_path: str):
    """
    Writes device list to CSV.
    Dynamically generates a complete set of fields across all devices.
    Missing attributes in some devices are left empty.
    """
    if not devices:
        logger.info("No devices found to write to CSV.")
        return

    # Determine all possible fields across all devices
    all_fields: Set[str] = set()
    for device in devices:
        all_fields.update(device.keys())
    fields = sorted(all_fields)

    # Write CSV
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for device in devices:
            writer.writerow({k: device.get(k, "") for k in fields})

# ------------------------------
# Main execution
# ------------------------------
if __name__ == "__main__":
    logger.info("Starting device fetch process...")

    # Attempt to get access token (3 retries)
    try:
        token = get_access_token()
    except RuntimeError as e:
        logger.error(
            f"Failed to generate or use access token after multiple retries. "
            f"Please verify team_id, key_id, and PEM file in Apple_AxM_OAuth.py. Details: {e}"
        )
        raise

    device_list = fetch_devices(token)
    write_csv(device_list, csv_file)
    abs_path = os.path.abspath(csv_file)
    logger.info(f"Device fetch and CSV export completed successfully. Absolute path: {abs_path}")