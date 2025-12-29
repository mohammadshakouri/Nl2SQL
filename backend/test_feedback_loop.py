"""
Quick Test Script for Feedback Loop

This script performs a quick smoke test of the feedback loop functionality.
Run this after starting your backend server to verify everything works.
"""

import httpx
import json
import sys
import app.dotenv as env

# Configuration
API_KEY = env.simac_api_key  # UPDATE THIS!
BASE_URL = "http://localhost:80"
TIMEOUT = 30.0
    

def test_connection():
    """Test basic server connectivity"""
    print("🔌 Testing server connection...")
    try:
        response = httpx.get(f"{BASE_URL}/docs", timeout=5.0)
        if response.status_code == 200:
            print("✅ Server is running")
            return True
        else:
            print(f"⚠️  Server returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Cannot connect to server: {e}")
        print("   Make sure the backend is running on localhost:80")
        return False


def test_nl2sql_endpoint():
    """Test NL2SQL endpoint and get a run_id"""
    print("\n📝 Testing /nl2sql endpoint...")
    
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            with client.stream(
                "POST",
                f"{BASE_URL}/nl2sql",
                headers={"api-key": API_KEY},
                json={
                    "threadId": "",
                    "question": "Show all customers",
                    "schema_name": "simacnashr",
                    "culture": "fa",
                    "validate_execution": False
                }
            ) as response:
                if response.status_code != 200:
                    print(f"❌ Request failed with status {response.status_code}")
                    error_content = response.read().decode('utf-8')
                    print(f"   Response: {error_content}")
                    return None
                
                run_id = None
                sql = ""
                
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            
                            if data["event"] == "on_start":
                                run_id = data["run_id"]
                                print(f"✅ Got run_id: {run_id[:16]}...")
                            
                            elif data["event"] == "on_stream":
                                sql += data["data"]
                            
                            elif data["event"] == "on_end":
                                print(f"✅ SQL generated: {sql[:50]}...")
                                return run_id
                            
                            elif data["event"] == "on_error":
                                print(f"❌ Error: {data['data']}")
                                return None
                        except json.JSONDecodeError:
                            continue
                
                return run_id
    
    except httpx.TimeoutException:
        print("❌ Request timed out")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_positive_feedback(run_id: str):
    """Test submitting positive feedback"""
    print(f"\n👍 Testing positive feedback for run_id: {run_id[:16]}...")
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{BASE_URL}/feedback",
                headers={"api-key": API_KEY},
                json={
                    "run_id": run_id,
                    "feedback": 1
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ {result['message']}")
                return True
            else:
                print(f"❌ Failed with status {response.status_code}")
                print(f"   Response: {response.text}")
                return False
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_negative_feedback(run_id: str):
    """Test submitting negative feedback with correction"""
    print(f"\n👎 Testing negative feedback for run_id: {run_id[:16]}...")
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{BASE_URL}/feedback",
                headers={"api-key": API_KEY},
                json={
                    "run_id": run_id,
                    "feedback": -1,
                    "corrected_sql": "SELECT * FROM customers WHERE active = 1",
                    "comment": "Test correction - added active filter"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ {result['message']}")
                return True
            else:
                print(f"❌ Failed with status {response.status_code}")
                print(f"   Response: {response.text}")
                return False
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_history_endpoint():
    """Test history endpoint"""
    print("\n📊 Testing /history endpoint...")
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{BASE_URL}/history",
                headers={"api-key": API_KEY},
                json={}
            )
            
            if response.status_code == 200:
                records = response.json()
                print(f"✅ Retrieved {len(records)} records")
                
                if len(records) > 0:
                    # Show the first record
                    record = records[0]
                    print(f"\n   Latest record:")
                    print(f"   - Question: {record.get('input', 'N/A')[:50]}...")
                    print(f"   - Feedback: {record.get('feedback', 'N/A')}")
                    if record.get('corrected_sql'):
                        print(f"   - Has correction: Yes")
                
                return True
            else:
                print(f"❌ Failed with status {response.status_code}")
                return False
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║         NL2SQL Feedback Loop - Quick Test Script          ║
╚═══════════════════════════════════════════════════════════╝
""")
    
    # Check if API_KEY is set
    if API_KEY == "your-api-key-here":
        print("❌ ERROR: Please update API_KEY in this script!")
        print("   Edit the script and set API_KEY to your actual API key.")
        sys.exit(1)
    
    results = {
        "connection": False,
        "nl2sql": False,
        "positive_feedback": False,
        "negative_feedback": False,
        "history": False
    }
    
    # Test 1: Connection
    results["connection"] = test_connection()
    if not results["connection"]:
        print("\n❌ Cannot proceed - server is not accessible")
        sys.exit(1)
    
    # Test 2: NL2SQL endpoint (get run_id for feedback tests)
    run_id = test_nl2sql_endpoint()
    results["nl2sql"] = run_id is not None
    
    if run_id:
        # Test 3: Positive feedback
        results["positive_feedback"] = test_positive_feedback(run_id)
        
        # Generate another query for negative feedback test
        print("\n🔄 Generating another query for negative feedback test...")
        run_id2 = test_nl2sql_endpoint()
        
        if run_id2:
            # Test 4: Negative feedback
            results["negative_feedback"] = test_negative_feedback(run_id2)
    
    # Test 5: History endpoint
    results["history"] = test_history_endpoint()
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name.replace('_', ' ').title():.<40} {status}")
    
    print("="*60)
    
    all_passed = all(results.values())
    if all_passed:
        print("\n🎉 All tests passed! Feedback loop is working correctly.")
        print("\nNext steps:")
        print("1. Try the full example: python example_feedback_loop.py")
        print("2. Read the guide: FEEDBACK_LOOP_GUIDE.md")
        print("3. Integrate feedback UI in your frontend")
    else:
        print("\n⚠️  Some tests failed. Please check:")
        print("1. Backend server is running")
        print("2. API_KEY is correct")
        print("3. Database is accessible")
        print("4. Schema is properly configured")
        sys.exit(1)


if __name__ == "__main__":
    main()
