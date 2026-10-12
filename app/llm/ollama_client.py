import json
import os
import time
from pathlib import Path
from typing import TypeVar

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

T = TypeVar("T", bound=BaseModel)


class OllamaClient:
    def __init__(self):
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", "qwen3.5:latest")
        self.num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
        self.timeout = 60

    def check_health(self) -> bool:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def is_model_available(self) -> bool:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])
        except (requests.RequestException, json.JSONDecodeError, AttributeError):
            return False

        return any(
            isinstance(model, dict)
            and isinstance(model.get("name"), str)
            and (
                model["name"] == self.model
                or model["name"].startswith(f"{self.model}:")
            )
            for model in models
        )

    def validate_model_available(self) -> None:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])
        except (requests.RequestException, json.JSONDecodeError, AttributeError) as error:
            raise RuntimeError(
                f"Could not verify configured Ollama model '{self.model}' at "
                f"{self.host}: {error}"
            ) from error

        if not any(
            isinstance(model, dict)
            and isinstance(model.get("name"), str)
            and (
                model["name"] == self.model
                or model["name"].startswith(f"{self.model}:")
            )
            for model in models
        ):
            raise RuntimeError(
                f"Configured Ollama model '{self.model}' is not available at "
                f"{self.host}. Install it with: ollama pull {self.model}"
            )

    def generate_structured(
        self, prompt: str, response_model: type[T], retries: int = 3
    ) -> T:
        self.validate_model_available()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": response_model.model_json_schema(),
            "options": {"temperature": 0.1, "num_ctx": self.num_ctx},
        }
        request_attempts = max(1, retries)
        validation_retried = False

        for attempt in range(request_attempts):
            try:
                response = requests.post(
                    f"{self.host}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                result_text = response.json().get("response", "")
                return response_model.model_validate_json(result_text)
            except (requests.RequestException, json.JSONDecodeError) as error:
                if attempt + 1 == request_attempts:
                    raise RuntimeError(
                        f"Ollama request failed after {request_attempts} attempts: "
                        f"{error}"
                    ) from error
                time.sleep(min(attempt + 1, 2))
            except ValidationError as error:
                if validation_retried or attempt + 1 == request_attempts:
                    raise RuntimeError(
                        "Ollama returned invalid structured output after one "
                        f"validation retry: {error}"
                    ) from error
                validation_retried = True
                payload["prompt"] += (
                    "\n\nYour previous response did not match the required "
                    f"JSON schema. Validation error: {error}. Return corrected "
                    "JSON only."
                )

        raise RuntimeError("Ollama request ended without a response.")
