import asyncio
import websockets
import json
import sys

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

async def test_migration_websocket():
    uri = "wss://anydash.reshu.app/api/nodes/2/migrate?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJyZXNpc3QiLCJhY2Nlc3MiOiJzdWRvIiwiaWF0IjoxNzY1OTcxODQyLCJleHAiOjE3NjYwNTgyNDJ9.SF91it1-AnY5R9apg09GJ-cMMLcdtJVwSxZrXhmQYrc&ssh_user=root&ssh_port=22&ssh_password=6tM3i7qsmM"
    
    try:
        print(f"Attempting to connect to WebSocket migration endpoint...")
        print(f"URL: {uri[:80]}...")
        async with websockets.connect(uri) as websocket:
            print("[OK] WebSocket connected successfully!")
            
            # Wait for initial message
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(message)
                print(f"[OK] Received message: {data}")
            except asyncio.TimeoutError:
                print("[WARN] No message received within 5 seconds")
            except json.JSONDecodeError:
                print(f"[WARN] Received non-JSON message: {message}")
                
    except websockets.exceptions.InvalidStatus as e:
        print(f"[ERROR] WebSocket connection rejected with HTTP {e.response.status_code}")
        print(f"[ERROR] This means the endpoint does not exist on the server")
        print(f"\nPossible causes:")
        print(f"  1. Server is running an older version without the migration endpoint")
        print(f"  2. The endpoint is not properly registered")
        print(f"  3. Nginx/reverse proxy is not configured for WebSocket routing")
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test_migration_websocket())

