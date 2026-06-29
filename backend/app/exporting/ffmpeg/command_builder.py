from pathlib import Path

from backend.app.exporting.models import ClipSpec, ExportPreset


class FFmpegCommandBuilder:
    """Build shell-free, frame-accurate FFmpeg clip commands."""

    def __init__(self, ffmpeg_binary: str = "ffmpeg") -> None:
        self._ffmpeg_binary = ffmpeg_binary

    def build(
        self,
        source_path: Path,
        output_path: Path,
        spec: ClipSpec,
        preset: ExportPreset,
    ) -> tuple[str, ...]:
        command = [
            self._ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{spec.start_seconds:.6f}",
            "-i",
            str(source_path.resolve()),
            "-t",
            f"{spec.duration_seconds:.6f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
        ]
        video_filter = _video_filter(preset)
        if video_filter:
            command.extend(("-vf", video_filter))
        if preset.fps is not None:
            command.extend(("-r", str(preset.fps)))
        command.extend(
            (
                "-c:v",
                preset.video_codec,
                "-preset",
                preset.encoder_preset,
                "-crf",
                str(preset.crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                preset.audio_codec,
                "-b:a",
                preset.audio_bitrate,
                "-movflags",
                "+faststart",
                "-avoid_negative_ts",
                "make_zero",
                "-f",
                "mp4",
                str(output_path.resolve()),
            )
        )
        return tuple(command)


def _video_filter(preset: ExportPreset) -> str | None:
    if preset.width is None or preset.height is None:
        return None
    scale = (
        f"scale={preset.width}:{preset.height}:"
        "force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    if preset.fit_mode == "pad":
        return (
            f"{scale},pad={preset.width}:{preset.height}:"
            "(ow-iw)/2:(oh-ih)/2:color=black"
        )
    return scale
