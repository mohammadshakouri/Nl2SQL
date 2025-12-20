# Schema-RAG (NL2SQL) - System Architecture

## 📊 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          USER APPLICATION                           │
│                    (Web, Mobile, API Client)                        │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                │ HTTP POST /nl2sql
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI Server                               │
│                         (main.py)                                   │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │ Chat Endpoint    │  │ NL2SQL Endpoint  │  │ Validate        │  │
│  │ /chat            │  │ /nl2sql          │  │ /nl2sql/validate│  │
│  └──────────────────┘  └──────────────────┘  └─────────────────┘  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
                    ▼                       ▼
        ┌─────────────────────┐   ┌─────────────────────┐
        │   Text RAG Chain    │   │  NL2SQL Chain       │
        │   (dt_chain.py)     │   │  (nl2sql_chain.py)  │
        └─────────────────────┘   └──────────┬──────────┘
                                              │
                                              │
    ┌─────────────────────────────────────────┴─────────────────┐
    │                                                             │
    ▼                                                             ▼
┌─────────────────────┐                              ┌─────────────────────┐
│  Schema Manager     │                              │   SQL Validator     │
│ (schema_manager.py) │                              │ (sql_validator.py)  │
│                     │                              │                     │
│ • Table → Text      │                              │ • Syntax Check      │
│ • Column → Text     │                              │ • Schema Check      │
│ • Relation → Text   │                              │ • Feedback Loop     │
└──────────┬──────────┘                              └─────────────────────┘
           │
           │ Embeddings
           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         ChromaDB                                    │
│                   (Vector Database)                                 │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │ Text RAG     │  │ Schema_ecom  │  │ Schema_hr    │   ...      │
│  │ Collections  │  │              │  │              │            │
│  └──────────────┘  └──────────────┘  └──────────────┘            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 NL2SQL Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    STAGE 1: Question Input                          │
│                                                                     │
│  Natural Language Question (Persian or English)                    │
│  "کدام مشتریان در ماه گذشته بیش از ۵ میلیون تومان خرید کرده‌اند؟"     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STAGE 2: Schema Embedding (Pre-computed)               │
│                                                                     │
│  Schema JSON → Embedding Texts                                     │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐           │
│  │ Tables       │   │ Columns      │   │ Relations    │           │
│  │ • Customers  │   │ • CustomerID │   │ • Purchases  │           │
│  │ • Purchases  │   │ • Name       │   │   .CustomerID│           │
│  │ • Products   │   │ • Amount     │   │   ↔          │           │
│  └──────────────┘   └──────────────┘   │   Customers  │           │
│                                         │   .CustomerID│           │
│                                         └──────────────┘           │
│                                                                     │
│  Each element → 30-60 token description → Embedding vector         │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│             STAGE 3: Schema Linking (Vector Retrieval)              │
│                                                                     │
│  Question Embedding:                                               │
│  [0.12, 0.45, 0.78, 0.23, ...]                                     │
│                                                                     │
│  ChromaDB Query:                                                   │
│  • Similarity search                                               │
│  • Top-K = 10                                                      │
│  • Threshold = 0.7                                                 │
│                                                                     │
│  Retrieved Schema Elements:                                        │
│  1. Customers Table (distance: 0.23)                               │
│  2. Purchases Table (distance: 0.31)                               │
│  3. PurchaseAmount Column (distance: 0.28)                         │
│  4. PurchaseDate Column (distance: 0.34)                           │
│  5. CustomerID Relation (distance: 0.35)                           │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STAGE 4: Context Enrichment                            │
│                                                                     │
│  Assemble Structured Prompt:                                       │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │ User Question:                                            │     │
│  │ کدام مشتریان در ماه گذشته بیش از ۵ میلیون تومان...       │     │
│  │                                                           │     │
│  │ Available Database Schema:                                │     │
│  │                                                           │     │
│  │ Tables:                                                   │     │
│  │   - Customers Table: اطلاعات مشتریان...                   │     │
│  │   - Purchases Table: ثبت خریدها...                        │     │
│  │                                                           │     │
│  │ Columns:                                                  │     │
│  │   - PurchaseAmount Column: مبلغ خرید...                   │     │
│  │   - PurchaseDate Column: تاریخ خرید...                    │     │
│  │                                                           │     │
│  │ Relations:                                                │     │
│  │   - Purchases.CustomerID ↔ Customers.CustomerID          │     │
│  │                                                           │     │
│  │ Rules:                                                    │     │
│  │   - Use only provided schema                             │     │
│  │   - Do not invent tables or columns                      │     │
│  │   - Output SQL only                                      │     │
│  └───────────────────────────────────────────────────────────┘     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                STAGE 5: SQL Generation                              │
│                                                                     │
│  LLM Model (Ollama or OpenAI)                                      │
│  Temperature: 0.1 (deterministic)                                  │
│                                                                     │
│  System Prompt: "You are an SQL expert. Generate only SQL..."     │
│  User Prompt: [Assembled context from Stage 4]                    │
│                                                                     │
│  Generated SQL (Streaming):                                        │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │ SELECT c.Name, SUM(p.PurchaseAmount) as TotalPurchase    │     │
│  │ FROM Customers c                                          │     │
│  │ JOIN Purchases p ON p.CustomerID = c.CustomerID          │     │
│  │ WHERE p.PurchaseDate >= DATEADD(month, -1, GETDATE())    │     │
│  │ GROUP BY c.Name                                           │     │
│  │ HAVING SUM(p.PurchaseAmount) > 5000000;                  │     │
│  └───────────────────────────────────────────────────────────┘     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│            STAGE 6: Validation & Feedback Loop                      │
│                                                                     │
│  Step 1: Clean SQL                                                 │
│  • Remove markdown (```sql)                                        │
│  • Remove comments                                                 │
│  • Ensure semicolon                                                │
│                                                                     │
│  Step 2: Validate Syntax                                           │
│  • Use sqlparse                                                    │
│  • Check SELECT-only                                               │
│  • Validate structure                                              │
│                                                                     │
│  Step 3: Validate Schema Elements                                  │
│  • Extract table names                                             │
│  • Extract column names                                            │
│  • Verify all exist in schema                                      │
│                                                                     │
│  Step 4: Optional Execution Validation                             │
│  • Execute query against DB                                        │
│  • Catch runtime errors                                            │
│                                                                     │
│  If Error: Generate Feedback → Back to Stage 5 (max 3 times)      │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │ Feedback Example:                                       │       │
│  │                                                         │       │
│  │ Previous SQL failed:                                    │       │
│  │ SELECT Name FROM Customer WHERE Amount > 5000000       │       │
│  │                                                         │       │
│  │ Error: Table 'Customer' does not exist                 │       │
│  │                                                         │       │
│  │ Please fix:                                             │       │
│  │ - Check table name spelling                            │       │
│  │ - Available tables: Customers, Purchases, Products     │       │
│  │                                                         │       │
│  │ Generate corrected SQL:                                │       │
│  └─────────────────────────────────────────────────────────┘       │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        FINAL OUTPUT                                 │
│                                                                     │
│  ✅ Valid, Executable SQL Query                                     │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │ SELECT c.Name, SUM(p.PurchaseAmount) as TotalPurchase    │     │
│  │ FROM Customers c                                          │     │
│  │ JOIN Purchases p ON p.CustomerID = c.CustomerID          │     │
│  │ WHERE p.PurchaseDate >= DATEADD(month, -1, GETDATE())    │     │
│  │ GROUP BY c.Name                                           │     │
│  │ HAVING SUM(p.PurchaseAmount) > 5000000;                  │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
│  Metadata:                                                         │
│  • Success: true                                                   │
│  • Iterations: 1                                                   │
│  • Retrieved Elements: 5                                           │
│  • Latency: 1.2s                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🗃️ Data Flow Diagram

```
Schema JSON Files                ChromaDB Collections           LLM Services
─────────────────               ─────────────────────          ─────────────
                                                               
ecommerce_schema.json ─────►    Schema_ecommerce   ◄─────┐    
                        embed                            │    
                                                         │    Ollama
hr_schema.json ─────────────►   Schema_hr          ◄────┼───  or
                        embed                            │    OpenAI
                                                         │    
inventory_schema.json ───────►  Schema_inventory   ◄────┘    (Temperature: 0.1)
                        embed                                 
                                                              
                                     │                        
                                     │ query                  
                                     │                        
                                     ▼                        
                                                              
                            NL2SQLChain                       
                          (nl2sql_chain.py)                   
                                     │                        
                                     │                        
                                     ▼                        
                                                              
                            SQL Validator                     
                          (sql_validator.py)                  
                                     │                        
                                     │                        
                                     ▼                        
                                                              
                          Valid SQL Query                     
```

---

## 🧩 Component Interaction

```
┌─────────────────────────────────────────────────────────────────────┐
│                          API Layer                                  │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  main.py                                                     │   │
│  │  • /nl2sql endpoint                                          │   │
│  │  • Stream management                                         │   │
│  │  • Error handling                                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Orchestration Layer                            │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  nl2sql_chain.py                                             │   │
│  │  • NL2SQLChain class                                         │   │
│  │  • Pipeline execution                                        │   │
│  │  • Retrieval → Context → Generation → Validation            │   │
│  └──────────────────────────────────────────────────────────────┘   │
└───────────────┬───────────────────────────┬─────────────────────────┘
                │                           │
                ▼                           ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│   Schema Manager         │    │   SQL Validator          │
│  (schema_manager.py)     │    │  (sql_validator.py)      │
│                          │    │                          │
│  • SchemaManager         │    │  • SQLValidator          │
│  • Table                 │    │  • SQLFeedbackLoop       │
│  • Column                │    │  • Syntax validation     │
│  • Relation              │    │  • Schema validation     │
│  • JSON loading          │    │  • Error feedback        │
│  • Embedding generation  │    │  • SQL cleanup           │
└────────┬─────────────────┘    └──────────────────────────┘
         │
         ▼
┌──────────────────────────┐
│   Utilities              │
│  (utilities.py)          │
│                          │
│  • create_schema_vector  │
│  • validate_nl2sql_setup │
│  • get_schema_collection │
└──────────────────────────┘
```

---

## 🔐 Security Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Security Layers                               │
│                                                                     │
│  Layer 1: API Authentication                                       │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │  • API Key validation (check_api_key dependency)          │     │
│  │  • All /nl2sql endpoints protected                        │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
│  Layer 2: Input Validation                                         │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │  • Question length limit (250 chars)                      │     │
│  │  • Schema name validation                                 │     │
│  │  • Pydantic model validation                              │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
│  Layer 3: SQL Security                                             │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │  • SELECT-only enforcement                                │     │
│  │  • No DML/DDL allowed (INSERT, UPDATE, DELETE, DROP)     │     │
│  │  • Schema boundary enforcement                            │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
│  Layer 4: Execution Validation (Optional)                          │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │  • Query testing in transaction                           │     │
│  │  • Rollback on error                                      │     │
│  │  • No data modification                                   │     │
│  └───────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📈 Scaling Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Production Deployment                           │
│                                                                     │
│  ┌─────────────────┐     ┌─────────────────┐                       │
│  │  Load Balancer  │     │  Load Balancer  │                       │
│  └────────┬────────┘     └────────┬────────┘                       │
│           │                       │                                 │
│    ┌──────┴──────┐         ┌──────┴──────┐                         │
│    │             │         │             │                         │
│    ▼             ▼         ▼             ▼                         │
│  ┌────┐       ┌────┐     ┌────┐       ┌────┐                      │
│  │API │       │API │     │API │       │API │                      │
│  │ 1  │       │ 2  │     │ 3  │       │ 4  │                      │
│  └─┬──┘       └─┬──┘     └─┬──┘       └─┬──┘                      │
│    │            │          │            │                          │
│    └────────┬───┴──────────┴───┬────────┘                          │
│             │                  │                                   │
│             ▼                  ▼                                   │
│      ┌──────────────┐   ┌──────────────┐                          │
│      │  ChromaDB    │   │   LLM Pool   │                          │
│      │  Cluster     │   │  (Ollama/    │                          │
│      │              │   │   OpenAI)    │                          │
│      └──────────────┘   └──────────────┘                          │
│                                                                     │
│  Features:                                                         │
│  • Horizontal scaling (multiple API instances)                    │
│  • ChromaDB clustering (future)                                   │
│  • LLM pooling (multiple instances)                               │
│  • Async/await for concurrency                                    │
│  • Streaming for responsiveness                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Performance Characteristics

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Latency Breakdown                                │
│                                                                     │
│  Total Pipeline: 1.5-4 seconds                                     │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │                                                           │     │
│  │  Schema Retrieval (ChromaDB)                             │     │
│  │  ████ 100-200ms                                          │     │
│  │                                                           │     │
│  │  Context Assembly                                        │     │
│  │  ██ 20-50ms                                              │     │
│  │                                                           │     │
│  │  LLM SQL Generation                                      │     │
│  │  ████████████████████████ 1-3s                          │     │
│  │                                                           │     │
│  │  SQL Validation                                          │     │
│  │  ██ 50ms                                                 │     │
│  │                                                           │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
│  Optimization Opportunities:                                       │
│  • Cache schema retrievals for similar questions                  │
│  • Use faster embedding models                                    │
│  • Optimize ChromaDB index                                        │
│  • Use GPT-4o-mini instead of GPT-4                              │
└─────────────────────────────────────────────────────────────────────┘
```

---

**Diagram Version:** 1.0
**Last Updated:** December 2025
