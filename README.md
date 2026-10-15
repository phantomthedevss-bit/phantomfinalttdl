# 💜 Phantom TT Hub

**Phantom TT Hub** is a lightweight, single-repository video-link extractor with a web frontend and a Flask API. TikTok is the main focus: the backend first tries to retrieve an HD/no-watermark stream, then falls back to `yt-dlp` when needed.

> **Use responsibly:** only download videos you own or have permission to save. Follow each platform's terms and applicable copyright laws. Availability depends on the source platform, privacy settings, region, and whether a link has expired.

## Features

- Extracts available video details from public links.
- TikTok-first HD/no-watermark attempt using TikWM, with `yt-dlp` fallback.
- Supports extraction attempts for Instagram, Facebook, X/Twitter, Pinterest, YouTube, and other links supported by `yt-dlp`.
- Streams downloads through a backend proxy to reduce the chance of saving an expired HTML page as an MP4.
- Shows thumbnail, title, uploader, platform, and recent extraction history.
- Includes `/api/health` for a basic service check.
- Responsive frontend with the footer **“Made with 💜 by Phantom • PhantomTheDev”**.

**Important:** no-watermark extraction is not guaranteed for every site or every TikTok URL. The generic `yt-dlp` fallback does not remove watermarks. Private, restricted, unsupported, or expired content may fail.

## Project structure

The app has four required runtime files, plus this README for documentation:

```text
phantom-tt-hub/
├── index.html
├── vercel.json
├── requirements.txt
└── api/
    └── index.py
```

Keep `api/index.py` inside the `api` directory at the project root. Do not move it or rename the required files. The `vercel.json` and `requirements.txt` files are intentionally kept minimal and use the project's specified configuration and package versions.

## Deploy to Vercel

1. Create a GitHub repository, for example `phantom-tt-hub`.
2. Upload `index.html`, `vercel.json`, and `requirements.txt` to the repository root.
3. Create an `api` folder and upload `index.py` inside it, so its full path is `api/index.py`.
4. Add this `README.md` to the root if you want the project documentation displayed on GitHub.
5. Open [Vercel](https://vercel.com/), import the GitHub repository, and deploy it. Let Vercel detect the Python/Flask app; do not add a custom runtime/build configuration to `vercel.json`.
6. After deployment, open your Vercel project URL. Visit `/api/health` to confirm that the API responds.

Vercel's Flask guide: https://vercel.com/docs/frameworks/backend/flask

## Local development

Use Python 3 and install the pinned dependencies:

```bash
python -m venv .venv
```

Activate the environment:

**Windows PowerShell**

```powershell
.venv\Scripts\Activate.ps1
```

**macOS/Linux**

```bash
source .venv/bin/activate
```

Then install dependencies and use the Vercel CLI to run the project in a Vercel-like local environment:

```bash
pip install -r requirements.txt
npm install -g vercel
vercel dev
```

The Vercel CLI requires Node.js/npm. You can also follow Vercel's current local-development instructions in the official guide linked above.

## API endpoints

### `GET /api/health`

Checks whether the Flask service responds.

Example response:

```json
{
  "success": true,
  "service": "Phantom TT Hub",
  "status": "ok"
}
```

### `POST /api/download`

Extracts information and an available video-stream URL.

Request body (`Content-Type: application/json`):

```json
{
  "url": "https://www.tiktok.com/@creator/video/VIDEO_ID"
}
```

A successful response includes fields such as `success`, `title`, `thumbnail`, `uploader`, `direct_url`, `watermark_url`, `platform`, `is_no_watermark`, and `watermark_removed`. For generic fallback results, the last two fields are `false`; watermarks are not removed by that fallback.

### `GET /api/proxy-download?url=...&filename=...`

Streams the selected video URL through the backend and returns it as an MP4 attachment. If the upstream response is HTML or the stream appears expired/unavailable, the endpoint returns a JSON error instead of deliberately saving that HTML as a video.

The link supplied in `url` is expected to be a public HTTP/HTTPS media URL. Extract a fresh link when a source URL expires.

### `GET /api/history`

Returns recent extractions recorded by the currently running application instance. This is **temporary, best-effort history**, not a permanent database; serverless instances may restart or handle requests separately, so history can disappear or differ between requests.

## Troubleshooting

- **Extraction failed:** verify that the URL is public and valid. Some platforms block automated requests or require sign-in.
- **Link expired:** run Extract again to obtain a fresh media URL, then retry the download.
- **A platform fails while another works:** extraction support changes over time and differs by platform; not every link is supported by `yt-dlp` or the upstream provider.
- **Vercel deployment fails:** check that `api/index.py` is in the correct folder, dependency versions in `requirements.txt` were not changed, and `vercel.json` remains valid JSON.
- **History is empty after a while:** this is expected for in-memory history on serverless infrastructure.

## Tech stack

- Frontend: HTML, CSS, and browser JavaScript
- Backend: Python, Flask, Flask-CORS
- Extraction: TikWM API for the initial TikTok attempt and `yt-dlp` fallback
- Hosting: Vercel

Made with 💜 by Phantom • PhantomTheDev
