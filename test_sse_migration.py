import sys
import requests
import json

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def test_sse_migration():
    """Test the Server-Sent Events migration endpoint"""
    
    # Configuration
    base_url = "https://anydash.reshu.app"
    node_id = 2
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJyZXNpc3QiLCJhY2Nlc3MiOiJzdWRvIiwiaWF0IjoxNzY1OTcxODQyLCJleHAiOjE3NjYwNTgyNDJ9.SF91it1-AnY5R9apg09GJ-cMMLcdtJVwSxZrXhmQYrc"
    
    # Build URL with query parameters
    url = f"{base_url}/api/nodes/{node_id}/migrate"
    params = {
        "token": token,
        "ssh_user": "root",
        "ssh_port": "22",
        "ssh_password": "6tM3i7qsmM"
    }
    
    print(f"Testing SSE migration endpoint...")
    print(f"URL: {url}")
    print(f"Node ID: {node_id}")
    print("=" * 60)
    
    try:
        # Make streaming request
        response = requests.get(url, params=params, stream=True, timeout=300)
        
        print(f"Status Code: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        print("=" * 60)
        
        if response.status_code == 200:
            print("\n[OK] Connection established! Receiving events...\n")
            
            # Process Server-Sent Events
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                
                # Parse SSE format
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                    print(f"\n[EVENT: {event_type}]")
                elif line.startswith("data:"):
                    data_json = line.split(":", 1)[1].strip()
                    try:
                        data = json.loads(data_json)
                        print(json.dumps(data, indent=2, ensure_ascii=False))
                    except json.JSONDecodeError:
                        print(data_json)
                
        else:
            print(f"\n[ERROR] Request failed with status {response.status_code}")
            print(f"Response: {response.text}")
            
    except requests.exceptions.Timeout:
        print("\n[ERROR] Request timed out after 5 minutes")
    except requests.exceptions.RequestException as e:
        print(f"\n[ERROR] Request failed: {e}")
    except KeyboardInterrupt:
        print("\n\n[INFO] Interrupted by user")

if __name__ == "__main__":
    test_sse_migration()

