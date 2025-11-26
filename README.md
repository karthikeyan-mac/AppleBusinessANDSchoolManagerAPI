# Apple Business and School Manager API

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

## Requirements

To run this script, you will need to generate the following credentials from the Apple Business or School Manager portal:

- **PEM File**: An EC private key (.pem file) used for JWT signing.
- **Client ID** & **Team ID**: These can be the same for your account.
- **Key ID**: A unique identifier for the key used in the ABM/ASM portal.

For detailed instructions on how to generate these credentials, refer to the [Apple Support Guide for Apple School Manager](https://support.apple.com/en-ca/guide/apple-school-manager/axm33189f66a/1/web/1) and [Apple Support Guide for Apple Business Manager](https://support.apple.com/en-ca/guide/apple-business-manager/axm33189f66a/1/web/1)

- Python 3.7 or higher  

## Python Dependencies

Install required Python packages:

```bash
pip install requests authlib pycryptodome cryptography 
```


## Script Features

- 🔐 OAuth2 authentication with signed ECC JWT  
- 📦 Organization-wide device export  
- 🎧 AppleCare warranty & coverage lookup  
- 🖥 MDM server list & metadata  
- 🔁 Assign / Unassign devices to MDM servers  
- 🔎 Device information lookup (serial-based)  
- 📄 CSV output for auditing and reporting  
- 🔄 Automatic retry, rate-limit handling, and error logging  
- 🧠 AI-enhanced structure, logging, and reliability  

---

# 📂 Project Structure

```
/AppleAxMTools
├── Apple_AxM_OAuth.py
├── Assign_Unassign_MDM_Server_Devices.py
├── Get_AppleCare_Coverage.py
├── Get_Assigned_MDM_forSerialNumber.py
├── Get_Device_Information_from_Serials.py
├── Get_DevicesList_MDM_Server.py
├── Get_Organization_Devices.py
├── Get_Organization_MDM_Servers.py
```
# 🚀 Usage Examples

Clone and run any script:

```bash
git clone https://github.com/karthikeyan-mac/AppleBusinessManager.git
cd AppleBusinessManager
python3 Get_Organization_Devices.py
```

CSV outputs will be generated in the same folder:

---

# 📄 Script Descriptions

## 1. `Apple_AxM_OAuth.py`
Handles:
- ECC JWT signing  
- OAuth token creation  
- Automatic retries  
- Encrypted token caching  
- Update the private_key_file, client_id, key_id & scope
- Generate Fernet key (Base64) using https://fernet.utils.com/ and update cache_key. This is to encrypt and decrypt the cache file. 

**Usage:**
```python
from Apple_AxM_OAuth import get_access_token
token = get_access_token()
```

---

## 2. `Get_Organization_Devices.py`
Fetches **all devices** in the organization and exports a large CSV.

**Run:**
```bash
python3 Get_Organization_Devices.py
```

---

## 3. `Get_Device_Information_from_Serials.py`
Reads serials from `serial_numbers.txt` and returns:

- Model  
- Description  
- Enrollment details  
- Purchase info  

**Run:**
```bash
python3 Get_Device_Information_from_Serials.py
```

---

## 4. `Get_AppleCare_Coverage.py`
Fetches AppleCare warranty for devices.

**Run:**
```bash
python3 Get_AppleCare_Coverage.py
```

---

## 5. `Get_Organization_MDM_Servers.py`
Fetches all MDM servers of the organization:

- Name  
- ID  
- Type  
- Link details  

**Run:**
```bash
python3 Get_Organization_MDM_Servers.py
```

---

## 6. `Get_DevicesList_MDM_Server.py`
Fetches all devices under a **specific MDM server**.

**Run:**
```bash
python3 Get_DevicesList_MDM_Server.py
```

⮞ You will be prompted for an MDM Server ID.

---

## 7. `Get_Assigned_MDM_forSerialNumber.py`
Reads serials and returns which MDM server each is assigned to.

**Run:**
```bash
python3 Get_Assigned_MDM_forSerialNumber.py
```

---

## 8. `Assign_Unassign_MDM_Server_Devices.py`
Assigns or unassigns devices in bulk.

- Reads serials  
- Runs an Activity API job  
- Polls job status  
- Generates CSV result  

**Run:**
```bash
python3 Assign_Unassign_MDM_Server_Devices.py
```

---

# 🧪 Testing Guidelines (Highly Recommended)

Before using in production:

✔ Review logs for API errors & rate limits  
✔ Test MDM assignment on a **non-production** MDM server  

---

> ⚠ **Important:**  
> These scripts were reviewed and optimized using **AI assistance**.  
> Before deploying in production, **make sure to test** all scripts thoroughly in a safe environment.

---

# 📝 License

Free to use, modify, and redistribute.


---