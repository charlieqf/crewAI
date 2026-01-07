import os
import sys
import logging
import json

# Add project src to path
sys.path.append("/opt/wecom-callback")

def load_env(path):
    if not os.path.exists(path):
        return
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

# Load env before importing SDK to ensure env vars are available
load_env("/etc/wecom-callback/env")

from src.crewai_enterprise.utils.wework_finance_sdk import WeWorkFinanceSDK

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_sdk_full():
    corp_id = os.getenv("WECOM_CORP_ID")
    secret = os.getenv("ARCHIVE_SECRET")
    
    print(f"Testing with CorpID: {corp_id}")
    if not corp_id or not secret:
        print("Error: WECOM_CORP_ID or ARCHIVE_SECRET not set in environment")
        return

    try:
        sdk = WeWorkFinanceSDK()
        print("SDK Instance created")
        
        if not sdk.init(corp_id, secret):
            print("SDK Initialization failed")
            return
            
        print("SDK Initialized successfully")
        
        # Test GetChatData
        print("Testing GetChatData (seq=0, limit=1)...")
        chat_data = sdk.get_chat_data(0, 1)
        
        if chat_data is None:
            print("GetChatData returned None (Error)")
        elif len(chat_data) == 0:
            print("GetChatData returned empty list (No data yet or caught up)")
        else:
            print(f"GetChatData returned {len(chat_data)} items")
            print(json.dumps(chat_data[0], indent=2))
            
            # DecryptData test would need RSA decryption of the key
            # and real private key. For now, just verifying it doesn't crash on pull.

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_sdk_full()
