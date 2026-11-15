# Deploying FieldWise

FieldWise is one Python web service plus a folder of downloaded NASA data. Any host that runs a Docker container with a **persistent disk** works: Render, Railway, Fly.io, Google Cloud Run (with a mounted volume), or your own server.

## 1. Earth Engine on a server (service account)

A server can't use `earthengine authenticate`. Use a service account instead:

1. Google Cloud Console → your Earth Engine project → **IAM & Admin → Service accounts → Create**. Name it `fieldwise`.
2. Give it the role **Earth Engine Resource Viewer** (and **Service Usage Consumer**).
3. **Keys → Add key → JSON**. Download the file. Keep it secret.
4. Register the service account for Earth Engine: https://code.earthengine.google.com/register (choose your project, noncommercial).
5. On the host, store the JSON as a secret file and set:
   ```
   GEE_PROJECT=your-project-id
   GEE_SERVICE_ACCOUNT=fieldwise@your-project-id.iam.gserviceaccount.com
   GEE_KEY_FILE=/secrets/gee-key.json
   ```

## 2. Environment variables

| Variable | Value |
|---|---|
| `GEE_PROJECT`, `GEE_SERVICE_ACCOUNT`, `GEE_KEY_FILE` | from step 1 |
| `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` | your NASA Earthdata login (for ECOSTRESS) |
| `FIELDWISE_DATA_DIR` | `/data` (the persistent disk) |
| `FIELDWISE_DEMO` | `0` (always, in production) |
| `ANTHROPIC_API_KEY` | optional |
| `FIELDWISE_FETCH_LIMIT_PER_HOUR` | new fields per visitor per hour (default 6) |
| `FIELDWISE_MAX_CONCURRENT_FETCHES` | downloads at the same time (default 2) |

## 3. Build and run

```bash
docker build -t fieldwise .
docker run -p 8000:8000 --env-file .env -v fieldwise-data:/data -v $PWD/secrets:/secrets:ro fieldwise
```

Most hosts set `PORT` themselves; the container uses it automatically. Point the health check at `/api/health`.

**Render example:** New → Web Service → your repo → Docker. Add a Disk mounted at `/data` (5 GB is plenty for hundreds of fields). Add the environment variables and a Secret File `gee-key.json` (Render mounts it at `/etc/secrets/gee-key.json`, so set `GEE_KEY_FILE` to that path).

## 4. After the first deploy

```bash
# inside the running container (host's shell / console)
python scripts/check_setup.py
python scripts/build_cache.py --all        # reference fields with real data
```

Run `python scripts/build_cache.py --refresh` daily (a cron job or the host's scheduler) to collect finished ECOSTRESS requests. The app also checks by itself when a field is opened.

## 5. Notes for scale

- Run **one worker per instance**: download jobs and their progress live in memory. To scale out, put a shared disk under `/data` and route `/api/fields` + `/api/jobs` to one instance, or move jobs to a queue (Redis/RQ).
- Map tiles: OpenStreetMap and Esri limit heavy use. For many users, switch `baseLayers()` in `frontend/app.js` to a provider with an API key (MapTiler, Mapbox, Stadia). NASA GIBS tiles have no key.
- Place search uses OpenStreetMap Nominatim (max 1 request/second, fair use). For heavy use, host your own or use a paid geocoder.
- Back up `/data`. It holds every farmer field downloaded so far.
- HTTPS is required for "Use my location", installing the app and offline mode. All the hosts above provide it.
