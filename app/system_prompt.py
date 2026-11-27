# ============================================================================
# NL2SQL System Prompts - Schema-RAG
# ============================================================================
# Both benchmarks (Spider, BIRD) run on SQLite, so the dialect is stated outright. Each rule
# answers something the error analyses found (docs/thesis/Error_Analysis_*_fa.md): first
# attempts rejected for FETCH FIRST / EXTRACT / ALL, integer division through CAST AS DECIMAL,
# and result columns that are not the ones the question asks for. Every construct named below
# was checked against SQLite 3.49 (the version of the harness). The full-name, join, LIMIT and
# CAST wording follows the analysis of the runs after value grounding: gold sometimes has a
# full-name column (winner_name, FullName) and sometimes first_name + last_name, and failures
# that join more tables than gold, add a LIMIT or CAST a column were two to four times as common.
# There is no rule against Yes/No: gold itself answers 5 of 17 yes/no questions with a literal.

_SQLITE_RULES: str = """\
SQLite rules:
- LIMIT n for row limits (no TOP, no FETCH FIRST); no ANY/ALL/ILIKE.
- Dates are text: strftime('%Y', c), date(), julianday() (no EXTRACT, YEAR(), DATEDIFF); substr(x, i, n) (no SUBSTRING ... FROM); || concatenates.
- Integer division truncates: CAST(x AS REAL) / y (CAST AS DECIMAL does not help; use CAST only for this); ROUND(x, n) to round.
- Strings in single quotes, compared case-sensitively by =: copy a value listed under Values exactly; quote names with spaces or symbols as "name"."""

_RESULT_RULES: str = """\
Result columns: exactly what the question asks for, in its order, one column per item (a full name: the column that holds it, else the first-name and last-name columns); no extra id/count/helper columns; no SELECT * unless every column is asked for; no LIMIT unless the question asks for a top, first or single row."""

SYSTEM_PROMPT_NL2SQL: str = f"""\
Write one SQLite query that answers the question, using only the tables, columns and relations of the Schema: never invent any. Join along the relations, but only the tables the answer needs (a key that one table already holds needs no join).

{_SQLITE_RULES}

{_RESULT_RULES}

Output only the SQL, no explanation.
"""

SYSTEM_PROMPT_NL2SQL_FEEDBACK: str = f"""\
Your previous SQLite query failed or was rejected: fix it using the error you are given. Check table and column spellings against the Schema and the JOIN conditions, and qualify ambiguous columns with aliases.

{_SQLITE_RULES}

{_RESULT_RULES}

Output only the corrected SQL, no explanation.
"""
