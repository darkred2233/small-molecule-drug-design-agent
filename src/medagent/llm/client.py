"""
LLM调用封装层

提供统一的LLM调用接口，支持：
- 多个LLM提供商（千问/DeepSeek）
- 流式和非流式输出
- 自动重试
- 错误处理
- Token计数
- 调用日志
"""

import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator


@dataclass
class LLMMessage:
    """LLM消息"""
    role: str  # system, user, assistant
    content: str
    name: str | None = None


@dataclass
class LLMRequest:
    """LLM请求"""
    messages: list[LLMMessage]
    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float = 1.0
    stream: bool = False
    stop: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """LLM响应"""
    content: str
    model: str
    provider: str
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMStreamChunk:
    """流式响应块"""
    content: str
    finish_reason: str | None = None


class LLMProvider:
    """LLM提供商基类"""

    def __init__(self, api_key: str, base_url: str, default_model: str):
        try:
            from openai import AsyncOpenAI, OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI-compatible LLM support requires the 'openai' package. "
                "Install project dependencies or add openai>=1.0.0."
            ) from exc

        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    def complete(
        self,
        request: LLMRequest,
        retry_count: int = 3,
        retry_delay: float = 1.0,
    ) -> LLMResponse:
        """同步调用"""
        start_time = time.time()
        last_error = None

        for attempt in range(retry_count):
            try:
                messages = [
                    {"role": msg.role, "content": msg.content}
                    for msg in request.messages
                ]

                response = self.client.chat.completions.create(
                    model=request.model or self.default_model,
                    messages=messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    top_p=request.top_p,
                    stop=request.stop,
                    stream=False,
                )

                latency_ms = (time.time() - start_time) * 1000

                return LLMResponse(
                    content=response.choices[0].message.content or "",
                    model=response.model,
                    provider=self.__class__.__name__,
                    finish_reason=response.choices[0].finish_reason,
                    prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                    completion_tokens=response.usage.completion_tokens if response.usage else 0,
                    total_tokens=response.usage.total_tokens if response.usage else 0,
                    latency_ms=latency_ms,
                    metadata=request.metadata,
                )

            except Exception as e:
                last_error = e
                if attempt < retry_count - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    raise RuntimeError(f"LLM调用失败 (尝试{retry_count}次): {e}") from e

        raise RuntimeError(f"LLM调用失败: {last_error}")

    def stream(
        self,
        request: LLMRequest,
        retry_count: int = 3,
    ) -> Iterator[LLMStreamChunk]:
        """同步流式调用"""
        last_error = None

        for attempt in range(retry_count):
            try:
                messages = [
                    {"role": msg.role, "content": msg.content}
                    for msg in request.messages
                ]

                response = self.client.chat.completions.create(
                    model=request.model or self.default_model,
                    messages=messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    top_p=request.top_p,
                    stop=request.stop,
                    stream=True,
                )

                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield LLMStreamChunk(
                            content=chunk.choices[0].delta.content,
                            finish_reason=chunk.choices[0].finish_reason,
                        )

                return

            except Exception as e:
                last_error = e
                if attempt < retry_count - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                else:
                    raise RuntimeError(f"LLM流式调用失败 (尝试{retry_count}次): {e}") from e

        raise RuntimeError(f"LLM流式调用失败: {last_error}")

    async def async_complete(
        self,
        request: LLMRequest,
        retry_count: int = 3,
        retry_delay: float = 1.0,
    ) -> LLMResponse:
        """异步调用"""
        import asyncio
        start_time = time.time()
        last_error = None

        for attempt in range(retry_count):
            try:
                messages = [
                    {"role": msg.role, "content": msg.content}
                    for msg in request.messages
                ]

                response = await self.async_client.chat.completions.create(
                    model=request.model or self.default_model,
                    messages=messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    top_p=request.top_p,
                    stop=request.stop,
                    stream=False,
                )

                latency_ms = (time.time() - start_time) * 1000

                return LLMResponse(
                    content=response.choices[0].message.content or "",
                    model=response.model,
                    provider=self.__class__.__name__,
                    finish_reason=response.choices[0].finish_reason,
                    prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                    completion_tokens=response.usage.completion_tokens if response.usage else 0,
                    total_tokens=response.usage.total_tokens if response.usage else 0,
                    latency_ms=latency_ms,
                    metadata=request.metadata,
                )

            except Exception as e:
                last_error = e
                if attempt < retry_count - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    raise RuntimeError(f"LLM异步调用失败 (尝试{retry_count}次): {e}") from e

        raise RuntimeError(f"LLM异步调用失败: {last_error}")

    async def async_stream(
        self,
        request: LLMRequest,
        retry_count: int = 3,
    ) -> AsyncIterator[LLMStreamChunk]:
        """异步流式调用"""
        import asyncio
        last_error = None

        for attempt in range(retry_count):
            try:
                messages = [
                    {"role": msg.role, "content": msg.content}
                    for msg in request.messages
                ]

                response = await self.async_client.chat.completions.create(
                    model=request.model or self.default_model,
                    messages=messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    top_p=request.top_p,
                    stop=request.stop,
                    stream=True,
                )

                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield LLMStreamChunk(
                            content=chunk.choices[0].delta.content,
                            finish_reason=chunk.choices[0].finish_reason,
                        )

                return

            except Exception as e:
                last_error = e
                if attempt < retry_count - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                else:
                    raise RuntimeError(f"LLM异步流式调用失败 (尝试{retry_count}次): {e}") from e

        raise RuntimeError(f"LLM异步流式调用失败: {last_error}")


class QwenProvider(LLMProvider):
    """千问提供商"""

    def __init__(self, api_key: str, base_url: str | None = None, default_model: str = "qwen-plus"):
        super().__init__(
            api_key=api_key,
            base_url=base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            default_model=default_model,
        )


class DeepSeekProvider(LLMProvider):
    """DeepSeek提供商"""

    def __init__(self, api_key: str, base_url: str | None = None, default_model: str = "deepseek-chat"):
        super().__init__(
            api_key=api_key,
            base_url=base_url or "https://api.deepseek.com/v1",
            default_model=default_model,
        )


class LLMClient:
    """LLM客户端 - 统一入口"""

    def __init__(self):
        self.providers: dict[str, LLMProvider] = {}

    def register_provider(self, name: str, provider: LLMProvider):
        """注册提供商"""
        self.providers[name] = provider

    def complete(
        self,
        messages: list[LLMMessage],
        provider: str = "qwen",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        retry_count: int = 3,
    ) -> LLMResponse:
        """同步调用"""
        if provider not in self.providers:
            raise ValueError(f"未注册的提供商: {provider}")

        request = LLMRequest(
            messages=messages,
            model=model or "",
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return self.providers[provider].complete(request, retry_count=retry_count)

    def stream(
        self,
        messages: list[LLMMessage],
        provider: str = "qwen",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        retry_count: int = 3,
    ) -> Iterator[LLMStreamChunk]:
        """同步流式调用"""
        if provider not in self.providers:
            raise ValueError(f"未注册的提供商: {provider}")

        request = LLMRequest(
            messages=messages,
            model=model or "",
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        return self.providers[provider].stream(request, retry_count=retry_count)

    async def async_complete(
        self,
        messages: list[LLMMessage],
        provider: str = "qwen",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        retry_count: int = 3,
    ) -> LLMResponse:
        """异步调用"""
        if provider not in self.providers:
            raise ValueError(f"未注册的提供商: {provider}")

        request = LLMRequest(
            messages=messages,
            model=model or "",
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return await self.providers[provider].async_complete(request, retry_count=retry_count)

    async def async_stream(
        self,
        messages: list[LLMMessage],
        provider: str = "qwen",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        retry_count: int = 3,
    ) -> AsyncIterator[LLMStreamChunk]:
        """异步流式调用"""
        if provider not in self.providers:
            raise ValueError(f"未注册的提供商: {provider}")

        request = LLMRequest(
            messages=messages,
            model=model or "",
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        async for chunk in self.providers[provider].async_stream(request, retry_count=retry_count):
            yield chunk


# 全局客户端实例
_global_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """获取全局LLM客户端"""
    global _global_client

    if _global_client is None:
        _global_client = LLMClient()

        # 从配置加载
        from medagent.core.config import get_settings
        import os

        settings = get_settings()

        # 注册千问
        if settings.dashscope_api_key:
            try:
                qwen_provider = QwenProvider(
                    api_key=settings.dashscope_api_key,
                    base_url=settings.dashscope_compatible_base_url,
                    default_model=settings.qwen_task_model,
                )
                _global_client.register_provider("qwen", qwen_provider)
            except RuntimeError:
                pass

        # 注册DeepSeek
        deepseek_key = os.getenv("MEDAGENT_DEEPSEEK_API_KEY")
        if deepseek_key:
            try:
                deepseek_provider = DeepSeekProvider(
                    api_key=deepseek_key,
                    base_url=os.getenv("MEDAGENT_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                    default_model=settings.deepseek_refutation_model,
                )
                _global_client.register_provider("deepseek", deepseek_provider)
            except RuntimeError:
                pass

    return _global_client
