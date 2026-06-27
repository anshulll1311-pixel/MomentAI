# MomentAI

MomentAI is a production-oriented AI SaaS foundation. This repository currently contains **Phase 1 only**: a FastAPI upload API and a Next.js upload interface. It intentionally contains no AI, analysis, media-processing, or authentication features.

## Stack

- Python 3.14
- FastAPI
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
    services/            File-storage business logic
frontend/                Next.js application
uploads/                 Uploaded source videos (runtime data)
clips/                   Reserved for a later phase
frames/                  Reserved for a later phase
temp/                    Reserved for temporary runtime data
```

## Backend setup

From the repository root:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn backend.app.main:app --reload
```

The API runs at `http://localhost:8000`. Interactive documentation is available at `http://localhost:8000/docs`.

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
  "content_type": "video/mp4"
}
```

Files are streamed to `uploads/` with collision-resistant names. Upload size is bounded by `MOMENTAI_MAX_UPLOAD_SIZE_MB` (500 MB by default). Partial files are deleted if validation or writing fails.

## Environment variables

Copy `.env.example` to `.env` for the backend and to `frontend/.env.local` for the frontend. Update CORS origins before deploying to a non-local environment.

## Verification

```powershell
python -m compileall backend
Set-Location frontend
npm run lint
npm run build
```

## Phase 1 boundaries

This phase does not include Gemini, FFmpeg, Whisper, OpenCV, scene detection, authentication, or any Analyze action. The Analyze button only reflects that an upload has completed; processing belongs to a later phase.
