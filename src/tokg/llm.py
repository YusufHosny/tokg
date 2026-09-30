# ABOUTME: Default chat model factory. Any LangChain BaseChatModel can be injected instead;
# ABOUTME: the default drives Claude Code headlessly through langchain_cli_agents (no API key).
import os

from langchain_core.language_models import BaseChatModel


class CONFIG:
  MODEL = os.environ.get("TOKG_MODEL", "sonnet")


def default_llm() -> BaseChatModel:
  try:
    from langchain_cli_agents.claude import ChatClaudeCLI
  except ImportError as e:
    raise ImportError("default LLM needs the 'claude' extra (`uv sync --extra claude`), "
                      "or inject your own BaseChatModel") from e
  return ChatClaudeCLI(model=CONFIG.MODEL, system_mode="replace")
