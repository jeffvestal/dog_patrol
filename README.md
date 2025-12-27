# 🐕‍🦺 Dog Patrol - Strava Activity Auto-Renamer

Automatically rename your Strava walk activities with fun, time-based names via a serverless Google Cloud Function.

## 🎯 What It Does

Automatically renames outdoor walk activities based on time of day:

- **4:00 AM - 10:59 AM** → "Morning Shakeout 🐕‍🦺"
- **11:00 AM - 1:59 PM** → "Lunch Break Sniffari 👃🐕‍🦺"
- **2:00 PM - 3:59 AM** → "Evening Patrol 🐕‍🦺"

**Filters:** Only outdoor Walk activities (no runs, rides, or treadmill)

## 🏗️ Architecture

```
Strava Webhook → Cloud Function → Firestore (tokens)
                      ↓
                 Strava API (rename)
```

**Stack:** Python 3.11, Google Cloud Functions (Gen 2), Firestore, Strava API v3

## 🚀 Quick Start

### Prerequisites

- GCP account with billing enabled
- [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed
- Strava API application ([create here](https://www.strava.com/settings/api))

### Deploy

```bash
# Clone
git clone git@github.com:jeffvestal/dog_patrol.git
cd dog_patrol

# Configure GCP (if multiple accounts, use configurations)
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Enable APIs
gcloud services enable cloudfunctions.googleapis.com firestore.googleapis.com cloudbuild.googleapis.com run.googleapis.com

# Set up Firestore: Create database in Native Mode, then create:
# Collection: auth, Document: strava_config
# Fields: refresh_token (your Strava token), verify_token (webhook secret)

# Deploy
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
  --set-env-vars="STRAVA_CLIENT_ID=YOUR_ID,STRAVA_CLIENT_SECRET=YOUR_SECRET,TIMEZONE=America/Chicago"

# Register webhook with Strava
curl -X POST https://www.strava.com/api/v3/push_subscriptions \
  -F client_id=YOUR_CLIENT_ID \
  -F client_secret=YOUR_CLIENT_SECRET \
  -F callback_url=YOUR_FUNCTION_URL \
  -F verify_token=YOUR_VERIFY_TOKEN
```

**For detailed setup instructions, see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)**

## 🔄 Backfilling Past Activities

Rename all your past walks in one go:

```bash
# Setup (first time only)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure Application Default Credentials
gcloud auth application-default login

# Set credentials
export STRAVA_CLIENT_ID=YOUR_ID
export STRAVA_CLIENT_SECRET=YOUR_SECRET

# Preview changes (dry run)
python backfill_activities.py --dry-run --months 6

# Actually rename them
python backfill_activities.py --months 6

# Just last 30 days
python backfill_activities.py --days 30
```

**Features:**
- ✅ Smart rate limit handling (waits for Strava's 15-min reset windows)
- ✅ Detailed progress logging with rate limit info
- ✅ Skips activities that already have the correct name
- ✅ Dry-run mode to preview changes
- ✅ Safe to re-run multiple times

## 📁 Project Files

```
dog_patrol/
├── main.py                   # Cloud Function (webhook handler)
├── backfill_activities.py    # Local script to rename past activities
├── requirements.txt          # Python dependencies
├── README.md                 # This file
└── DEPLOYMENT_GUIDE.md       # Detailed setup & troubleshooting
```

## 🔧 Configuration

### Environment Variables (Cloud Function)

| Variable | Description | Example |
|----------|-------------|---------|
| `STRAVA_CLIENT_ID` | Strava App Client ID | `57804` |
| `STRAVA_CLIENT_SECRET` | Strava App Client Secret | `abc123...` |
| `TIMEZONE` | Your timezone ([list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)) | `America/Chicago` |

### Firestore (`auth/strava_config`)

| Field | Type | Description |
|-------|------|-------------|
| `refresh_token` | string | Strava OAuth refresh token (auto-updated) |
| `verify_token` | string | Webhook verification secret |

## 🛠️ Maintenance

**Update timezone:**
```bash
gcloud functions deploy strava-webhook --gen2 --region=us-central1 --update-env-vars TIMEZONE=America/New_York
```

**View logs:**
```bash
gcloud functions logs read strava-webhook --gen2 --region=us-central1 --limit=50
```

**Redeploy after code changes:**
```bash
git commit -am "Update logic"
gcloud functions deploy strava-webhook --gen2 --runtime=python311 --region=us-central1 --source=. --entry-point=strava_webhook --trigger-http --allow-unauthenticated --timeout=60s --memory=256MB
```

## 🐛 Troubleshooting

**Activities not renaming?**
- Check webhook is registered: `curl -G https://www.strava.com/api/v3/push_subscriptions -d client_id=YOUR_ID -d client_secret=YOUR_SECRET`
- View logs: `gcloud functions logs read strava-webhook --gen2 --region=us-central1`
- Verify Firestore has valid `refresh_token` and `verify_token`
- Only works for outdoor Walk activities (not runs, rides, or treadmill)

**Backfill script errors?**
- Run `gcloud auth application-default login` to set up local credentials
- Set `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` environment variables
- Ensure your refresh token has `activity:read_all` and `activity:write` scopes

**Rate limited during backfill?**
- Script automatically waits for Strava's 15-minute reset windows (100 requests per 15 min for non-upload endpoints)
- Check the logs for detailed rate limit info

**See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for more troubleshooting**

## 🔐 Security

- `--allow-unauthenticated` required (Strava webhooks can't use GCP IAM)
- Credentials stored in GCP environment variables and Firestore
- Never commit secrets to git (`.gitignore` configured)
- Refresh tokens auto-update in Firestore

## 📄 License

MIT License - use and modify freely!

---

**Built for dog lovers who walk a lot 🐕 | Powered by [Strava API](https://developers.strava.com/) | Deployed on [Google Cloud](https://cloud.google.com/functions)**
