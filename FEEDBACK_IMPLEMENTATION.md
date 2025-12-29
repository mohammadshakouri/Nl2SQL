# Feedback Loop Implementation Summary

## Overview
A complete feedback loop system has been implemented to allow users to provide feedback on generated SQL queries and submit corrections when queries are incorrect.

## Changes Made

### 1. Database Model Updates ([models.py](backend/app/models.py))

Added two new fields to the `Message` model:
- `corrected_sql`: Stores the user-provided correct SQL query
- `feedback_comment`: Stores optional user comments about the feedback

```python
corrected_sql = Column(Text, nullable=True)
feedback_comment = Column(Text, nullable=True)
```

### 2. API Schema Updates ([schemas.py](backend/app/schemas.py))

Added new request model `FeedbackSubmissionRequest`:
```python
class FeedbackSubmissionRequest(BaseModel):
    run_id: str                          # Unique ID from query generation
    feedback: int                        # 1 (positive) or -1 (negative)
    corrected_sql: Optional[str] = None  # Corrected SQL if wrong
    comment: Optional[str] = None        # Optional comment
```

### 3. New Feedback Endpoint ([main.py](backend/main.py))

**POST `/feedback`** - Submit feedback for generated SQL

Features:
- Updates feedback status in database
- Stores corrected SQL when provided
- Updates query status (success/corrected)
- Returns confirmation response

```python
@app.post('/feedback', dependencies=[Depends(check_api_key)])
async def submit_feedback(request: FeedbackSubmissionRequest):
    # Find and update message with feedback
    # Store corrected SQL if provided
    # Update status
    return {"success": True, "message": "Feedback submitted successfully"}
```

### 4. Enhanced Query Tracking ([main.py](backend/main.py))

Both streaming functions now save queries to database:
- `generate_nl2sql_ollama_stream()` 
- `generate_nl2sql_openai_stream()`

Each query is now stored with:
- `run_id`: Unique identifier
- `input`: User's question
- `output`: Generated SQL
- `latency`: Generation time
- `status`: "generated" (can be updated via feedback)

### 5. Documentation

Created comprehensive guides:
- **FEEDBACK_LOOP_GUIDE.md**: Complete usage documentation
- **example_feedback_loop.py**: Working code examples

## How It Works

### Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    1. User Asks Question                    │
│                                                             │
│  POST /nl2sql                                              │
│  {                                                         │
│    "question": "Show all customers from Tehran",          │
│    "schema_name": "ecommerce"                             │
│  }                                                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              2. System Generates SQL (Streaming)            │
│                                                             │
│  Response:                                                 │
│  - on_start: run_id = "abc-123"                           │
│  - on_stream: "SELECT", " *", " FROM"...                  │
│  - on_end: full SQL query                                 │
│                                                             │
│  Query saved to database with run_id                      │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              3. User Tests SQL in Database                  │
│                                                             │
│  User executes the generated SQL                           │
└─────────────────────────────────────────────────────────────┘
                              ↓
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
    ┌───────────────────────┐  ┌──────────────────────┐
    │  4a. SQL is Correct   │  │  4b. SQL is Wrong   │
    │                       │  │                      │
    │  POST /feedback       │  │  POST /feedback      │
    │  {                    │  │  {                   │
    │    "run_id": "...",   │  │    "run_id": "...",  │
    │    "feedback": 1      │  │    "feedback": -1,   │
    │  }                    │  │    "corrected_sql":  │
    │                       │  │    "SELECT...",      │
    │  Status → "success"   │  │    "comment": "..."  │
    │                       │  │  }                   │
    │                       │  │                      │
    │                       │  │  Status → "corrected"│
    └───────────────────────┘  └──────────────────────┘
                    │                   │
                    └─────────┬─────────┘
                              ↓
            ┌─────────────────────────────────┐
            │  5. Feedback Stored in Database │
            │                                 │
            │  - Feedback value               │
            │  - Corrected SQL (if provided)  │
            │  - Comment (if provided)        │
            │  - Updated status               │
            └─────────────────────────────────┘
```

## API Usage Examples

### Example 1: Complete Workflow (Python)

```python
import httpx
import json

async def workflow():
    # 1. Generate SQL
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:80/nl2sql",
            headers={"api_key": "your-key"},
            json={
                "threadId": "",
                "question": "Show total sales by product",
                "schema_name": "ecommerce",
                "culture": "en"
            }
        )
        
        # Parse streaming response
        run_id = None
        sql = None
        
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data["event"] == "on_start":
                    run_id = data["run_id"]
                elif data["event"] == "on_end":
                    sql = data["sql"]
        
        # 2. Test SQL (execute in your database)
        # results = execute_sql(sql)
        
        # 3. Submit feedback
        if sql_is_correct:
            # Positive feedback
            await client.post(
                "http://localhost:80/feedback",
                headers={"api_key": "your-key"},
                json={
                    "run_id": run_id,
                    "feedback": 1
                }
            )
        else:
            # Negative feedback with correction
            await client.post(
                "http://localhost:80/feedback",
                headers={"api_key": "your-key"},
                json={
                    "run_id": run_id,
                    "feedback": -1,
                    "corrected_sql": "SELECT product, SUM(amount) FROM sales GROUP BY product",
                    "comment": "Missing GROUP BY clause"
                }
            )
```

### Example 2: View Feedback History

```python
# Get all negative feedback
response = await client.post(
    "http://localhost:80/history",
    headers={"api_key": "your-key"},
    json={"feedback": -1}
)

history = response.json()
for item in history:
    print(f"Question: {item['input']}")
    print(f"Wrong SQL: {item['output']}")
    print(f"Correct SQL: {item['corrected_sql']}")
    print(f"Comment: {item['feedback_comment']}")
```

## Benefits

1. **Quality Tracking**: Monitor which queries work and which don't
2. **Continuous Improvement**: Use feedback data to improve prompts and fine-tune models
3. **Error Analysis**: Identify common failure patterns
4. **User Satisfaction**: Collect user corrections to understand issues
5. **Training Data**: Build dataset of question → correct SQL pairs

## Future Enhancements

1. **Learning from Feedback**: Use corrected queries as few-shot examples
2. **Pattern Detection**: Automatically identify common error types
3. **Feedback Analytics Dashboard**: Visualize success rates and trends
4. **Auto-correction**: Suggest fixes based on similar past corrections
5. **Model Fine-tuning**: Use feedback data to fine-tune the LLM

## Testing

Run the example script to test the feedback loop:

```bash
cd backend
python example_feedback_loop.py
```

Make sure to:
1. Update `API_KEY` in the script
2. Ensure backend server is running
3. Have a valid schema configured

## Database Migration

The new fields will be automatically created when the application starts (SQLAlchemy's `create_all`). 

For existing databases, you may need to manually add columns:

```sql
ALTER TABLE messages ADD COLUMN corrected_sql TEXT;
ALTER TABLE messages ADD COLUMN feedback_comment TEXT;
```

## Integration with Frontend

To integrate with your frontend:

1. **Capture run_id**: Save the run_id from the initial streaming response
2. **Add Feedback UI**: Add thumbs up/down buttons or feedback form
3. **Submit Feedback**: Call `/feedback` endpoint when user provides feedback
4. **Show Corrections**: Display corrected SQL if available

Example frontend integration in [frontend/src/Scripts/Components/Message.tsx](frontend/src/Scripts/Components/Message.tsx):

```typescript
// Add to Message component
const [feedback, setFeedback] = useState<number>(0);

const submitFeedback = async (isPositive: boolean, correctedSql?: string) => {
    await fetch('/feedback', {
        method: 'POST',
        headers: {
            'api_key': API_KEY,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            run_id: message.runId,
            feedback: isPositive ? 1 : -1,
            corrected_sql: correctedSql,
            comment: "User provided feedback"
        })
    });
    setFeedback(isPositive ? 1 : -1);
};

// Add buttons to UI
<div className="feedback-buttons">
    <button onClick={() => submitFeedback(true)}>👍 Correct</button>
    <button onClick={() => submitFeedback(false)}>👎 Incorrect</button>
</div>
```

## Questions & Support

For questions or issues:
1. Check [FEEDBACK_LOOP_GUIDE.md](backend/FEEDBACK_LOOP_GUIDE.md) for detailed usage
2. Run [example_feedback_loop.py](backend/example_feedback_loop.py) to test functionality
3. Review the API endpoint implementations in [main.py](backend/main.py)
