import urllib.request
import json
import sys

BASE_URL = "http://127.0.0.1:8000"

def get_json(url):
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode())

def test_dataset_format():
    # 1. Test Crypto (ETH)
    print("Testing Crypto (ETH)...")
    try:
        url = f"{BASE_URL}/api/candles?dataset=ETHUSDT_2Y_OHLCV_Trans&interval=1d"
        data = get_json(url)
        if not data["candles"]:
            print("ETH: No candles returned")
            return
        
        first_time = data["candles"][0]["time"]
        print(f"ETH Time Sample: {first_time} (Type: {type(first_time)})")
        
        if not isinstance(first_time, int):
            print("FAIL: ETH time should be int (timestamp)")
        else:
            print("PASS: ETH time is int")
            
    except Exception as e:
        print(f"ETH Test Failed: {e}")

    # 2. Test Stock (SAMSUNG)
    print("\nTesting Stock (SAMSUNG)...")
    try:
        url = f"{BASE_URL}/api/candles?dataset=SAMSUNG_2Y_OHLCV&interval=1d"
        data = get_json(url)
        if not data["candles"]:
            print("SAMSUNG: No candles returned")
            return
        
        first_time = data["candles"][0]["time"]
        print(f"SAMSUNG Time Sample: {first_time} (Type: {type(first_time)})")
        
        if not isinstance(first_time, str):
            print("FAIL: SAMSUNG time should be str (YYYY-MM-DD)")
        else:
            print("PASS: SAMSUNG time is str")

    except Exception as e:
        print(f"SAMSUNG Test Failed: {e}")

if __name__ == "__main__":
    test_dataset_format()
