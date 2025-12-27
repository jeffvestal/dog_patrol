import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

import pytz
import requests
from google.cloud import firestore
from functions_framework import http

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Firestore client
db = firestore.Client()

# Constants
STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
FIRESTORE_COLLECTION = "auth"
FIRESTORE_DOCUMENT = "strava_config"

# Environment variables
STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
TIMEZONE = os.environ.get("TIMEZONE", "America/Los_Angeles")


def get_firestore_config() -> Dict[str, Any]:
    """Retrieve configuration from Firestore."""
    doc_ref = db.collection(FIRESTORE_COLLECTION).document(FIRESTORE_DOCUMENT)
    doc = doc_ref.get()
    if not doc.exists:
        raise ValueError(f"Firestore document {FIRESTORE_COLLECTION}/{FIRESTORE_DOCUMENT} does not exist")
    return doc.to_dict()


def update_firestore_config(field: str, value: str) -> None:
    """Update a field in the Firestore configuration."""
    doc_ref = db.collection(FIRESTORE_COLLECTION).document(FIRESTORE_DOCUMENT)
    doc_ref.update({field: value})
    logger.info(f"Updated {field} in Firestore")


def get_access_token() -> str:
    """
    Get a valid access token by refreshing using the stored refresh_token.
    Updates Firestore if a new refresh_token is returned.
    """
    config = get_firestore_config()
    refresh_token = config.get("refresh_token")
    
    if not refresh_token:
        raise ValueError("refresh_token not found in Firestore")
    
    if not STRAVA_CLIENT_ID or not STRAVA_CLIENT_SECRET:
        raise ValueError("STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET must be set")
    
    # Refresh the access token
    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    
    if response.status_code != 200:
        logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
        raise Exception(f"Failed to refresh token: {response.status_code}")
    
    token_data = response.json()
    new_access_token = token_data.get("access_token")
    new_refresh_token = token_data.get("refresh_token")
    
    # Update Firestore if refresh_token changed
    if new_refresh_token and new_refresh_token != refresh_token:
        update_firestore_config("refresh_token", new_refresh_token)
        logger.info("Updated refresh_token in Firestore")
    
    return new_access_token


def get_activity_details(activity_id: int, access_token: str) -> Dict[str, Any]:
    """Fetch activity details from Strava API."""
    url = f"{STRAVA_API_BASE}/activities/{activity_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    response = requests.get(url, headers=headers, timeout=10)
    
    if response.status_code != 200:
        logger.error(f"Failed to fetch activity {activity_id}: {response.status_code} - {response.text}")
        raise Exception(f"Failed to fetch activity: {response.status_code}")
    
    return response.json()


def determine_activity_name(start_date_local: str) -> str:
    """
    Determine activity name based on time of day.
    
    Time ranges:
    - 04:00 - 10:59: Morning Shakeout 🐕‍🦺
    - 11:00 - 13:59: Lunch Break Sniffari 👃🐕‍🦺
    - 14:00 - 03:59: Evening Patrol 🐕‍🦺
    """
    # Parse the ISO format datetime string from Strava
    # start_date_local is ALREADY in local time, no conversion needed
    # Example: "2024-12-26T07:30:00Z"
    dt = datetime.fromisoformat(start_date_local.replace("Z", ""))
    hour = dt.hour
    
    # Determine time range
    if 4 <= hour < 11:
        return "Morning Shakeout 🐕‍🦺"
    elif 11 <= hour < 14:
        return "Lunch Break Sniffari 👃🐕‍🦺"
    else:  # 14:00 - 03:59 (14-23 and 0-3)
        return "Evening Patrol 🐕‍🦺"


def update_activity_name(activity_id: int, new_name: str, access_token: str) -> None:
    """Update the activity name on Strava."""
    url = f"{STRAVA_API_BASE}/activities/{activity_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    data = {"name": new_name}
    
    response = requests.put(url, headers=headers, json=data, timeout=10)
    
    if response.status_code != 200:
        logger.error(f"Failed to update activity {activity_id}: {response.status_code} - {response.text}")
        raise Exception(f"Failed to update activity: {response.status_code}")
    
    logger.info(f"Successfully renamed activity {activity_id} to '{new_name}'")


@http
def strava_webhook(request):
    """
    Cloud Function entry point for Strava webhook.
    Handles both GET (verification) and POST (event) requests.
    """
    try:
        # Handle GET request (webhook verification)
        if request.method == "GET":
            return handle_webhook_verification(request)
        
        # Handle POST request (event processing)
        elif request.method == "POST":
            return handle_event_processing(request)
        
        else:
            logger.warning(f"Unsupported method: {request.method}")
            return ("Method not allowed", 405)
    
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        # Always return 200 to prevent Strava from retrying
        return ("OK", 200)


def handle_webhook_verification(request) -> tuple:
    """Handle Strava webhook verification (GET request)."""
    hub_mode = request.args.get("hub.mode")
    hub_challenge = request.args.get("hub.challenge")
    hub_verify_token = request.args.get("hub.verify_token")
    
    logger.info(f"Webhook verification request: mode={hub_mode}, challenge={hub_challenge}")
    
    if not all([hub_mode, hub_challenge, hub_verify_token]):
        logger.warning("Missing required verification parameters")
        return ("Bad Request", 400)
    
    # Get verify_token from Firestore
    try:
        config = get_firestore_config()
        stored_verify_token = config.get("verify_token")
        
        if not stored_verify_token:
            logger.error("verify_token not found in Firestore")
            return ("Internal Server Error", 500)
        
        # Verify token matches
        if hub_verify_token != stored_verify_token:
            logger.warning(f"Token mismatch: received={hub_verify_token}, stored={stored_verify_token}")
            return ("Forbidden", 403)
        
        # Return challenge
        response_data = {"hub.challenge": hub_challenge}
        logger.info("Webhook verification successful")
        return (json.dumps(response_data), 200, {"Content-Type": "application/json"})
    
    except Exception as e:
        logger.error(f"Error during webhook verification: {str(e)}", exc_info=True)
        return ("Internal Server Error", 500)


def handle_event_processing(request) -> tuple:
    """Handle Strava event processing (POST request)."""
    try:
        # Parse incoming JSON
        event_data = request.get_json(silent=True)
        if not event_data:
            logger.warning("No JSON data in POST request")
            return ("OK", 200)
        
        logger.info(f"Received event: {json.dumps(event_data)}")
        
        # Filter 1: Check aspect_type is "create"
        aspect_type = event_data.get("aspect_type")
        if aspect_type != "create":
            logger.info(f"Skipping event: aspect_type={aspect_type} (not 'create')")
            return ("OK", 200)
        
        # Get activity ID
        object_id = event_data.get("object_id")
        if not object_id:
            logger.warning("Missing object_id in event data")
            return ("OK", 200)
        
        logger.info(f"Processing activity creation: {object_id}")
        
        # Get access token
        try:
            access_token = get_access_token()
        except Exception as e:
            logger.error(f"Failed to get access token: {str(e)}")
            return ("OK", 200)
        
        # Filter 2: Fetch activity details
        try:
            activity = get_activity_details(object_id, access_token)
        except Exception as e:
            logger.error(f"Failed to fetch activity details: {str(e)}")
            return ("OK", 200)
        
        # Filter 3: Check activity type is "Walk"
        activity_type = activity.get("type")
        if activity_type != "Walk":
            logger.info(f"Skipping activity {object_id}: type={activity_type} (not 'Walk')")
            return ("OK", 200)
        
        # Filter 4: Check trainer is False (outdoor only)
        trainer = activity.get("trainer", False)
        if trainer:
            logger.info(f"Skipping activity {object_id}: trainer=True (indoor activity)")
            return ("OK", 200)
        
        # Get current name for logging
        old_name = activity.get("name", "Unnamed")
        
        # Determine new name based on time
        start_date_local = activity.get("start_date_local")
        if not start_date_local:
            logger.warning(f"Activity {object_id} missing start_date_local")
            return ("OK", 200)
        
        new_name = determine_activity_name(start_date_local)
        
        # Update activity name
        try:
            update_activity_name(object_id, new_name, access_token)
            logger.info(f"Renamed activity {object_id}: '{old_name}' -> '{new_name}'")
        except Exception as e:
            logger.error(f"Failed to update activity name: {str(e)}")
            return ("OK", 200)
        
        return ("OK", 200)
    
    except Exception as e:
        logger.error(f"Error processing event: {str(e)}", exc_info=True)
        return ("OK", 200)

