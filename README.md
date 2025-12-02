# Apple Business and School Manager API Scripts

![Python](https://img.shields.io/badge/Python-3.7%2B-blue?logo=python)
![Platform](https://img.shields.io/badge/Platform-ABM%20%7C%20ASM-black)
![Status](https://img.shields.io/badge/Status-Public%20Release-success)
![AI Enhanced](https://img.shields.io/badge/AI%20Optimized-Code%20Reviewed%20%26%20Enhanced-purple)

Python scripts for **Apple Business Manager (ABM)** and **Apple School Manager (ASM)** APIs.  
These scripts use Apple’s official Device Management APIs to automate device inventory, AppleCare lookup, MDM assignment, and more.

📌 Change the **scope** variable in **Apple_AxM_OAuth.py** for switching Apple Business Manager or Apple School Manager APIs. 

This script follows the **Implementing OAuth for the Apple School and Business Manager API** to generate client assertion and access token. 

You can refer to the official [Apple documentation](https://developer.apple.com/documentation/apple-school-and-business-manager-api/implementing-oauth-for-the-apple-school-and-business-manager-api) for further details on the OAuth implementation.

---

> ⚠ **Important:**  
> These scripts were reviewed and optimized using **AI assistance**.  
> Before deploying in production, **make sure to test** all scripts thoroughly in a safe environment.

---

## Overview

This repository contains a collection of Python scripts that automate
interactions with **Apple School Manager (ASM)** and **Apple Business Manager (ABM)** APIs.

These tools are designed so **even non‑technical users** can run them easily from macOS Terminal.

---

## What These Scripts Can Do

### 1. Generate OAuth Tokens Automatically
- Creates secure JWT client assertions
- Fetches API access tokens from Apple
- Caches token securely (encrypted with Fernet)
- Reuses the token until it expires
- Automatically refreshes the token if expired or invalid

### 2. Download Organization Device Inventory
- Fetches devices registered in Apple School/Business Manager
- Handles pagination and API limits
- Exports results into CSV format

### 3. Get Device Information for a List of Serial Numbers
- Reads serial numbers from `serialnumbers.txt`
- Fetches device details one by one
- Handles:
  - Missing devices (404)
  - Unauthorized responses (401)
  - Rate limits (429 Too Many Requests)
- Generates CSV output

### 4. Fetch Assigned MDM Server Info for Each Device
- Reads device list from `serialnumbers.txt`
- Gets each device’s current assigned MDM server using the `assignedServer` endpoint
- Exports results to CSV

### 5. Fetch AppleCare Coverage for Devices
- Reads serial numbers from `serialnumbers.txt`
- Queries AppleCare / warranty coverage details per device
- Supports multiple coverage types:
  - Limited Warranty
  - AppleCare+
  - AppleCare for Business Essentials
- Outputs a clean CSV

### 6. Get All Device Management Servers
- Lists all MDM servers (Device Management Services) in ASM/ABM
- Includes metadata like:
  - serverName
  - serverType
  - created / updated timestamps
- Outputs to CSV

### 7. Assign / Unassign Devices to an MDM Server
- Uses `orgDeviceActivities`:
  - `ASSIGN_DEVICES`
  - `UNASSIGN_DEVICES`
- Reads devices from `serialnumbers.txt`
- Configuration done via variables at the top of the script:
  - `MODE = "ASSIGN"` or `"UNASSIGN"`
  - `MDM_SERVER_ID = "..."` (your MDM server)
- Automatically:
  - Creates the activity
  - Waits 30 seconds
  - Checks status via `GET /orgDeviceActivities/{id}`
  - Downloads the result CSV if available

---

## Requirements

To run these scripts, you need to generate the following credentials from the Apple Business or School Manager portal:

- **PEM File**: An EC private key (`.pem` file) used for JWT signing.
- **Client ID** & **Team ID**: Provided in the ABM/ASM portal (often the same for your account).
- **Key ID**: A unique identifier for the key used in the ABM/ASM portal.
- **API Scope**: Either `business.api` or `school.api`, depending on whether you use ABM or ASM.
- **Python**: Version **3.7 or higher** (3.10+ recommended).

For detailed instructions on how to generate these credentials, refer to:

- [Apple Support Guide for Apple School Manager](https://support.apple.com/en-ca/guide/apple-school-manager/axm33189f66a/1/web/1)
- [Apple Support Guide for Apple Business Manager](https://support.apple.com/en-ca/guide/apple-business-manager/axm33189f66a/1/web/1)

---

## Python Dependencies

Install required Python packages:

```bash
pip install requests authlib pycryptodome cryptography python-dotenv
```

> If you are using `pip3` on macOS:
> ```bash
> pip3 install requests authlib pycryptodome cryptography python-dotenv
> ```

---

## Environment Configuration (`AxM_Variables.env`)

Create a file named **`AxM_Variables.env`** in the same directory as the scripts.

Example content:

```env
APPLE_CLIENT_ID=BUSINESSAPI.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
APPLE_KEY_ID=YOUR_KEY_ID
APPLE_SCOPE=business.api    # or school.api
PRIVATE_KEY_FILE=private-key.pem

# Fernet encryption key used to encrypt the cached access token
FERNET_KEY=YOUR_FERNET_KEY_HERE
```

### Generating a Fernet Key

Run this command in Terminal to generate a valid Fernet key:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output and paste it into `FERNET_KEY` in `AxM_Variables.env`.

---

## Private Key (`private-key.pem`)

Place your **EC private key** file in the repository folder, for example:

```text
AppleBusinessANDSchoolManagerAPI/
  AxM_OAuth.py
  AxM_AssignUnassign_MdmServers.py
  AxM_GetAppleCareCoverage_FromList.py
  ...
  AxM_Variables.env
  private-key.pem
  serialnumbers.txt
```

The `PRIVATE_KEY_FILE` value in `AxM_Variables.env` must match this filename.

---

## File Overview

| File | Description |
|------|-------------|
| `AxM_OAuth.py` | Core OAuth helper: generates client assertion, calls Apple OAuth endpoint, encrypts and caches access tokens |
| `AxM_OrgDevices_To_CSV.py` | Downloads all organization devices to a CSV |
| `AxM_GetDeviceInfo_FromList.py` | Fetches detailed information for each serial number in `serialnumbers.txt` |
| `AxM_GetAppleCareCoverage_FromList.py` | Gets AppleCare coverage information for devices listed in `serialnumbers.txt` |
| `AxM_MdmServers_To_CSV.py` | Lists all MDM servers (Device Management Services) and exports to CSV |
| `AxM_GetAssignedServer_FromList.py` | Fetches the assigned MDM server for each device in `serialnumbers.txt` |
| `AxM_MdmServerDevices_To_CSV.py` | Given an MDM server ID, exports all linked device IDs |
| `AxM_AssignUnassign_MdmServers.py` | Assigns or unassigns devices (from `serialnumbers.txt`) to/from a specific MDM server and downloads the activity log CSV |
| `serialnumbers.txt` | Input file: one serial number (or orgDevice ID) per line |
| `AxM_Variables.env` | Environment configuration: OAuth parameters, scope, and Fernet key |

---

## How to Use (Step by Step)

### 1. Setup Once

1. Install Python & dependencies.
2. Create `AxM_Variables.env` with your Apple credentials and Fernet key.
3. Place your EC private key as `private-key.pem`.
4. Create `serialnumbers.txt` where needed:
   ```text
   C02ABC123XYZ
   C02DEF456UVW
   C02GHI789JKL
   ```

### 2. Generate & Use OAuth Tokens (Automatic)

You **do not need to run anything manually** to create tokens.  
Each script imports `AxM_OAuth.py`, which:

- Generates a client assertion JWT
- Requests an OAuth access token
- Encrypts and caches it
- Reuses it within its validity period
- Handles 401 (Unauthorized) by regenerating once

---

## Running Common Scripts

> All commands are run from the repository directory, e.g.:
> ```bash
> cd /path/to/AppleBusinessANDSchoolManagerAPI
> ```

### A. Get AppleCare Coverage for a List of Devices

1. Populate `serialnumbers.txt` with serials.
2. Run:

```bash
python3 AxM_GetAppleCareCoverage_FromList.py
```

Output:

- `appleCareCoverage_details.csv`
- Summary of devices with/without coverage in the console.

### B. Get Assigned MDM Server for a List of Devices

```bash
python3 AxM_GetAssignedServer_FromList.py
```

Output:

- `assignedServer_details.csv`

### C. Export All MDM Servers

```bash
python3 AxM_MdmServers_To_CSV.py
```

Output:

- `appleMdmServers.csv`

### D. Assign / Unassign Devices to MDM

Edit the top of `AxM_AssignUnassign_MdmServers.py`:

```python
MODE = "ASSIGN"          # or "UNASSIGN"
MDM_SERVER_ID = "YOUR_MDM_SERVER_ID"
```

Ensure `serialnumbers.txt` contains the devices to assign/unassign.

Then run:

```bash
python3 AxM_AssignUnassign_MdmServers.py
```

The script will:

1. Create an `orgDeviceActivity` in Apple.
2. Wait 30 seconds.
3. Check the activity status via API.
4. If a `downloadUrl` is available and the activity is COMPLETED, automatically download the CSV log (e.g. `ABM-ActivityLog_...csv`).

---

## Error Handling & Logs

The scripts are designed to **fail loudly but clearly**:

- **401 Unauthorized**  
  - Token cache invalidated and regenerated once.  
  - If still 401: asks you to verify credentials in `AxM_Variables.env`.

- **429 Too Many Requests**  
  - Uses `Retry-After` header when available.  
  - Otherwise waits 60 seconds and retries once.

- **404 Not Found**  
  - For device queries: device not in AxM.  
  - For activities: invalid activity ID.

- **Other Errors**  
  - Full HTTPs status and response body printed for debugging (excluding tokens or keys).

---

## Security Notes

- Access tokens are never printed to the console.
- Token cache is **encrypted using Fernet** with your `FERNET_KEY`.
- Private keys and environment files should never be committed to a public repository.
- Treat `AxM_Variables.env` and `private-key.pem` as secrets.

---

## References

- [Implementing OAuth for the Apple School and Business Manager API](https://developer.apple.com/documentation/apple-school-and-business-manager-api/implementing-oauth-for-the-apple-school-and-business-manager-api)
- [Apple Support – Apple School Manager](https://support.apple.com/en-ca/guide/apple-school-manager/axm33189f66a/1/web/1)
- [Apple Support – Apple Business Manager](https://support.apple.com/en-ca/guide/apple-business-manager/axm33189f66a/1/web/1)
- [My old scripts](https://github.com/karthikeyan-mac/AppleBusinessManager)
---

## Final Notes

These scripts are meant to **save time** and reduce manual work in Apple device management workflows,
but you are responsible for:

- Verifying CSV outputs
- Testing in a non‑production environment first
- Reviewing logs for any failed devices or errors

If you expand the repository with new scripts (e.g., updating device metadata, filtering by MDM, etc.),
you can follow the same structure and reuse `AxM_OAuth.py` for authentication.
