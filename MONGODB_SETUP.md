# MongoDB Local Setup - Eagle 3D Streaming Analytics Hub

## Install (macOS)

    brew tap mongodb/brew
    brew install mongodb-community@7.0

## Start / Stop

    brew services start   mongodb-community@7.0
    brew services stop    mongodb-community@7.0
    brew services restart mongodb-community@7.0
    brew services list | grep mongodb

## Verify connection

    cd ~/eagle3d-kpi-automation
    source venv/bin/activate
    python3 -c "from mongo_client import get_mongo_status; import json; print(json.dumps(get_mongo_status(), indent=2))"

Expected:

    {
      "connected": true,
      "db": "eagle3d",
      "collections": 45,
      "daily_kpis_count": 904
    }

## Backup

    mongodump --db eagle3d --archive=./backups/eagle3d_$(date +%Y%m%d).gz --gzip

## Restore

    mongorestore --archive=./backups/eagle3d_20260101.gz --gzip

## Collections

- signups                  - Verified sign-ups
- uploads                  - First-upload events
- payments                 - Paying customers
- daily_kpis               - One row per day
- manual_overrides         - Human ACCEPTED/REJECTED
- linkedin_posts           - Latest per post
- linkedin_posts_daily     - Per-post per-day history
- youtube_channel          - Channel snapshot
- youtube_videos           - Per-video metrics
- customer_success_master  - Raw CS sheet rows
- customer_success_enriched- Per-email joined
- access_control           - Email allow-list
- access_log               - Every login attempt
- pipeline_runs            - Per-stage pass/fail

## GUI (optional)

- MongoDB Compass: https://www.mongodb.com/products/compass
- Connect: mongodb://localhost:27017, Database: eagle3d

## Troubleshooting

MongoDB not reachable:
    brew services restart mongodb-community@7.0
    sleep 3
    python3 verify_mongo.py

Port 27017 in use:
    lsof -i :27017
