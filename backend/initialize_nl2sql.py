"""
NL2SQL System Initialization Script

This script automates the setup of the Schema-RAG (NL2SQL) system:
1. Validates dependencies
2. Creates schema vector stores
3. Validates setup
4. Provides next steps

Run this after installing requirements.txt
"""

import os
import sys

def check_dependencies():
    """Check if all required packages are installed"""
    
    print("Checking dependencies...")
    print("-" * 80)
    
    required_packages = {
        'chromadb': 'ChromaDB',
        'sqlparse': 'SQL Parser',
        'fastapi': 'FastAPI',
        'openai': 'OpenAI',
        'ollama': 'Ollama',
        'sqlalchemy': 'SQLAlchemy',
    }
    
    missing = []
    
    for package, name in required_packages.items():
        try:
            __import__(package)
            print(f"✓ {name} installed")
        except ImportError:
            print(f"✗ {name} missing")
            missing.append(package)
    
    print()
    
    if missing:
        print(f"❌ Missing packages: {', '.join(missing)}")
        print("Run: pip install -r requirements.txt")
        return False
    
    print("✓ All dependencies installed")
    return True


def check_schema_files():
    """Check if schema files exist"""
    
    print("\nChecking schema files...")
    print("-" * 80)
    
    schema_dir = "./data_schema"
    
    if not os.path.exists(schema_dir):
        print(f"✗ Schema directory not found: {schema_dir}")
        return False
    
    print(f"✓ Schema directory found: {schema_dir}")
    
    # Check example schema
    example_schema = os.path.join(schema_dir, "ecommerce_schema.json")
    if os.path.exists(example_schema):
        print(f"✓ Example schema found: {example_schema}")
        return True
    else:
        print(f"✗ Example schema not found: {example_schema}")
        return False


def initialize_schema_vector_stores():
    """Create vector stores for all schemas in data_schema/"""
    
    print("\nInitializing schema vector stores...")
    print("-" * 80)
    
    try:
        from app.utilities import create_schema_vector_store
        import json
        
        schema_dir = "./data_schema"
        
        # Find all schema JSON files
        schema_files = [
            f for f in os.listdir(schema_dir) 
            if f.endswith('_schema.json')
        ]
        
        if not schema_files:
            print("✗ No schema files found in data_schema/")
            return False
        
        print(f"Found {len(schema_files)} schema file(s)")
        print()
        
        for schema_file in schema_files:
            schema_path = os.path.join(schema_dir, schema_file)
            schema_name = schema_file.replace('_schema.json', '')
            
            print(f"Processing: {schema_name}")
            print(f"  File: {schema_file}")
            
            try:
                # Create vector store
                stats = create_schema_vector_store(
                    schema_json_path=schema_path,
                    schema_name=schema_name
                )
                
                print(f"  ✓ Vector store created")
                print(f"    - Tables: {stats['tables']}")
                print(f"    - Columns: {stats['columns']}")
                print(f"    - Relations: {stats['relations']}")
                print(f"    - Collection: {stats['collection_name']}")
                print()
                
            except Exception as e:
                print(f"  ✗ Error: {e}")
                return False
        
        print("✓ All schema vector stores created successfully")
        return True
        
    except Exception as e:
        print(f"✗ Initialization failed: {e}")
        return False


def validate_setup():
    """Validate the complete setup"""
    
    print("\nValidating system setup...")
    print("-" * 80)
    
    try:
        from app.utilities import validate_nl2sql_setup
        
        # Validate ecommerce schema
        results = validate_nl2sql_setup("ecommerce")
        
        if results['is_valid']:
            print("✓ System validation passed")
            print(f"  - Schema JSON: {'✓' if results['schema_json_exists'] else '✗'}")
            print(f"  - Collection: {'✓' if results['collection_exists'] else '✗'}")
            print(f"  - Elements: {results.get('collection_count', 'N/A')}")
            return True
        else:
            print("✗ System validation failed")
            for error in results.get('errors', []):
                print(f"  - {error}")
            return False
            
    except Exception as e:
        print(f"✗ Validation error: {e}")
        return False


def print_next_steps():
    """Print next steps for the user"""
    
    print("\n" + "="*80)
    print("NL2SQL System Ready! 🚀")
    print("="*80)
    print()
    print("Next Steps:")
    print()
    print("1. Run the demo:")
    print("   python demo_nl2sql.py")
    print()
    print("2. Start the FastAPI server:")
    print("   python main.py")
    print()
    print("3. Test via API:")
    print('   curl -X POST "http://localhost:80/nl2sql" \\')
    print('     -H "api_key: YOUR_API_KEY" \\')
    print('     -H "Content-Type: application/json" \\')
    print('     -d \'{"threadId": "", "question": "کدام مشتریان بیش از ۵ میلیون تومان خرید کرده‌اند؟", "schema_name": "ecommerce", "culture": "fa"}\'')
    print()
    print("4. Read the documentation:")
    print("   - NL2SQL_README.md - Complete overview")
    print("   - NL2SQL_SETUP.md - Detailed setup guide")
    print("   - data_schema/example_queries.md - Test cases")
    print()
    print("5. Add your own database schema:")
    print("   - Create data_schema/yourdb_schema.json")
    print("   - Run: python -c 'from app.utilities import create_schema_vector_store; create_schema_vector_store(\"./data_schema/yourdb_schema.json\", \"yourdb\")'")
    print()


def main():
    """Main initialization workflow"""
    
    print("="*80)
    print("Schema-RAG (NL2SQL) System Initialization")
    print("="*80)
    print()
    
    # Step 1: Check dependencies
    if not check_dependencies():
        print("\n❌ Initialization failed: Missing dependencies")
        sys.exit(1)
    
    # Step 2: Check schema files
    if not check_schema_files():
        print("\n❌ Initialization failed: Schema files not found")
        sys.exit(1)
    
    # Step 3: Create vector stores
    if not initialize_schema_vector_stores():
        print("\n❌ Initialization failed: Vector store creation failed")
        sys.exit(1)
    
    # Step 4: Validate setup
    if not validate_setup():
        print("\n❌ Initialization failed: Validation failed")
        sys.exit(1)
    
    # Success
    print_next_steps()


if __name__ == "__main__":
    main()
