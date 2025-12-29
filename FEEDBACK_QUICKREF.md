# NL2SQL Feedback Loop - Quick Reference

## API Endpoints

### 1. Generate SQL Query
```
POST /nl2sql
Headers: api_key: <your-key>
Body: {
  "threadId": "",
  "question": "Your question here",
  "schema_name": "your_schema",
  "culture": "en"
}
```

**Response (Streaming):**
```
data: {"event": "on_start", "run_id": "uuid", "thread_id": "uuid"}
data: {"event": "on_stream", "data": "SELECT"}
data: {"event": "on_end", "sql": "SELECT...", "latency": 1.23}
```

**Important:** Save the `run_id` from `on_start` event!

---

### 2. Submit Feedback

#### Positive Feedback (SQL is correct)
```
POST /feedback
Headers: api_key: <your-key>
Body: {
  "run_id": "uuid-from-generation",
  "feedback": 1
}
```

#### Negative Feedback (SQL is wrong)
```
POST /feedback
Headers: api_key: <your-key>
Body: {
  "run_id": "uuid-from-generation",
  "feedback": -1,
  "corrected_sql": "SELECT correct query...",
  "comment": "Explanation of what was wrong"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Feedback submitted successfully",
  "run_id": "uuid",
  "feedback": -1
}
```

---

### 3. Query History
```
POST /history
Headers: api_key: <your-key>
Body: {
  "run_id": "optional-uuid",
  "feedback": -1,  // -1, 1, or omit for all
  "from_time": "2025-01-01T00:00:00",
  "to_time": "2025-12-31T23:59:59"
}
```

**Response:**
```json
[
  {
    "start_time": "2025-12-28T10:30:00",
    "provinceName": "schema_name",
    "input": "User question",
    "output": "Generated SQL",
    "culture": "en",
    "feedback": -1,
    "corrected_sql": "Corrected SQL",
    "feedback_comment": "User comment"
  }
]
```

---

## Quick Usage Examples

### Python
```python
import httpx

API_KEY = "your-key"

# Generate SQL
async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:80/nl2sql",
        headers={"api_key": API_KEY},
        json={
            "threadId": "",
            "question": "Show all customers",
            "schema_name": "ecommerce",
            "culture": "en"
        }
    )
    
    run_id = None
    async for line in response.aiter_lines():
        if 'on_start' in line:
            import json
            data = json.loads(line[6:])
            run_id = data["run_id"]
    
    # Submit feedback
    await client.post(
        "http://localhost:80/feedback",
        headers={"api_key": API_KEY},
        json={
            "run_id": run_id,
            "feedback": 1  # or -1 with corrected_sql
        }
    )
```

### cURL
```bash
# Generate SQL
curl -X POST http://localhost:80/nl2sql \
  -H "api_key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "threadId": "",
    "question": "Show all customers",
    "schema_name": "ecommerce",
    "culture": "en"
  }'

# Submit positive feedback
curl -X POST http://localhost:80/feedback \
  -H "api_key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "your-run-id",
    "feedback": 1
  }'

# Submit negative feedback with correction
curl -X POST http://localhost:80/feedback \
  -H "api_key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "your-run-id",
    "feedback": -1,
    "corrected_sql": "SELECT * FROM customers",
    "comment": "Missing table name"
  }'
```

### JavaScript/TypeScript
```typescript
const API_KEY = "your-key";

// Generate SQL
const response = await fetch("http://localhost:80/nl2sql", {
  method: "POST",
  headers: {
    "api_key": API_KEY,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    threadId: "",
    question: "Show all customers",
    schema_name: "ecommerce",
    culture: "en"
  })
});

// Parse streaming response for run_id
const reader = response.body.getReader();
let runId: string;
// ... parse stream ...

// Submit feedback
await fetch("http://localhost:80/feedback", {
  method: "POST",
  headers: {
    "api_key": API_KEY,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    run_id: runId,
    feedback: -1,
    corrected_sql: "SELECT * FROM customers",
    comment: "Missing table name"
  })
});
```

---

## Feedback Values

| Value | Meaning | Required Fields |
|-------|---------|----------------|
| `1`   | Positive (SQL is correct) | `run_id`, `feedback` |
| `-1`  | Negative (SQL is wrong) | `run_id`, `feedback`, optionally `corrected_sql` and `comment` |
| `0`   | No feedback yet (default) | - |

---

## Status Values

| Status | Meaning |
|--------|---------|
| `generated` | SQL was generated, no feedback yet |
| `success` | User marked SQL as correct (feedback=1) |
| `corrected` | User provided corrected SQL (feedback=-1) |
| `error` | Error during generation |

---

## Common Workflow

1. **Generate SQL** → Get `run_id`
2. **Test SQL** → Execute in your database
3. **Submit Feedback**:
   - If works: `feedback=1`
   - If doesn't work: `feedback=-1` + `corrected_sql` + `comment`
4. **Query History** → Analyze patterns and improve

---

## Tips

✅ **DO:**
- Always save the `run_id` from the initial response
- Test generated SQL before submitting feedback
- Provide clear comments explaining issues
- Include working `corrected_sql` when marking as incorrect

❌ **DON'T:**
- Submit feedback without testing the SQL first
- Submit corrected_sql that hasn't been tested
- Forget to save the run_id
- Use placeholder values in corrected_sql

---

## Files

- **Full Guide**: [FEEDBACK_LOOP_GUIDE.md](FEEDBACK_LOOP_GUIDE.md)
- **Implementation Details**: [FEEDBACK_IMPLEMENTATION.md](FEEDBACK_IMPLEMENTATION.md)
- **Example Code**: [example_feedback_loop.py](backend/example_feedback_loop.py)
- **API Code**: [main.py](backend/main.py)
