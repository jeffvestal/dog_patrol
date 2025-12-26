# Dog Patrol - Deployment Guide

## Managing Multiple GCP Accounts

### Add Your Personal Account

```bash
# Add your personal account (won't logout your work account)
gcloud auth login
```

### List All Your Accounts

```bash
gcloud auth list
```

### Switch Between Accounts (Simple Method)

```bash
# Switch to your personal account
gcloud config set account personal-email@gmail.com

# Switch back to work account
gcloud config set account work-email@company.com
```

### Configuration Profiles (Recommended)

This is cleaner and lets you switch entire contexts (account + project + region):

```bash
# Create a profile for personal
gcloud config configurations create personal

# This automatically activates the personal profile
# Now set it up:
gcloud auth login
gcloud config set project YOUR_PERSONAL_PROJECT_ID
gcloud config set compute/region us-central1

# Create/switch to work profile
gcloud config configurations create work
gcloud config set account work-email@company.com
gcloud config set project YOUR_WORK_PROJECT_ID
```

**Switch Between Profiles:**

```bash
# Switch to personal
gcloud config configurations activate personal

# Switch to work
gcloud config configurations activate work

# List all profiles
gcloud config configurations list
```

---

## Deployment Steps

### 1. Configure GCP Authentication

```bash
# Switch to personal account/profile
gcloud config configurations activate personal

# Or if using simple account switching:
gcloud config set account personal-email@gmail.com

# Set your project
gcloud config set project YOUR_PROJECT_ID

# Verify configuration
gcloud config list
```

### 2. Enable Required APIs

```bash
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable firestore.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
```

### 3. Set Up Firestore

1. Go to [GCP Console Firestore](https://console.cloud.google.com/firestore)
2. Click "Create Database"
3. Select **Native Mode** (important!)
4. Choose a region (e.g., `us-central1`)
5. Once created, manually add your config:
   - Click "Start collection"
   - Collection ID: `auth`
   - Document ID: `strava_config`
   - Add these fields:
     - `refresh_token` (string): Your Strava refresh token
     - `verify_token` (string): Create a secret string (e.g., `my-secret-verify-token-123`)

### 4. Get Your Strava Credentials

If you don't have them yet:
- Go to [Strava API Settings](https://www.strava.com/settings/api)
- Note your `Client ID` and `Client Secret`
- You'll need to generate an initial `refresh_token` through OAuth flow

### 5. Deploy the Function

From the `dog_patrol` directory:

```bash
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
  --set-env-vars="STRAVA_CLIENT_ID=YOUR_CLIENT_ID,STRAVA_CLIENT_SECRET=YOUR_CLIENT_SECRET,TIMEZONE=America/Los_Angeles"
```

**Replace:**
- `YOUR_CLIENT_ID` with your Strava Client ID
- `YOUR_CLIENT_SECRET` with your Strava Client Secret
- `America/Los_Angeles` with your timezone (if different)

### 6. Register Webhook with Strava

After deployment, copy the function URL from the output (looks like `https://us-central1-PROJECT_ID.cloudfunctions.net/strava-webhook`).

Then register it:

```bash
curl -X POST https://www.strava.com/api/v3/push_subscriptions \
  -F client_id=YOUR_CLIENT_ID \
  -F client_secret=YOUR_CLIENT_SECRET \
  -F callback_url=YOUR_FUNCTION_URL \
  -F verify_token=YOUR_VERIFY_TOKEN
```

Use the same `verify_token` you put in Firestore.

---

## Testing & Debugging

### View Logs

```bash
gcloud functions logs read strava-webhook --gen2 --region=us-central1 --limit=50
```

### Follow Logs in Real-time

```bash
gcloud functions logs read strava-webhook --gen2 --region=us-central1 --limit=50 --format=json
```

### Describe Function

```bash
gcloud functions describe strava-webhook --gen2 --region=us-central1
```

### Test the Function

Go for a walk with Strava recording and check if it gets renamed!

---

## Updating the Function

### Update Environment Variables Only

```bash
gcloud functions deploy strava-webhook \
  --update-env-vars TIMEZONE=America/New_York
```

### Redeploy with Code Changes

Just run the full deploy command again from step 5.

### Delete Function

```bash
gcloud functions delete strava-webhook --gen2 --region=us-central1
```

---

## Troubleshooting

### Function not triggering?

1. Check webhook is registered:
   ```bash
   curl -G https://www.strava.com/api/v3/push_subscriptions \
     -d client_id=YOUR_CLIENT_ID \
     -d client_secret=YOUR_CLIENT_SECRET
   ```

2. Check function logs for errors

3. Verify Firestore has correct tokens

### Authentication issues?

- Verify `refresh_token` in Firestore is valid
- Check `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` environment variables
- Tokens may expire - regenerate through Strava OAuth

### Activities not being renamed?

Check filters in logs:
- Is it a "Walk" activity?
- Is `trainer` set to `false` (outdoor)?
- Is the time zone configured correctly?

---

## Switch Back to Work Account

When done:

```bash
gcloud config configurations activate work
```

