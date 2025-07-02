#!/usr/bin/env python3
"""
Simple test script to verify the realtime chat app functionality.
"""

import requests
import json
import time
from threading import Thread
import sys

# Test configuration
FLASK_URL = "http://127.0.0.1:5001"
TEST_MESSAGES = [
    {"sender": "Alice", "content": "Hello everyone!"},
    {"sender": "Bob", "content": "Hi Alice, how are you?"},
    {"sender": "Alice", "content": "I'm doing great, thanks for asking!"},
    {"sender": "Charlie", "content": "Can I join this conversation?"},
    {"sender": "Bob", "content": "Of course! Welcome Charlie!"}
]

def test_send_message(sender, content):
    """Test sending a message to the chat."""
    try:
        response = requests.post(
            f"{FLASK_URL}/send_message",
            headers={"Content-Type": "application/json"},
            json={"sender": sender, "content": content},
            timeout=5
        )
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "success":
                print(f"✅ Message sent successfully: {sender}: {content}")
                return True
            else:
                print(f"❌ Error sending message: {result.get('message')}")
                return False
        else:
            print(f"❌ HTTP error {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception sending message: {e}")
        return False

def test_homepage():
    """Test if the homepage loads correctly."""
    try:
        response = requests.get(FLASK_URL, timeout=5)
        if response.status_code == 200 and "Real-Time Chat" in response.text:
            print("✅ Homepage loads correctly")
            return True
        else:
            print(f"❌ Homepage error: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Exception accessing homepage: {e}")
        return False

def test_sse_stream():
    """Test if the SSE stream is working."""
    print("🔄 Testing SSE stream...")
    try:
        response = requests.get(f"{FLASK_URL}/stream", stream=True, timeout=10)
        if response.status_code == 200:
            # Read a few lines to see if we get heartbeats
            lines = []
            for i, line in enumerate(response.iter_lines(decode_unicode=True)):
                if line:
                    lines.append(line)
                if i >= 5:  # Read first few lines
                    break
            
            if lines:
                print("✅ SSE stream is working (receiving data)")
                return True
            else:
                print("❌ SSE stream not receiving data")
                return False
        else:
            print(f"❌ SSE stream error: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Exception testing SSE: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Starting realtime chat app tests...")
    print("=" * 50)
    
    # Test 1: Homepage
    print("Test 1: Homepage accessibility")
    if not test_homepage():
        print("❌ Basic functionality test failed. Stopping tests.")
        sys.exit(1)
    
    # Test 2: Send messages
    print("\nTest 2: Sending messages")
    success_count = 0
    for msg in TEST_MESSAGES:
        if test_send_message(msg["sender"], msg["content"]):
            success_count += 1
        time.sleep(0.5)  # Small delay between messages
    
    print(f"📊 Message sending: {success_count}/{len(TEST_MESSAGES)} successful")
    
    # Test 3: SSE Stream
    print("\nTest 3: Server-Sent Events stream")
    test_sse_stream()
    
    print("\n" + "=" * 50)
    print("🎉 Test suite completed!")
    print("💡 To test the UI, open http://127.0.0.1:5001 in your browser")
    print("💡 You should see the messages sent during this test")

if __name__ == "__main__":
    main()
