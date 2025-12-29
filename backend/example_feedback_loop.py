"""
Example: Using NL2SQL Feedback Loop

This script demonstrates how to:
1. Generate SQL from natural language
2. Test the SQL
3. Submit feedback (positive or negative with corrections)
"""

import httpx
import json
import asyncio
from typing import Optional, Tuple
import app.dotenv as env

API_KEY = env.simac_api_key
BASE_URL = "http://localhost:80"


async def generate_sql(question: str, schema_name: str, culture: str = "en") -> Tuple[Optional[str], Optional[str]]:
    """
    Generate SQL from natural language question
    
    Returns:
        Tuple of (run_id, sql_query)
    """
    print(f"\n📝 Question: {question}")
    print(f"🗄️  Schema: {schema_name}")
    print(f"🌍 Culture: {culture}")
    print("\n⏳ Generating SQL...")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/nl2sql",
            headers={"api-key": API_KEY},
            json={
                "threadId": "",
                "question": question,
                "schema_name": schema_name,
                "culture": culture,
                "validate_execution": True
            }
        ) as response:
            run_id = None
            sql_query = ""
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        
                        if data["event"] == "on_start":
                            run_id = data["run_id"]
                            print(f"✅ Started (run_id: {run_id[:8]}...)")
                        
                        elif data["event"] == "on_stream":
                            token = data["data"]
                            sql_query += token
                            print(token, end="", flush=True)
                        
                        elif data["event"] == "on_end":
                            sql_query = data["sql"]
                            latency = data["latency"]
                            print(f"\n\n⚡ Generated in {latency:.2f}s")
                        
                        elif data["event"] == "on_error":
                            print(f"\n❌ Error: {data['data']}")
                            return None, None
                    
                    except json.JSONDecodeError:
                        continue
            
            return run_id, sql_query


async def submit_positive_feedback(run_id: str) -> bool:
    """Submit positive feedback for correct SQL"""
    print(f"\n✅ Submitting positive feedback for run_id: {run_id[:8]}...")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
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
            print(f"❌ Failed: {response.text}")
            return False


async def submit_negative_feedback(
    run_id: str,
    corrected_sql: str,
    comment: Optional[str] = None
) -> bool:
    """Submit negative feedback with corrected SQL"""
    print(f"\n❌ Submitting negative feedback for run_id: {run_id[:8]}...")
    print(f"🔧 Corrected SQL: {corrected_sql}")
    if comment:
        print(f"💬 Comment: {comment}")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{BASE_URL}/feedback",
            headers={"api-key": API_KEY},
            json={
                "run_id": run_id,
                "feedback": -1,
                "corrected_sql": corrected_sql,
                "comment": comment
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ {result['message']}")
            return True
        else:
            print(f"❌ Failed: {response.text}")
            return False


async def get_feedback_history(feedback_type: Optional[int] = None):
    """
    Get feedback history
    
    Args:
        feedback_type: Filter by feedback type (1=positive, -1=negative, None=all)
    """
    print(f"\n📊 Fetching feedback history...")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        payload = {}
        if feedback_type is not None:
            payload["feedback"] = feedback_type
        
        response = await client.post(
            f"{BASE_URL}/history",
            headers={"api-key": API_KEY},
            json=payload
        )
        
        if response.status_code == 200:
            records = response.json()
            print(f"\n📈 Found {len(records)} records")
            
            for i, record in enumerate(records[:5], 1):  # Show first 5
                print(f"\n{i}. Question: {record['input']}")
                print(f"   SQL: {record['output']}")
                print(f"   Feedback: {record.get('feedback', 0)}")
                if record.get('corrected_sql'):
                    print(f"   Corrected: {record['corrected_sql']}")
                if record.get('feedback_comment'):
                    print(f"   Comment: {record['feedback_comment']}")
            
            return records
        else:
            print(f"❌ Failed: {response.text}")
            return []


async def example_workflow_correct_sql():
    """Example: User asks question, SQL is correct, submit positive feedback"""
    print("\n" + "="*80)
    print("EXAMPLE 1: Correct SQL - Positive Feedback")
    print("="*80)
    
    # Step 1: Generate SQL
    run_id, sql = await generate_sql(
        question="لیست همه محصولات را نشان بده",
        schema_name="simacnashr",
        culture="fa",
    )
    
    if not run_id or not sql:
        print("Failed to generate SQL")
        return
    
    # Step 2: User tests SQL (simulated)
    print("\n🧪 Testing SQL in database...")
    print("✅ SQL executed successfully! Results look correct.")
    
    # Step 3: Submit positive feedback
    await submit_positive_feedback(run_id)


async def example_workflow_incorrect_sql():
    """Example: User asks question, SQL is wrong, submit correction"""
    print("\n" + "="*80)
    print("EXAMPLE 2: Incorrect SQL - Negative Feedback with Correction")
    print("="*80)
    
    # Step 1: Generate SQL
    run_id, sql = await generate_sql(
        question="لیست همه مشتری هایی که پرفروش ترین تاب را بیش از 10 بار خریده اند بگو",
        schema_name="simacnashr",
        culture="fa"
    )
    
    if not run_id or not sql:
        print("Failed to generate SQL")
        return
    
    # Step 2: User tests SQL (simulated)
    print("\n🧪 Testing SQL in database...")
    print("❌ SQL has an error! The date calculation is wrong.")
    
    # Step 3: Submit negative feedback with correction
    corrected_sql = "SELECT COUNT(*) FROM orders WHERE order_date >= DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH)"
    await submit_negative_feedback(
        run_id=run_id,
        corrected_sql=corrected_sql,
        comment="Used wrong date function - should use DATE_SUB with CURRENT_DATE"
    )


async def example_view_history():
    """Example: View feedback history"""
    print("\n" + "="*80)
    print("EXAMPLE 3: View Feedback History")
    print("="*80)
    
    # View all negative feedback
    await get_feedback_history(feedback_type=-1)


async def main():
    """Run all examples"""
    print("""
╔════════════════════════════════════════════════════════════════╗
║                 NL2SQL Feedback Loop Examples                  ║
╚════════════════════════════════════════════════════════════════╝

This script demonstrates the complete feedback loop workflow:
- Generate SQL from natural language
- Test the generated SQL
- Submit feedback (positive or negative)
- View feedback history

Make sure to:
1. Update API_KEY in this script
2. Ensure the backend server is running
3. Have a valid schema configured
""")
    
    input("Press Enter to start examples...")
    
    # Example 1: Correct SQL
    await example_workflow_correct_sql()
    
    input("\n\nPress Enter for next example...")
    
    # Example 2: Incorrect SQL
    await example_workflow_incorrect_sql()
    
    input("\n\nPress Enter for next example...")
    
    # Example 3: View history
    await example_view_history()
    
    print("\n\n✅ All examples completed!")
    print("\n💡 Next steps:")
    print("1. Integrate feedback UI in your frontend")
    print("2. Set up monitoring dashboard")
    print("3. Analyze feedback patterns to improve the system")
    print("4. Use feedback data for model fine-tuning")


if __name__ == "__main__":
    asyncio.run(main())
