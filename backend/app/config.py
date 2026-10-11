import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    # OpenAI 호환 /v1/chat/completions 를 내는 서버면 무엇이든 된다 (vLLM, Ollama 등).
    # 운영에서는 사내 서버의 자체 호스팅 모델을 썼다. 자료가 밖으로 나가지 않으므로
    # 비식별화 단계를 두지 않았고, 외부 모델로 옮긴다면 그 앞단에 비식별화가 먼저 들어가야 한다.
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:8001/v1")
    llm_model: str = os.getenv("LLM_MODEL", "local-model")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    # reasoning 을 끄면 첫 응답이 크게 빨라진다. 지원하지 않는 서버면 무시된다.
    llm_disable_thinking: bool = os.getenv("LLM_DISABLE_THINKING", "1") == "1"
    # 모델 컨텍스트가 좁다는 전제로 도구 결과를 줄인다.
    context_budget_tokens: int = int(os.getenv("CONTEXT_BUDGET_TOKENS", "16000"))
    warmup_on_start: bool = os.getenv("WARMUP_ON_START", "0") == "1"

    db_path: Path = Path(os.getenv("DB_PATH", BASE_DIR / "data" / "work.db"))
    token_secret: str = os.getenv("TOKEN_SECRET", "dev-only-secret")

    max_tool_rounds: int = 6
    max_history_turns: int = 8
    connect_timeout: float = 3.0
    read_timeout: float = 180.0


settings = Settings()
