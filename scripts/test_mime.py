
import os
import base64
import requests
import json

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-3-flash-preview"

PDF_B64 = "JVBERi0xLjQKMSAwIG9iago8PAovVGl0bGUgKFRlc3QgUERGKQovQ3JlYXRvciAoTW9jayBQREYgR2VuZXJhdG9yKQo+PgplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMyAwIFIKPj4KZW5kb2JqCjMgMCBvYmoKPDwKL1R5cGUgL1BhZ2VzCi9Db3VudCAxCi9LaWRzIFs0IDAgUl0KPj4KZW5kb2JqCjQgMCBvYmoKPDwKL1R5cGUgL1BhZ2UKL1BhcmVudCAzIDAgUgovTWVkaWFCb3ggWzAgMCA2MTIgNzkyXQovQ29udGVudHMgNSAwIFIKL1Jlc291cmNlcyA8PAovRm9udCA8PAovRjEgPDwKL1R5cGUgL0ZvbnQKL1N1YnR5cGUgL1R5cGUxCi9CYXNlRm9udCAvSGVsdmV0aWNhCj4+Cj4+Cj4+Cj4+CmVuZG9iago1IDAg2YJqCjw8Ci9MZW5ndGggNTkKPj4Kc3RyZWFtCkJUCi9GMSAxMiBUZgoyMCA3MDAgVGQKKEhlbGxvLiBUaGlzIGlzIGEgdGVzdCBQREYgY29udGVudCEpIFRqCkVUCmVuZHN0cmVhbQplbmRvYmoKdHJhaWxlcgo8PAovU2l6ZSA2Ci9Sb290IDIgMCBSCj4+CnN0YXJ0eHJlZgoyODIKJSVFT0YK"

def test_mime(mime):
    print(f"\n--- Testing PDF with mime={mime} ---")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
    
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": mime, "data": PDF_B64}},
                {"text": "Analyze."}
            ]
        }]
    }
    
    res = requests.post(url, json=payload, timeout=10)
    print(f"Status: {res.status_code}")
    if res.status_code != 200:
        print(res.text)
    else:
        print("SUCCESS")

if __name__ == "__main__":
    test_mime("application/pdf")
    test_mime("application/octet-stream")
    test_mime("text/plain")
