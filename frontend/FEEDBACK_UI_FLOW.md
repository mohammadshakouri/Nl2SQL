# Frontend Feedback UI - User Experience Flow

## Visual Flow Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│  1. USER ASKS QUESTION                                             │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  User Input:                                              │   │
│  │  ┌────────────────────────────────────────────────────┐  │   │
│  │  │ How many customers from Tehran?                     │  │   │
│  │  └────────────────────────────────────────────────────┘  │   │
│  │                                              [Send 📤]   │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────────┐
│  2. BOT RESPONDS WITH SQL                                          │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  🤖 AI Assistant                          10:30 AM       │   │
│  │  ┌────────────────────────────────────────────────────┐  │   │
│  │  │ SELECT COUNT(*) FROM customers                      │  │   │
│  │  │ WHERE city = 'Tehran'                               │  │   │
│  │  └────────────────────────────────────────────────────┘  │   │
│  │                                                           │   │
│  │  [👍 Like] [👎 Dislike] [📋 Copy]                       │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
                              ↓
                   ┌──────────┴──────────┐
                   │                     │
                   ▼                     ▼
┌─────────────────────────────┐  ┌──────────────────────────────────┐
│  3A. USER LIKES (CORRECT)   │  │  3B. USER DISLIKES (INCORRECT)  │
│                             │  │                                  │
│  User clicks: [👍]          │  │  User clicks: [👎]               │
│         ↓                   │  │         ↓                        │
│  Button changes to: [👍]    │  │  ⚡ MODAL OPENS ⚡               │
│  (filled/blue)              │  │                                  │
│         ↓                   │  │  ┌────────────────────────────┐ │
│  API Request:               │  │  │ Provide Corrected SQL    × │ │
│  {                          │  │  ├────────────────────────────┤ │
│    "run_id": "abc-123",     │  │  │ Please provide corrected   │ │
│    "feedback": 1            │  │  │ SQL and explain issue:     │ │
│  }                          │  │  │                            │ │
│         ↓                   │  │  │ Corrected SQL Query:       │ │
│  ✅ Success!                │  │  │ ┌────────────────────────┐ │ │
│  Feedback saved             │  │  │ │ SELECT COUNT(*)        │ │ │
│                             │  │  │ │ FROM customers         │ │ │
└─────────────────────────────┘  │  │ │ WHERE province=        │ │ │
                                 │  │ │ 'Tehran'               │ │ │
                                 │  │ │                        │ │ │
                                 │  │ └────────────────────────┘ │ │
                                 │  │                            │ │
                                 │  │ Comment (optional):        │ │
                                 │  │ ┌────────────────────────┐ │ │
                                 │  │ │ Used 'city' instead    │ │ │
                                 │  │ │ of 'province'          │ │ │
                                 │  │ └────────────────────────┘ │ │
                                 │  │                            │ │
                                 │  │ [Cancel] [Submit Feedback] │ │
                                 │  └────────────────────────────┘ │
                                 │         ↓                        │
                                 │  4. USER EDITS & SUBMITS         │
                                 │         ↓                        │
                                 │  API Request:                    │
                                 │  {                               │
                                 │    "run_id": "abc-123",          │
                                 │    "feedback": -1,               │
                                 │    "corrected_sql": "SELECT...", │
                                 │    "comment": "Used 'city'..."   │
                                 │  }                               │
                                 │         ↓                        │
                                 │  ✅ Success!                     │
                                 │  Button changes to: [👎]         │
                                 │  (filled/red)                    │
                                 │  Modal closes                    │
                                 │                                  │
                                 └──────────────────────────────────┘
```

## UI States

### Initial State (No Feedback)
```
┌──────────────────────────────────────────────────┐
│  🤖 AI Assistant                    10:30 AM    │
│  ┌────────────────────────────────────────────┐  │
│  │ SELECT * FROM customers                     │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  [👍] [👎] [📋]  ← All buttons enabled, gray   │
└──────────────────────────────────────────────────┘
```

### After Positive Feedback
```
┌──────────────────────────────────────────────────┐
│  🤖 AI Assistant                    10:30 AM    │
│  ┌────────────────────────────────────────────┐  │
│  │ SELECT * FROM customers                     │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  [👍] [👎] [📋]  ← Like is filled/blue          │
└──────────────────────────────────────────────────┘
```

### After Negative Feedback
```
┌──────────────────────────────────────────────────┐
│  🤖 AI Assistant                    10:30 AM    │
│  ┌────────────────────────────────────────────┐  │
│  │ SELECT * FROM customers                     │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  [👍] [👎] [📋]  ← Dislike is filled/red        │
└──────────────────────────────────────────────────┘
```

### Loading State (During Submission)
```
┌──────────────────────────────────────────────────┐
│  🤖 AI Assistant                    10:30 AM    │
│  ┌────────────────────────────────────────────┐  │
│  │ SELECT * FROM customers                     │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  [👍] [👎] [📋]  ← All buttons disabled, faded │
│                   "Submitting..."               │
└──────────────────────────────────────────────────┘
```

## Modal States

### Modal Open (Dislike Clicked)
```
┌──────────────────────────────────────────────────────┐
│                  Background Overlay (50% black)      │
│                                                      │
│     ┌──────────────────────────────────────────┐   │
│     │ Provide Corrected SQL               × │   │
│     ├──────────────────────────────────────────┤   │
│     │                                          │   │
│     │ Please provide the corrected SQL query  │   │
│     │ and explain what was wrong:             │   │
│     │                                          │   │
│     │ Corrected SQL Query:                    │   │
│     │ ┌────────────────────────────────────┐  │   │
│     │ │ SELECT COUNT(*)                    │  │   │
│     │ │ FROM customers                     │  │   │
│     │ │ WHERE city = 'Tehran'              │  │   │
│     │ │                                    │  │   │
│     │ │ ← Pre-filled with original SQL     │  │   │
│     │ └────────────────────────────────────┘  │   │
│     │                                          │   │
│     │ Comment (optional):                     │   │
│     │ ┌────────────────────────────────────┐  │   │
│     │ │                                    │  │   │
│     │ │ ← Empty, user can type             │  │   │
│     │ └────────────────────────────────────┘  │   │
│     │                                          │   │
│     ├──────────────────────────────────────────┤   │
│     │              [Cancel] [Submit Feedback]  │   │
│     └──────────────────────────────────────────┘   │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Modal - User Editing
```
┌──────────────────────────────────────────────────────┐
│                  Background Overlay                  │
│                                                      │
│     ┌──────────────────────────────────────────┐   │
│     │ Provide Corrected SQL               × │   │
│     ├──────────────────────────────────────────┤   │
│     │                                          │   │
│     │ Please provide the corrected SQL query  │   │
│     │ and explain what was wrong:             │   │
│     │                                          │   │
│     │ Corrected SQL Query:                    │   │
│     │ ┌────────────────────────────────────┐  │   │
│     │ │ SELECT COUNT(*)                    │  │   │
│     │ │ FROM customers                     │  │   │
│     │ │ WHERE province = 'Tehran'  ← edited│  │   │
│     │ │                                    │  │   │
│     │ └────────────────────────────────────┘  │   │
│     │                                          │   │
│     │ Comment (optional):                     │   │
│     │ ┌────────────────────────────────────┐  │   │
│     │ │ Used 'city' column instead of      │  │   │
│     │ │ 'province' column  ← user typed    │  │   │
│     │ └────────────────────────────────────┘  │   │
│     │                                          │   │
│     ├──────────────────────────────────────────┤   │
│     │              [Cancel] [Submit Feedback]  │   │
│     └──────────────────────────────────────────┘   │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Modal - Submitting
```
┌──────────────────────────────────────────────────────┐
│                  Background Overlay                  │
│                                                      │
│     ┌──────────────────────────────────────────┐   │
│     │ Provide Corrected SQL               × │   │
│     ├──────────────────────────────────────────┤   │
│     │                                          │   │
│     │ Please provide the corrected SQL query  │   │
│     │ and explain what was wrong:             │   │
│     │                                          │   │
│     │ Corrected SQL Query:                    │   │
│     │ ┌────────────────────────────────────┐  │   │
│     │ │ SELECT COUNT(*)                    │  │   │
│     │ │ FROM customers                     │  │   │
│     │ │ WHERE province = 'Tehran'          │  │   │
│     │ │                                    │  │   │
│     │ └────────────────────────────────────┘  │   │
│     │                                          │   │
│     │ Comment (optional):                     │   │
│     │ ┌────────────────────────────────────┐  │   │
│     │ │ Used 'city' instead of 'province'  │  │   │
│     │ └────────────────────────────────────┘  │   │
│     │                                          │   │
│     ├──────────────────────────────────────────┤   │
│     │              [Cancel] [Submitting...]    │   │
│     │                           ↑ disabled     │   │
│     └──────────────────────────────────────────┘   │
│                                                      │
└──────────────────────────────────────────────────────┘
```

## Keyboard Interactions

### In Modal
- **Escape** - Close modal (same as Cancel)
- **Tab** - Navigate between fields
- **Enter** - In textareas, creates new line
- **Click outside** - Close modal

### Button States
- **Disabled** - Gray, no pointer, opacity 0.5
- **Enabled** - Full color, pointer cursor
- **Hover** - Slightly lighter/darker

## Responsive Behavior

### Desktop (> 600px)
- Modal: 600px wide, centered
- Textareas: Full width within modal
- Buttons: Side by side

### Mobile (< 600px)
- Modal: 90% width
- Textareas: Full width
- Buttons: May stack vertically

## Accessibility

✅ **ARIA Labels**: All buttons have aria-label attributes
✅ **Keyboard Navigation**: Full keyboard support
✅ **Focus Management**: Modal traps focus when open
✅ **Screen Reader**: All content is readable
✅ **Color Contrast**: Meets WCAG AA standards
✅ **Error Messages**: Clear, actionable feedback

## Animation Timing

- **Modal Open**: 0.3s slide up + fade in
- **Background Overlay**: 0.2s fade in
- **Button State Change**: Instant with smooth color transition
- **Modal Close**: 0.2s fade out

## Error Handling

### Network Error
```
┌────────────────────────────────────────┐
│  ⚠️ Alert Dialog                      │
├────────────────────────────────────────┤
│  Failed to submit feedback.           │
│  Please try again.                    │
│                                        │
│                          [OK]          │
└────────────────────────────────────────┘
```

### Validation Error (Empty SQL)
```
┌────────────────────────────────────────┐
│  ⚠️ Alert Dialog                      │
├────────────────────────────────────────┤
│  Please provide a corrected SQL query. │
│                                        │
│                          [OK]          │
└────────────────────────────────────────┘
```

## Backend Integration Points

### When User Clicks Like (👍)
```typescript
POST /feedback
{
  "run_id": "uuid-from-message",
  "feedback": 1
}
→ Backend saves: feedback=1, status='success'
```

### When User Submits Dislike (👎)
```typescript
POST /feedback
{
  "run_id": "uuid-from-message",
  "feedback": -1,
  "corrected_sql": "SELECT...",
  "comment": "Explanation..."
}
→ Backend saves: feedback=-1, status='corrected', corrected_sql, comment
```

## Testing Checklist

- [ ] Like button works and turns blue
- [ ] Dislike button opens modal
- [ ] Modal shows original SQL pre-filled
- [ ] Can edit SQL in modal
- [ ] Can add comment in modal
- [ ] Cancel button closes modal
- [ ] Submit button validates SQL is not empty
- [ ] Submit button sends feedback to backend
- [ ] Dislike button turns red after submission
- [ ] Modal closes after successful submission
- [ ] Error alert shows on network failure
- [ ] Buttons disable during submission
- [ ] Buttons re-enable after submission
- [ ] Works in both Persian (fa) and English (en)
- [ ] Works on mobile devices
- [ ] Keyboard navigation works
