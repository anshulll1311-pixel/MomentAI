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
