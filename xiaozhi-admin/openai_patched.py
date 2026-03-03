import httpx
import openai
from openai.types import CompletionUsage
from config.logger import setup_logging
from core.utils.util import check_model_key
from core.providers.llm.base import LLMProviderBase

TAG = __name__
logger = setup_logging()


class LLMProvider(LLMProviderBase):
    def __init__(self, config):
        self.model_name = config.get("model_name")
        self.api_key = config.get("api_key")
        if "base_url" in config:
            self.base_url = config.get("base_url")
        else:
            self.base_url = config.get("url")
        timeout = config.get("timeout", 300)
        self.timeout = int(timeout) if timeout else 300

        param_defaults = {
            "max_tokens": int,
            "temperature": lambda x: round(float(x), 1),
            "top_p": lambda x: round(float(x), 1),
            "frequency_penalty": lambda x: round(float(x), 1),
        }

        for param, converter in param_defaults.items():
            value = config.get(param)
            try:
                setattr(
                    self,
                    param,
                    converter(value) if value not in (None, "") else None,
                )
            except (ValueError, TypeError):
                setattr(self, param, None)

        logger.debug(
            f"意图识别参数初始化: {self.temperature}, {self.max_tokens}, {self.top_p}, {self.frequency_penalty}"
        )

        model_key_msg = check_model_key("LLM", self.api_key)
        if model_key_msg:
            logger.bind(tag=TAG).error(model_key_msg)
        self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=httpx.Timeout(self.timeout))

    def _is_restricted_model(self):
        """GPT-5/o3/o4 models have restricted parameter support."""
        return self.model_name and any(
            self.model_name.startswith(p) for p in ("gpt-5", "o3", "o4")
        )

    def _get_token_param_name(self):
        """Newer models require max_completion_tokens instead of max_tokens."""
        if self._is_restricted_model():
            return "max_completion_tokens"
        return "max_tokens"

    def _build_optional_params(self, **kwargs):
        """Build optional params, skipping unsupported ones for restricted models."""
        params = {}
        token_key = self._get_token_param_name()
        token_val = kwargs.get("max_tokens", self.max_tokens)
        if token_val is not None:
            params[token_key] = token_val

        # Restricted models only accept default temperature/top_p — skip custom values
        if not self._is_restricted_model():
            for key, attr in [("temperature", self.temperature), ("top_p", self.top_p),
                              ("frequency_penalty", self.frequency_penalty)]:
                val = kwargs.get(key, attr)
                if val is not None:
                    params[key] = val
        return params

    @staticmethod
    def normalize_dialogue(dialogue):
        """自动修复 dialogue 中缺失 content 的消息"""
        for msg in dialogue:
            if "role" in msg and "content" not in msg:
                msg["content"] = ""
        return dialogue

    def response(self, session_id, dialogue, **kwargs):
        dialogue = self.normalize_dialogue(dialogue)

        request_params = {
            "model": self.model_name,
            "messages": dialogue,
            "stream": True,
        }

        request_params.update(self._build_optional_params(**kwargs))

        responses = self.client.chat.completions.create(**request_params)

        is_active = True
        for chunk in responses:
            try:
                delta = chunk.choices[0].delta if getattr(chunk, "choices", None) else None
                content = getattr(delta, "content", "") if delta else ""
            except IndexError:
                content = ""
            if content:
                if "<think>" in content:
                    is_active = False
                    content = content.split("<think>")[0]
                if "</think>" in content:
                    is_active = True
                    content = content.split("</think>")[-1]
                if is_active:
                    yield content

    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):
        dialogue = self.normalize_dialogue(dialogue)

        request_params = {
            "model": self.model_name,
            "messages": dialogue,
            "stream": True,
            "tools": functions,
        }

        request_params.update(self._build_optional_params(**kwargs))

        stream = self.client.chat.completions.create(**request_params)

        for chunk in stream:
            if getattr(chunk, "choices", None):
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", "")
                tool_calls = getattr(delta, "tool_calls", None)
                yield content, tool_calls
            elif isinstance(getattr(chunk, "usage", None), CompletionUsage):
                usage_info = getattr(chunk, "usage", None)
                logger.bind(tag=TAG).info(
                    f"Token 消耗：输入 {getattr(usage_info, 'prompt_tokens', '未知')}，"
                    f"输出 {getattr(usage_info, 'completion_tokens', '未知')}，"
                    f"共计 {getattr(usage_info, 'total_tokens', '未知')}"
                )
