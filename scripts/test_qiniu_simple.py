import requests

print("Testing Qiniu bucket access via different methods\n")

# File to test
key = "wecom/20251231/a49d0e305f0f44c48a64825b9d6d2c96.html"
bucket = "wecom-bot-storage"

# Test different URLs
tests = [
    ("CDN test domain", "http://t83xy5wfa.sabkt.gdipper.com/wecom/20251231/a49d0e305f0f44c48a64825b9d6d2c96.html"),
    ("S3 endpoint", f"http://s3-cn-south-1.qiniucs.com/{bucket}/{key}"),
    ("iovip endpoint", f"http://iovip-z1.qbox.me/{bucket}/{key}"),
]

for name, url in tests:
    print(f"{name}:")
    print(f"  URL: {url}")
    try:
        r = requests.get(url, timeout=5)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            print(f"  ✅ SUCCESS! Content length: {len(r.content)} bytes")
            print(f"  First 100 chars: {r.text[:100]}")
            break
        else:
            print(f"  ❌ Error: {r.text[:150]}")
    except Exception as e:
        print(f"  ❌ Exception: {e}")
    print()
