import os
import base64
from dotenv import load_dotenv
from fastapi import HTTPException
from openai import OpenAI
from sqlalchemy.orm import Session
from io import BytesIO
from PIL import Image
import requests

# Load environment variables
load_dotenv()

# Initialize OpenAI client ONCE
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")   # ✅ Correct way
)

# Helper function to download and convert an image to base64
async def download_image(image_url: str):
    try:
        response = requests.get(image_url)
        response.raise_for_status()

        img = Image.open(BytesIO(response.content))

        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

        return img_base64
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image download failed: {str(e)}")


# Function to generate an image with DALL·E
async def generate_image(prompt: str):
    try:
        # Generate image using the already initialized client
        response = client.images.generate(
            model="dall-e-3",
            prompt=f"generate an image of {prompt} "
                   f"The image should be friendly to children with ASD",
            n=1,
            size="1024x1024"
        )

        image_url = response.data[0].url
        return image_url

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"OpenAI image generation failed: {str(e)}"
        )


async def generate_pronunciation_audio(text: str):
    # This would use OpenAI's TTS when available
    # For now, we'll just return a placeholder
    return f"https://example.com/audio/{text.lower()}.mp3"