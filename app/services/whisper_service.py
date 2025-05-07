import time  # Add this import at the top of your file
from datetime import datetime  # Make sure you have this import

import ffmpeg
import openai
import os
import subprocess
from dotenv import load_dotenv
from fastapi import HTTPException, UploadFile
import tempfile

from openai import OpenAI, AsyncOpenAI
from pydub import AudioSegment

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY")   # ✅ Correct way
)


async def transcribe_audio(audio_file: UploadFile):
    """Enhanced audio transcription with robust error handling"""
    temp_dir = "temp_audio"
    os.makedirs(temp_dir, exist_ok=True)
    timestamp = str(int(time.time()))
    file_ext = os.path.splitext(audio_file.filename)[-1].lower()

    try:
        # 1. Save original file
        input_path = os.path.join(temp_dir, f"input_{timestamp}{file_ext}")
        with open(input_path, "wb") as f:
            content = await audio_file.read()
            f.write(content)

        print(f"Original file saved: {input_path} ({os.path.getsize(input_path)} bytes)")

        # 2. Convert to optimized WAV format
        processed_path = os.path.join(temp_dir, f"processed_{timestamp}.wav")
        await convert_audio(input_path, processed_path)

        # 3. Normalize audio
        normalized_path = os.path.join(temp_dir, f"normalized_{timestamp}.wav")
        await normalize_audio(processed_path, normalized_path)

        # 4. Verify audio quality
        await verify_audio(normalized_path)

        # 5. Transcribe with Whisper
        return await call_whisper(normalized_path)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Audio processing failed: {str(e)}")
    finally:
        for path in [input_path, processed_path, normalized_path]:
            try:
                if path and os.path.exists(path):
                    os.unlink(path)
            except:
                pass


async def convert_audio(input_path: str, output_path: str):
    """Convert to Whisper-optimized WAV format"""
    try:
        (
            ffmpeg
            .input(input_path)
            .output(output_path,
                    ac=1, ar=16000, acodec='pcm_s16le',
                    af='highpass=f=300,lowpass=f=4000')
            .overwrite_output()
            .run(cmd='ffmpeg', capture_stdout=True, capture_stderr=True)
        )
        print(f"Converted audio saved: {output_path}")
    except ffmpeg.Error as e:
        print(f"FFmpeg error: {e.stderr.decode()}")
        raise HTTPException(400, f"Audio conversion failed: {e.stderr.decode()}")


async def normalize_audio(input_path: str, output_path: str):
    """Normalize volume and add padding"""
    try:
        (
            ffmpeg
            .input(input_path)
            .output(output_path,
                    af='loudnorm=I=-16:TP=-1.5:LRA=11,apad=pad_dur=0.5')
            .overwrite_output()
            .run(cmd='ffmpeg')
        )
        print(f"Normalized audio saved: {output_path}")
    except ffmpeg.Error as e:
        print(f"Normalization failed: {e.stderr.decode()}")
        raise HTTPException(400, "Audio normalization failed")


async def verify_audio(file_path: str):
    """Validate audio meets requirements"""
    try:
        info = ffmpeg.probe(file_path)
        duration = float(info['format']['duration'])
        if duration < 0.5:
            raise ValueError("Audio too short (<500ms)")

        print(f"Audio verified: duration={duration}s")
    except Exception as e:
        raise HTTPException(400, f"Invalid audio: {str(e)}")


async def call_whisper(audio_path: str):
    """Call Whisper API with optimized settings"""
    try:
        with open(audio_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="en",
                temperature=0.0,
                prompt="Transcribe the following children's speech clearly:"
            )
            print(f"Whisper response: {transcript}")
            return transcript.text
    except Exception as e:
        raise HTTPException(500, f"Transcription failed: {str(e)}")


async def validate_audio_file(file: UploadFile):
    """Validate the audio file before processing"""
    if not file.content_type.startswith('audio/'):
        raise HTTPException(
            status_code=400,
            detail="File must be an audio file"
        )

    # Limit file size (e.g., 5MB)
    max_size = 5 * 1024 * 1024
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Reset pointer

    if file_size > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size is {max_size} bytes"
        )

    return True