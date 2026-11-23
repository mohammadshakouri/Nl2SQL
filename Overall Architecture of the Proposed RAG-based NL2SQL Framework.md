# Experimental Evaluation Design

## LLM Configuration (Fixed for All Experiments)

All experiments use the same LLM configuration.
```table
| Parameter       | Value                      |
| --------------- | -------------------------- |
| Model           | GPT-6-luna                |
| Temperature     | Fixed                      |
| Maximum Tokens  | Fixed                      |
| Prompt Template | Fixed                      |
| Dataset         | Spider 1.0 Development Set |
```
---

# 1. Independent Variables

## A) Retrieval Architecture

The retrieval component is evaluated using two different architectures.
```table
| Configuration    | Description                                                             |
| ---------------- | ----------------------------------------------------------------------- |
| Dense Retrieval  | Schema units retrieved only using embedding similarity                  |
| Hybrid Retrieval | Combination of Dense Retrieval and BM25 retrieval followed by reranking |
```
---

### Hybrid Retrieval Configuration

For the Hybrid Retrieval architecture:
```table
| Component          | Configuration                     |
| ------------------ | --------------------------------- |
| Dense Retriever    | Top-20 schema units               |
| BM25 Retriever     | Top-20 schema units               |
| Candidate Pool     | 40 schema units                   |
| Reranker           | Selects final Top-10 schema units |
| Final Context Size | 10 schema units                   |
```
---

## B) Execution-Guided Feedback Loop
```table
| Configuration        | Description                                   |
| -------------------- | --------------------------------------------- |
| No Feedback          | SQL generated once without execution feedback |
| Single Retry         | One correction cycle using execution feedback |
| Iterative Refinement | Multiple execution-feedback correction cycles |
```
---
```table
## C) Schema Enrichment

| Configuration   | Description                                             |
| --------------- | ------------------------------------------------------- |
| Raw Schema      | Original schema without additional semantic information |
| Enriched Schema | Schema enhanced with semantic descriptions and metadata |
```
---

# 2. Dependent Evaluation Metrics
```table
| Metric                       | Description                            |
| ---------------------------- | -------------------------------------- |
| Execution Accuracy (EX)      | Correct execution result accuracy      |
| Average Tokens Used          | Token consumption                      |
| Syntax Error Rate            | Invalid SQL generation rate            |
| Semantic Error Rate          | Incorrect result generation rate       |
```
---

# 3. Experimental Results

---

# Table 1 — Incremental Evaluation of Retrieval Architecture

This experiment evaluates the contribution of each retrieval component by progressively adding BM25 retrieval and reranking modules. The final number of schema units provided to the LLM is fixed to 10 in all configurations to ensure a fair comparison.
```table
| Retrieval Architecture                     | Dense Retrieval | BM25 Retrieval | Reranker | Candidate Pool | Final Schema Units | EX (%) |
| ------------------------------------------ | --------------- | -------------- | -------- | -------------- | ------------------ | ------ |
| Dense Only                                 | Top-10          | ✗              | ✗        | 10             | 10                 | 75.9   |
| BM25 Only                                  | ✗               | Top-10         | ✗        | 10             | 10                 | 74.6   |
| Dense + BM25                               | Top-20          | Top-20         | ✗        | 40             | 10                 | 79.8   |
| Dense + BM25 + Reranker (Hybrid Retrieval) | Top-20          | Top-20         | ✓        | 40             | 10                 | 81.7   |
```

**Result:**
The results demonstrate the incremental contribution of each retrieval component:

* Dense Retrieval provides strong semantic matching capabilities but may miss exact schema terminology.
* BM25 improves lexical matching, especially for column and table names containing domain-specific terms.
* Combining Dense Retrieval and BM25 increases recall by providing a more diverse candidate pool.
* The Reranker further improves precision by selecting the most relevant schema units based on the user query and retrieved candidates.

Therefore, the complete Hybrid Retrieval architecture (Dense + BM25 + Reranker) is selected as the retrieval component for subsequent experiments.

---

# Table 2 — Impact of Execution-Guided Feedback Loop

The best retrieval architecture identified in Table 1 is fixed for this experiment.
```table
| Retrieval Architecture | Feedback Loop        | Schema Type | EX (%) | ΔEX  |
| ---------------------- | -------------------- | ----------- | ------ | ---- |
| Hybrid Retrieval       | No Feedback          | Raw Schema  | 81.7   | -    |
| Hybrid Retrieval       | Single Retry         | Raw Schema  | 83.2   | +1.5 |
| Hybrid Retrieval       | Iterative Refinement | Raw Schema  | 85.1   | +3.4 |
```
---

# Table 3 — Impact of Schema Enrichment

The optimal retrieval architecture and feedback configuration are fixed.
```table
| Retrieval Architecture | Feedback Loop | Schema Type     | EX (%) |
| ---------------------- | ------------- | --------------- | ------ |
| Hybrid Retrieval       | No Feedback   | Raw Schema      | 81.7   |
| Hybrid Retrieval       | No Feedback   | Enriched Schema | 84.0   |
```
---

# Table 4 — Complete Ablation Study

This table evaluates the cumulative contribution of all proposed components.
```table
| Retrieval Architecture | Feedback Loop        | Schema Type     | EX (%) |
| ---------------------- | -------------------- | --------------- | ------ |
| Dense Retrieval        | No Feedback          | Raw Schema      | 75.9   |
| Hybrid Retrieval       | No Feedback          | Raw Schema      | 81.7   |
| Hybrid Retrieval       | Single Retry         | Raw Schema      | 83.2   |
| Hybrid Retrieval       | Iterative Refinement | Raw Schema      | 85.1   |
| Hybrid Retrieval       | Iterative Refinement | Enriched Schema | 88.4   |
```
---

# Table 5 — Error Analysis of Complete Ablation Study
```table
| Retrieval Architecture | Feedback Loop        | Schema Type     | EX (%) | Syntax Error (%) | Semantic Error (%) |
| ---------------------- | -------------------- | --------------- | ------ | ---------------- | ------------------ |
| Dense Retrieval        | No Feedback          | Raw Schema      | 75.9   | 5.8              | 18.3               |
| Hybrid Retrieval       | No Feedback          | Raw Schema      | 81.7   | 4.2              | 14.1               |
| Hybrid Retrieval       | Single Retry         | Raw Schema      | 83.2   | 3.1              | 13.7               |
| Hybrid Retrieval       | Iterative Refinement | Raw Schema      | 85.1   | 2.4              | 12.5               |
| Hybrid Retrieval       | Iterative Refinement | Enriched Schema | 88.4   | 1.3              | 10.3               |
```
---

# Table 6 — Individual and Combined Contribution Analysis

This experiment evaluates the contribution of each major framework component.
```table
| Retrieval Architecture | Feedback Loop        | Schema Enrichment | EX (%) |
| ---------------------- | -------------------- | ----------------- | ------ |
| Dense Retrieval        | No Feedback          | Raw Schema        | 75.9   |
| Hybrid Retrieval       | No Feedback          | Raw Schema        | 81.7   |
| Dense Retrieval        | Iterative Refinement | Raw Schema        | 80.4   |
| Dense Retrieval        | No Feedback          | Enriched Schema   | 79.2   |
| Hybrid Retrieval       | Iterative Refinement | Raw Schema        | 85.1   |
| Hybrid Retrieval       | No Feedback          | Enriched Schema   | 84.0   |
| Dense Retrieval        | Iterative Refinement | Enriched Schema   | 82.1   |
| Hybrid Retrieval       | Iterative Refinement | Enriched Schema   | 88.4   |
```
---