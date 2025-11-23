import urllib.request
import json
import sys

BASE_URL = "http://127.0.0.1:8000"

def get_json(url):
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode())

def test_dataset_type():
    # 1. Test Crypto (ETH)
    print("Testing Crypto (ETH)...")
    try:
        url = f"{BASE_URL}/api/candles?dataset=ETHUSDT_2Y_OHLCV_Trans&interval=1d"
        data = get_json(url)
        print(f"ETH Type: {data.get('type')}")
        
        if data.get("type") != "crypto":
            print("FAIL: ETH type should be 'crypto'")
        else:
            print("PASS: ETH type is 'crypto'")
            
    except Exception as e:
        print(f"ETH Test Failed: {e}")

    # 2. Test Stock (SAMSUNG)
    print("\nTesting Stock (SAMSUNG)...")
    try:
        url = f"{BASE_URL}/api/candles?dataset=SAMSUNG_2Y_OHLCV&interval=1d"
        data = get_json(url)
        print(f"SAMSUNG Type: {data.get('type')}")
        
        if data.get("type") != "stock":
            print("FAIL: SAMSUNG type should be 'stock'")
        else:
            print("PASS: SAMSUNG type is 'stock'")

    except Exception as e:
        print(f"SAMSUNG Test Failed: {e}")

if __name__ == "__main__":
    test_dataset_type()
