import sys
import requests
import json

def send_webhook_message(webhook_url, content):
    """Send a message to WeCom group via Webhook."""
    payload = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("errcode") == 0:
            print(f"✅ Webhook message sent successfully!")
            return True
        else:
            print(f"❌ Failed to send webhook message: {data.get('errmsg')} (Code: {data.get('errcode')})")
            return False
    except Exception as e:
        print(f"❌ Error sending webhook message: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/poc_webhook_message.py <WEBHOOK_URL> <CONTENT>")
        sys.exit(1)
        
    url = sys.argv[1]
    msg = sys.argv[2]
    
    send_webhook_message(url, msg)
