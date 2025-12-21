"""
Interactive Schema Extractor CLI
Run this to extract schema from any SQL Server database
"""

from extract_schema import SchemaExtractor
import sys


def main():
    print("=" * 70)
    print("         SQL Server Schema Extractor - Interactive Mode")
    print("=" * 70)
    print()
    
    # Get database connection details
    print("Enter SQL Server connection details:")
    print()
    
    server = input("Server name or IP (default: 192.168.100.16): ").strip()
    if not server:
        server = "192.168.100.16"
    
    database = input("Database name (default: SimacNashr): ").strip()
    if not database:
        database = "SimacNashr"
    
    username = input("Username (default: sa): ").strip()
    if not username:
        username = "sa"
    
    password = input("Password: ").strip()
    if not password:
        print("❌ Password is required!")
        return
    
    # Get output file path
    default_output = f"data_schema/{database.lower()}_schema.json"
    output_file = input(f"Output file path (default: {default_output}): ").strip()
    if not output_file:
        output_file = default_output
    
    print()
    print("=" * 70)
    print(f"Server:   {server}")
    print(f"Database: {database}")
    print(f"User:     {username}")
    print(f"Output:   {output_file}")
    print("=" * 70)
    print()
    
    # Confirm extraction
    confirm = input("Proceed with extraction? (y/n): ").strip().lower()
    if confirm != 'y':
        print("❌ Extraction cancelled.")
        return
    
    print()
    print("🔍 Starting extraction...")
    print()
    
    # Extract schema
    extractor = SchemaExtractor(
        server=server,
        database=database,
        username=username,
        password=password
    )
    
    success = extractor.save_schema(output_file)
    
    if success:
        print()
        print("=" * 70)
        print("✅ Schema extraction completed successfully!")
        print("=" * 70)
        print()
        print(f"📄 File saved to: {output_file}")
        print()
        print("Next steps:")
        print("  1. Review the generated JSON file")
        print("  2. Add Persian descriptions if needed")
        print("  3. Update with your NL2SQL system")
        print()
    else:
        print()
        print("=" * 70)
        print("❌ Schema extraction failed!")
        print("=" * 70)
        print()
        print("Common issues:")
        print("  - Check network connectivity to SQL Server")
        print("  - Verify SQL Server authentication is enabled")
        print("  - Ensure ODBC Driver 17 for SQL Server is installed")
        print("  - Check username and password")
        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Extraction cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        sys.exit(1)
