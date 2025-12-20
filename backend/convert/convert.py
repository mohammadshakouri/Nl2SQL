import pandas as pd
import json

def excel_to_json(excel_path, question_col, answer_col, output_file_path_json):
    all_sheets = pd.read_excel(excel_path, sheet_name=None)
    all_data = []  # برای ذخیره همه ردیف‌ها از همه شیت‌ها
    for sheet_name, sheet_content in all_sheets.items():     
        all_data.extend(sheet_content.to_dict(orient="records"))

    df = pd.DataFrame(all_data)
    df.drop_duplicates(subset=[question_col, answer_col], inplace=True)
    df.drop_duplicates(subset=[question_col], keep='first', inplace=True)
    df.dropna(subset=[question_col, answer_col], inplace=True)
    df["question"] = df[question_col].astype(str).apply(
        lambda x: x.replace("\n", " ").replace("\r", " ").strip()
    )
    df["answer"] = df[answer_col].astype(str).apply(
        lambda x: x.replace("\n", " ").replace("\r", " ").strip()
    )   
    df = df[["question", "answer"]]

    with open(output_file_path_json, "w", encoding="utf-8") as f:
        json.dump(df.to_dict(orient="records"), f, ensure_ascii=False, indent=4, default=str)

    output_file_path_txt = output_file_path_json.split(".json")[0] + ".txt"

    with open(output_file_path_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(output_file_path_txt, "w", encoding="utf-8") as f:
        for item in data:
            f.write("| \n")
            f.write(item["question"] + "\n")
            # f.write(f'"answer": "{item["answer"]}')

    print(f"✅ Done! Total records: {len(all_data)} saved to {output_file_path_json}")

if __name__ == "__main__":
    excel_to_json(excel_path="./yaraneh.xlsx", question_col="سوال نهایی", answer_col="پاسخ نهایی", output_file_path_json="../data_fa/yaraneh.json")
    excel_to_json(excel_path="./login_fa.xlsx", question_col="سوال نهایی", answer_col="پاسخ نهایی", output_file_path_json="../data_fa/beforelogin.json")
    excel_to_json(excel_path="./all_fa.xlsx", question_col="سوال نهایی", answer_col="پاسخ نهایی", output_file_path_json="../data_fa/afterlogin.json")
    excel_to_json(excel_path="./login_en.xlsx", question_col="question", answer_col="answer", output_file_path_json="../data_en/beforelogin.json")
    excel_to_json(excel_path="./all_en.xlsx", question_col="question", answer_col="answer", output_file_path_json="../data_en/afterlogin.json")
