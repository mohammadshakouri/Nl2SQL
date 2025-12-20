# Schema-RAG (NL2SQL) - Setup Verification Checklist

Use this checklist to verify your NL2SQL system is properly configured and ready to use.

---

## 📋 Pre-Installation Checklist

### Environment Setup
- [ ] Python 3.8+ installed
- [ ] pip package manager available
- [ ] Virtual environment activated (recommended)
- [ ] Git repository cloned
- [ ] Working directory: `backend/`

### Existing System Check
- [ ] Existing RAG system working
- [ ] ChromaDB accessible
- [ ] LLM configured (Ollama or OpenAI)
- [ ] Embedding model configured
- [ ] FastAPI server can start

---

## 📦 Installation Checklist

### Dependencies
- [ ] Run: `pip install -r requirements.txt`
- [ ] Verify: `pip show sqlparse` (should show version 0.5.3+)
- [ ] Verify: `pip show chromadb`
- [ ] Verify: `pip show fastapi`
- [ ] No import errors when starting Python

### Files Check
- [ ] All new files present in `app/`:
  - [ ] `schema_manager.py`
  - [ ] `sql_validator.py`
  - [ ] `nl2sql_chain.py`
- [ ] System prompts updated in `system_prompt.py`
- [ ] Utilities extended in `utilities.py`
- [ ] Schemas updated in `schemas.py`
- [ ] Main API updated in `main.py`

### Data Files
- [ ] `data_schema/` directory exists
- [ ] `ecommerce_schema.json` present
- [ ] `example_queries.md` present

### Scripts
- [ ] `initialize_nl2sql.py` exists
- [ ] `demo_nl2sql.py` exists

### Documentation
- [ ] All markdown files present:
  - [ ] `PROJECT_SUMMARY.md`
  - [ ] `NL2SQL_SETUP.md`
  - [ ] `NL2SQL_README.md`
  - [ ] `IMPLEMENTATION_REPORT.md`
  - [ ] `ARCHITECTURE.md`
  - [ ] `QUICK_REFERENCE.md`
  - [ ] `INDEX.md`

---

## 🚀 Initialization Checklist

### Run Setup Script
- [ ] Execute: `python initialize_nl2sql.py`
- [ ] Output shows: "All dependencies installed"
- [ ] Output shows: "Schema directory found"
- [ ] Output shows: "Example schema found"
- [ ] Output shows: "Vector store created successfully"
- [ ] Output shows: "System validation passed"
- [ ] No error messages in output

### Manual Verification
- [ ] ChromaDB directory exists: `chroma_db/`
- [ ] Schema collection created: `chroma_db/chroma.sqlite3` updated
- [ ] Collection visible in ChromaDB

---

## 🧪 Testing Checklist

### Demo Script
- [ ] Run: `python demo_nl2sql.py`
- [ ] All steps complete without errors:
  - [ ] Step 1: Schema vector store setup ✓
  - [ ] Step 2: System validation ✓
  - [ ] Step 3: Schema manager loaded ✓
  - [ ] Step 4: NL2SQL chain initialized ✓
  - [ ] Step 5: Test questions generate SQL ✓
  - [ ] Step 6: Schema retrieval works ✓
  - [ ] Step 7: Demo completed ✓

### Test Questions
For each test question, verify:
- [ ] SQL generated without errors
- [ ] SQL is syntactically valid
- [ ] SQL uses correct table names
- [ ] SQL uses correct column names
- [ ] JOINs are properly inferred
- [ ] No markdown in output
- [ ] No comments in output

---

## 🌐 API Checklist

### Server Startup
- [ ] Run: `python main.py`
- [ ] Server starts without errors
- [ ] Shows: "Uvicorn running on..."
- [ ] No import errors
- [ ] Swagger docs accessible (if enabled)

### Endpoint Testing

#### `/nl2sql` Endpoint
- [ ] Endpoint responds to POST requests
- [ ] Accepts JSON payload
- [ ] Requires API key authentication
- [ ] Returns SSE (Server-Sent Events) stream
- [ ] Stream contains:
  - [ ] `on_start` event
  - [ ] Multiple `on_stream` events
  - [ ] `on_end` event with SQL

#### Example Request
```bash
curl -X POST "http://localhost:80/nl2sql" \
  -H "api_key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "threadId": "",
    "question": "کدام مشتریان بیش از ۵ میلیون تومان خرید کرده‌اند؟",
    "schema_name": "ecommerce",
    "culture": "fa"
  }'
```

**Verify:**
- [ ] Request succeeds (no 500 errors)
- [ ] Streaming response received
- [ ] SQL generated in response
- [ ] Latency acceptable (< 5 seconds)

#### `/nl2sql/validate` Endpoint
- [ ] Endpoint responds to POST requests
- [ ] Returns validation JSON
- [ ] Shows schema status
- [ ] Shows collection status
- [ ] Returns `is_valid: true`

---

## 🔧 Configuration Checklist

### Environment Variables
- [ ] `USE_LOCAL_LLM` set (true/false)
- [ ] `USE_LOCAL_EMBEDDING` set (true/false)
- [ ] `OPENAI_API_KEY` set (if using OpenAI)
- [ ] `SIMAC_API_KEY` set
- [ ] `SQL_DATABASE_URL` set (if using execution validation)

### LLM Configuration
If using Ollama:
- [ ] Ollama installed
- [ ] Ollama running (`ollama serve`)
- [ ] Model pulled (`ollama pull gemma3:4b`)
- [ ] Embedding model available

If using OpenAI:
- [ ] API key valid
- [ ] API key has credits
- [ ] Network access to OpenAI API

---

## 📊 Functional Testing Checklist

### Basic Functionality
- [ ] Simple question generates SQL
- [ ] Complex question with JOIN generates SQL
- [ ] Aggregation query generates SQL
- [ ] Temporal query generates SQL
- [ ] Persian questions work
- [ ] English questions work

### Schema Retrieval
- [ ] Relevant tables retrieved
- [ ] Relevant columns retrieved
- [ ] Relevant relations retrieved
- [ ] Retrieval threshold working (< 0.7)
- [ ] Top-K limiting working (10 elements)

### SQL Validation
- [ ] Valid SQL passes validation
- [ ] Invalid syntax caught
- [ ] Non-existent table caught
- [ ] Non-existent column caught
- [ ] Non-SELECT queries rejected

### Feedback Loop
- [ ] Error triggers feedback
- [ ] Feedback prompt generated
- [ ] SQL regenerated
- [ ] Maximum 3 iterations enforced
- [ ] Successful correction possible

---

## 🔒 Security Checklist

### API Security
- [ ] API key required for all endpoints
- [ ] Invalid API key rejected (401)
- [ ] No authentication bypass possible

### SQL Security
- [ ] Only SELECT statements allowed
- [ ] INSERT rejected
- [ ] UPDATE rejected
- [ ] DELETE rejected
- [ ] DROP rejected
- [ ] Schema boundary enforced

### Input Validation
- [ ] Question length limited (250 chars)
- [ ] Schema name validated
- [ ] Culture validated (fa/en)
- [ ] Thread ID format checked

---

## 📈 Performance Checklist

### Response Time
- [ ] Schema retrieval: < 200ms
- [ ] SQL generation: < 3s
- [ ] Total pipeline: < 5s
- [ ] Streaming starts immediately
- [ ] No timeout errors

### Scalability
- [ ] Multiple concurrent requests handled
- [ ] No memory leaks observed
- [ ] ChromaDB responsive under load
- [ ] LLM handles multiple calls

---

## 📚 Documentation Checklist

### Read Documentation
- [ ] Read PROJECT_SUMMARY.md
- [ ] Read NL2SQL_SETUP.md
- [ ] Read QUICK_REFERENCE.md
- [ ] Understand architecture (ARCHITECTURE.md)
- [ ] Know how to add new schema

### Understand Components
- [ ] Understand SchemaManager role
- [ ] Understand SQLValidator role
- [ ] Understand NL2SQLChain role
- [ ] Understand pipeline stages
- [ ] Know how to extend system

---

## 🎯 Production Readiness Checklist

### Code Quality
- [ ] No compilation errors
- [ ] No import errors
- [ ] Type hints present
- [ ] Docstrings present
- [ ] Error handling implemented
- [ ] Logging configured

### Testing
- [ ] Demo script passes
- [ ] Example queries work
- [ ] Edge cases handled
- [ ] Error cases handled

### Monitoring
- [ ] Logs accessible
- [ ] Error logging works
- [ ] Performance metrics tracked
- [ ] API health checkable

### Deployment
- [ ] Requirements documented
- [ ] Setup automated
- [ ] Configuration documented
- [ ] Troubleshooting guide available

---

## ✅ Final Verification

### System Health
- [ ] All dependencies installed ✓
- [ ] All files present ✓
- [ ] Initialization successful ✓
- [ ] Demo script passes ✓
- [ ] API endpoints working ✓
- [ ] Test queries generate SQL ✓
- [ ] Validation passes ✓
- [ ] Documentation complete ✓

### Ready for Production
- [ ] Error handling robust ✓
- [ ] Security measures in place ✓
- [ ] Performance acceptable ✓
- [ ] Monitoring possible ✓
- [ ] Documentation comprehensive ✓

---

## 🚨 Common Issues Checklist

### If Demo Fails
- [ ] Check: Python version (3.8+)
- [ ] Check: All dependencies installed
- [ ] Check: Schema file exists
- [ ] Check: ChromaDB accessible
- [ ] Check: LLM configured

### If API Fails
- [ ] Check: Server started
- [ ] Check: Port 80 available
- [ ] Check: API key correct
- [ ] Check: Request format correct
- [ ] Check: Schema name valid

### If SQL Invalid
- [ ] Check: Schema embeddings created
- [ ] Check: Collection exists
- [ ] Check: Retrieval working
- [ ] Check: LLM responding
- [ ] Check: Prompts loaded

### If Slow Performance
- [ ] Check: Using local vs cloud LLM
- [ ] Check: Using local vs cloud embedding
- [ ] Check: Network latency
- [ ] Check: ChromaDB index
- [ ] Check: Concurrent requests

---

## 📞 Next Steps After Verification

### If All Checks Pass ✅
1. System is ready for production
2. Add your own database schemas
3. Customize prompts if needed
4. Integrate with your application
5. Monitor performance
6. Gather user feedback

### If Some Checks Fail ❌
1. Review failed items
2. Check troubleshooting guide (NL2SQL_SETUP.md)
3. Verify dependencies
4. Check logs for errors
5. Run initialization again
6. Contact support if needed

---

## 📊 Verification Summary

Date: _______________

**Status:**
- [ ] ✅ All checks passed - System ready
- [ ] ⚠️ Some checks failed - Review needed
- [ ] ❌ Many checks failed - Setup incomplete

**Failed Checks:**
1. _________________________________
2. _________________________________
3. _________________________________

**Actions Taken:**
1. _________________________________
2. _________________________________
3. _________________________________

**Final Status:**
- [ ] System operational
- [ ] Ready for testing
- [ ] Ready for production

---

**Verified By:** _______________
**Date:** _______________
**Notes:** _______________________________________________
