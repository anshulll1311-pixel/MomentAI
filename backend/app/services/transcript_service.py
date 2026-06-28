import asyncio
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.services.scene_service import SceneService
from backend.app.services.video_service import VideoService

logger = logging.getLogger(__name__)


class TranscriptServiceError(RuntimeError):
    """Base error for transcript processing failures."""


class MissingAudioError(TranscriptServiceError):
    """Raised when a video has no audio stream."""


class AudioToolUnavailableError(TranscriptServiceError):
    """Raised when FFmpeg cannot be started for audio extraction."""


class AudioExtractionError(TranscriptServiceError):
    """Raised when audio cannot be extracted from a video."""


class TranscriptionUnavailableError(TranscriptServiceError):
    """Raised when faster-whisper or its configured model is unavailable."""


class TranscriptionTimeoutError(TranscriptServiceError):
    """Raised when audio extraction or transcription exceeds its timeout."""


class EmptyTranscriptError(TranscriptServiceError):
    """Raised when no speech segments are detected."""


class TranscriptionError(TranscriptServiceError):
    """Raised when faster-whisper fails unexpectedly."""


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    scene_id: int


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    language: str
    duration_seconds: float
    segments: tuple[TranscriptSegment, ...]


@dataclass(frozen=True, slots=True)
class _RawTranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str


class TranscriptService:
    """Extract audio, transcribe speech, and map segments to video scenes."""

    def __init__(
        self,
        video_service: VideoService,
        scene_service: SceneService,
        temporary_directory: Path,
        model_directory: Path,
        ffmpeg_binary: str = "ffmpeg",
        model_size: str = "tiny.en",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 5,
        audio_timeout_seconds: float = 60.0,
        transcription_timeout_seconds: float = 600.0,
    ) -> None:
        self._video_service = video_service
        self._scene_service = scene_service
        self._temporary_directory = temporary_directory
        self._model_directory = model_directory
        self._ffmpeg_binary = ffmpeg_binary
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._beam_size = beam_size
        self._audio_timeout_seconds = audio_timeout_seconds
        self._transcription_timeout_seconds = transcription_timeout_seconds

    async def transcribe(self, video_path: Path) -> TranscriptResult:
        metadata = await self._video_service.extract_metadata(video_path)
        if metadata.audio_codec is None:
            raise MissingAudioError("The uploaded video does not contain an audio stream.")

        scene_boundaries = await self._scene_service.detect_boundaries(
            video_path,
            metadata.duration_seconds,
        )
        self._temporary_directory.mkdir(parents=True, exist_ok=True)
        audio_path = self._temporary_directory / f"{video_path.stem}.wav"

        await self._extract_audio(video_path, audio_path)
        cleanup_deferred = False
        transcription_task = asyncio.create_task(
            asyncio.to_thread(self._transcribe_audio, audio_path)
        )
        try:
            language, raw_segments = await asyncio.wait_for(
                asyncio.shield(transcription_task),
                timeout=self._transcription_timeout_seconds,
            )
        except TimeoutError as error:
            cleanup_deferred = True
            transcription_task.add_done_callback(lambda _: audio_path.unlink(missing_ok=True))
            logger.warning("Transcription timed out for %s", video_path.name)
            raise TranscriptionTimeoutError("Video transcription timed out.") from error
        except asyncio.CancelledError:
            cleanup_deferred = True
            transcription_task.add_done_callback(lambda _: audio_path.unlink(missing_ok=True))
            raise
        finally:
            if not cleanup_deferred:
                audio_path.unlink(missing_ok=True)

        segments = []
        for segment in raw_segments:
            start = min(segment.start_seconds, metadata.duration_seconds)
            end = min(segment.end_seconds, metadata.duration_seconds)
            if end <= start:
                continue
            segments.append(
                TranscriptSegment(
                    start_seconds=start,
                    end_seconds=end,
                    text=segment.text,
                    scene_id=_scene_for_segment(start, end, scene_boundaries),
                )
            )
        if not segments:
            raise EmptyTranscriptError("No speech was detected in the uploaded video.")

        logger.info(
            "Transcribed %s into %s segments across %s scenes",
            video_path.name,
            len(segments),
            len(scene_boundaries) - 1,
        )
        return TranscriptResult(
            language=language,
            duration_seconds=metadata.duration_seconds,
            segments=tuple(segments),
        )

    async def _extract_audio(self, video_path: Path, audio_path: Path) -> None:
        command = (
            self._ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path.resolve()),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(audio_path.resolve()),
        )

        logger.info("Extracting transcript audio from %s", video_path.name)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as error:
            logger.exception("Unable to start FFmpeg executable: %s", self._ffmpeg_binary)
            raise AudioToolUnavailableError("Audio extraction service is unavailable.") from error

        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._audio_timeout_seconds,
            )
        except TimeoutError as error:
            await _terminate_process(process)
            audio_path.unlink(missing_ok=True)
            logger.warning("Audio extraction timed out for %s", video_path.name)
            raise TranscriptionTimeoutError("Audio extraction timed out.") from error
        except asyncio.CancelledError:
            await _terminate_process(process)
            audio_path.unlink(missing_ok=True)
            raise

        if process.returncode != 0:
            audio_path.unlink(missing_ok=True)
            diagnostic = stderr.decode("utf-8", errors="replace").strip()
            logger.warning(
                "Audio extraction failed for %s: %s",
                video_path.name,
                diagnostic[:500] or "unknown FFmpeg error",
            )
            raise AudioExtractionError("Audio could not be extracted from this video.")

        try:
            audio_size = audio_path.stat().st_size
        except OSError as error:
            audio_path.unlink(missing_ok=True)
            raise AudioExtractionError("Extracted audio could not be read.") from error
        if audio_size <= 44:
            audio_path.unlink(missing_ok=True)
            raise MissingAudioError("The uploaded video contains no usable audio.")

    def _transcribe_audio(
        self,
        audio_path: Path,
    ) -> tuple[str, tuple[_RawTranscriptSegment, ...]]:
        model = _load_whisper_model(
            self._model_size,
            self._device,
            self._compute_type,
            str(self._model_directory.resolve()),
        )
        try:
            generated_segments, info = model.transcribe(
                str(audio_path.resolve()),
                beam_size=self._beam_size,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            segments = tuple(
                _RawTranscriptSegment(
                    start_seconds=max(0.0, float(segment.start)),
                    end_seconds=max(0.0, float(segment.end)),
                    text=str(segment.text).strip(),
                )
                for segment in generated_segments
                if str(segment.text).strip() and float(segment.end) > float(segment.start)
            )
        except TranscriptServiceError:
            raise
        except Exception as error:
            logger.exception("faster-whisper transcription failed")
            raise TranscriptionError("The audio could not be transcribed.") from error

        language = str(getattr(info, "language", "") or "unknown")
        return language, segments


@lru_cache(maxsize=4)
def _load_whisper_model(
    model_size: str,
    device: str,
    compute_type: str,
    model_directory: str,
) -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise TranscriptionUnavailableError("faster-whisper is not installed.") from error

    Path(model_directory).mkdir(parents=True, exist_ok=True)
    logger.info("Loading faster-whisper model %s on %s", model_size, device)
    try:
        return WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=model_directory,
        )
    except Exception as error:
        logger.exception("Unable to load faster-whisper model %s", model_size)
        raise TranscriptionUnavailableError(
            "The configured transcription model is unavailable."
        ) from error


def _scene_for_segment(
    segment_start: float,
    segment_end: float,
    boundaries: tuple[float, ...],
) -> int:
    best_scene_id = 1
    best_overlap = -1.0
    midpoint = segment_start + ((segment_end - segment_start) / 2)

    for index, (scene_start, scene_end) in enumerate(
        zip(boundaries, boundaries[1:]),
        start=1,
    ):
        overlap = max(0.0, min(segment_end, scene_end) - max(segment_start, scene_start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_scene_id = index
        if overlap == best_overlap and scene_start <= midpoint < scene_end:
            best_scene_id = index
    return best_scene_id


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.communicate()
