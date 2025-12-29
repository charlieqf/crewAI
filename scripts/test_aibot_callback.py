#!/usr/bin/env python
"""
Interactive Test Script for AI Bot Callback.

This script simulates WeCom intelligent robot callbacks to test the local server.
It handles the JSON encryption/decryption required by the AI bot protocol.

Usage:
    1. Start the server: python -m uvicorn src.crewai_enterprise.server.wecom_callback:app --reload --port 8000
    2. Run this script: python scripts/test_aibot_callback.py

The script will:
    1. Test URL verification endpoint
    2. Test text message handling (with real LLM call if API keys are present)
    3. Test stream refresh
"""

import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Test configuration
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")
TEST_TOKEN = os.getenv("GEMINI_BOT_TOKEN", "test_token_12345")
TEST_AES_KEY = os.getenv("GEMINI_BOT_ENCODING_AES_KEY", "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG")
BOT_TYPE = "gemini"  # Can be: gemini, chatgpt, grok


def get_crypto():
    """Get crypto instance for the test bot."""
    from src.crewai_enterprise.utils.wecom_json_crypto import WXBizJsonMsgCrypt
    return WXBizJsonMsgCrypt(TEST_TOKEN, TEST_AES_KEY, "")


def test_health_endpoint():
    """Test the health check endpoint."""
    print("\n" + "=" * 60)
    print("📋 Testing Health Endpoint")
    print("=" * 60)
    
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200
    except requests.exceptions.ConnectionError:
        print("❌ Connection failed. Is the server running?")
        print(f"   Expected server at: {BASE_URL}")
        return False


def test_url_verification():
    """Test the URL verification endpoint."""
    print("\n" + "=" * 60)
    print("🔐 Testing URL Verification")
    print("=" * 60)
    
    crypto = get_crypto()
    
    # Generate test parameters
    timestamp = str(int(time.time()))
    nonce = "test_nonce_123"
    echostr = "test_echo_string"
    
    # Encrypt echostr
    ret, encrypted_echo = crypto.EncryptMsg(echostr, nonce, timestamp)
    if ret != 0:
        print(f"❌ Failed to encrypt echostr: {ret}")
        return False
    
    # Extract encrypted content
    encrypted_data = json.loads(encrypted_echo)
    
    # Make request
    url = f"{BASE_URL}/ai-bot/{BOT_TYPE}"
    params = {
        "msg_signature": encrypted_data["msgsignature"],
        "timestamp": timestamp,
        "nonce": nonce,
        "echostr": encrypted_data["encrypt"]
    }
    
    print(f"URL: {url}")
    print(f"Params: {json.dumps(params, indent=2)}")
    
    response = requests.get(url, params=params, timeout=10)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:200]}")
    
    if response.status_code == 200 and response.text == echostr:
        print("✅ URL verification passed!")
        return True
    else:
        print(f"❌ URL verification failed. Expected echostr={echostr}")
        return False


def test_text_message(message_content: str = "你好，请介绍一下你自己。"):
    """Test sending a text message to the bot."""
    print("\n" + "=" * 60)
    print("💬 Testing Text Message")
    print("=" * 60)
    
    crypto = get_crypto()
    
    # Generate test parameters
    timestamp = str(int(time.time()))
    nonce = "test_nonce_456"
    msg_id = f"msg_{int(time.time() * 1000)}"
    
    # Create message payload
    message = {
        "msgtype": "text",
        "msgid": msg_id,
        "chat_id": "test_group_123",
        "from": {
            "user_id": "test_user",
            "name": "测试用户"
        },
        "text": {
            "content": message_content
        }
    }
    
    print(f"Message: {json.dumps(message, ensure_ascii=False, indent=2)}")
    
    # Encrypt message
    message_json = json.dumps(message, ensure_ascii=False)
    ret, encrypted = crypto.EncryptMsg(message_json, nonce, timestamp)
    if ret != 0:
        print(f"❌ Failed to encrypt message: {ret}")
        return None
    
    encrypted_data = json.loads(encrypted)
    
    # Make request
    url = f"{BASE_URL}/ai-bot/{BOT_TYPE}"
    params = {
        "msg_signature": encrypted_data["msgsignature"],
        "timestamp": timestamp,
        "nonce": nonce
    }
    
    print(f"\nSending to: {url}")
    response = requests.post(
        url, 
        params=params, 
        data=encrypted, 
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    
    print(f"Status: {response.status_code}")
    
    if response.status_code != 200:
        print(f"❌ Request failed: {response.text}")
        return None
    
    # Decrypt response
    response_data = json.loads(response.text)
    print(f"Encrypted response: {json.dumps(response_data, indent=2)[:300]}...")
    
    ret, decrypted = crypto.DecryptMsg(
        response.text.encode(),
        response_data.get("msgsignature"),
        str(response_data.get("timestamp")),
        nonce
    )
    
    if ret != 0:
        print(f"❌ Failed to decrypt response: {ret}")
        return None
    
    decrypted_data = json.loads(decrypted)
    print(f"\n✅ Decrypted response:")
    print(json.dumps(decrypted_data, ensure_ascii=False, indent=2))
    
    return decrypted_data


def test_stream_refresh(stream_id: str):
    """Test stream refresh to get updated content."""
    print("\n" + "=" * 60)
    print("🔄 Testing Stream Refresh")
    print("=" * 60)
    
    crypto = get_crypto()
    
    timestamp = str(int(time.time()))
    nonce = "test_nonce_789"
    
    # Create stream refresh request
    refresh_msg = {
        "msgtype": "stream",
        "stream": {
            "id": stream_id
        }
    }
    
    print(f"Refresh request: {json.dumps(refresh_msg, indent=2)}")
    
    # Encrypt
    refresh_json = json.dumps(refresh_msg)
    ret, encrypted = crypto.EncryptMsg(refresh_json, nonce, timestamp)
    if ret != 0:
        print(f"❌ Failed to encrypt refresh: {ret}")
        return None
    
    encrypted_data = json.loads(encrypted)
    
    # Make request
    url = f"{BASE_URL}/ai-bot/{BOT_TYPE}"
    params = {
        "msg_signature": encrypted_data["msgsignature"],
        "timestamp": timestamp,
        "nonce": nonce
    }
    
    response = requests.post(
        url,
        params=params,
        data=encrypted,
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    
    if response.status_code != 200:
        print(f"❌ Request failed: {response.text}")
        return None
    
    # Decrypt response
    response_data = json.loads(response.text)
    ret, decrypted = crypto.DecryptMsg(
        response.text.encode(),
        response_data.get("msgsignature"),
        str(response_data.get("timestamp")),
        nonce
    )
    
    if ret != 0:
        print(f"❌ Failed to decrypt response: {ret}")
        return None
    
    decrypted_data = json.loads(decrypted)
    print(f"✅ Stream response:")
    print(json.dumps(decrypted_data, ensure_ascii=False, indent=2))
    
    return decrypted_data


def run_full_test():
    """Run a full test of the AI bot workflow."""
    print("\n" + "=" * 60)
    print("🚀 AI Bot Callback Full Test")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"Bot Type: {BOT_TYPE}")
    print(f"Token configured: {'Yes' if TEST_TOKEN else 'No'}")
    print(f"AES Key configured: {'Yes' if TEST_AES_KEY else 'No'}")
    
    # 1. Health check
    if not test_health_endpoint():
        print("\n❌ Server not reachable. Please start the server first.")
        print(f"   Run: python -m uvicorn src.crewai_enterprise.server.wecom_callback:app --reload --port 8000")
        return
    
    # 2. URL verification
    if not test_url_verification():
        print("\n❌ URL verification failed.")
        return
    
    # 3. Text message
    response = test_text_message("你好！请用简短的话介绍一下你自己。")
    if not response:
        print("\n❌ Text message test failed.")
        return
    
    # Check if we got a stream response
    if response.get("msgtype") == "stream":
        stream_id = response.get("stream", {}).get("id")
        finish = response.get("stream", {}).get("finish", False)
        
        # 4. Poll for completion
        print("\n⏳ Waiting for LLM response...")
        max_polls = 30
        for i in range(max_polls):
            time.sleep(2)
            refresh_response = test_stream_refresh(stream_id)
            
            if refresh_response and refresh_response.get("stream", {}).get("finish"):
                print("\n" + "=" * 60)
                print("🎉 TEST COMPLETED SUCCESSFULLY!")
                print("=" * 60)
                final_content = refresh_response.get("stream", {}).get("content", "")
                print(f"\n📝 Final AI Response:\n{final_content}")
                return
            
            print(f"   Poll {i+1}/{max_polls}: Still processing...")
        
        print("\n⚠️ Timeout waiting for LLM response.")
    else:
        print(f"\n⚠️ Unexpected response type: {response.get('msgtype')}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test AI Bot Callback")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of the server")
    parser.add_argument("--bot", default="gemini", choices=["gemini", "chatgpt", "grok"], help="Bot type to test")
    parser.add_argument("--message", "-m", default="你好！请用简短的话介绍一下你自己。", help="Message to send")
    
    args = parser.parse_args()
    
    BASE_URL = args.url
    BOT_TYPE = args.bot
    
    run_full_test()
