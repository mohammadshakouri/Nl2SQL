# 🔄 NL2SQL Feedback Loop System

## What Was Implemented

A complete feedback loop system that allows you to:
- ✅ Track all generated SQL queries
- ✅ Collect user feedback (correct/incorrect)
- ✅ Store corrected SQL when queries are wrong
- ✅ Query feedback history for analysis
- ✅ Use feedback data to improve the system

## Quick Start

### 1. Run the Test Script

```bash
cd backend
python test_feedback_loop.py
```

This will verify that:
- Server is running
- NL2SQL endpoint works
- Feedback submission works
- History endpoint works

### 2. Try the Complete Example

```bash
python example_feedback_loop.py
```

This demonstrates:
- Generating SQL from questions
- Submitting positive feedback
- Submitting negative feedback with corrections
- Viewing feedback history

## Files Created/Modified

### Modified Files
- **backend/app/models.py** - Added `corrected_sql` and `feedback_comment` fields
- **backend/app/schemas.py** - Added `FeedbackSubmissionRequest` schema
- **backend/main.py** - Added `/feedback` endpoint and query tracking

### New Documentation
- **backend/FEEDBACK_LOOP_GUIDE.md** - Complete usage guide
- **FEEDBACK_IMPLEMENTATION.md** - Implementation details and architecture
- **FEEDBACK_QUICKREF.md** - Quick API reference

### New Example Scripts
- **backend/example_feedback_loop.py** - Interactive examples
- **backend/test_feedback_loop.py** - Quick smoke test

## How to Use

### Basic Flow

```python
# 1. Generate SQL
response = await client.post("/nl2sql", json={
    "question": "Show all customers",
    "schema_name": "ecommerce",
    "culture": "en"
})
# Save the run_id from the response!

# 2. Test the SQL in your database
# results = execute_sql(generated_sql)

# 3. Submit feedback
if sql_works:
    # Positive feedback
    await client.post("/feedback", json={
        "run_id": run_id,
        "feedback": 1
    })
else:
    # Negative feedback with correction
    await client.post("/feedback", json={
        "run_id": run_id,
        "feedback": -1,
        "corrected_sql": "SELECT * FROM customers WHERE active = 1",
        "comment": "Original query was missing active filter"
    })
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/nl2sql` | POST | Generate SQL from natural language |
| `/feedback` | POST | Submit feedback (positive/negative) |
| `/history` | POST | Query feedback history |

See **FEEDBACK_QUICKREF.md** for detailed API documentation.

## Database Changes

Two new fields added to `messages` table:
- `corrected_sql` (TEXT) - User-provided correct SQL
- `feedback_comment` (TEXT) - User's feedback comment

These will be automatically created when you restart the backend.

## Integration Checklist

- [ ] Update API_KEY in test scripts
- [ ] Run `test_feedback_loop.py` to verify installation
- [ ] Read through `FEEDBACK_LOOP_GUIDE.md`
- [ ] Add feedback UI to your frontend
- [ ] Set up monitoring/analytics for feedback
- [ ] Plan how to use feedback data for improvements

## Frontend Integration

Add feedback buttons to your UI:

```typescript
// In your message component
<div className="feedback-buttons">
  <button onClick={() => submitFeedback(message.runId, 1)}>
    👍 Correct
  </button>
  <button onClick={() => showCorrectionDialog(message.runId)}>
    👎 Incorrect
  </button>
</div>

async function submitFeedback(runId: string, feedback: number) {
  await fetch('/feedback', {
    method: 'POST',
    headers: { 'api_key': API_KEY },
    body: JSON.stringify({ run_id: runId, feedback })
  });
}
```

## Using Feedback Data

### View all incorrect queries
```python
response = await client.post("/history", json={"feedback": -1})
failed_queries = response.json()
```

### Analyze patterns
```python
# Count common error types from comments
errors = {}
for query in failed_queries:
    comment = query.get('feedback_comment', 'Unknown')
    errors[comment] = errors.get(comment, 0) + 1
```

### Create training data
```python
# Convert feedback into training examples
training_data = [
    {
        "question": q["input"],
        "correct_sql": q["corrected_sql"],
        "schema": q["provinceName"]
    }
    for q in failed_queries
    if q.get("corrected_sql")
]
```

## Next Steps

1. **Test the implementation** - Run test_feedback_loop.py
2. **Try examples** - Run example_feedback_loop.py
3. **Read documentation** - FEEDBACK_LOOP_GUIDE.md has everything
4. **Add UI** - Integrate feedback buttons in frontend
5. **Monitor** - Track feedback metrics and patterns
6. **Improve** - Use feedback to enhance prompts and fine-tune models

## Support

For detailed information, see:
- **Complete Guide**: backend/FEEDBACK_LOOP_GUIDE.md
- **API Reference**: FEEDBACK_QUICKREF.md
- **Implementation**: FEEDBACK_IMPLEMENTATION.md
- **Code Examples**: backend/example_feedback_loop.py

---

**Key Point**: Always save the `run_id` from the SQL generation response - you need it to submit feedback!
