"""
Schema-RAG (NL2SQL) System - End-to-End Demo

This script demonstrates the complete NL2SQL pipeline:
1. Schema loading and embedding generation
2. Question-to-SQL conversion
3. Validation and error handling

Run this to verify the system is working correctly.
"""

import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.schema_manager import SchemaManager
from app.nl2sql_chain import NL2SQLChain
from app.utilities import create_schema_vector_store, validate_nl2sql_setup


async def demo_nl2sql_pipeline():
    """
    Demonstrate complete NL2SQL pipeline
    """
    
    print("="*80)
    print("Schema-RAG (NL2SQL) System - End-to-End Demo")
    print("="*80)
    print()
    
    # Step 1: Setup Schema
    print("Step 1: Setting up schema vector store...")
    print("-" * 80)
    
    schema_json_path = "./data_schema/ecommerce_schema.json"
    schema_name = "ecommerce"
    
    # Check if schema exists
    if not os.path.exists(schema_json_path):
        print(f"❌ Schema file not found: {schema_json_path}")
        return
    
    print(f"✓ Schema file found: {schema_json_path}")
    
    # Create vector store if needed
    try:
        stats = create_schema_vector_store(schema_json_path, schema_name)
        print(f"✓ Schema vector store created/updated:")
        print(f"  - Tables: {stats['tables']}")
        print(f"  - Columns: {stats['columns']}")
        print(f"  - Relations: {stats['relations']}")
        print(f"  - Total units: {stats['total_units']}")
        print(f"  - Collection: {stats['collection_name']}")
    except Exception as e:
        print(f"❌ Error creating vector store: {e}")
        return
    
    print()
    
    # Step 2: Validate Setup
    print("Step 2: Validating NL2SQL setup...")
    print("-" * 80)
    
    validation = validate_nl2sql_setup(schema_name)
    
    if validation['is_valid']:
        print("✓ System is properly configured")
        print(f"  - Schema JSON exists: {validation['schema_json_exists']}")
        print(f"  - Collection exists: {validation['collection_exists']}")
        print(f"  - Embedded elements: {validation.get('collection_count', 'N/A')}")
    else:
        print("❌ System validation failed:")
        for error in validation['errors']:
            print(f"  - {error}")
        return
    
    print()
    
    # Step 3: Load Schema Manager
    print("Step 3: Loading schema manager...")
    print("-" * 80)
    
    manager = SchemaManager()
    manager.load_schema_from_json(schema_json_path)
    
    summary = manager.get_schema_summary()
    print(f"✓ Schema loaded successfully")
    print(f"  - Tables: {summary['tables']}")
    print(f"  - Columns: {summary['columns']}")
    print(f"  - Relations: {summary['relations']}")
    
    print()
    
    # Step 4: Initialize NL2SQL Chain
    print("Step 4: Initializing NL2SQL chain...")
    print("-" * 80)
    
    chain = NL2SQLChain(
        schema_manager=manager,
        collection_name=f"Schema_{schema_name}",
        culture="fa"
    )
    
    print("✓ NL2SQL chain initialized")
    print()
    
    # Step 5: Test Questions
    print("Step 5: Testing NL2SQL generation...")
    print("-" * 80)
    
    test_questions = [
        "کدام مشتریان در ماه گذشته بیش از ۵ میلیون تومان خرید کرده‌اند؟",
        "محبوب‌ترین محصولات از نظر تعداد فروش کدامند؟",
        "میانگین مبلغ خرید در سه ماه گذشته چقدر بوده است؟",
    ]
    
    for i, question in enumerate(test_questions, 1):
        print(f"\nTest {i}:")
        print(f"Question: {question}")
        print()
        
        # Execute pipeline
        result = await chain.execute_pipeline(
            question=question,
            validate_execution=False,
            max_feedback_iterations=3
        )
        
        if result['success']:
            print("✓ SQL Generated Successfully")
            print(f"\nSQL Query:")
            print("-" * 40)
            print(result['sql'])
            print("-" * 40)
            print(f"Iterations: {result['iterations']}")
            print(f"Retrieved elements: {result['retrieved_elements']}")
        else:
            print(f"❌ SQL Generation Failed")
            print(f"Error: {result.get('error', 'Unknown error')}")
            if result.get('sql'):
                print(f"Last attempted SQL: {result['sql']}")
        
        print()
    
    # Step 6: Demonstrate Schema Retrieval
    print("Step 6: Demonstrating schema retrieval...")
    print("-" * 80)
    
    question = "مشتریان و خریدهای آنها"
    retrieved, distances = chain.retrieve_schema_elements(question, n_results=5)
    
    print(f"Question: {question}")
    print(f"Retrieved {len(retrieved)} schema elements:")
    print()
    
    for doc, dist in zip(retrieved, distances):
        print(f"  [Distance: {dist:.3f}] {doc}")
    
    print()
    
    # Step 7: Summary
    print("="*80)
    print("Demo completed successfully! ✓")
    print("="*80)
    print()
    print("Next steps:")
    print("1. Test with your own questions via API: POST /nl2sql")
    print("2. Add your own database schema in data_schema/")
    print("3. Customize SQL generation prompts in app/system_prompt.py")
    print("4. Enable SQL execution validation with real database")
    print()


def demo_schema_transformation():
    """
    Demonstrate schema-to-embedding transformation
    """
    
    print("="*80)
    print("Schema Transformation Demo")
    print("="*80)
    print()
    
    from app.schema_manager import Table, Column, Relation
    
    # Example table
    table = Table(
        name="Customers",
        description="اطلاعات مشتریان شامل نام و تاریخ عضویت",
        key_columns=["CustomerID", "Name", "JoinDate"],
        business_role="نگهداری اطلاعات اشخاصی که خرید انجام داده‌اند"
    )
    
    print("Table Definition:")
    print(f"  Name: {table.name}")
    print(f"  Description: {table.description}")
    print()
    print("Embedding Text:")
    print(f"  {table.to_embedding_text()}")
    print()
    print("-" * 80)
    print()
    
    # Example column
    column = Column(
        table_name="Purchases",
        column_name="PurchaseAmount",
        meaning="مبلغ پرداختی خرید",
        data_type="decimal",
        operations="محاسبه مجموع و میانگین خریدها"
    )
    
    print("Column Definition:")
    print(f"  Table: {column.table_name}")
    print(f"  Column: {column.column_name}")
    print(f"  Meaning: {column.meaning}")
    print()
    print("Embedding Text:")
    print(f"  {column.to_embedding_text()}")
    print()
    print("-" * 80)
    print()
    
    # Example relation
    relation = Relation(
        source_table="Purchases",
        source_column="CustomerID",
        target_table="Customers",
        target_column="CustomerID",
        relationship_type="many-to-one",
        join_purpose="connecting each purchase to its customer"
    )
    
    print("Relation Definition:")
    print(f"  Source: {relation.source_table}.{relation.source_column}")
    print(f"  Target: {relation.target_table}.{relation.target_column}")
    print(f"  Type: {relation.relationship_type}")
    print()
    print("Embedding Text:")
    print(f"  {relation.to_embedding_text()}")
    print()


if __name__ == "__main__":
    
    import argparse
    
    parser = argparse.ArgumentParser(description="Schema-RAG NL2SQL Demo")
    parser.add_argument(
        "--mode",
        choices=["full", "transform"],
        default="full",
        help="Demo mode: 'full' for complete pipeline, 'transform' for schema transformation only"
    )
    
    args = parser.parse_args()
    
    if args.mode == "transform":
        demo_schema_transformation()
    else:
        asyncio.run(demo_nl2sql_pipeline())
