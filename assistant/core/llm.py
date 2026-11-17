"""Sends a prompt to a language model and returns its answer, with retries and caching."""

from __future__ import annotations                            # lets us write modern type hints safely

import os                                                      # reads the API key from the environment
import time                                                    # measures how long an answer takes

import requests                                                # sends the request over HTTPS
from dotenv import load_dotenv                                 # loads the key out of our .env file

from assistant.core import cache                               # our answer cache

load_dotenv()                                                  # read .env once, when this file is first imported

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"   # where hosted requests are sent
RETRY_STATUS = {429, 500, 502, 503, 504}                       # errors worth trying again: rate limits and outages


class LLMError(RuntimeError):                                  # our own error type, so callers can catch it cleanly
    """Raised when the model cannot be reached or refuses the request."""


def _call_openrouter(settings: dict, prompt: str) -> tuple[str, dict]:
    """Send one prompt to OpenRouter, retrying the errors that are worth retrying."""
    api_key = os.environ.get("OPENROUTER_API_KEY")             # the key loaded from .env
    if not api_key:                                            # if it is missing
        raise LLMError("OPENROUTER_API_KEY is missing. Check your .env file.")   # say so plainly
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}   # how we authenticate
    payload = {                                                # what we are asking for
        "model": settings["model"],                            # which model, from config.yaml
        "messages": [{"role": "user", "content": prompt}],     # the prompt itself
        "temperature": settings["temperature"],                # 0 means the most predictable answer
        "max_tokens": settings["max_tokens"],                  # the longest answer we allow
    }
    wait = 2.0                                                 # seconds to wait before the next try
    last_error = ""                                            # what went wrong most recently
    for attempt in range(1, settings["max_retries"] + 1):      # try a few times before giving up
        try:                                                   # the network itself can fail
            response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=settings["timeout_seconds"])
        except requests.RequestException as error:             # no connection, timeout, DNS failure
            last_error = f"network error: {error}"             # remember why
            time.sleep(wait)                                   # wait before trying again
            wait *= 2                                          # and wait twice as long next time
            continue                                           # try again
        if response.status_code == 200:                        # success
            body = response.json()                             # read the reply
            return body["choices"][0]["message"]["content"], body.get("usage", {})   # the text, and token counts
        if response.status_code in RETRY_STATUS:               # a rate limit or a server problem
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"       # remember why
            print(f"  retry {attempt}/{settings['max_retries']} after {last_error}") # tell the user we are waiting
            time.sleep(wait)                                   # wait before trying again
            wait *= 2                                          # each wait is twice the last, so we back off
            continue                                           # try again
        raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")        # a bad key or a bad request
    raise LLMError(f"giving up after {settings['max_retries']} attempts - {last_error}")


def generate(config: dict, prompt: str) -> dict:               # the one function the rest of the project calls
    """Answer one prompt, using the cache when possible, and report how it was produced."""
    settings = config["llm"]                                   # the language-model section of the settings
    provider, model = settings["provider"], settings["model"]  # which service, and which model on it
    key = cache.make_key(provider, model, prompt)              # the fingerprint this request is filed under

    hit = cache.get(config, key)                               # have we answered exactly this before?
    if hit is not None:                                        # if yes
        return {"text": hit, "provider": provider, "model": model, "seconds": 0.0, "cached": True, "usage": {}}

    started = time.time()                                      # note the time before we start
    if provider == "openrouter":                               # the hosted model
        text, usage = _call_openrouter(settings, prompt)       # send it over the network
    elif provider == "local":                                  # the model running on this laptop
        from assistant.core.local_llm import generate_local    # imported only when needed, as it is slow to load
        text, usage = generate_local(settings, prompt)         # run it here
    else:                                                      # anything else is a configuration mistake
        raise LLMError(f"unknown provider '{provider}' - use 'openrouter' or 'local'")
    elapsed = time.time() - started                            # how long the answer took

    cache.put(config, key, provider, model, prompt, text)      # remember it, so the next identical ask is free
    return {"text": text, "provider": provider, "model": model, "seconds": elapsed, "cached": False, "usage": usage}