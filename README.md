# 🐕‍🦺 Dog Patrol - Strava Activity Auto-Renamer

A serverless Google Cloud Function that automatically renames your Strava walk activities with fun, time-based names. Never manually rename your dog walks again!

## 🎯 What It Does

When you complete a walk activity on Strava, this function automatically renames it based on the time of day:

- **4:00 AM - 10:59 AM** → "Morning Dog Patrol 🐕‍🦺"
- **11:00 AM - 1:59 PM** → "Lunch Break Sniffari 👃"
- **2:00 PM - 3:59 AM** → "Evening Dog Patrol 🐕‍🦺"

**Filters applied:**
- ✅ Only "Walk" activities (ignores runs, rides, etc.)
- ✅ Only outdoor walks (ignores treadmill activities)
- ✅ Only new activities (triggered on creation, not edits)

## 🏗️ Architecture

```
Strava Webhook → Google Cloud Function → Firestore (token storage)
                       ↓
                  Strava API (rename activity)
```

**Tech Stack:**
- Python 3.11
- Google Cloud Functions (Gen 2, HTTP Trigger)
- Google Cloud Firestore (Native Mode)
- Strava API v3

## 📋 Prerequisites

1. **Google Cloud Platform Account**
   - Active GCP project
   - Billing enabled

2. **Strava API Application**
   - Create an app at https://www.strava.com/settings/api
   - Note your Client ID and Client Secret
   - Generate a refresh token via OAuth flow

3. **Local Tools**
   - [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed
   - Git

## 🚀 Setup & Deployment

### Step 1: Configure GCP

```bash
# Create a personal configuration (if you have multiple GCP accounts)
gcloud config configurations create personal

# Login
gcloud auth login

# Set your project
gcloud config set project YOUR_PROJECT_ID

# Set region
gcloud config set compute/region us-central1
```

### Step 2: Enable Required APIs

```bash
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable firestore.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
```

### Step 3: Set Up Firestore

1. Go to [GCP Console Firestore](https://console.cloud.google.com/firestore)
2. Click "Create Database"
3. Select **Native Mode**
4. Choose a region (e.g., `us-central1`)
5. Create the configuration document:
   - Collection: `auth`
   - Document ID: `strava_config`
   - Fields:
     - `refresh_token` (string): Your Strava refresh token
     - `verify_token` (string): A secret string for webhook verification (e.g., `my-secret-token-123`)

### Step 4: Clone and Deploy

```bash
# Clone the repository
git clone git@github.com:jeffvestal/dog_patrol.git
cd dog_patrol

# Deploy the function
gcloud functions deploy strava-webhook \
  --gen2 \
  --runtime=python311 \
  --region=us-central1 \
  --source=. \
  --entry-point=strava_webhook \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=60s \
  --memory=256MB \
  --set-env-vars="STRAVA_CLIENT_ID=YOUR_CLIENT_ID,STRAVA_CLIENT_SECRET=YOUR_CLIENT_SECRET,TIMEZONE=America/Chicago"
```

**Replace:**
- `YOUR_CLIENT_ID` - Your Strava Client ID
- `YOUR_CLIENT_SECRET` - Your Strava Client Secret
- `America/Chicago` - Your timezone ([see list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones))

### Step 5: Register Webhook with Strava

After deployment, note the function URL from the output (e.g., `https://us-central1-PROJECT.cloudfunctions.net/strava-webhook`).

Register it with Strava:

```bash
curl -X POST https://www.strava.com/api/v3/push_subscriptions \
  -F client_id=YOUR_CLIENT_ID \
  -F client_secret=YOUR_CLIENT_SECRET \
  -F callback_url=YOUR_FUNCTION_URL \
  -F verify_token=YOUR_VERIFY_TOKEN
```

Use the same `verify_token` you stored in Firestore.

**Expected response:**
```json
{"id": 123456}
```

### Step 6: Verify Setup

```bash
# Check your webhook is registered
curl -G https://www.strava.com/api/v3/push_subscriptions \
  -d client_id=YOUR_CLIENT_ID \
  -d client_secret=YOUR_CLIENT_SECRET

# View function logs
gcloud functions logs read strava-webhook --gen2 --region=us-central1 --limit=50
```

## 🧪 Testing

1. Open the Strava app on your phone
2. Start recording a Walk activity
3. Walk for a minute or two
4. Complete and save the activity
5. Check if it was automatically renamed! 🎉

## 📁 Project Structure

```
dog_patrol/
├── main.py                 # Cloud Function code
├── requirements.txt        # Python dependencies
├── README.md              # This file
└── DEPLOYMENT_GUIDE.md    # Detailed deployment instructions
```

## 🔧 Configuration

### Environment Variables

Set during deployment via `--set-env-vars`:

| Variable | Description | Example |
|----------|-------------|---------|
| `STRAVA_CLIENT_ID` | Your Strava App Client ID | `12345` |
| `STRAVA_CLIENT_SECRET` | Your Strava App Client Secret | `abc123...` |
| `TIMEZONE` | Your local timezone | `America/Chicago` |

### Firestore Document

Collection: `auth` / Document: `strava_config`

| Field | Type | Description |
|-------|------|-------------|
| `refresh_token` | string | Strava OAuth refresh token |
| `verify_token` | string | Webhook verification secret |

## 🛠️ Maintenance

### Update Environment Variables

```bash
gcloud functions deploy strava-webhook \
  --gen2 \
  --region=us-central1 \
  --update-env-vars TIMEZONE=America/New_York
```

### Redeploy with Code Changes

```bash
# Make your changes to main.py
git commit -am "Update logic"

# Redeploy
gcloud functions deploy strava-webhook \
  --gen2 \
  --runtime=python311 \
  --region=us-central1 \
  --source=. \
  --entry-point=strava_webhook \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=60s \
  --memory=256MB
```

### View Logs

```bash
# Command line
gcloud functions logs read strava-webhook --gen2 --region=us-central1 --limit=50

# Or in the console
open https://console.cloud.google.com/functions/details/us-central1/strava-webhook
```

### Delete the Function

```bash
gcloud functions delete strava-webhook --gen2 --region=us-central1
```

## 🐛 Troubleshooting

### Activities not being renamed?

1. **Check webhook is registered:**
   ```bash
   curl -G https://www.strava.com/api/v3/push_subscriptions \
     -d client_id=YOUR_CLIENT_ID \
     -d client_secret=YOUR_CLIENT_SECRET
   ```

2. **Check function logs for errors:**
   ```bash
   gcloud functions logs read strava-webhook --gen2 --region=us-central1
   ```

3. **Verify Firestore has correct tokens:**
   - Go to Firestore console
   - Check `auth/strava_config` document
   - Ensure `refresh_token` and `verify_token` are set

4. **Common issues:**
   - Activity must be type "Walk" (not Run, Ride, etc.)
   - Activity must be outdoor (`trainer: false`)
   - Webhook only triggers on NEW activities (not edits)
   - Refresh token may have expired (regenerate via OAuth)

### Authentication errors?

The `refresh_token` may have expired. Regenerate it through Strava's OAuth flow and update Firestore.

### Webhook verification failing?

Ensure the `verify_token` in Firestore matches exactly what you used when registering the webhook with Strava.

## 🔐 Security Notes

- `--allow-unauthenticated` is required because Strava webhooks can't use GCP IAM auth
- Store secrets (Client Secret, tokens) in environment variables and Firestore
- Never commit credentials to git
- Refresh tokens are automatically updated in Firestore when they change

## 📝 How It Works

1. **Webhook Verification (GET):**
   - Strava sends a verification challenge
   - Function validates `verify_token` against Firestore
   - Returns challenge to confirm webhook

2. **Event Processing (POST):**
   - Strava sends webhook event for new activity
   - Function filters for "create" events only
   - Fetches activity details via Strava API
   - Checks if it's an outdoor Walk activity
   - Gets fresh access token using refresh token
   - Determines new name based on start time
   - Updates activity name via Strava API
   - Logs old and new names

3. **Token Refresh:**
   - Automatically refreshes Strava access token on each run
   - Updates Firestore if refresh token changes
   - Ensures persistent authentication

## 🤝 Contributing

Feel free to open issues or submit PRs! Some ideas:
- Add more activity types (Run, Ride, etc.)
- Customize naming schemes
- Add weather integration
- Support multiple time zones per activity location

## 📄 License

MIT License - feel free to use and modify!

## 🙏 Acknowledgments

- Built for dog lovers who walk a lot 🐕
- Powered by [Strava API](https://developers.strava.com/)
- Deployed on [Google Cloud Functions](https://cloud.google.com/functions)

---

**Happy walking! 🐕‍🦺🚶‍♂️**

