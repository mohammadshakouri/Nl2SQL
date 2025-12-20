from dotenv import load_dotenv
load_dotenv()
import os


def str_to_bool(value: str) -> bool:
    return str(value).lower() in ("true", "1")


documentation = str_to_bool(os.getenv('DOCUMENTATION', default=False))
simac_api_key = os.getenv('SIMAC_API_KEY')
openai_api_key = os.getenv('OPENAI_API_KEY')
sql_database_url = os.getenv('SQL_DATABASE_URL')
use_local_llm = str_to_bool(os.getenv('USE_LOCAL_LLM', default=False))
use_local_embedding = str_to_bool(os.getenv('USE_LOCAL_EMBEDDING', default=False))