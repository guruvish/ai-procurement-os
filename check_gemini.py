from google import genai
from app import config

client = genai.Client(api_key=config.GEMINI_API_KEY)
resp = client.models.generate_content(
    model=config.GEMINI_MODEL,
    contents="Reply with exactly: Gemini connected",
)
print("Model:", config.GEMINI_MODEL)
print("Reply:", resp.text)