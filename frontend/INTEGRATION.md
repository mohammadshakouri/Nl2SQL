# NL2SQL Chatbot Frontend-Backend Integration

This document explains how the React/TypeScript frontend communicates with the FastAPI backend.

## Overview

The chatbot UI sends natural language questions to the FastAPI backend's `/nl2sql` endpoint, which returns SQL queries via Server-Sent Events (SSE) streaming.

## Architecture

```
User Input → SendUserMessageToServer() → FastAPI /nl2sql → SSE Stream → HandleServerEvent()
```

## Configuration

### 1. Frontend Setup

Create a `.env` file in the `frontend/` directory:

```bash
cp .env.example .env
```

Edit `.env` and set your configuration:

```env
VITE_API_KEY=your-simac-api-key-here
VITE_SCHEMA_NAME=ecommerce
```

**Important:** The `VITE_API_KEY` must match the `SIMAC_API_KEY` in your backend's `.env` file.

### 2. Backend Setup

Ensure your backend `.env` file (in `backend/`) has:

```env
SIMAC_API_KEY=your-simac-api-key-here
```

## How It Works

### Request Flow

1. **User sends message** → `SendUserMessage()` is called
2. **Prepare payload**:
   ```typescript
   {
     threadId: "uuid-string",
     question: "user's natural language question",
     schema_name: "ecommerce",
     culture: "fa" or "en",
     validate_execution: false
   }
   ```
3. **Send to FastAPI** → POST to `/nl2sql` with `api-key` header
4. **Backend streams response** → SSE format with events

### SSE Event Types

The backend sends different event types:

#### 1. `on_start`
Sent when processing begins:
```json
{
  "event": "on_start",
  "run_id": "uuid",
  "thread_id": "uuid",
  "type": "nl2sql"
}
```

#### 2. `on_stream`
Sent for each SQL token:
```json
{
  "event": "on_stream",
  "data": "SELECT"
}
```

#### 3. `on_end`
Sent when complete:
```json
{
  "event": "on_end",
  "sql": "SELECT * FROM products",
  "latency": 1.234
}
```

#### 4. `on_error`
Sent on error:
```json
{
  "event": "on_error",
  "data": "Error message"
}
```

## Key Functions

### `SendUserMessageToServer(text: string)`

Handles communication with the FastAPI backend:

- Creates request payload with question and metadata
- Sets up SSE streaming reader
- Parses incoming events
- Handles errors and connection cleanup

### `HandleServerEvent(event: MessageEvent)`

Processes SSE events from the backend:

- `on_start`: Initializes message UI
- `on_stream`: Appends SQL tokens in real-time
- `on_end`: Finalizes message, enables input
- `on_error`: Shows error message

## Error Handling

The system handles several error scenarios:

1. **Network errors**: Caught in try-catch, calls `OnRespondError()`
2. **HTTP errors**: Checked via `response.ok`
3. **Backend errors**: Sent as `on_error` events
4. **Question length**: Maximum 250 characters (validated backend)

## API Authentication

All requests require the `api-key` header:

```typescript
headers: {
  "Content-Type": "application/json",
  "api-key": config.apiKey
}
```

If the key is invalid, the backend returns HTTP 401.

## Culture/Language Support

The system supports multilingual queries:

- `fa`: Persian/Farsi
- `en`: English

The culture is detected from `document.documentElement.lang` or defaults to `"fa"`.

## Schema Selection

The `schema_name` parameter specifies which database schema to query:

- `ecommerce`: E-commerce database
- Other schemas as configured in `backend/data_schema/`

## Development vs Production

The `baseUrl` is automatically configured:

```typescript
export const baseUrl = 
  import.meta.env.MODE === "development" 
    ? "http://localhost:1000" 
    : window.location.origin;
```

- **Development**: Points to `http://localhost:1000`
- **Production**: Uses the same origin as the frontend

## Comparison with C# Version

| Feature | C# Version | TypeScript Version |
|---------|-----------|-------------------|
| HTTP Client | `HttpWebRequest` | `fetch()` API |
| Streaming | `StreamReader.ReadLine()` | `ReadableStream` reader |
| SSE Parsing | Manual chunk building | Line-by-line parsing |
| Error Handling | try-catch-finally | try-catch with async |
| Threading | Synchronous blocking | Async/await non-blocking |

## Testing

### 1. Start Backend

```bash
cd backend
python main.py
```

### 2. Start Frontend

```bash
cd frontend
npm run dev
```

### 3. Test the Chatbot

1. Open browser to frontend URL
2. Click chatbot button
3. Type a question (e.g., "Show me all products")
4. Watch SQL stream in real-time

## Troubleshooting

### "Invalid API Key" Error

- Verify `VITE_API_KEY` in frontend `.env` matches `SIMAC_API_KEY` in backend `.env`
- Restart both frontend and backend after changing `.env` files

### No Response from Backend

- Check backend is running on correct port
- Verify `baseUrl` in [enums.tsx](src/Scripts/enums.tsx)
- Check browser console for CORS errors

### SSE Connection Errors

- Ensure backend is streaming correctly (check backend logs)
- Verify `Content-Type: text/event-stream` in response headers
- Check for network/proxy issues blocking SSE

## Files Modified/Created

### Created:
- [`config.ts`](src/Scripts/config.ts) - Configuration management
- [`.env.example`](.env.example) - Environment variable template
- [`INTEGRATION.md`](INTEGRATION.md) - This file

### Modified:
- [`index.tsx`](src/Scripts/index.tsx) - Updated `SendUserMessageToServer()` function
- [`index.tsx`](src/Scripts/index.tsx) - Enhanced `OnRespondError()` function

## Next Steps

1. Create your `.env` file with the correct API key
2. Test the integration with a simple query
3. Monitor backend logs for any issues
4. Customize schema_name if using a different database

## Security Notes

- Never commit `.env` files to version control
- Keep API keys secure and rotate them regularly
- Consider implementing rate limiting for production
- Use HTTPS in production for encrypted communication
