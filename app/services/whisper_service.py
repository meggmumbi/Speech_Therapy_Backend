import openai
import os
from dotenv import load_dotenv
from fastapi import HTTPException, UploadFile
import tempfile
from pydub import AudioSegment

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")


async def transcribe_audio(audio_file: UploadFile):
    try:
        # Save the uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            content = await audio_file.read()
            tmp.write(content)
            tmp_path = tmp.name

        # Convert to format Whisper prefers (16kHz mono)
        audio = AudioSegment.from_file(tmp_path)
        audio = audio.set_frame_rate(16000).set_channels(1)
        processed_path = tmp_path.replace(".wav", "_processed.wav")
        audio.export(processed_path, format="wav")

        # Transcribe with Whisper
        with open(processed_path, "rb") as audio_file:
            transcript = await openai.Audio.atranscribe(
                "whisper-1",
                audio_file,
                language="en"  # Set to your preferred language
            )

        # Clean up temporary files
        os.unlink(tmp_path)
        os.unlink(processed_path)

        return transcript["text"]

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Audio processing failed: {str(e)}"
        )


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