"""
Schema Enhancer - Add better descriptions using AI
Enhances auto-generated schema with meaningful descriptions
"""

import json
from pathlib import Path
from typing import Dict, Any


class SchemaEnhancer:
    """Enhance schema with better descriptions and business context"""
    
    # Template for improving descriptions
    PERSIAN_TEMPLATES = {
        'Book': {
            'description': 'اطلاعات کتاب‌های موجود در سامانه نشر',
            'business_role': 'نگهداری اطلاعات کامل کتاب‌ها شامل عنوان، نویسنده، قیمت و موجودی'
        },
        'Category': {
            'description': 'دسته‌بندی کتاب‌ها بر اساس موضوع',
            'business_role': 'سازماندهی کتاب‌ها در دسته‌های مختلف مانند ادبیات، علمی، کودک و نوجوان'
        },
        'Orders': {
            'description': 'سفارشات ثبت شده توسط کاربران',
            'business_role': 'مدیریت سفارشات خرید کاربران از ثبت تا تحویل'
        },
        'OrderDetails': {
            'description': 'جزئیات اقلام هر سفارش',
            'business_role': 'ثبت کتاب‌های موجود در هر سفارش همراه با تعداد و قیمت'
        },
        'AspNetUsers': {
            'description': 'کاربران سامانه',
            'business_role': 'مدیریت حساب‌های کاربری و احراز هویت'
        },
        'Tokens': {
            'description': 'توکن‌های دسترسی کاربران',
            'business_role': 'مدیریت نشست‌ها و احراز هویت کاربران'
        },
        'Error': {
            'description': 'ثبت خطاهای سیستم',
            'business_role': 'لاگ خطاها برای رفع مشکلات و بهبود سیستم'
        }
    }
    
    # Common column name patterns
    COLUMN_PATTERNS = {
        'ID': 'شناسه یکتا',
        'Name': 'نام',
        'Title': 'عنوان',
        'Description': 'توضیحات',
        'Price': 'قیمت',
        'Date': 'تاریخ',
        'CreateDate': 'تاریخ ایجاد',
        'UpdateDate': 'تاریخ به‌روزرسانی',
        'IsActive': 'وضعیت فعال/غیرفعال',
        'IsDeleted': 'حذف شده',
        'Quantity': 'تعداد',
        'Amount': 'مبلغ',
        'Total': 'جمع کل',
        'Status': 'وضعیت',
        'Email': 'ایمیل',
        'Phone': 'شماره تماس',
        'Address': 'آدرس',
        'City': 'شهر',
        'Author': 'نویسنده',
        'Publisher': 'ناشر',
        'ISBN': 'شابک',
        'Stock': 'موجودی',
        'Image': 'تصویر',
        'Discount': 'تخفیف'
    }
    
    def __init__(self, schema_file: str):
        """Initialize with schema file path"""
        self.schema_file = Path(schema_file)
        self.schema = self._load_schema()
    
    def _load_schema(self) -> Dict[str, Any]:
        """Load schema from JSON file"""
        with open(self.schema_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _save_schema(self):
        """Save enhanced schema back to file"""
        output_file = self.schema_file.parent / f"{self.schema_file.stem}_enhanced.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.schema, f, indent=2, ensure_ascii=False)
        return output_file
    
    def enhance_table_descriptions(self):
        """Improve table descriptions"""
        for table in self.schema['tables']:
            table_name = table['name']
            if table_name in self.PERSIAN_TEMPLATES:
                template = self.PERSIAN_TEMPLATES[table_name]
                table['description'] = template['description']
                table['business_role'] = template['business_role']
    
    def enhance_column_descriptions(self):
        """Improve column descriptions based on patterns"""
        for column in self.schema['columns']:
            col_name = column['column_name']
            
            # Try to match patterns
            for pattern, persian_desc in self.COLUMN_PATTERNS.items():
                if pattern.lower() in col_name.lower():
                    column['meaning'] = f"{persian_desc} {column['table_name']}"
                    break
            
            # Enhance operations
            data_type = column['data_type']
            if data_type in ['integer', 'decimal']:
                column['operations'] = 'محاسبات، فیلتر، مرتب‌سازی'
            elif data_type == 'varchar':
                column['operations'] = 'جستجو، فیلتر، نمایش'
            elif data_type in ['date', 'datetime']:
                column['operations'] = 'فیلتر بازه زمانی، مرتب‌سازی'
            elif data_type == 'boolean':
                column['operations'] = 'فیلتر وضعیت'
    
    def enhance(self):
        """Perform all enhancements"""
        print("🔧 Enhancing schema...")
        
        self.enhance_table_descriptions()
        print("  ✓ Table descriptions enhanced")
        
        self.enhance_column_descriptions()
        print("  ✓ Column descriptions enhanced")
        
        output_file = self._save_schema()
        print(f"\n✅ Enhanced schema saved to: {output_file}")
        
        return output_file


def main():
    """Main execution"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python enhance_schema.py <schema_file>")
        print("Example: python enhance_schema.py data_schema/simacnashr_schema.json")
        sys.exit(1)
    
    schema_file = sys.argv[1]
    
    print("=" * 70)
    print("         Schema Enhancer")
    print("=" * 70)
    print(f"\nInput:  {schema_file}")
    
    enhancer = SchemaEnhancer(schema_file)
    output_file = enhancer.enhance()
    
    print("\n" + "=" * 70)
    print("Enhancement completed!")
    print("=" * 70)
    print("\nNext steps:")
    print("  1. Review the enhanced file")
    print("  2. Manually add more specific descriptions")
    print("  3. Use with your NL2SQL system")


if __name__ == "__main__":
    main()
