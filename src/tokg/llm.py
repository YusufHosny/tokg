# ABOUTME: Default chat model factory. Any LangChain BaseChatModel can be injected instead;
# ABOUTME: the default drives Claude Code headlessly through langchain_cli_agents (no API key).
import os
import re

from langchain_core.language_models import BaseChatModel

MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,127}")
MIN_TIMEOUT, MAX_TIMEOUT = 1, 3600


def parse_model(value: str) -> str:
  if not MODEL_PATTERN.fullmatch(value):
    raise ValueError("TOKG_MODEL must be a plain model name (letters, digits, '.', '_', ':', '-', '[]')")
  return value


def parse_timeout(value: str) -> int:
  if not re.fullmatch(r"[0-9]{1,5}", value.strip()) or not MIN_TIMEOUT <= (seconds := int(value)) <= MAX_TIMEOUT:
    raise ValueError(f"TOKG_LLM_TIMEOUT must be whole seconds between {MIN_TIMEOUT} and {MAX_TIMEOUT}")
  return seconds


def fence(tag: str, text: str) -> str:
  body = re.sub(rf"<(?=\s*/?\s*{re.escape(tag)}\b)", "&lt;", text, flags=re.IGNORECASE)
  return f"<{tag}>\n{body}\n</{tag}>"


class CONFIG:
  MODEL = parse_model(os.environ.get("TOKG_MODEL", "sonnet"))
  TIMEOUT = parse_timeout(os.environ.get("TOKG_LLM_TIMEOUT", "180"))


def default_llm() -> BaseChatModel:
  try:
    from langchain_cli_agents.claude import ChatClaudeCLI
  except ImportError as e:
    raise ImportError("default LLM needs the 'claude' extra (`uv sync --extra claude`), "
                      "or inject your own BaseChatModel") from e
  return ChatClaudeCLI(model=CONFIG.MODEL, system_mode="replace", timeout=CONFIG.TIMEOUT)
