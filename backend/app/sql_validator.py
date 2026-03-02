"""
SQL Validator Module for NL2SQL RAG System

Provides SQL syntax validation and execution error handling with feedback loop support.
"""

import re
import sqlparse
from typing import Dict, List, Tuple, Optional
from sqlalchemy import text, MetaData, Table as SQLATable
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.exc import SQLAlchemyError


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
        if not sql_query or not sql_query.strip():
            return False, "Empty SQL query"
        
        try:
            # Parse SQL
            parsed = sqlparse.parse(sql_query)
            
            if not parsed:
                return False, "Unable to parse SQL query"
            
            # Check if it's a valid statement
            statement = parsed[0]
            
            # Must be a SELECT statement for read-only queries
            first_token = statement.token_first(skip_ws=True, skip_cm=True)
            if first_token and first_token.ttype is sqlparse.tokens.Keyword.DML:
                if first_token.value.upper() != 'SELECT':
                    return False, "Only SELECT queries are allowed"
            
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
        
        sql_lower = sql_query.lower()
        
        # Extract table names (basic pattern matching)
        # Look for FROM and JOIN clauses
        table_pattern = r'(?:from|join)\s+([a-z_][a-z0-9_]*)'
        found_tables = re.findall(table_pattern, sql_lower)
        
        # Check if tables exist
        for table in found_tables:
            if table not in self.valid_tables:
                return False, f"Table '{table}' does not exist in schema"
        
        # Extract column names (basic pattern matching)
        # This is simplified - in production use SQL parser
        column_pattern = r'([a-z_][a-z0-9_]*)\s*\.'
        found_columns_with_table = re.findall(column_pattern, sql_lower)
        
        # Validate columns belong to tables
        for table_name in found_columns_with_table:
            if table_name not in self.valid_tables:
                # Might be an alias, skip
                continue
        
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
    
    async def execute_and_validate(
        self, 
        sql_query: str, 
        db_session: AsyncSession,
        fetch_results: bool = False
    ) -> Tuple[bool, Optional[str], Optional[List[Dict]]]:
        """
        Execute SQL query and catch errors for feedback loop
        
        Args:
            sql_query: SQL query to execute
            db_session: Database session
            fetch_results: Whether to fetch and return results
        
        Returns:
            Tuple of (success, error_message, results)
        """
        try:
            # Execute query
            result = await db_session.execute(text(sql_query))
            
            if fetch_results:
                rows = result.fetchall()
                # Convert to list of dicts
                columns = result.keys()
                results = [dict(zip(columns, row)) for row in rows]
                return True, None, results
            else:
                return True, None, None
            
        except SQLAlchemyError as e:
            error_msg = str(e.orig) if hasattr(e, 'orig') else str(e)
            return False, f"SQL execution error: {error_msg}", None
        except Exception as e:
            return False, f"Unexpected error: {str(e)}", None
    
    def extract_error_feedback(self, error_message: str) -> str:
        """
        Convert SQL error into natural language feedback for LLM
        
        Args:
            error_message: Raw error message from database
        
        Returns:
            Formatted feedback string for LLM
        """
        feedback = "SQL execution failed:\n\n"
        feedback += f"Error: {error_message}\n\n"
        feedback += "Please regenerate the SQL query fixing the following:\n"
        
        # Parse common error types
        if "does not exist" in error_message.lower():
            feedback += "- Check table and column names\n"
            feedback += "- Verify spelling matches schema exactly\n"
        elif "syntax error" in error_message.lower():
            feedback += "- Fix SQL syntax\n"
            feedback += "- Check JOIN conditions and WHERE clauses\n"
        elif "ambiguous" in error_message.lower():
            feedback += "- Use table aliases to qualify column names\n"
            feedback += "- Ensure column references are unambiguous\n"
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
    
    def get_feedback_prompt(self) -> str:
        """
        Generate feedback prompt for LLM based on previous failures
        
        Returns:
            Formatted feedback string
        """
        if not self.iteration_history:
            return ""
        
        last_iteration = self.iteration_history[-1]
        
        if last_iteration["success"]:
            return ""
        
        feedback = f"\nPrevious attempt failed (Iteration {last_iteration['iteration']}):\n\n"
        feedback += f"SQL: {last_iteration['sql']}\n\n"
        feedback += self.validator.extract_error_feedback(last_iteration['error'])
        feedback += "\nGenerate corrected SQL query:\n"
        
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
