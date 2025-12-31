#!/usr/bin/env python3
"""
Test Qiniu bucket access with different URL formats.
"""
import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get Qiniu credentials
ACCESS_KEY = os.getenv("QINIU_ACCESS_KEY", "ScTsKz5mYH7PiGc0zMI1Q346JeImXmSCiufteaAx")
SECRET_KEY = os.getenv("QINIU_SECRET_KEY", "rUaEP6LYTbMMBJFpN6_Bgia2t4B7ewlKwqETwdWH")
BUCKET = os.getenv("QINIU_BUCKET", "wecom-bot-storage")
DOMAIN = os.getenv("QINIU_DOMAIN", "t83xy5wfa.sabkt.gdipper.com")

# Test file key
TEST_KEY = "wecom/20251231/a49d0e305f0f44c48a64825b9d6d2c96.html"

print("=" * 80)
print("Qiniu Bucket Access Test")
print("=" * 80)
print(f"Bucket: {BUCKET}")
print(f"Domain: {DOMAIN}")
print(f"Test Key: {TEST_KEY}")
print()

# Test 1: Direct public URL (HTTP)
print("Test 1: Direct public URL (HTTP)")
url1 = f"http://{DOMAIN}/{TEST_KEY}"
print(f"URL: {url1}")
try:
    resp = requests.get(url1, timeout=10)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print(f"Content Length: {len(resp.content)} bytes")
        print(f"Content-Type: {resp.headers.get('Content-Type')}")
        print("✅ SUCCESS")
    else:
        print(f"Response: {resp.text[:200]}")
        print("❌ FAILED")
except Exception as e:
    print(f"❌ ERROR: {e}")
print()

# Test 2: Direct public URL (HTTPS)
print("Test 2: Direct public URL (HTTPS)")
url2 = f"https://{DOMAIN}/{TEST_KEY}"
print(f"URL: {url2}")
try:
    resp = requests.get(url2, timeout=10, verify=False)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print(f"Content Length: {len(resp.content)} bytes")
        print(f"Content-Type: {resp.headers.get('Content-Type')}")
        print("✅ SUCCESS")
    else:
        print(f"Response: {resp.text[:200]}")
        print("❌ FAILED")
except Exception as e:
    print(f"❌ ERROR: {e}")
print()

# Test 3: Generate signed URL
print("Test 3: Signed URL (for private bucket)")
try:
    from qiniu import Auth
    
    auth = Auth(ACCESS_KEY, SECRET_KEY)
    base_url = f"http://{DOMAIN}/{TEST_KEY}"
    
    # Generate signed URL (1 hour expiry)
    signed_url = auth.private_download_url(base_url, expires=3600)
    
    print(f"URL: {signed_url[:100]}...")
    
    resp = requests.get(signed_url, timeout=10)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print(f"Content Length: {len(resp.content)} bytes")
        print(f"Content-Type: {resp.headers.get('Content-Type')}")
        print("✅ SUCCESS")
    else:
        print(f"Response: {resp.text[:200]}")
        print("❌ FAILED")
except ImportError:
    print("❌ Qiniu SDK not installed. Run: pip install qiniu")
except Exception as e:
    print(f"❌ ERROR: {e}")
print()

# Test 4: Alternative Qiniu domains
print("Test 4: Try Qiniu default domain (if available)")
# Qiniu default domain pattern: bucket.domain
default_domains = [
    f"{BUCKET}.bkt.clouddn.com",
    f"{BUCKET}.qiniudn.com",
]

for domain in default_domains:
    url = f"http://{domain}/{TEST_KEY}"
    print(f"Testing: {url}")
    try:
        resp = requests.get(url, timeout=5)
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 200:
            print("  ✅ This domain works!")
            print(f"  Suggest using: {domain}")
            break
    except Exception as e:
        print(f"  ❌ {e}")
print()

print("=" * 80)
print("Recommendation:")
print("=" * 80)
print("If all tests fail with 403, the issue might be:")
print("1. CDN domain not properly bound in Qiniu console")
print("2. Bucket ACL settings (even if set to public, CDN config matters)")
print("3. Need to use Qiniu's default test domain instead of custom CDN domain")
print()
print("Solution:")
print("1. Go to Qiniu Console → wecom-bot-storage → Domain Management")
print("2. Either:")
print("   a) Bind your custom domain properly with CDN")
print("   b) Or use Qiniu's default test domain (bucket.bkt.clouddn.com)")
print("=" * 80)
