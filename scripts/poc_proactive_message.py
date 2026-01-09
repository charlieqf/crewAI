import os
import sys
import json
import requests
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_access_token(corp_id, secret):
    """Fetch access token from WeCom API."""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={secret}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("errcode") == 0:
            return data.get("access_token")
        else:
            logger.error(f"Failed to get token: {data.get('errmsg')}")
            return None
    except Exception as e:
        logger.error(f"Error fetching token: {e}")
        return None

def send_proactive_message(chat_id, content, agent_id, access_token):
    """Send a proactive message to a specific chat_id."""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
    
    payload = {
        "chatid": chat_id,
        "msgtype": "text",
        "agentid": agent_id,
        "text": {
            "content": content
        },
        "safe": 0
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("errcode") == 0:
            logger.info(f"✅ Message sent successfully to {chat_id}")
            return True
        else:
            logger.error(f"❌ Failed to send message: {data.get('errmsg')} (Code: {data.get('errcode')})")
            logger.error(f"Payload: {json.dumps(payload)}")
            return False
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return False

if __name__ == "__main__":
    # Load environment variables from .env
    load_dotenv()
    
    # Configuration (Prioritizing the ones you just shared)
    CORP_ID = os.getenv("WECOM_CORP_ID", "wwd6d27c7581b127b9")
    AGENT_ID = os.getenv("WECOM_AGENT_ID", "1000038")
    SECRET = os.getenv("WECOM_SECRET", "1f4FiIxltSRVXIhuGRN6kE4EUF85sNUEiNByPQZst0k")
    
    if len(sys.argv) < 3:
        print("Usage: python scripts/poc_proactive_message.py <CHAT_ID> <CONTENT>")
        print("Example: python scripts/poc_proactive_message.py \"wrXXXXXXXX\" \"Hello World!\"")
        sys.exit(1)
        
    target_chat_id = sys.argv[1]
    message_content = sys.argv[2]
    
    logger.info("Step 1: Fetching Access Token...")
    token = get_access_token(CORP_ID, SECRET)
    
    if token:
        logger.info(f"Step 2: Sending message to {target_chat_id}...")
        send_proactive_message(target_chat_id, message_content, AGENT_ID, token)
    else:
        logger.error("Failed to proceed without access token.")
