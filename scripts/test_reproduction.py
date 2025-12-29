
import os
import base64
import requests
import json

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-3-flash-preview"

# Mock SQL content
SQL_CONTENT = "ALTER TABLE users DROP COLUMN start_date;"
PDF_B64 = "JVBERi0xLjQKMSAwIG9iago8PAovVGl0bGUgKFRlc3QgUERGKQovQ3JlYXRvciAoTW9jayBQREYgR2VuZXJhdG9yKQo+PgplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMyAwIFIKPj4KZW5kb2JqCjMgMCBvYmoKPDwKL1R5cGUgL1BhZ2VzCi9Db3VudCAxCi9LaWRzIFs0IDAgUl0KPj4KZW5kb2JqCjQgMCBvYmoKPDwKL1R5cGUgL1BhZ2UKL1BhcmVudCAzIDAgUgovTWVkaWFCb3ggWzAgMCA2MTIgNzkyXQovQ29udGVudHMgNSAwIFIKL1Jlc291cmNlcyA8PAovRm9udCA8PAovRjEgPDwKL1R5cGUgL0ZvbnQKL1N1YnR5cGUgL1R5cGUxCi9CYXNlRm9udCAvSGVsdmV0aWNhCj4+Cj4+Cj4+Cj4+CmVuZG9iago1IDAg2YJqCjw8Ci9MZW5ndGggNTkKPj4Kc3RyZWFtCkJUCi9GMSAxMiBUZgoyMCA3MDAgVGQKKEhlbGxvLiBUaGlzIGlzIGEgdGVzdCBQREYgY29udGVudCEpIFRqCkVUCmVuZHN0cmVhbQplbmRvYmoKdHJhaWxlcgo8PAovU2l6ZSA2Ci9Sb290IDIgMCBSCj4+CnN0YXJ0eHJlZgoyODIKJSVFT0YK"

def test_inline(mime, data_b64, label):
    print(f"\n--- Testing {label} ({mime}) ---")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
    
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": mime, "data": data_b64}},
                {"text": "Analyze this."}
            ]
        }]
    }
    
    res = requests.post(url, json=payload, timeout=30)
    print(f"Status: {res.status_code}")
    if res.status_code == 200:
        print("SUCCESS")
        print(res.json()["candidates"][0]["content"]["parts"][0]["text"][:100])
    else:
        print(res.text)

if __name__ == "__main__":
    sql_b64 = base64.b64encode(SQL_CONTENT.encode('utf-8')).decode('utf-8')
    test_inline("text/plain", sql_b64, "SQL")
    test_inline("application/pdf", PDF_B64, "PDF")
