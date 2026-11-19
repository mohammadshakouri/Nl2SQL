"""
SQL Validator Module for NL2SQL RAG System

Provides static SQL syntax/schema validation with feedback-loop support.
Actual SQLite execution (used for Execution Accuracy and, with
``--exec-feedback``, as an extra error signal in the feedback loop) lives in
``app.spider_eval.spider_sqlite_executor``.
"""

import re
import sqlparse
from typing import Dict, List, Tuple, Optional


class SQLValidator:
    """Validates SQL queries against schema metadata and syntax rules"""
    
    def __init__(self, schema_manager=None):
        """
        Initialize SQL validator
        
        Args:
            schema_manager: Optional SchemaManager instance for schema validation
        """
        self.schema_manager = schema_manager
        self.valid_tables = set()
        self.valid_columns = {}  # {table_name: [column_names]}
        
        if schema_manager:
            self._load_schema_metadata()
    
    def _load_schema_metadata(self):
        """Load table and column names from schema manager"""
        for table in self.schema_manager.tables:
            self.valid_tables.add(table.name.lower())
        
        for column in self.schema_manager.columns:
            table_name = column.table_name.lower()
            if table_name not in self.valid_columns:
                self.valid_columns[table_name] = []
            self.valid_columns[table_name].append(column.column_name.lower())
    
    def validate_syntax(self, sql_query: str) -> Tuple[bool, Optional[str]]:
        """
        Validate SQL syntax using sqlparse
        
        Args:
            sql_query: SQL query string
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # clean_sql_output() turns an empty LLM response into ";"
        if not sql_query or not sql_query.strip().strip(';').strip():
            return False, "Empty SQL query"

        try:
            # Parse SQL
            parsed = [s for s in sqlparse.parse(sql_query) if s.value.strip().strip(';').strip()]

            if not parsed:
                return False, "Unable to parse SQL query"

            if len(parsed) > 1:
                return False, "Multiple SQL statements; return exactly one SELECT query"

            # Check if it's a valid statement
            statement = parsed[0]

            # Must be a SELECT statement (optionally with a CTE) for read-only queries
            first_token = statement.token_first(skip_ws=True, skip_cm=True)
            if first_token is None:
                return False, "Unable to parse SQL query"
            if first_token.ttype is sqlparse.tokens.Keyword.DML:
                if first_token.value.upper() != 'SELECT':
                    return False, "Only SELECT queries are allowed"
            elif first_token.ttype is not sqlparse.tokens.Keyword.CTE:
                return False, (
                    f"Query must start with SELECT, found '{first_token.value[:30]}'; "
                    "do not write any text before the SQL"
                )

            return True, None
            
        except Exception as e:
            return False, f"Syntax error: {str(e)}"
    
    def validate_schema_elements(self, sql_query: str) -> Tuple[bool, Optional[str]]:
        """
        Validate that tables and columns in SQL exist in schema
        
        Args:
            sql_query: SQL query string
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.schema_manager:
            # Skip validation if no schema manager
            return True, None
        
        # Blank out string literals so words inside them ('... from X') are ignored
        sql_lower = re.sub(r"'(?:[^']|'')*'", "''", sql_query.lower())

        # CTE names are legal FROM/JOIN targets even though they are not tables
        cte_names = set(re.findall(r'(?:\bwith(?:\s+recursive)?|,)\s+([a-z_][a-z0-9_]*)\s+as\s*\(', sql_lower))

        # Extract table names (basic pattern matching)
        # Look for FROM and JOIN clauses
        table_pattern = r'\b(?:from|join)\s+["`\[]?([a-z_][a-z0-9_]*)'
        found_tables = re.findall(table_pattern, sql_lower)

        # Check if tables exist
        for table in found_tables:
            if table not in self.valid_tables and table not in cte_names:
                return False, f"Table '{table}' does not exist in schema"

        # Column names are not checked here; use execution feedback
        # (SpiderSQLiteExecutor) to catch "no such column" errors.
        return True, None
    
    def validate_query(self, sql_query: str) -> Tuple[bool, Optional[str]]:
        """
        Comprehensive validation: syntax + schema
        
        Args:
            sql_query: SQL query string
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Step 1: Syntax validation
        is_valid, error = self.validate_syntax(sql_query)
        if not is_valid:
            return False, error
        
        # Step 2: Schema validation
        is_valid, error = self.validate_schema_elements(sql_query)
        if not is_valid:
            return False, error
        
        return True, None
    
    def extract_error_feedback(self, error_message: str) -> str:
        """
        Convert a validation or SQLite execution error into feedback for the LLM

        Args:
            error_message: Error from validate_query() or from executing the SQL

        Returns:
            Formatted feedback string for LLM
        """
        feedback = f"Error: {error_message}\n"
        feedback += "Fix:\n"

        # Parse common error types (static validator and SQLite messages)
        error_lower = error_message.lower()
        if any(s in error_lower for s in ("does not exist", "no such table", "no such column")):
            feedback += "- Check table and column names\n"
            feedback += "- Verify spelling matches schema exactly\n"
        elif "ambiguous" in error_lower:
            feedback += "- Use table aliases to qualify column names\n"
            feedback += "- Ensure column references are unambiguous\n"
        elif "no such function" in error_lower:
            feedback += "- Use only functions supported by SQLite\n"
        elif "empty sql" in error_lower or "must start with select" in error_lower:
            feedback += "- Output only the SQL query, starting with SELECT, with no other text\n"
        elif "syntax error" in error_lower or "incomplete input" in error_lower:
            feedback += "- Fix SQL syntax (the query runs on SQLite)\n"
            feedback += "- Check JOIN conditions and WHERE clauses\n"
        else:
            feedback += "- Review the error and adjust the query accordingly\n"

        return feedback
    
    def clean_sql_output(self, llm_output: str) -> str:
        """
        Extract clean SQL from LLM output (remove markdown, comments, etc.)
        
        Args:
            llm_output: Raw LLM output
        
        Returns:
            Clean SQL query string
        """
        # Remove markdown code blocks
        sql = re.sub(r'```sql\s*', '', llm_output)
        sql = re.sub(r'```\s*', '', sql)
        
        # Remove single-line comments
        sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
        
        # Remove multi-line comments
        sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        
        # also remove \n and \t
        sql = sql.replace('\n', ' ').replace('\t', ' ')
        
        # Remove leading/trailing whitespace
        sql = sql.strip()
        
        # Ensure ends with semicolon
        if not sql.endswith(';'):
            sql += ';'
        
        return sql


class SQLFeedbackLoop:
    """Manages iterative SQL generation with error feedback"""
    
    def __init__(self, validator: SQLValidator, max_iterations: int = 3):
        """
        Initialize feedback loop
        
        Args:
            validator: SQLValidator instance
            max_iterations: Maximum number of regeneration attempts
        """
        self.validator = validator
        self.max_iterations = max_iterations
        self.iteration_history: List[Dict] = []
    
    def add_iteration(self, sql: str, error: Optional[str] = None, success: bool = False):
        """Record an iteration in the feedback loop"""
        self.iteration_history.append({
            "sql": sql,
            "error": error,
            "success": success,
            "iteration": len(self.iteration_history) + 1
        })
    
    def get_feedback_prompt(self) -> Optional[str]:
        """
        Generate feedback prompt for LLM based on previous failures.

        Returns ``None`` when there is no failure history (first iteration or
        last iteration succeeded) so callers can distinguish "no feedback"
        from an empty string.
        """
        if not self.iteration_history:
            return None

        if self.iteration_history[-1]["success"]:
            return None

        # Show every failed attempt, not just the last one, so the model does
        # not oscillate back to a query that was already rejected.
        feedback = "Previous attempts failed:\n\n"
        for iteration in self.iteration_history:
            if iteration["success"]:
                continue
            feedback += f"Attempt {iteration['iteration']}:\n"
            feedback += f"SQL: {iteration['sql']}\n"
            feedback += self.validator.extract_error_feedback(iteration['error'])
            feedback += "\n"

        return feedback
    
    def should_continue(self) -> bool:
        """Check if should continue iteration"""
        return len(self.iteration_history) < self.max_iterations
    
    def get_final_result(self) -> Dict:
        """Get final result summary"""
        if not self.iteration_history:
            return {"success": False, "error": "No iterations performed"}
        
        last = self.iteration_history[-1]
        
        return {
            "success": last["success"],
            "sql": last["sql"],
            "error": last.get("error"),
            "iterations": len(self.iteration_history),
            "history": self.iteration_history
        }
