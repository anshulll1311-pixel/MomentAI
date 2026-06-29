export interface UploadResponse {
  status: "success";
  message: string;
  original_filename: string;
  filename: string;
  size_bytes: number;
  content_type: string | null;
  metadata: {
    duration_seconds: number;
    width: number;
    height: number;
    fps: number;
    video_codec: string;
    audio_codec: string | null;
    file_size_bytes: number;
  };
}

export interface AnalysisResponse {
  success: true;
  filename: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  video_codec: string;
  audio_codec: string | null;
  bitrate: number;
  rotation: number | null;
  thumbnail: string;
  filesize: number;
}

export type ExportPreset =
  | "standard"
  | "preview"
  | "high_quality"
  | "youtube_shorts"
  | "tiktok";

export interface ExportOptions {
  preset: ExportPreset;
  topK: number;
  paddingBeforeSeconds: number;
  paddingAfterSeconds: number;
}

export interface ExportDiagnostic {
  stage: string;
  status: string;
  message: string;
}

export interface ExportClip {
  clip_id: string;
  rank: number;
  start: number;
  end: number;
  duration: number;
  score: number;
  size_bytes: number;
  sha256: string;
  download_url: string;
}

export interface ExportResponse {
  success: true;
  export_id: string;
  profile: string;
  preset: ExportPreset;
  clip_count: number;
  clips: ExportClip[];
  manifest_url: string;
  package_url: string;
  package_sha256: string;
  diagnostics: ExportDiagnostic[];
}

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export async function uploadVideo(file: File): Promise<UploadResponse> {
  const body = new FormData();
  body.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/v1/uploads`, {
    method: "POST",
    body,
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorBody?.detail ?? "The upload could not be completed.");
  }

  return (await response.json()) as UploadResponse;
}

export async function analyzeVideo(file: File): Promise<AnalysisResponse> {
  const body = new FormData();
  body.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/v1/analyze`, {
    method: "POST",
    body,
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorBody?.detail ?? "The video could not be analyzed.");
  }

  return (await response.json()) as AnalysisResponse;
}

export async function exportClips(
  file: File,
  options: ExportOptions,
): Promise<ExportResponse> {
  const body = new FormData();
  body.append("file", file);
  body.append("preset", options.preset);
  body.append("top_k", String(options.topK));
  body.append("padding_before_seconds", String(options.paddingBeforeSeconds));
  body.append("padding_after_seconds", String(options.paddingAfterSeconds));

  const response = await fetch(`${API_BASE_URL}/api/v1/exports`, {
    method: "POST",
    body,
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorBody?.detail ?? "The clips could not be exported.");
  }

  return (await response.json()) as ExportResponse;
}

export function backendAssetUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}
