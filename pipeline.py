#!/usr/bin/env python3
"""
Vocal Reference Generator — Core Pipeline
Reusable module for CLI, GUI, and Web versions.
"""

import os
import sys
import tempfile
import shutil
import warnings
import traceback

import numpy as np
import soundfile as sf

# Demucs for source separation
try:
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    from demucs.audio import AudioFile, save_audio
except ImportError as e:
    raise ImportError(f"demucs not installed or incompatible version. Run: pip install demucs ({e})")

# Parselmouth (Praat) for formant shifting
try:
    import parselmouth
except ImportError:
    raise ImportError("praat-parselmouth not installed. Run: pip install praat-parselmouth")

# pydub for mixing
try:
    from pydub import AudioSegment
except ImportError:
    raise ImportError("pydub not installed. Run: pip install pydub")


def separate_stems(input_path: str, output_dir: str, device: str = "cpu", progress_callback=None):
    """Separate audio into stems using Demucs."""
    if progress_callback:
        progress_callback("Loading Demucs model...", 5)

    model = get_model("htdemucs")

    if progress_callback:
        progress_callback("Loading audio...", 10)

    # Load audio
    wav = AudioFile(input_path).read(
        streams=0,
        samplerate=model.samplerate,
        channels=model.audio_channels,
    )

    # Normalize (same as demucs.separate CLI)
    ref = wav.mean(0)
    wav -= ref.mean()
    wav /= ref.std() + 1e-8

    if progress_callback:
        progress_callback("Separating stems (this may take a while)...", 20)

    # Apply model
    sources = apply_model(
        model,
        wav.unsqueeze(0),
        device=device,
        shifts=1,
        split=True,
        overlap=0.25,
        progress=False,
    )[0]

    # Denormalize
    sources *= ref.std() + 1e-8
    sources += ref.mean()

    if progress_callback:
        progress_callback("Saving stems...", 60)

    # Save stems
    stems = {}
    for source, name in zip(sources, model.sources):
        stem_path = os.path.join(output_dir, f"{name}.wav")
        save_audio(source, stem_path, samplerate=model.samplerate)
        stems[name] = stem_path

    # Build instrumental from drums + bass + other
    if all(k in stems for k in ["drums", "bass", "other"]):
        instrumental = None
        sr = None
        for stem in ["drums", "bass", "other"]:
            audio, sr = sf.read(stems[stem])
            if audio.ndim == 1:
                audio = np.column_stack([audio, audio])
            if instrumental is None:
                instrumental = audio
            else:
                instrumental += audio

        # Normalize
        max_val = np.max(np.abs(instrumental))
        if max_val > 1.0:
            instrumental = instrumental / max_val * 0.95

        inst_path = os.path.join(output_dir, "no_vocals.wav")
        sf.write(inst_path, instrumental, sr)
        stems["no_vocals"] = inst_path

    return stems, model.samplerate


def formant_shift(input_path: str, output_path: str, formant_ratio: float = 1.5,
                  pitch_shift_semitones: float = 0.0,
                  pitch_range_ratio: float = 1.0,
                  progress_callback=None):
    """Apply formant shift using Praat."""
    if progress_callback:
        progress_callback("Shifting formants...", 65)

    sound = parselmouth.Sound(input_path)
    # Change Gender only works on mono sounds
    if sound.n_channels > 1:
        sound = sound.convert_to_mono()

    new_pitch_median = 2 ** (pitch_shift_semitones / 12) if pitch_shift_semitones != 0 else 0.0

    new_sound = parselmouth.praat.call(
        sound, "Change gender",
        75, 600,
        formant_ratio,
        new_pitch_median,
        pitch_range_ratio,  # pitch range ratio
        1.0,  # duration factor
    )

    new_sound.save(output_path, "WAV")


def synthesize_humming(input_path: str, output_path: str,
                       vibrato_depth: float = 0.15,
                       vibrato_rate: float = 5.0,
                       progress_callback=None):
    """
    Extract pitch contour from vocals and resynthesize as a humming sound.
    This completely eliminates phonetic content (words) while preserving
    melody, rhythm, and expression.
    """
    if progress_callback:
        progress_callback("Extracting melody...", 62)

    sound = parselmouth.Sound(input_path)

    # Extract pitch contour
    pitch = sound.to_pitch(pitch_floor=75, pitch_ceiling=600)

    times = pitch.xs()
    frequencies = pitch.selected_array['frequency']

    # Convert to numpy and fill unvoiced gaps
    freqs = np.array(frequencies)
    freqs[freqs == 0] = np.nan

    # Forward-fill for gaps
    last_valid = None
    for i in range(len(freqs)):
        if not np.isnan(freqs[i]):
            last_valid = freqs[i]
        elif last_valid is not None:
            freqs[i] = last_valid

    # Handle leading silence
    if np.isnan(freqs[0]):
        first_valid = np.where(~np.isnan(freqs))[0]
        if len(first_valid) > 0:
            freqs[:first_valid[0]] = freqs[first_valid[0]]
        else:
            freqs[:] = 150  # fallback hum

    sr = int(sound.sampling_frequency)
    duration = sound.duration
    n_samples = int(duration * sr)
    t = np.arange(n_samples) / sr

    # Interpolate pitch to sample rate
    pitch_contour = np.interp(t, times, freqs)
    pitch_contour[pitch_contour <= 0] = 75

    # Add vibrato for naturalness
    if vibrato_depth > 0 and vibrato_rate > 0:
        vibrato = 1.0 + vibrato_depth * np.sin(2 * np.pi * vibrato_rate * t)
        pitch_contour *= vibrato

    if progress_callback:
        progress_callback("Synthesizing humming...", 67)

    # Phase integration: phase = 2π * ∫ f(t) dt
    dt = 1.0 / sr
    phase = 2 * np.pi * np.cumsum(pitch_contour) * dt

    # Rich tone: fundamental + harmonics for "mm-hmm" warmth
    fundamental = np.sin(phase)
    h2 = 0.35 * np.sin(2 * phase)          # octave
    h3 = 0.15 * np.sin(3 * phase)          # twelfth
    h4 = 0.08 * np.sin(4 * phase)          # 2 octaves
    humming = fundamental + h2 + h3 + h4

    # Apply amplitude envelope from original for natural phrasing
    audio = sound.values[0] if sound.n_channels > 1 else sound.values.flatten()
    audio = np.asarray(audio).flatten()

    if len(audio) > len(humming):
        audio = audio[:len(humming)]
    elif len(audio) < len(humming):
        audio = np.pad(audio, (0, len(humming) - len(audio)))

    # Smooth envelope
    envelope = np.abs(audio)
    window_size = int(sr * 0.025)  # 25ms
    if window_size > 1:
        kernel = np.ones(window_size) / window_size
        envelope = np.convolve(envelope, kernel, mode='same')

    humming *= envelope[:len(humming)]

    # Normalize
    max_val = np.max(np.abs(humming))
    if max_val > 0:
        humming = humming / max_val * 0.95

    sf.write(output_path, humming.astype(np.float32), sr)


def add_noise(input_path: str, output_path: str, noise_db: float = -75.0, progress_callback=None):
    """Add sub-audible noise."""
    if progress_callback:
        progress_callback("Adding noise...", 75)

    audio, sr = sf.read(input_path)

    noise_rms = 10 ** (noise_db / 20.0)
    noise = np.random.randn(*audio.shape).astype(np.float32)
    noise *= noise_rms / (np.sqrt(np.mean(noise ** 2)) + 1e-10)

    noisy_audio = audio + noise
    max_val = np.max(np.abs(noisy_audio))
    if max_val > 1.0:
        noisy_audio = noisy_audio / max_val * 0.99

    sf.write(output_path, noisy_audio, sr)


def transpose_audio(input_path: str, output_path: str, semitones: float = 0.0, progress_callback=None):
    """Pitch-shift audio by changing playback speed and resampling back.
    Breaks audio fingerprinting by shifting all spectral content."""
    if semitones == 0:
        # Just copy
        import shutil
        shutil.copy(input_path, output_path)
        return

    if progress_callback:
        progress_callback(f"Transposing {semitones:+.1f} semitones...", 88)

    audio = AudioSegment.from_file(input_path)
    # Speed ratio for N semitones: 2^(N/12)
    ratio = 2.0 ** (semitones / 12.0)
    new_rate = int(audio.frame_rate * ratio)

    # Change frame rate (changes pitch + speed)
    shifted = audio._spawn(audio.raw_data, overrides={'frame_rate': new_rate})
    # Resample back to original rate (restores speed, pitch stays shifted)
    shifted = shifted.set_frame_rate(audio.frame_rate)

    shifted.export(output_path, format="wav")


def mix(vocals_path: str, inst_path: str, output_path: str,
        vocal_gain_db: float = -2.0, progress_callback=None):
    """Mix vocals with instrumental."""
    if progress_callback:
        progress_callback("Mixing...", 85)

    vocals = AudioSegment.from_wav(vocals_path)
    inst = AudioSegment.from_wav(inst_path)

    min_len = min(len(vocals), len(inst))
    vocals = vocals[:min_len]
    inst = inst[:min_len]

    vocals = vocals + vocal_gain_db
    inst = inst + 0.0

    mixed = inst.overlay(vocals - 3)
    mixed.export(output_path, format="mp3", bitrate="320k")


def process_file(input_path: str, output_path: str,
                 formant_ratio: float = 1.5,
                 pitch_shift_semitones: float = 0.0,
                 pitch_range_ratio: float = 1.0,
                 noise_db: float = -75.0,
                 vocal_gain_db: float = -2.0,
                 device: str = "cpu",
                 vocal_style: str = "formant",
                 transpose_semitones: float = 0.0,
                 keep_tempdir: bool = False,
                 progress_callback=None) -> str:
    """
    Single-call process: input file -> gibberish vocal reference.

    Args:
        input_path: Path to source audio (mp3, wav, flac, etc.)
        output_path: Path for output mp3
        formant_ratio: 1.0=original, 1.5=gibberish, 1.8+=alien
        pitch_shift_semitones: 0=keep melody, ±N=transpose
        pitch_range_ratio: 1.0=normal, >1.0=exaggerated pitch (Simlish effect)
        noise_db: sub-audible noise level
        vocal_style: "formant" (disguised voice) or "humming" (pitch-only synthesis)
        transpose_semitones: shift final mix pitch (breaks audio fingerprinting)
        vocal_gain_db: vocal level in the mix
        device: "cpu" or "cuda"
        keep_tempdir: Set True to inspect intermediate files
        progress_callback: Callable(message, percent)

    Returns:
        Path to output file
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    temp_dir = tempfile.mkdtemp(prefix="vref_")

    try:
        # 1. Separate
        stems, samplerate = separate_stems(input_path, temp_dir, device=device,
                                           progress_callback=progress_callback)

        if "vocals" not in stems:
            raise RuntimeError("Could not extract vocals from input")

        # 2. Process vocals
        proc_vocals = os.path.join(temp_dir, "vocals_processed.wav")
        if vocal_style == "humming":
            synthesize_humming(stems["vocals"], proc_vocals,
                               progress_callback=progress_callback)
        else:
            if vocal_style == "humming":
                synthesize_humming(stems["vocals"], proc_vocals,
                                   progress_callback=progress_callback)
            else:
                formant_shift(stems["vocals"], proc_vocals,
                              formant_ratio=formant_ratio,
                              pitch_shift_semitones=pitch_shift_semitones,
                              pitch_range_ratio=pitch_range_ratio,
                              progress_callback=progress_callback)

        # 3. Noise
        if noise_db > -100:
            noise_vocals = os.path.join(temp_dir, "vocals_noisy.wav")
            add_noise(proc_vocals, noise_vocals, noise_db=noise_db,
                      progress_callback=progress_callback)
            proc_vocals = noise_vocals

        # 4. Mix
        inst_source = stems.get("no_vocals", input_path)
        mix(proc_vocals, inst_source, output_path,
            vocal_gain_db=vocal_gain_db,
            progress_callback=progress_callback)

        # 5. Optional transpose to break audio fingerprinting
        if transpose_semitones != 0:
            transpose_audio(output_path, output_path,
                            semitones=transpose_semitones,
                            progress_callback=progress_callback)

        if progress_callback:
            progress_callback("Done!", 100)

        return output_path

    finally:
        if not keep_tempdir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            print(f"   Temp files: {temp_dir}")


def process_vocals_only(input_path: str, output_path: str,
                        formant_ratio: float = 1.5,
                        pitch_shift_semitones: float = 0.0,
                        pitch_range_ratio: float = 1.0,
                        noise_db: float = -75.0,
                        device: str = "cpu",
                        vocal_style: str = "formant",
                        keep_tempdir: bool = False,
                        progress_callback=None) -> str:
    """
    Process only the vocals stem (no remix with instrumental).
    Useful for uploading clean melody references to AI tools.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    temp_dir = tempfile.mkdtemp(prefix="vref_")

    try:
        # 1. Separate
        stems, samplerate = separate_stems(input_path, temp_dir, device=device,
                                           progress_callback=progress_callback)

        if "vocals" not in stems:
            raise RuntimeError("Could not extract vocals from input")

        # 2. Process vocals
        proc_vocals = os.path.join(temp_dir, "vocals_processed.wav")
        if vocal_style == "humming":
            synthesize_humming(stems["vocals"], proc_vocals,
                               progress_callback=progress_callback)
        else:
            if vocal_style == "humming":
                synthesize_humming(stems["vocals"], proc_vocals,
                                   progress_callback=progress_callback)
            else:
                formant_shift(stems["vocals"], proc_vocals,
                              formant_ratio=formant_ratio,
                              pitch_shift_semitones=pitch_shift_semitones,
                              pitch_range_ratio=pitch_range_ratio,
                              progress_callback=progress_callback)

        # 3. Noise
        if noise_db > -100:
            noise_vocals = os.path.join(temp_dir, "vocals_noisy.wav")
            add_noise(proc_vocals, noise_vocals, noise_db=noise_db,
                      progress_callback=progress_callback)
            proc_vocals = noise_vocals

        # 4. Convert to MP3
        if progress_callback:
            progress_callback("Exporting...", 90)

        audio = AudioSegment.from_wav(proc_vocals)
        audio.export(output_path, format="mp3", bitrate="320k")

        if progress_callback:
            progress_callback("Done!", 100)

        return output_path

    finally:
        if not keep_tempdir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            print(f"   Temp files: {temp_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python pipeline.py <input.mp3> <output.mp3>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    def print_progress(msg, pct):
        print(f"[{pct:3d}%] {msg}")

    process_file(input_file, output_file, progress_callback=print_progress)
