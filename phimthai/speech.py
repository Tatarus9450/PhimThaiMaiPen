"""Conservative WebRTC speech detection with padding around utterances."""
import contextlib
import wave
from pathlib import Path


@contextlib.contextmanager
def prepare_speech(source, enabled=True):
    import typhoon_service as service
    path = service.prepare_audio(Path(source))
    try:
        with wave.open(str(path), "rb") as audio:
            rate = audio.getframerate()
            pcm = audio.readframes(audio.getnframes())
        duration = len(pcm) / 2 / rate
        metadata = {"input_duration": duration, "vad_applied": enabled, "no_speech": False}
        if enabled:
            import webrtcvad
            vad = webrtcvad.Vad(1)
            frame_bytes = rate * 30 // 1000 * 2
            voiced = [offset for offset in range(0, len(pcm), frame_bytes)
                      if vad.is_speech(pcm[offset:offset + frame_bytes].ljust(frame_bytes, b"\0"), rate)]
            if not voiced:
                metadata["no_speech"] = True
            else:
                # Preserve internal pauses and 400 ms at each edge. VAD can be
                # disabled for quiet voices or recordings it misclassifies.
                padding = rate * 400 // 1000 * 2
                start = max(0, voiced[0] - padding)
                end = min(len(pcm), voiced[-1] + frame_bytes + padding)
                with wave.open(str(path), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(rate)
                    output.writeframes(pcm[start:end])
                metadata["retained_duration"] = (end - start) / 2 / rate
        yield path, metadata
    finally:
        path.unlink(missing_ok=True)
