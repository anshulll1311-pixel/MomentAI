# MomentAI

MomentAI is a production-oriented AI SaaS foundation. The current **Milestone 3** backend analyzes uploaded videos through FFprobe and FFmpeg, extracts technical metadata, and generates a middle-frame thumbnail. It intentionally contains no AI analysis, transcription, scene detection, or authentication features.

## Stack

- Python 3.14
- FastAPI
- FFmpeg / ffprobe
- Next.js 15
- React 19
- TypeScript
- Tailwind CSS

## Project structure

```text
backend/                 FastAPI application
  app/
    api/routes/          HTTP endpoint handlers
    core/                Environment configuration
    schemas/             API response contracts
    services/            File storage and reusable video metadata logic
frontend/                Next.js application
uploads/                 Uploaded source videos (runtime data)
thumbnails/              Generated middle-frame thumbnails (runtime data)
clips/                   Reserved for a later phase
frames/                  Reserved for a later phase
temp/                    Reserved for temporary runtime data
```

## Backend setup

From the repository root:

```powershell
ffprobe -version
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn backend.app.main:app --reload
```

Run the Uvicorn command from the repository root; backend imports consistently use the `backend.app` package namespace.

The API runs at `http://localhost:8000`. Interactive documentation is available at `http://localhost:8000/docs`. FFmpeg must be installed with `ffprobe` available in `PATH`, or `MOMENTAI_FFPROBE_BINARY` must point to the executable.

## Frontend setup

In a second terminal:

```powershell
Set-Location frontend
npm install
Copy-Item ..\.env.example .env.local
npm run dev
```

The web app runs at `http://localhost:3000`.

## API

### Health check

`GET /api/v1/health`

```json
{
  "status": "ok",
  "service": "MomentAI API",
  "environment": "development"
}
```

### Upload video

`POST /api/v1/uploads` as `multipart/form-data`, using the form field `file`.

Accepted filename extensions: `.mp4`, `.mov`, `.mkv`, and `.avi`.

```json
{
  "status": "success",
  "message": "Video uploaded successfully.",
  "original_filename": "demo.mp4",
  "filename": "demo-<unique-id>.mp4",
  "size_bytes": 123456,
  "content_type": "video/mp4",
  "metadata": {
    "duration_seconds": 12.5,
    "width": 1920,
    "height": 1080,
    "fps": 30.0,
    "video_codec": "h264",
    "audio_codec": "aac",
    "file_size_bytes": 123456
  }
}
```

Files are streamed to `uploads/` with collision-resistant names, then probed without invoking a shell. Upload size is bounded by `MOMENTAI_MAX_UPLOAD_SIZE_MB` (500 MB by default), and metadata probing is bounded by `MOMENTAI_FFPROBE_TIMEOUT_SECONDS` (30 seconds by default). Partial, corrupted, and invalid video files are deleted when processing fails. Videos without an audio stream return `null` for `audio_codec`.

Invalid or corrupted video content returns `422`. A probe timeout returns `504`, and an unavailable ffprobe executable returns `503`.

### Analyze video

`POST /api/v1/analyze` as `multipart/form-data`, using the form field `file`.

Accepted extensions: `.mp4`, `.mov`, `.mkv`, `.avi`, and `.webm`. The endpoint enforces the configured upload limit, validates the media with FFprobe, and generates one JPEG thumbnail at the middle of the video.

```json
{
  "success": true,
  "filename": "demo.mp4",
  "duration": 12.54,
  "width": 1920,
  "height": 1080,
  "fps": 30.0,
  "video_codec": "h264",
  "audio_codec": "aac",
  "bitrate": 4200000,
  "rotation": null,
  "thumbnail": "/thumbnails/demo-<unique-id>.jpg",
  "filesize": 6599250
}
```

Generated thumbnails are served by the backend under `/thumbnails/<filename>`. Videos without audio return `null` for `audio_codec`; videos without rotation metadata return `null` for `rotation`. Empty uploads return `400`, unsupported extensions return `415`, oversized files return `413`, corrupted media returns `422`, unavailable FFmpeg tools return `503`, and processing timeouts return `504`.

## Environment variables

Copy `.env.example` to `.env` for the backend and to `frontend/.env.local` for the frontend. Update CORS origins before deploying to a non-local environment.

## Verification

```powershell
python -m compileall backend
Set-Location frontend
npm run lint
npm run build
```

## Milestone 3 boundaries

This milestone implements deterministic technical video analysis and one thumbnail only. It does not include Gemini, Whisper, OpenCV, bulk frame extraction, scene detection, authentication, or any AI analysis.
