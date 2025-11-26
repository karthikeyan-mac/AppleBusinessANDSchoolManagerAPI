#!/usr/bin/env python3

#!/usr/bin/env python3
#
# Script to generate JWT and Access token for interacting with Apple Business and School Manager API.
# Documentation: 
# https://developer.apple.com/documentation/apple-school-and-business-manager-api/implementing-oauth-for-the-apple-school-and-business-manager-api
#
# IMPORTANT: Update the following variables before running:
# - client_id: Your Apple API client ID
# - key_id: Your Apple API key ID
# - private_key_file: Path to your Apple API private key (.pem)
# - cache_key: 32-byte Fernet key for encrypting cached token
# - scope: 'school.api' for Apple School Manager or 'business.api' for Apple Business Manager

import os
import sys
import time
import json
import uuid
import logging
import datetime as dt
from typing import Dict
import requests
from authlib.jose import jwt
from Crypto.PublicKey import ECC
from cryptography.fernet import Fernet, InvalidToken

# ------------------------------
# Logging configuration
# ------------------------------
logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------------------
# Scope configuration
# ------------------------------
# Update this depending on your use case:
# 'school.api' → Apple School Manager
# 'business.api' → Apple Business Manager
scope = "school.api"

# ------------------------------
# Configuration (update variables)
# ------------------------------
private_key_file = "private_cert.pem"  # Path to your .pem private key file
client_id = "SCHOOLAPI.dddddfffgg-b912-470e-ssddff-861267824526"  # Apple API client ID
key_id = "0e07d12e-30bf-4ee5-b3bb-sssddfff"  # Apple API key ID
algorithm = "ES256"  # JWT signing algorithm (Apple requires ES256)
cache_file = "auth_cache.enc"  # Encrypted file to store cached token
token_url = "https://account.apple.com/auth/oauth2/v2/token"  # Apple token endpoint

# Fernet encryption key (32-byte url-safe base64)
# Update this with your own secure key to encrypt cached token
cache_key = b'UGSkK7NYDpVILV7EzAqS9D33FDY0j6S-F0Z_c6Yu7XU'
fernet = Fernet(cache_key)

# ------------------------------
# Python version check
# ------------------------------
if sys.version_info < (3, 7):
	logger.error("Python 3.7+ is required.")
	sys.exit(1)
	
# ------------------------------
# Function to create client assertion (JWT)
# ------------------------------
def create_client_assertion() -> str:
	"""
	Generates a JWT signed with the app's private key.
	The JWT is used as client_assertion to obtain access tokens.
	"""
	logger.info("Generating new client assertion (JWT)...")
	now = int(dt.datetime.now(dt.timezone.utc).timestamp())
	exp = now + 86400 * 180  # JWT expires in 180 days (Apple allows long-lived JWTs)
	
	headers = {"alg": algorithm, "kid": key_id}
	payload = {
		"sub": client_id,            # The client ID
		"aud": token_url,            # Token endpoint
		"iat": now,                  # Issued at timestamp
		"exp": exp,                  # Expiration timestamp
		"jti": str(uuid.uuid4()),    # Unique identifier for the JWT
		"iss": client_id             # Issuer is the client ID
	}
	
	try:
		# Load private key from PEM file
		with open(private_key_file, "rt") as f:
			key = ECC.import_key(f.read())
		# Create JWT using ES256
		token = jwt.encode(header=headers, payload=payload, key=key.export_key(format="PEM"))
		return token  # Authlib now returns string, no decode needed
	except Exception as e:
		logger.error(f"Failed to create client assertion: {e}")
		raise
		
# ------------------------------
# Load cached token (encrypted)
# ------------------------------
def load_cache() -> Dict:
	"""
	Load cached access token from encrypted file.
	Returns an empty dict if cache is missing, expired, or corrupted.
	"""
	if not os.path.exists(cache_file):
		logger.info("Cache file not found. Will generate new tokens.")
		return {}
	try:
		with open(cache_file, "rb") as f:
			data = f.read()
		decrypted = fernet.decrypt(data)
		cache = json.loads(decrypted)
		return cache
	except (InvalidToken, json.JSONDecodeError) as e:
		logger.warning(f"Failed to load cache (will regenerate tokens): {e}")
		return {}
	except Exception as e:
		logger.warning(f"Unexpected error loading cache: {e}")
		return {}
	
# ------------------------------
# Save token to cache (encrypted)
# ------------------------------
def save_cache(data: Dict):
	"""
	Save access token and expiration time to encrypted cache file.
	"""
	try:
		encrypted = fernet.encrypt(json.dumps(data).encode("utf-8"))
		with open(cache_file, "wb") as f:
			f.write(encrypted)
		logger.info("Access token saved to cache.")
	except Exception as e:
		logger.error(f"Failed to save cache: {e}")
		
# ------------------------------
# Get access token
# ------------------------------
def get_access_token(force: bool = False, max_retries: int = 3) -> str:
	"""
	Returns a valid access token.
	If force=True or token is expired/missing, generates new JWT and requests token.
	Implements retry for 429 (rate-limiting) and 401 (unauthorized) errors.
	"""
	now = int(dt.datetime.now(dt.timezone.utc).timestamp())
	cache = load_cache()
	token = cache.get("access_token")
	expires_at = cache.get("expires_at", 0)
	# Use cached token if valid and not forced to refresh
	if token and now < expires_at - 60 and not force:
		logger.info("Using cached access token.")
		return token
	
	retries = 0
	while retries < max_retries:
		try:
			logger.info("Requesting new access token using JWT...")
			client_assertion = create_client_assertion()
			resp = requests.post(
				token_url,
				data={
					"grant_type": "client_credentials",
					"client_id": client_id,
					"client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
					"client_assertion": client_assertion,
					"scope": scope
				},
				timeout=10
			)
			
			# Handle rate limit
			if resp.status_code == 429:
				retry_after = int(resp.headers.get("Retry-After", "5"))
				logger.warning(f"Rate limited (429). Retrying after {retry_after}s...")
				time.sleep(retry_after * (2 ** retries))
				retries += 1
				continue
			
			resp.raise_for_status()
			data = resp.json()
			token = data["access_token"]
			expires_at = int(dt.datetime.now(dt.timezone.utc).timestamp()) + data.get("expires_in", 3600)
			save_cache({"access_token": token, "expires_at": expires_at})
			logger.info("Access token obtained successfully.")
			return token
		
		except requests.RequestException as e:
			retries += 1
			logger.warning(f"Request error: {e}. Retry {retries}/{max_retries}")
			time.sleep(2 ** retries)
			
	raise RuntimeError(f"Failed to obtain access token after {max_retries} retries") from e