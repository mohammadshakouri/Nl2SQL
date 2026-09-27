from dotenv import load_dotenv
load_dotenv()
import os


def str_to_bool(value: str) -> bool:
    return str(value).lower() in ("true", "1")


openai_api_key = os.getenv('OPENAI_API_KEY')
use_local_llm = str_to_bool(os.getenv('USE_LOCAL_LLM', default=False))
use_local_embedding = str_to_bool(os.getenv('USE_LOCAL_EMBEDDING', default=False))
embedding_model_dir = os.getenv('EMBEDDING_MODEL_DIR')
