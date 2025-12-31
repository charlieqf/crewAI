import os
import base64
import asyncio
from src.crewai_enterprise.utils.llm_router import get_router

async def test_pdf_extraction():
    print("--- Testing PDF Extraction Fallback ---")
    router = get_router()
    
    # Create a dummy PDF-like byte string (or use a real one if available)
    # Since we use pypdf, we need a valid-ish PDF header at least, but pypdf will fail on empty.
    # We'll just test the routing logic and mock the extraction if needed, 
    # but for a real test we'd need a small PDF.
    
    # Let's try once with dummy data to see the error handling
    dummy_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    
    print("\n1. Testing non-Gemini PDF routing...")
    try:
        # This should trigger the fallback logic in chat_with_file
        response = router.chat_with_file(
            provider="openai", # Force non-Gemini
            text="Summarize this PDF",
            file_data=dummy_pdf,
            file_mime_type="application/pdf",
            filename="test.pdf"
        )
        print(f"Response: {response.content[:100]}...")
    except Exception as e:
        print(f"Error (Expected if PDF is too broken): {e}")

if __name__ == "__main__":
    asyncio.run(test_pdf_extraction())
