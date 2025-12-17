import asyncio
import websockets
import sys

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

async def test_websocket(uri, name):
    try:
        print(f"\nTesting {name}...")
        async with websockets.connect(uri, open_timeout=5) as websocket:
            print(f"  [OK] Connected to {name}")
            return True
    except websockets.exceptions.InvalidStatus as e:
        print(f"  [ERROR] HTTP {e.response.status_code} - Endpoint not found")
        return False
    except Exception as e:
        print(f"  [INFO] {type(e).__name__}: {e}")
        return False

async def main():
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJyZXNpc3QiLCJhY2Nlc3MiOiJzdWRvIiwiaWF0IjoxNzY1OTcxODQyLCJleHAiOjE3NjYwNTgyNDJ9.SF91it1-AnY5R9apg09GJ-cMMLcdtJVwSxZrXhmQYrc"
    
    endpoints = [
        (f"wss://anydash.reshu.app/api/nodes/2/xray/logs?token={token}", "Node Xray Logs"),
        (f"wss://anydash.reshu.app/api/nodes/2/sing-box/logs?token={token}", "Node Sing-box Logs"),
        (f"wss://anydash.reshu.app/api/nodes/2/migrate?token={token}&ssh_user=root&ssh_port=22&ssh_password=test", "Node Migration"),
    ]
    
    print("Testing WebSocket endpoints on anydash.reshu.app...")
    print("=" * 60)
    
    for uri, name in endpoints:
        await test_websocket(uri, name)
    
    print("\n" + "=" * 60)
    print("Summary: If logs endpoints work but migration doesn't,")
    print("         the server is likely running an older version.")

if __name__ == "__main__":
    asyncio.run(main())

