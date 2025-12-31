
import os
import time
import base64
import google.generativeai as genai

# Valid minimal PDF (One blank page)
MINIMAL_PDF_B64 = "JVBERi0xLjQKJcfsj6IKNSAwIG9iago8PC9MZW5ndGggMjUvRmlsdGVyL0ZsYXRlRGVjb2RlPj5zdHJlYW0KeJzT0yvKLy5RyE0tLk5MTwUAGyUFFAplbmRzdHJlYW0KZW5kb2JqCjQgMCBvYmoKPDwvVHlwZS9QYWdlL01lZGlhQm94WzAgMCA1OTUgODQyXS9SZXNvdXJjZXM8PC9Qcm9jU2V0Wy9QREYvVGV4dF0vRm9udDw8L0YxIDEgMCBSPj4+Pi9Db250ZW50cyA1IDAgUi9QYXJlbnQgMiAwIFI+PgplbmRvYmoKMSAwIG9iago8PC9UeXBlL0ZvbnQvU3VidHlwZS9UeXBlMS9CYXNlRm9udC9IZWx2ZXRpY2EvRW5jb2RpbmcvV2luQW5zaUVuY29kaW5nPj4KZW5kb2JqCjMgMCBvYmoKPDwvVHlwZS9QYWdlcy9Db3VudCAxL0tpZHxbNCAwIFJdPj4KZW5kb2JqCjIgMCBvYmoKPDwvVHlwZS9DYXRhbG9nL1BhZ2VzIDMgMCBSPj4KZW5kb2JqCjYgMCBvYmoKPDwvUHJvZHVjZXIocGRmY3B1IHYwLjMuMykvQ3JlYXRpb25EYXRlKEQ6MjAyMTAyMjUxMTI5MDNaKS9Nb2REYXRlKEQ6MjAyMTAyMjUxMTI5MDNaKT4+CmVuZG9iagp4cmVmCjAgNwowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAxNDkgMDAwMDAgbiAKMDAwMDAwMDI3OCAwMDAwMCBuIAowMDAwMDAwMjI4IDAwMDAwIG4gCjAwMDAwMDAwNjIgMDAwMDAgbiAKMDAwMDAwMDAwOSAwMDAwMCBuIAowMDAwMDAwMzI1IDAwMDAwIG4gCnRyYWlsZXIKPDwvU2l6ZSA3L1Jvb3QgMiAwIFIvSW5mbyA2IDAgUi9JRCBbPDMyYTE4ZDQxZjUzMDJhM2U0MmI0MmYxMjEwM2QxMzQ4PzwzMmExOGQ0MWY1MzAyYTNlNDJiNDJmMTIxMDNkMTM0OD5dPj4Kc3RhcnR4cmVmCjQyOAolJUVPRgo="

def create_dummy_pdf():
    with open("test_doc.pdf", "wb") as f:
        f.write(base64.b64decode(MINIMAL_PDF_B64))
    print("Created test_doc.pdf (Valid Blank PDF)")

def test_sdk(api_key, model_name):
    print(f"\n--- Testing Google SDK with {model_name} ---")
    genai.configure(api_key=api_key)
    
    # Upload
    print("Uploading file via SDK...")
    sample_file = genai.upload_file("test_doc.pdf", display_name="Test PDF")
    print(f"Uploaded: {sample_file.name} (URI: {sample_file.uri})")
    
    # Wait for Active
    print("Waiting for file to be active...")
    while sample_file.state.name == "PROCESSING":
        print(".", end="", flush=True)
        time.sleep(2)
        sample_file = genai.get_file(sample_file.name)
    
    print(f"\nFile State: {sample_file.state.name}")
    if sample_file.state.name != "ACTIVE":
        print("File is not active. Aborting.")
        return

    # Generate
    print("Generating content...")
    model = genai.GenerativeModel(model_name)
    try:
        response = model.generate_content([sample_file, "Summarize this document."])
        print("SUCCESS!")
        print(response.text)
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY missing")
    else:
        create_dummy_pdf()
        # Test 1: Gemini 2.0 Flash Exp
        test_sdk(api_key, "gemini-2.0-flash-exp") 
        # Test 2: Gemini 3 Flash Preview
        test_sdk(api_key, "gemini-3-flash-preview")
        # Test 3: Gemini 2.5 Pro (if alias exists, else fallback to check list)
        test_sdk(api_key, "gemini-2.5-pro")
