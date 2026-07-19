import os
import sys
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "qwen/qwen3.6-27b"


def image_to_data_url(image_path):
    ext = image_path.split('.')[-1].lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def read_id_card_with_groq(image_path_or_url):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("Set GROQ_API_KEY environment variable first")

    image_url = (image_path_or_url if image_path_or_url.startswith("http")
                 else image_to_data_url(image_path_or_url))

    prompt = (
        "This is an image of an Egyptian National ID card. "
        "Extract all the visible information from the ID card with extreme accuracy. "
        "Respond in JSON format with the following fields (in Arabic exactly as they appear): "
        "- Name (الاسم) "
        "- Address (العنوان) "
        "- ID_Number (الرقم القومي) "
        "- Governorate (المحافظة) "
        "- Religion (الديانة) "
        "- Marital_Status (الحالة الاجتماعية) "
        "- Profession (المهنة) "
        "- Gender (النوع) "
        "- Issue_Date (تاريخ الاصدار) "
        "- Expiry_Date (سارية حتى) "
        "- Husband_Name (اسم الزوج, if present) "
        "Make sure to read every character carefully, especially the 14-digit national ID number. "
        "If a field is not visible, set its value to null. "
        "Respond ONLY with the JSON string, and nothing else."
    )

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=60)
    if resp.status_code != 200:
        print("API Error Response:", resp.text)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python model.py path/to/egypt-id-card.jpeg")
        sys.exit(1)

    result = read_id_card_with_groq(sys.argv[1])
    print("Extracted ID Card Data:", result)