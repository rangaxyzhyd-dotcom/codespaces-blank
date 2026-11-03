"""Grounded LLM summaries using hosted free-tier providers by default."""

import json
import os
import re

import requests

from collectors.common import DataSourceError


def _configured_provider() -> tuple[str, str, str]:
    provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    if provider == "groq":
        return provider, os.getenv("GROQ_API_KEY", ""), os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    if provider == "openrouter":
        return provider, os.getenv("OPENROUTER_API_KEY", ""), os.getenv("LLM_MODEL", "openrouter/free")
    if provider == "gemini":
        return provider, os.getenv("GEMINI_API_KEY", ""), os.getenv("LLM_MODEL", "gemini-2.0-flash")
    if provider == "ollama":
        return provider, "local", os.getenv("LLM_MODEL", "llama3.1:8b")
    raise DataSourceError(f"Unsupported LLM_PROVIDER: {provider}")


def _fact_payload(report: dict) -> str:
    keys = (
        "symbol", "company", "exchange", "announcement_date", "previous_quarter", "consensus",
        "actual_results", "surprise_pct", "beat_miss_history", "guidance", "technical",
        "reaction_scenario", "sector_watch", "announcements",
    )
    return json.dumps({key: report.get(key) for key in keys}, ensure_ascii=False, default=str)


def _request_openai_compatible(provider: str, api_key: str, model: str, prompt: str) -> str:
    if provider == "groq":
        endpoint = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    elif provider == "openrouter":
        endpoint = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    else:
        endpoint = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    headers = {"Content-Type": "application/json"}
    if provider != "ollama":
        if not api_key:
            raise DataSourceError(f"Set {provider.upper()}_API_KEY to enable generated views")
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = requests.post(
            f"{endpoint.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "temperature": 0.2,
                "max_tokens": 350,
                "messages": [
                    {"role": "system", "content": "You are a cautious equity research summarizer. Use ONLY facts and numeric values in the supplied JSON. Never invent or infer a missing number. Explicitly say N/A when evidence is unavailable, state uncertainty, do not guarantee or predict returns, and do not give personalized financial advice. Return only valid JSON with keys scenario_commentary and investment_view."},
                    {"role": "user", "content": f"Draft a concise reaction scenario and final investment view from this data only. Name any missing evidence.\nDATA: {prompt}"},
                ],
            },
            timeout=35,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, ValueError, KeyError, IndexError) as error:
        raise DataSourceError(f"{provider} LLM request failed: {error}") from error


def _request_gemini(api_key: str, model: str, prompt: str) -> str:
    if not api_key:
        raise DataSourceError("Set GEMINI_API_KEY to enable generated views")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        response = requests.post(
            url,
            params={"key": api_key},
            json={"systemInstruction": {"parts": [{"text": "Use only supplied facts. Do not invent missing values, state uncertainty, never guarantee returns, and provide no personalized advice. Return JSON with scenario_commentary and investment_view."}]}, "contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}},
            timeout=35,
        )
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (requests.RequestException, ValueError, KeyError, IndexError) as error:
        raise DataSourceError(f"Gemini LLM request failed: {error}") from error


def generate_views(report: dict) -> dict[str, str]:
    """Return short LLM-written scenario commentary and investment view."""
    provider, api_key, model = _configured_provider()
    prompt = _fact_payload(report)
    text = _request_gemini(api_key, model, prompt) if provider == "gemini" else _request_openai_compatible(provider, api_key, model, prompt)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise DataSourceError("LLM output was not valid JSON") from error
    commentary = result.get("scenario_commentary")
    view = result.get("investment_view")
    if not isinstance(commentary, str) or not isinstance(view, str) or not commentary.strip() or not view.strip():
        raise DataSourceError("LLM output did not include both required text fields")
    if len(commentary) > 1600 or len(view) > 1600:
        raise DataSourceError("LLM output exceeded the allowed length")
    return {
        "scenario_commentary": commentary.strip(),
        "investment_view": view.strip(),
        "source": f"{provider} / {model}",
    }