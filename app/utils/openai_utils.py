import openai
import os
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

async def generate_image(prompt: str):
    try:
        response = await openai.Image.acreate(
            prompt=f"A cartoon style image of {prompt}, colorful, simple background",
            n=1,
            size="512x512"
        )
        return response['data'][0]['url']
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI image generation failed: {str(e)}")

async def generate_pronunciation_audio(text: str):
    # This would use OpenAI's TTS when available
    # For now, we'll just return a placeholder
    return f"https://example.com/audio/{text.lower()}.mp3"