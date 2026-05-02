from dotenv import load_dotenv
load_dotenv()
import os


def str_to_bool(value: str) -> bool:
    return str(value).lower() in ("true", "1")


documentation = str_to_bool(os.getenv('DOCUMENTATION', default=False))
simac_api_key = os.getenv('SIMAC_API_KEY')
openai_api_key = os.getenv('OPENAI_API_KEY')
gapgpt_api_key = os.getenv('GAPGPT_API_KEY')
main_database_url = os.getenv('MAIN_DATABASE_URL')
execution_database_url = os.getenv('EXECUTION_DATABASE_URL')
use_local_llm = str_to_bool(os.getenv('USE_LOCAL_LLM', default=False))
use_local_embedding = str_to_bool(os.getenv('USE_LOCAL_EMBEDDING', default=False))
embedding_model_dir = os.getenv('EMBEDDING_MODEL_DIR')
db_password = os.getenv('DB_PASSWORD')