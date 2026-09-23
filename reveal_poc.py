"""Proof of concept: log in to Tactacam Reveal and read camera data.

Read-only and small on purpose. It makes exactly these calls:
  1. Cognito login (one)
  2. GET /v1/account
  3. GET /v1/cameras
  4. GET /v1/photos?size=1 per camera (latest photo record only, no image download)

It never triggers cameras, changes settings, or requests HD media.
Raw responses are saved to data/poc/ for inspection.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "data" / "poc"

COGNITO_URL = "https://cognito-idp.us-east-1.amazonaws.com/"
COGNITO_CLIENT_ID = "6r9tpojvgvkci5trla0ip14mon"
API_BASE = "https://api.reveal.ishareit.net/v1"
PORTAL = "https://account.revealcellcam.com"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Seconds between API calls so we stay gentle on the shared account.
PAUSE = 1.0


def load_env(path):
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'\"")
    return env


def request(url, *, method="GET", headers=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()[:500]


def login(email, password):
    status, result = request(
        COGNITO_URL,
        method="POST",
        headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
            "User-Agent": BROWSER_UA,
            "Origin": PORTAL,
            "Referer": PORTAL + "/",
        },
        body={
            "AuthFlow": "USER_PASSWORD_AUTH",
            "AuthParameters": {"USERNAME": email, "PASSWORD": password},
            "ClientId": COGNITO_CLIENT_ID,
        },
    )
    if status != 200 or "AuthenticationResult" not in result:
        raise SystemExit(f"Login failed (HTTP {status}): {result}")
    return result["AuthenticationResult"]["AccessToken"]


def api_get(token, path, params=None):
    url = f"{API_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    time.sleep(PAUSE)
    status, result = request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "reveal-user-agent": "RevealWeb/5.4.0",
            "Accept": "application/json",
            "User-Agent": BROWSER_UA,
            "Origin": PORTAL,
            "Referer": PORTAL + "/",
        },
    )
    if status != 200:
        raise SystemExit(f"GET {path} failed (HTTP {status}): {result}")
    return result.get("response", result)


def save(name, payload):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(json.dumps(payload, indent=2))


def main():
    env = load_env(ROOT / ".env")
    token = login(env["EMAIL"], env["PASSWORD"])
    print("Logged in.")

    account = api_get(token, "account")
    save("account", account)

    cameras = api_get(token, "cameras").get("cameras", [])
    save("cameras", cameras)
    print(f"Found {len(cameras)} camera(s).\n")

    latest = {}
    for cam in cameras:
        cam_id = cam.get("cameraId")
        photos = api_get(
            token, "photos",
            {"size": 1, "page": 0, "cameraId": cam_id, "includeWeatherData": "true"},
        ).get("photos", [])
        photo = photos[0] if photos else {}
        latest[cam_id] = photo

        meta = photo.get("metadata", {})
        print(f"- {cam.get('cameraName') or cam.get('name')}  "
              f"[{cam.get('cameraModel') or cam.get('hardwareVersion')}]  "
              f"photos={cam.get('photoCount')}  "
              f"latest={photo.get('photoDateUtc')}  "
              f"battery={meta.get('batteryLevel')}  signal={meta.get('signal')}")

    save("latest_photo_per_camera", latest)

    fields = sorted({k for p in latest.values() for k in p})
    print(f"\nPhoto record fields: {', '.join(fields)}")
    print(f"Raw responses saved to {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
