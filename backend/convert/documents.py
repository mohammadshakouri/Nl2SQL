import os
from docx import Document
import re

# مسیر پوشه‌ی اصلی شامل زیرپوشه‌ها
base_dir = "./docx"
output_file = "../data_fa/documents.txt"

def clean_chunk(text):
    # حذف کاراکترهای کنترل راست‌به‌چپ و مشابه
    text = re.sub(r'[\u200f\u200e\u202a-\u202e]', '', text)
    text = text.replace('\xa0', ' ')
    # این‌جا دیگه \n رو نمی‌گیریم چون می‌خوایم چانک صاف باشه
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def read_docx_with_empty_paragraphs(path):
    doc = Document(path)
    parts = []
    for p in doc.paragraphs:
        txt = p.text
        if txt.strip() == "":
            # این یعنی کاربر واقعاً یک Enter خالی زده
            parts.append("\n\n")
        else:
            # پاراگراف واقعی
            parts.append(txt + "\n")
    full_text = "".join(parts)
    return full_text

def split_into_chunks_preserve_breaks(text):
    # حالا که \n\n واقعی داریم، می‌تونیم تقسیم کنیم
    # هر جایی یکی یا بیشتر بلوک خالی هست جدا کن
    raw_chunks = re.split(r'(?:\n\s*\n)+', text)
    # تمیز کردن هر چانک
    chunks = [clean_chunk(c) for c in raw_chunks if c.strip()]
    return chunks

all_chunks = []

for root, dirs, files in os.walk(base_dir):
    for file in files:
        if file.endswith(".docx"):
            file_path = os.path.join(root, file)
            folder_name = os.path.basename(root)
            file_name = os.path.splitext(file)[0]

            full_text = read_docx_with_empty_paragraphs(file_path)
            chunks = split_into_chunks_preserve_breaks(full_text)

            for chunk in chunks:
                line = f"{folder_name} - {file_name} - {chunk}\n|"
                all_chunks.append(line)

# نوشتن در فایل خروجی
with open(output_file, "w", encoding="utf-8") as f:
    for line in all_chunks:
        f.write(line + "\n")

print(f"✅ {len(all_chunks)} chunks saved to {output_file}")
