
import os
import base64
import requests
import json

# Use current Gemini API Key
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-3-flash-preview"
PDF_PATH = "test_doc.pdf"

def get_file_b64():
    if os.path.exists(PDF_PATH):
        with open(PDF_PATH, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    return None

def test_inline_data():
    print(f"\n--- Testing Gemini Inline Data (Base64) with {MODEL} ---")
    
    b64_data = get_file_b64()
    if not b64_data: return print("PDF missing")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
    
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": "application/pdf", "data": b64_data}},
                {"text": "Summarize this PDF."}
            ]
        }]
    }
    
    try:
        res = requests.post(url, json=payload, timeout=30)
        print(f"Status: {res.status_code}")
        if res.status_code == 200:
            print("SUCCESS!")
            print(res.json()["candidates"][0]["content"]["parts"][0]["text"][:200])
        else:
            print(res.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_inline_data()
