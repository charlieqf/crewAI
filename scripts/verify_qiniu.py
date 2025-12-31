import os
import sys
from qiniu import Auth, BucketManager

def verify_qiniu_creds(ak, sk):
    print(f"--- Verifying Qiniu Credentials ---")
    print(f"AK: {ak[:4]}...{ak[-4:]}")
    
    try:
        q = Auth(ak, sk)
        bucket_manager = BucketManager(q)
        
        # Test: List buckets (requires valid AK/SK)
        buckets, info = bucket_manager.buckets()
        
        if info.status_code == 200:
            print(f"✅ Success! Connected to Qiniu.")
            print(f"Available Buckets: {buckets}")
            return True
        else:
            print(f"❌ Failed to connect. Status Code: {info.status_code}")
            print(f"Error Message: {info.text_body}")
            return False
            
    except Exception as e:
        print(f"❌ Exception occurred: {e}")
        return False

if __name__ == "__main__":
    # In a real scenario, we'd use env vars, but here we test the provided keys
    # Note: These are the user's provided keys
    ak = "ScTsKz5mYH7PiGc0zMI1Q346JeImXmSCiufteaAx"
    sk = "rUaEP6LYTbMMBJFpN6_Bgia2t4B7ewlKwqETwdWH"
    
    success = verify_qiniu_creds(ak, sk)
    if not success:
        sys.exit(1)
