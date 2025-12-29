# NL2SQL Feedback Loop Implementation Guide

## Overview

This system now includes a comprehensive feedback loop mechanism that allows users to provide feedback on generated SQL queries and submit corrections when queries are incorrect.

## Features

### 1. **Feedback Submission**
Users can submit feedback for any generated SQL query with the following information:
- **Positive feedback** (feedback=1): Mark query as correct
- **Negative feedback** (feedback=-1): Mark query as incorrect
- **Corrected SQL**: Provide the correct SQL when marking as incorrect
- **Comment**: Optional comment explaining the issue or correction

### 2. **Database Tracking**
All SQL queries and feedback are stored in the database with:
- `run_id`: Unique identifier for each query generation
- `feedback`: Feedback value (0=no feedback, 1=positive, -1=negative)
- `corrected_sql`: Corrected SQL provided by user
- `feedback_comment`: Optional user comment
- `status`: Query status (generated, success, corrected, error)

## API Endpoints

### 1. Generate SQL Query: POST `/nl2sql`

**Request:**
```json
{
  "threadId": "optional-thread-id",
  "question": "Show me all customers from Tehran",
  "schema_name": "ecommerce",
  "culture": "fa"
}
```

**Streaming Response:**
```
data: {"event": "on_start", "run_id": "uuid-123", "thread_id": "thread-456", "type": "nl2sql"}

data: {"event": "on_stream", "data": "SELECT"}

data: {"event": "on_stream", "data": " *"}

data: {"event": "on_end", "sql": "SELECT * FROM customers WHERE city='Tehran'", "latency": 1.23}
```

**Important:** Save the `run_id` from the `on_start` event - you'll need it to submit feedback!

---

### 2. Submit Feedback: POST `/feedback`

**Headers:**
```
api_key: your-api-key
Content-Type: application/json
```

**Request for Positive Feedback:**
```json
{
  "run_id": "uuid-123",
  "feedback": 1
}
```

**Request for Negative Feedback with Correction:**
```json
{
  "run_id": "uuid-123",
  "feedback": -1,
  "corrected_sql": "SELECT * FROM customers WHERE province='Tehran'",
  "comment": "Used wrong column - should be province not city"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Feedback submitted successfully",
  "run_id": "uuid-123",
  "feedback": -1
}
```

---

### 3. Query History: POST `/history`

Retrieve history with optional filters:

**Request:**
```json
{
  "run_id": "uuid-123",
  "feedback": -1,
  "from_time": "2025-01-01T00:00:00",
  "to_time": "2025-12-31T23:59:59"
}
```

**Response:**
```json
[
  {
    "start_time": "2025-12-28T10:30:00",
    "provinceName": "ecommerce",
    "input": "Show me all customers from Tehran",
    "output": "SELECT * FROM customers WHERE city='Tehran'",
    "culture": "fa",
    "is_user_authenticated": "yes",
    "feedback": -1,
    "corrected_sql": "SELECT * FROM customers WHERE province='Tehran'",
    "feedback_comment": "Used wrong column"
  }
]
```

## Usage Flow

### Basic Workflow

```
1. User asks question
   ↓
2. System generates SQL (returns run_id)
   ↓
3. User tests SQL in their database
   ↓
4a. If correct: Submit positive feedback
    POST /feedback with {"run_id": "...", "feedback": 1}
   ↓
4b. If incorrect: Submit negative feedback with correction
    POST /feedback with {
      "run_id": "...", 
      "feedback": -1,
      "corrected_sql": "...",
      "comment": "..."
    }
```

### Example: Python Client

```python
import httpx
import json

API_KEY = "your-api-key"
BASE_URL = "http://localhost:80"

async def generate_and_test_sql():
    # 1. Generate SQL
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/nl2sql",
            headers={"api_key": API_KEY},
            json={
                "threadId": "",
                "question": "How many orders in last month?",
                "schema_name": "ecommerce",
                "culture": "en"
            }
        )
        
        # Parse streaming response
        run_id = None
        sql_query = None
        
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data["event"] == "on_start":
                    run_id = data["run_id"]
                elif data["event"] == "on_end":
                    sql_query = data["sql"]
        
        print(f"Run ID: {run_id}")
        print(f"Generated SQL: {sql_query}")
        
        # 2. Test SQL in your database
        # ... execute sql_query ...
        
        # 3. Submit feedback
        if sql_works_correctly:
            # Positive feedback
            await client.post(
                f"{BASE_URL}/feedback",
                headers={"api_key": API_KEY},
                json={
                    "run_id": run_id,
                    "feedback": 1
                }
            )
        else:
            # Negative feedback with correction
            await client.post(
                f"{BASE_URL}/feedback",
                headers={"api_key": API_KEY},
                json={
                    "run_id": run_id,
                    "feedback": -1,
                    "corrected_sql": "SELECT COUNT(*) FROM orders WHERE order_date >= DATE_SUB(NOW(), INTERVAL 1 MONTH)",
                    "comment": "Original query had wrong date calculation"
                }
            )
```

### Example: JavaScript/TypeScript Client

```typescript
const API_KEY = "your-api-key";
const BASE_URL = "http://localhost:80";

async function generateAndTestSQL() {
  // 1. Generate SQL with streaming
  const response = await fetch(`${BASE_URL}/nl2sql`, {
    method: "POST",
    headers: {
      "api_key": API_KEY,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      threadId: "",
      question: "Show total sales by product",
      schema_name: "ecommerce",
      culture: "en"
    })
  });

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  
  let runId: string | null = null;
  let sqlQuery: string = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split("\n");

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = JSON.parse(line.slice(6));
        
        if (data.event === "on_start") {
          runId = data.run_id;
        } else if (data.event === "on_stream") {
          sqlQuery += data.data;
        } else if (data.event === "on_end") {
          sqlQuery = data.sql;
        }
      }
    }
  }

  console.log("Run ID:", runId);
  console.log("Generated SQL:", sqlQuery);

  // 2. Test SQL in your database
  // ... execute sqlQuery ...

  // 3. Submit feedback
  const feedbackResponse = await fetch(`${BASE_URL}/feedback`, {
    method: "POST",
    headers: {
      "api_key": API_KEY,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      run_id: runId,
      feedback: -1,
      corrected_sql: "SELECT product_name, SUM(amount) FROM sales GROUP BY product_name",
      comment: "Needed to use SUM and GROUP BY"
    })
  });

  const result = await feedbackResponse.json();
  console.log("Feedback result:", result);
}
```

## Database Schema

The `messages` table stores all queries and feedback:

```sql
CREATE TABLE messages (
    run_id TEXT PRIMARY KEY,
    thread_id TEXT,
    start_time TEXT,
    latency REAL,
    input TEXT,              -- User's question
    output TEXT,             -- Generated SQL
    culture TEXT,            -- fa or en
    provinceName TEXT,       -- Schema name
    is_user_authenticated TEXT,
    feedback INTEGER DEFAULT 0,           -- 0=none, 1=positive, -1=negative
    status TEXT DEFAULT 'error',          -- generated, success, corrected, error
    corrected_sql TEXT,                   -- User-provided correct SQL
    feedback_comment TEXT                 -- User's feedback comment
);
```

## Advanced: Learning from Feedback

To improve the system over time using feedback data:

### 1. **Retrieve Failed Queries for Analysis**

```python
async def get_failed_queries():
    """Get all queries with negative feedback"""
    response = await client.post(
        f"{BASE_URL}/history",
        headers={"api_key": API_KEY},
        json={"feedback": -1}
    )
    return response.json()
```

### 2. **Create Training Examples**

```python
async def create_training_examples():
    """Convert feedback into training examples for fine-tuning"""
    failed = await get_failed_queries()
    
    training_examples = []
    for item in failed:
        if item.get("corrected_sql"):
            training_examples.append({
                "question": item["input"],
                "correct_sql": item["corrected_sql"],
                "wrong_sql": item["output"],
                "schema": item["provinceName"],
                "comment": item.get("feedback_comment", "")
            })
    
    return training_examples
```

### 3. **Use as Few-Shot Examples**

Modify the system prompt to include successful corrections as examples:

```python
# In nl2sql_chain.py, add to system prompt:
examples = get_feedback_examples(schema_name, limit=5)
prompt += "\n\nExamples of correct queries:\n"
for ex in examples:
    prompt += f"Q: {ex['input']}\nA: {ex['corrected_sql']}\n\n"
```

## Best Practices

1. **Always save the run_id** from the initial response
2. **Test queries before submitting feedback** - execute in your database first
3. **Provide clear comments** explaining why a query is wrong
4. **Submit corrected SQL** that actually works in your database
5. **Use positive feedback too** - it helps identify what works well
6. **Review feedback regularly** to identify patterns in errors
7. **Monitor feedback rate** to track system improvement over time

## Monitoring and Analytics

### Query Success Rate

```python
async def get_success_rate():
    all_queries = await client.post(f"{BASE_URL}/history", 
                                   headers={"api_key": API_KEY}, 
                                   json={})
    queries = all_queries.json()
    
    total = len(queries)
    positive = len([q for q in queries if q["feedback"] == 1])
    negative = len([q for q in queries if q["feedback"] == -1])
    
    print(f"Total queries: {total}")
    print(f"Positive feedback: {positive} ({positive/total*100:.1f}%)")
    print(f"Negative feedback: {negative} ({negative/total*100:.1f}%)")
```

### Common Error Patterns

```python
async def analyze_common_errors():
    failed = await get_failed_queries()
    
    errors = {}
    for item in failed:
        comment = item.get("feedback_comment", "Unknown")
        errors[comment] = errors.get(comment, 0) + 1
    
    # Sort by frequency
    for error, count in sorted(errors.items(), key=lambda x: x[1], reverse=True):
        print(f"{error}: {count} occurrences")
```

## Troubleshooting

### Issue: run_id not found
- **Cause**: The run_id doesn't exist in the database
- **Solution**: Ensure you're using the run_id from the `on_start` event

### Issue: Feedback not updating
- **Cause**: Database connection issue or invalid run_id
- **Solution**: Check logs and verify run_id exists

### Issue: corrected_sql not saved
- **Cause**: Only saved when feedback=-1
- **Solution**: Ensure feedback is -1 when submitting corrected_sql

## Next Steps

1. **Implement UI feedback buttons** in your frontend
2. **Add feedback analytics dashboard** to track improvements
3. **Use feedback data for model fine-tuning** or prompt engineering
4. **Set up alerts** for high error rates on specific question types
5. **Create feedback reports** for stakeholders
