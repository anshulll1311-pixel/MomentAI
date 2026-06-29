"use client";

import { useState } from "react";

import {
  backendAssetUrl,
  exportClips,
  type ExportPreset,
  type ExportResponse,
} from "@/lib/api";

type ExportState = "idle" | "exporting" | "complete" | "error";

const PRESETS: Array<{ value: ExportPreset; label: string; detail: string }> = [
  { value: "standard", label: "Standard", detail: "Balanced quality" },
  { value: "preview", label: "Preview", detail: "Fast, lightweight" },
  { value: "high_quality", label: "High quality", detail: "Slower, sharper" },
  { value: "youtube_shorts", label: "YouTube Shorts", detail: "Vertical 1080 × 1920" },
  { value: "tiktok", label: "TikTok", detail: "Vertical 1080 × 1920" },
];

export function ExportPanel({ file }: { file: File }) {
  const [preset, setPreset] = useState<ExportPreset>("standard");
  const [topK, setTopK] = useState(3);
  const [paddingBefore, setPaddingBefore] = useState(0);
  const [paddingAfter, setPaddingAfter] = useState(0);
  const [state, setState] = useState<ExportState>("idle");
  const [result, setResult] = useState<ExportResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");

  async function handleExport() {
    if (state === "exporting") return;
    setState("exporting");
    setResult(null);
    setErrorMessage("");

    try {
      const exported = await exportClips(file, {
        preset,
        topK,
        paddingBeforeSeconds: paddingBefore,
        paddingAfterSeconds: paddingAfter,
      });
      setResult(exported);
      setState("complete");
    } catch (error) {
      setState("error");
      setErrorMessage(error instanceof Error ? error.message : "Export failed. Please try again.");
    }
  }

  return (
    <section className="mt-5 rounded-2xl border border-violet-400/15 bg-violet-500/[0.035] p-5 text-left">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-violet-300">Export Engine</p>
          <h2 className="mt-1 text-lg font-semibold text-white">Export your best moments</h2>
          <p className="mt-1 max-w-xl text-sm leading-6 text-zinc-400">
            MomentAI will rank the video and create downloadable clips using your export settings.
          </p>
        </div>
        {result && (
          <span className="w-fit rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-300">
            {result.clip_count} {result.clip_count === 1 ? "clip" : "clips"} ready
          </span>
        )}
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="text-sm text-zinc-300">
          <span className="mb-2 block text-xs font-medium uppercase tracking-wide text-zinc-500">
            Export preset
          </span>
          <select
            value={preset}
            onChange={(event) => setPreset(event.target.value as ExportPreset)}
            disabled={state === "exporting"}
            className="w-full rounded-xl border border-white/10 bg-[#11131c] px-3 py-2.5 text-sm text-zinc-200 transition hover:border-white/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {PRESETS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label} — {item.detail}
              </option>
            ))}
          </select>
        </label>

        <NumberField label="Top moments" value={topK} min={1} max={20} step={1} disabled={state === "exporting"} onChange={setTopK} />
        <NumberField label="Padding before" suffix="seconds" value={paddingBefore} min={0} max={30} step={0.5} disabled={state === "exporting"} onChange={setPaddingBefore} />
        <NumberField label="Padding after" suffix="seconds" value={paddingAfter} min={0} max={30} step={0.5} disabled={state === "exporting"} onChange={setPaddingAfter} />
      </div>

      <button
        type="button"
        onClick={handleExport}
        disabled={state === "exporting"}
        className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-950/30 transition hover:bg-violet-500 disabled:cursor-wait disabled:bg-violet-900 disabled:text-violet-300 sm:w-auto"
      >
        {state === "exporting" ? (
          <>
            <LoadingSpinner />
            Exporting clips…
          </>
        ) : (
          <>
            <ExportIcon />
            {result ? "Export Again" : "Export Clips"}
          </>
        )}
      </button>

      <div className="mt-3 min-h-6" aria-live="polite">
        {state === "exporting" && (
          <p className="text-sm text-violet-200">
            Analyzing ranked moments, extracting clips, and building your ZIP package…
          </p>
        )}
        {state === "error" && <p className="text-sm text-rose-400">{errorMessage}</p>}
      </div>

      {result && <ExportResults result={result} />}
    </section>
  );
}

function NumberField({
  label,
  suffix,
  value,
  min,
  max,
  step,
  disabled,
  onChange,
}: {
  label: string;
  suffix?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label className="text-sm text-zinc-300">
      <span className="mb-2 flex items-center justify-between text-xs font-medium uppercase tracking-wide text-zinc-500">
        {label}
        {suffix && <span className="normal-case tracking-normal text-zinc-600">{suffix}</span>}
      </span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(event) => {
          const nextValue = event.currentTarget.valueAsNumber;
          if (Number.isFinite(nextValue)) onChange(Math.min(max, Math.max(min, nextValue)));
        }}
        className="w-full rounded-xl border border-white/10 bg-[#11131c] px-3 py-2.5 text-sm text-zinc-200 transition hover:border-white/20 disabled:cursor-not-allowed disabled:opacity-60"
      />
    </label>
  );
}

function ExportResults({ result }: { result: ExportResponse }) {
  return (
    <div className="mt-5 border-t border-white/10 pt-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="font-semibold text-white">Generated clips</h3>
          <p className="mt-1 text-xs text-zinc-500">
            {result.preset.replaceAll("_", " ")} preset · export {result.export_id.slice(-8)}
          </p>
        </div>
        <a
          href={backendAssetUrl(result.package_url)}
          download
          className="inline-flex items-center justify-center gap-2 rounded-xl border border-violet-400/30 bg-violet-500/10 px-4 py-2.5 text-sm font-semibold text-violet-200 transition hover:border-violet-300/50 hover:bg-violet-500/20"
        >
          <DownloadIcon />
          Download ZIP
        </a>
      </div>

      {result.diagnostics.length > 0 && (
        <div className="mt-4 rounded-xl border border-amber-400/20 bg-amber-400/[0.06] p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-300">Export diagnostics</p>
          <ul className="mt-2 space-y-2">
            {result.diagnostics.map((diagnostic, index) => (
              <li key={`${diagnostic.stage}-${index}`} className="text-sm leading-5 text-amber-100/80">
                <span className="font-medium text-amber-200">{diagnostic.stage}:</span>{" "}
                {diagnostic.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {result.clips.map((clip) => (
          <article key={clip.clip_id} className="overflow-hidden rounded-2xl border border-white/10 bg-black/20">
            <video controls preload="metadata" src={backendAssetUrl(clip.download_url)} className="aspect-video w-full bg-black object-contain">
              Your browser does not support video playback.
            </video>
            <div className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-white">Moment #{clip.rank}</p>
                  <p className="mt-1 text-xs text-zinc-500">
                    {clip.duration.toFixed(2)} s · score {(clip.score * 100).toFixed(0)}% · {formatBytes(clip.size_bytes)}
                  </p>
                </div>
                <span className="rounded-full border border-white/10 px-2 py-1 text-[11px] text-zinc-400">MP4</span>
              </div>
              <a
                href={backendAssetUrl(clip.download_url)}
                download={`${clip.clip_id}.mp4`}
                className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.05] px-4 py-2.5 text-sm font-medium text-zinc-200 transition hover:border-violet-400/30 hover:bg-violet-500/10"
              >
                <DownloadIcon />
                Download Clip
              </a>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function LoadingSpinner() {
  return <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true" />;
}

function ExportIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M12 3v12m0 0 4-4m-4 4-4-4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3" strokeLinecap="round" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M12 3v12m0 0 4-4m-4 4-4-4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 20h14" strokeLinecap="round" />
    </svg>
  );
}
