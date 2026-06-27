import { UploadPanel } from "@/components/upload-panel";

export default function HomePage() {
  return (
    <main className="relative min-h-screen overflow-hidden px-5 py-8 sm:px-8">
      <div className="ambient ambient-left" aria-hidden="true" />
      <div className="ambient ambient-right" aria-hidden="true" />

      <nav className="relative z-10 mx-auto flex max-w-6xl items-center justify-between">
        <a href="#main" className="flex items-center gap-3" aria-label="MomentAI home">
          <span className="grid h-9 w-9 place-items-center rounded-xl border border-violet-400/30 bg-violet-500/10 text-violet-300">
            <SparkIcon />
          </span>
          <span className="text-lg font-semibold tracking-tight text-white">MomentAI</span>
        </a>
        <span className="rounded-full border border-white/10 bg-white/[0.035] px-3 py-1 text-xs font-medium text-zinc-400">
          Phase 1
        </span>
      </nav>

      <section id="main" className="relative z-10 mx-auto flex max-w-3xl flex-col items-center pb-16 pt-20 text-center sm:pt-28">
        <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-violet-400/20 bg-violet-400/[0.07] px-3 py-1.5 text-xs font-medium text-violet-200">
          <span className="h-1.5 w-1.5 rounded-full bg-violet-400 shadow-[0_0_12px_#a78bfa]" />
          Your best moments start here
        </div>
        <h1 className="max-w-2xl text-balance text-4xl font-semibold leading-tight tracking-[-0.04em] text-white sm:text-6xl">
          Find the moments <span className="gradient-text">that matter.</span>
        </h1>
        <p className="mt-5 max-w-xl text-pretty text-base leading-7 text-zinc-400 sm:text-lg">
          Upload a video securely. MomentAI will be ready for the next step when you are.
        </p>

        <div className="mt-10 w-full">
          <UploadPanel />
        </div>
      </section>
    </main>
  );
}

function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
      <path d="M12 2.75 13.65 8.4 19.25 10 13.65 11.6 12 17.25l-1.65-5.65L4.75 10l5.6-1.6L12 2.75Z" fill="currentColor" />
      <path d="m18.25 15.25.7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z" fill="currentColor" opacity=".65" />
    </svg>
  );
}
