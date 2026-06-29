"use client";

import { ChangeEvent, DragEvent, useRef, useState } from "react";

import { ExportPanel } from "@/components/export-panel";
import { analyzeVideo, backendAssetUrl, uploadVideo } from "@/lib/api";
import type { AnalysisResponse } from "@/lib/api";

const ACCEPTED_EXTENSIONS = ["mp4", "mov", "mkv", "avi", "webm"] as const;
type UploadState = "idle" | "uploading" | "uploaded" | "error";
type AnalysisState = "idle" | "analyzing" | "complete" | "error";

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isAcceptedFile(file: File): boolean {
  const extension = file.name.split(".").pop()?.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((allowed) => allowed === extension);
}

export function UploadPanel() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [state, setState] = useState<UploadState>("idle");
  const [analysisState, setAnalysisState] = useState<AnalysisState>("idle");
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [message, setMessage] = useState<string>("");

  function selectFile(nextFile: File | undefined) {
    if (!nextFile) return;
    if (!isAcceptedFile(nextFile)) {
      setFile(null);
      setState("error");
      setAnalysisState("idle");
      setAnalysis(null);
      setMessage("Choose an MP4, MOV, MKV, AVI, or WebM video.");
      return;
    }

    setFile(nextFile);
    setState("idle");
    setAnalysisState("idle");
    setAnalysis(null);
    setMessage("");
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    selectFile(event.target.files?.[0]);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    selectFile(event.dataTransfer.files[0]);
  }

  async function handleUpload() {
    if (!file || state === "uploading") return;
    setState("uploading");
    setMessage("");

    try {
      const result = await uploadVideo(file);
      setState("uploaded");
      setMessage(`${result.original_filename} uploaded successfully.`);
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "Upload failed. Please try again.");
    }
  }

  async function handleAnalyze() {
    if (!file || state !== "uploaded" || analysisState === "analyzing") return;
    setAnalysisState("analyzing");
    setAnalysis(null);
    setMessage("");

    try {
      const result = await analyzeVideo(file);
      setAnalysis(result);
      setAnalysisState("complete");
      setMessage(`${result.filename} analyzed successfully.`);
    } catch (error) {
      setAnalysisState("error");
      setMessage(error instanceof Error ? error.message : "Analysis failed. Please try again.");
    }
  }

  return (
    <div className="rounded-3xl border border-white/10 bg-panel/90 p-3 shadow-2xl shadow-black/30 backdrop-blur sm:p-5">
      <div
        onDragEnter={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={`group relative grid min-h-64 place-items-center rounded-2xl border border-dashed px-6 py-10 transition sm:min-h-72 ${
          isDragging
            ? "border-violet-400 bg-violet-500/10"
            : "border-white/15 bg-white/[0.025] hover:border-violet-400/50 hover:bg-violet-500/[0.04]"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".mp4,.mov,.mkv,.avi,.webm,video/mp4,video/quicktime,video/x-matroska,video/x-msvideo,video/webm"
          onChange={handleInputChange}
          className="sr-only"
        />

        <div className="flex flex-col items-center">
          <span className="mb-5 grid h-14 w-14 place-items-center rounded-2xl border border-white/10 bg-white/[0.05] text-zinc-300 transition group-hover:border-violet-400/30 group-hover:text-violet-300">
            <UploadIcon />
          </span>

          {file ? (
            <>
              <p className="max-w-md truncate text-base font-medium text-white">{file.name}</p>
              <p className="mt-1 text-sm text-zinc-500">{formatBytes(file.size)}</p>
            </>
          ) : (
            <>
              <p className="text-base font-medium text-zinc-200">Drag &amp; drop your video here</p>
              <p className="mt-2 text-sm text-zinc-500">MP4, MOV, MKV, AVI, or WebM</p>
            </>
          )}

          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="mt-5 rounded-xl border border-white/10 bg-white/[0.06] px-4 py-2 text-sm font-medium text-zinc-200 transition hover:border-white/20 hover:bg-white/10"
          >
            Choose File
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={handleUpload}
          disabled={!file || state === "uploading" || state === "uploaded"}
          className="rounded-xl bg-violet-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-950/30 transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500 disabled:shadow-none"
        >
          {state === "uploading" ? "Uploading…" : state === "uploaded" ? "Uploaded" : "Upload"}
        </button>
        <button
          type="button"
          onClick={handleAnalyze}
          disabled={state !== "uploaded" || analysisState === "analyzing"}
          title={state === "uploaded" ? "Analyze video" : "Upload a video first"}
          className="rounded-xl border border-white/10 bg-white/[0.04] px-5 py-3 text-sm font-semibold text-zinc-200 transition hover:border-violet-400/40 hover:bg-violet-500/10 disabled:cursor-not-allowed disabled:border-white/5 disabled:bg-transparent disabled:text-zinc-600"
        >
          {analysisState === "analyzing" ? "Analyzing…" : "Analyze"}
        </button>
      </div>

      <div className="min-h-7 pt-3 text-left" aria-live="polite">
        {message && (
          <p className={`text-sm ${state === "error" || analysisState === "error" ? "text-rose-400" : "text-emerald-400"}`}>
            {message}
          </p>
        )}
      </div>

      {analysis && (
        <>
          <div className="mt-2 overflow-hidden rounded-2xl border border-white/10 bg-white/[0.025] text-left">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={backendAssetUrl(analysis.thumbnail)}
              alt={`Middle-frame thumbnail for ${analysis.filename}`}
              className="aspect-video w-full bg-black object-cover"
            />
            <dl className="grid grid-cols-2 gap-x-5 gap-y-4 p-5 text-sm sm:grid-cols-3">
              <AnalysisItem label="Filename" value={analysis.filename} />
              <AnalysisItem label="Duration" value={`${analysis.duration.toFixed(2)} s`} />
              <AnalysisItem label="Resolution" value={`${analysis.width} × ${analysis.height}`} />
              <AnalysisItem label="FPS" value={analysis.fps.toFixed(2)} />
              <AnalysisItem
                label="Codecs"
                value={`${analysis.video_codec.toUpperCase()} / ${analysis.audio_codec?.toUpperCase() ?? "No audio"}`}
              />
              <AnalysisItem label="Bitrate" value={`${(analysis.bitrate / 1_000_000).toFixed(2)} Mbps`} />
              {analysis.rotation !== null && (
                <AnalysisItem label="Rotation" value={`${analysis.rotation}°`} />
              )}
            </dl>
          </div>
          {file && <ExportPanel file={file} />}
        </>
      )}
    </div>
  );
}

function AnalysisItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wide text-zinc-500">{label}</dt>
      <dd className="mt-1 truncate font-medium text-zinc-200" title={value}>
        {value}
      </dd>
    </div>
  );
}

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M12 15V3m0 0L7.5 7.5M12 3l4.5 4.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 13v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5" strokeLinecap="round" />
    </svg>
  );
}
