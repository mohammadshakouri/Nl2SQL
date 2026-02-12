# Frontend Feedback Integration Guide

## Overview
The frontend chatbot now includes full feedback functionality that integrates with the backend `/feedback` endpoint. Users can submit positive feedback (like) or negative feedback with corrected SQL (dislike).

## What Was Changed

### 1. **Message.tsx Component**
- Updated `handleLikeOrDislike` function to call the correct backend endpoint
- Added `handleDislikeFeedback` function that shows a modal for corrected SQL
- Added `submitFeedback` function to POST feedback to the backend
- Changed from query parameters to JSON body format
- Added feedback values: 1 for like, -1 for dislike

### 2. **i18n.ts Translations**
Added new translation keys for both Persian (fa) and English (en):
- `provideCorrectionTitle` - Modal title
- `provideCorrectionText` - Modal description
- `correctedSqlLabel` - Label for SQL input
- `correctedSqlPlaceholder` - Placeholder for SQL input
- `commentLabel` - Label for comment input
- `commentPlaceholder` - Placeholder for comment input
- `cancelButton` - Cancel button text
- `submitButton` - Submit button text
- `submittingButton` - Submitting state text
- `correctedSqlRequired` - Validation message
- `feedbackError` - Error message

### 3. **Modal Styles**
Added inline CSS for the feedback modal with:
- Responsive design
- Smooth animations
- Professional styling
- Accessibility support

## How It Works

### User Flow

```
1. User receives SQL response
   ↓
2. User sees feedback buttons (👍 👎)
   ↓
3a. User clicks 👍 (Like)
    → Sends: { run_id, feedback: 1 }
    → Button turns blue/filled
   
3b. User clicks 👎 (Dislike)
    → Modal opens with:
      - Textarea for corrected SQL (pre-filled with original)
      - Textarea for comment (optional)
      - Cancel and Submit buttons
    ↓
4. User edits SQL and adds comment
   ↓
5. User clicks Submit
   → Sends: { run_id, feedback: -1, corrected_sql, comment }
   → Button turns red/filled
   → Modal closes
```

## API Integration

### Positive Feedback
```typescript
POST /feedback
Headers:
  Content-Type: application/json
  api-key: your-api-key

Body:
{
  "run_id": "abc-123-...",
  "feedback": 1
}
```

### Negative Feedback
```typescript
POST /feedback
Headers:
  Content-Type: application/json
  api-key: your-api-key

Body:
{
  "run_id": "abc-123-...",
  "feedback": -1,
  "corrected_sql": "SELECT * FROM customers WHERE active = 1",
  "comment": "Original query was missing the active filter"
}
```

## Features

✅ **Like Button**: One-click positive feedback
✅ **Dislike Button**: Opens modal for detailed feedback
✅ **Corrected SQL**: Pre-filled with original, editable
✅ **Optional Comment**: Explain what was wrong
✅ **Validation**: Requires corrected SQL before submission
✅ **Loading States**: Shows "Submitting..." during POST
✅ **Error Handling**: Shows alerts on failure
✅ **UI Updates**: Buttons change to filled icons when clicked
✅ **Bilingual**: Supports both Persian (fa) and English (en)
✅ **Responsive**: Works on all screen sizes
✅ **Accessible**: Keyboard navigation and ARIA labels

## Modal Screenshot (Conceptual)

```
┌─────────────────────────────────────────────────────────┐
│  Provide Corrected SQL                              × │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Please provide the corrected SQL query and explain    │
│  what was wrong:                                        │
│                                                         │
│  Corrected SQL Query:                                   │
│  ┌─────────────────────────────────────────────────┐  │
│  │ SELECT * FROM customers                          │  │
│  │ WHERE province='Tehran'                          │  │
│  │ AND active = 1                                   │  │
│  │                                                   │  │
│  └─────────────────────────────────────────────────┘  │
│                                                         │
│  Comment (optional):                                    │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Original query used 'city' instead of           │  │
│  │ 'province' and was missing active filter        │  │
│  └─────────────────────────────────────────────────┘  │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                           [Cancel] [Submit Feedback]    │
└─────────────────────────────────────────────────────────┘
```

## Testing

### Test Positive Feedback
1. Start the frontend and backend
2. Ask a question (e.g., "Show all customers")
3. Click the 👍 button
4. Check browser console for success
5. Verify in backend database: `feedback = 1`, `status = 'success'`

### Test Negative Feedback
1. Ask a question
2. Click the 👎 button
3. Modal should open with SQL pre-filled
4. Edit the SQL query
5. Add a comment (optional)
6. Click "Submit Feedback"
7. Check browser console for success
8. Verify in backend database:
   - `feedback = -1`
   - `status = 'corrected'`
   - `corrected_sql` has your edited SQL
   - `feedback_comment` has your comment

### Test Error Handling
1. Stop the backend server
2. Try to submit feedback
3. Should see error alert
4. Buttons should re-enable

## Configuration

Make sure your `config.ts` has the correct API key:

```typescript
export const config = {
  apiKey: "your-api-key-here",
  schemaName: "your_schema",
  validateExecution: false,
};
```

Or set in `.env`:
```
VITE_API_KEY=your-api-key-here
VITE_SCHEMA_NAME=your_schema
```

## Troubleshooting

### Feedback not submitting
- Check that `config.apiKey` matches backend `SIMAC_API_KEY`
- Verify backend is running on correct port
- Check browser console for errors
- Verify `baseUrl` in `enums.tsx` is correct

### Modal not showing
- Check browser console for JavaScript errors
- Verify i18n translations are loaded
- Check that modal styles are injected

### Run ID not found
- Make sure `run_id` is being captured from `on_start` event
- Verify the message component receives the correct `runId` prop
- Check that the message control box has the correct ID attribute

## Customization

### Change Modal Appearance
Edit the inline styles in `handleDislikeFeedback` function in `Message.tsx`

### Change Feedback Values
Modify the `submitFeedback` calls:
```typescript
await submitFeedback(runId, 1);  // Like
await submitFeedback(runId, -1); // Dislike
```

### Add More Fields
Add to the modal HTML and update `submitFeedback` payload:
```typescript
payload.your_field = value;
```

## Next Steps

1. ✅ Test feedback functionality thoroughly
2. ✅ Monitor feedback data in backend database
3. ✅ Analyze feedback patterns to improve SQL generation
4. ✅ Consider adding analytics dashboard
5. ✅ Use feedback data for model fine-tuning

## Backend Integration

The frontend now correctly integrates with these backend endpoints:

- `POST /nl2sql` - Generate SQL
- `POST /feedback` - Submit feedback
- `POST /history` - Query feedback history (optional for admin panel)

For backend details, see:
- `FEEDBACK_LOOP_GUIDE.md`
- `FEEDBACK_QUICKREF.md`
- `FEEDBACK_IMPLEMENTATION.md`
