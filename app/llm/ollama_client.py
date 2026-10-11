import requests
import json
import time
import os
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

load_dotenv()

T = TypeVar('T', bound=BaseModel)

class OllamaClient:
    def __init__(self):
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "qwen3-coder")
        self.num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
        self.timeout = 60

    def check_health(self) -> bool:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def is_model_available(self) -> bool:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            if response.status_code == 200:
                models = [m['name'] for m in response.json().get('models', [])]
                return any(self.model in m for m in models)
            return False
        except Exception:
            return False

    def generate_structured(self, prompt: str, response_model: Type[T], retries: int = 1) -> T:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_ctx": self.num_ctx
            }
        }

        attempt = 0
        last_error = None

        while attempt <= retries:
            try:
                response = requests.post(
                    f"{self.host}/api/generate",
                    json=payload,
                    timeout=self.timeout
                )
                response.raise_for_status()

                result_text = response.json().get("response", "")
                return response_model.model_validate_json(result_text)

            except (requests.RequestException, ValidationError, json.JSONDecodeError) as e:
                attempt += 1
                last_error = e
                if attempt <= retries:
                    # Append the error to the prompt for the retry
                    payload["prompt"] += f"\n\nYour previous response was invalid: {str(e)}. Please correct the JSON structure and try again."
                    time.sleep(1)

        raise RuntimeError(f"Failed to get structured response after {retries + 1} attempts. Last error: {last_error}")
