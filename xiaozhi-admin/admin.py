#!/usr/bin/env python3
"""Xiaozhi Admin Panel — lightweight config editor for the Xiaozhi server."""

import json
import logging
import os

import docker
import yaml
from aiohttp import web

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("xiaozhi-admin")

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/data/.config.yaml")
CONTAINER_NAME = os.environ.get("CONTAINER_NAME", "xiaozhi-server")
LITELLM_CONTAINER_NAME = os.environ.get("LITELLM_CONTAINER_NAME", "litellm")
LITELLM_CONFIG_PATH = os.environ.get("LITELLM_CONFIG_PATH", "/litellm_config.yaml")
API_KEYS_PATH = os.environ.get("API_KEYS_PATH", "/api_keys.env")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f) or {}


def write_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def get_docker_client():
    return docker.from_env()


def container_status() -> str:
    try:
        client = get_docker_client()
        container = client.containers.get(CONTAINER_NAME)
        return container.status  # running, exited, etc.
    except Exception as e:
        log.warning("Could not get container status: %s", e)
        return "unknown"


PATCH_FILE = "/app/openai_patched.py"
CONTAINER_LLM_FILE = "/opt/xiaozhi-esp32-server/core/providers/llm/openai/openai.py"


PLUGIN_PATCH_SCRIPT = "/app/patch_descriptions.py"


def patch_container() -> None:
    """Copy the patched OpenAI provider into the container.

    The upstream image doesn't support GPT-5/o3/o4 (max_completion_tokens,
    restricted temperature). We keep a known-good patched file and copy it in
    after every restart.
    """
    import io
    import tarfile

    client = get_docker_client()
    container = client.containers.get(CONTAINER_NAME)

    # --- OpenAI provider patch ---
    rc, _ = container.exec_run(f"grep '_build_optional_params' {CONTAINER_LLM_FILE}")
    if rc == 0:
        log.info("OpenAI provider already patched")
    else:
        try:
            with open(PATCH_FILE, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            log.warning("Patch file %s not found, skipping", PATCH_FILE)
            data = None

        if data:
            log.info("Applying OpenAI provider patch to container…")
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                info = tarfile.TarInfo(name="openai.py")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            buf.seek(0)
            container.put_archive("/opt/xiaozhi-esp32-server/core/providers/llm/openai/", buf)
            log.info("OpenAI provider patch applied")

    # --- Plugin description patches (Chinese → English) ---
    patch_plugin_descriptions(container)


def patch_plugin_descriptions(container) -> None:
    """Translate Chinese plugin function descriptions to English inside the container."""
    try:
        with open(PLUGIN_PATCH_SCRIPT, "rb") as f:
            script_data = f.read()
    except FileNotFoundError:
        log.warning("Plugin patch script %s not found, skipping", PLUGIN_PATCH_SCRIPT)
        return

    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name="patch_descriptions.py")
        info.size = len(script_data)
        tar.addfile(info, io.BytesIO(script_data))
    buf.seek(0)
    container.put_archive("/tmp/", buf)

    rc, output = container.exec_run("python3 /tmp/patch_descriptions.py")
    if rc == 0:
        log.info("Plugin descriptions patched: %s", output.decode().strip())
    else:
        log.warning("Plugin description patch failed: %s", output.decode().strip())


def restart_container() -> str:
    client = get_docker_client()
    container = client.containers.get(CONTAINER_NAME)
    container.restart(timeout=10)
    patch_container()
    return container.status


def restart_litellm() -> None:
    """Recreate the LiteLLM proxy container so it picks up new config/keys.

    A simple restart doesn't re-read env_file, so we must remove + recreate.
    """
    import subprocess
    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "--force-recreate", "litellm"],
            cwd="/opt/xiaozhi-admin",
            check=True,
            capture_output=True,
            timeout=60,
        )
        log.info("LiteLLM container recreated")
    except Exception as e:
        log.warning("Could not recreate LiteLLM container: %s", e)


# ---------------------------------------------------------------------------
# LiteLLM config — model list per provider
# ---------------------------------------------------------------------------

LITELLM_MODELS = {
    "openai": [
        "gpt-5.2", "gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-5-nano",
        "gpt-4.1", "gpt-4.1-mini", "o3", "o4-mini", "gpt-4o", "gpt-4o-mini",
    ],
    "anthropic": [
        "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5",
    ],
    "gemini": [
        "gemini-3.1-pro-preview", "gemini-3-flash-preview",
        "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash",
    ],
    "groq": [
        "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
        "llama-4-scout-17b-16e-instruct",
        "qwen3-32b", "kimi-k2-instruct-0905",
        "gpt-oss-120b", "gpt-oss-20b",
    ],
}

# Models that need an org prefix in the Groq/LiteLLM API model ID
LITELLM_MODEL_OVERRIDES = {
    "llama-4-scout-17b-16e-instruct": "groq/meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen3-32b": "groq/qwen/qwen3-32b",
    "kimi-k2-instruct-0905": "groq/moonshotai/kimi-k2-instruct-0905",
    "gpt-oss-120b": "groq/openai/gpt-oss-120b",
    "gpt-oss-20b": "groq/openai/gpt-oss-20b",
}

# Maps provider prefix to env var name
PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
}


def write_litellm_config(api_keys: dict) -> None:
    """Write litellm_config.yaml with all models and current API keys."""
    model_list = []
    for provider, models in LITELLM_MODELS.items():
        env_var = PROVIDER_KEY_ENV[provider]
        for model in models:
            litellm_model = LITELLM_MODEL_OVERRIDES.get(model, f"{provider}/{model}")
            entry = {
                "model_name": model,
                "litellm_params": {
                    "model": litellm_model,
                    "api_key": f"os.environ/{env_var}",
                },
            }
            model_list.append(entry)

    config = {
        "model_list": model_list,
        "litellm_settings": {
            "drop_params": True,
            "num_retries": 2,
        },
    }

    with open(LITELLM_CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    log.info("LiteLLM config written to %s", LITELLM_CONFIG_PATH)

    # Write a .env file next to litellm_config.yaml for docker-compose
    env_path = API_KEYS_PATH
    with open(env_path, "w") as f:
        for env_var, key_value in api_keys.items():
            f.write(f"{env_var}={key_value}\n")
    log.info("API keys written to %s", env_path)


def container_logs(tail: int = 50) -> str:
    try:
        client = get_docker_client()
        container = client.containers.get(CONTAINER_NAME)
        return container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
    except Exception as e:
        return f"Error fetching logs: {e}"


# ---------------------------------------------------------------------------
# API handlers
# ---------------------------------------------------------------------------

async def handle_index(request):
    return web.Response(text=HTML, content_type="text/html")


# ---------------------------------------------------------------------------
# Prompt builder — generates system prompt from agent_name + language + personality
# ---------------------------------------------------------------------------

LANGUAGE_CONFIGS = {
    "en": {
        "label": "English",
        "rule": "You MUST always respond in English. Never respond in any other language unless the user explicitly asks you to.",
        "exit_hint": 'When the user says goodbye, wants to stop talking, or says things like "bye", "see you", "that\'s all", "goodnight", or "I\'m done", you MUST call the handle_exit_intent function to properly end the conversation. Say a brief friendly goodbye in English.',
        "end_prompt": "Say a brief, friendly goodbye in English to end the conversation.",
    },
    "es": {
        "label": "Spanish",
        "rule": "SIEMPRE debes responder en espanol. Nunca respondas en otro idioma a menos que el usuario te lo pida explicitamente.",
        "exit_hint": 'Cuando el usuario diga adios, quiera dejar de hablar, o diga cosas como "adios", "nos vemos", "eso es todo", "buenas noches" o "ya termine", DEBES llamar a la funcion handle_exit_intent para terminar la conversacion correctamente. Di una breve despedida amigable en espanol.',
        "end_prompt": "Di una breve y amigable despedida en espanol para terminar la conversacion.",
    },
    "bilingual": {
        "label": "Bilingual (EN + ES)",
        "rule": "You are bilingual in English and Spanish. Respond in the same language the user speaks to you. If they speak English, respond in English. If they speak Spanish, respond in Spanish.",
        "exit_hint": 'When the user says goodbye in either language (e.g. "bye", "adios", "see you", "nos vemos"), you MUST call the handle_exit_intent function. Say goodbye in the same language they used.',
        "end_prompt": "Say a brief, friendly goodbye in the same language the user used.",
    },
}


def build_prompt(agent_name: str, language: str, personality: str) -> str:
    """Build the full system prompt from components."""
    lang = LANGUAGE_CONFIGS.get(language, LANGUAGE_CONFIGS["en"])
    name = agent_name or "Assistant"

    lines = [
        f"You are {name}, a friendly and helpful AI voice assistant. You speak naturally and concisely.",
        "Keep your responses short and conversational since this is a voice interface.",
    ]
    if personality.strip():
        lines.append(personality.strip())
    lines.append(f"IMPORTANT: {lang['rule']}")
    lines.append(lang["exit_hint"])

    return "\n".join(lines) + "\n"


def extract_agent_name(prompt: str) -> str:
    """Extract agent name from prompt like 'You are Xiaozhi, a friendly...'"""
    import re
    m = re.match(r"You are (\w+)", prompt, re.IGNORECASE)
    return m.group(1) if m else ""


def extract_personality(prompt: str) -> str:
    """Extract custom personality lines (not the boilerplate we generate)."""
    skip_prefixes = (
        "You are ", "Keep your responses", "IMPORTANT:", "You MUST",
        "SIEMPRE", "Nunca responda", "You are bilingual",
        "When the user says goodbye", "Cuando el usuario",
    )
    lines = []
    for line in prompt.strip().splitlines():
        stripped = line.strip()
        if stripped and not any(stripped.startswith(p) for p in skip_prefixes):
            lines.append(stripped)
    return "\n".join(lines)


def read_api_keys() -> dict:
    """Read API keys from the .env file (if it exists)."""
    env_path = API_KEYS_PATH
    keys = {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": "", "GROQ_API_KEY": ""}
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if k in keys:
                        keys[k] = v
    except FileNotFoundError:
        pass
    return keys


async def handle_get_config(request):
    try:
        cfg = read_config()
        prompt = cfg.get("prompt", "")
        cfg["agent_name"] = extract_agent_name(prompt)
        # Prefer stored personality field; fall back to extracting from prompt
        if "personality" not in cfg:
            cfg["personality"] = extract_personality(prompt)
        status = container_status()
        api_keys = read_api_keys()
        return web.json_response({"config": cfg, "status": status, "api_keys": api_keys})
    except FileNotFoundError:
        return web.json_response({"config": {}, "status": container_status(), "api_keys": {}}, status=200)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_post_config(request):
    try:
        body = await request.json()
        updates = body.get("config", {})
        api_keys_update = body.get("api_keys", {})

        # Read existing config so we only overwrite known fields
        try:
            cfg = read_config()
        except FileNotFoundError:
            cfg = {}

        agent_name = updates.get("agent_name", extract_agent_name(cfg.get("prompt", "")))
        language = updates.get("language", cfg.get("language", "en"))
        personality = updates.get("personality", cfg.get("personality", ""))

        # Store personality as its own field so it survives round-trips
        cfg["personality"] = personality

        # Build prompt dynamically from agent_name + language + personality
        cfg["prompt"] = build_prompt(agent_name, language, personality)

        # Update end_prompt to match language
        lang = LANGUAGE_CONFIGS.get(language, LANGUAGE_CONFIGS["en"])
        cfg.setdefault("end_prompt", {})["prompt"] = lang["end_prompt"] + "\n"

        if "llm_model" in updates:
            cfg.setdefault("LLM", {}).setdefault("OpenAILLM", {})["model_name"] = updates["llm_model"]
        if "tts_voice" in updates:
            cfg.setdefault("TTS", {}).setdefault("EdgeTTS", {})["voice"] = updates["tts_voice"]
        if "language" in updates:
            cfg["language"] = updates["language"]

        # Point Xiaozhi at LiteLLM proxy instead of directly at OpenAI
        cfg.setdefault("LLM", {}).setdefault("OpenAILLM", {})["base_url"] = "http://litellm:4000/v1"

        write_config(cfg)
        log.info("Config saved")

        # Write LiteLLM config + .env with API keys
        existing_keys = read_api_keys()
        existing_keys.update({k: v for k, v in api_keys_update.items() if v})
        write_litellm_config(existing_keys)

        # Restart LiteLLM first (picks up new config/keys), then Xiaozhi
        messages = []
        try:
            restart_litellm()
            messages.append("LiteLLM restarted")
        except Exception as e:
            messages.append(f"LiteLLM restart failed: {e}")

        try:
            restart_container()
            messages.append("Xiaozhi restarted")
        except Exception as e:
            messages.append(f"Xiaozhi restart failed: {e}")

        msg = "Config saved. " + "; ".join(messages) + "."
        return web.json_response({"message": msg, "status": container_status()})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_get_logs(request):
    logs = container_logs()
    return web.json_response({"logs": logs})


# ---------------------------------------------------------------------------
# HTML — single-page admin panel
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Xiaozhi Admin</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body { font-family: 'Inter', system-ui, sans-serif; }
  .fade-in { animation: fadeIn .3s ease-in; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  textarea { resize: vertical; }
  .modal-backdrop { transition: opacity .2s ease; }
  .modal-panel { transition: opacity .2s ease, transform .2s ease; }
  .modal-backdrop.hidden { opacity: 0; pointer-events: none; }
  .modal-backdrop.hidden .modal-panel { opacity: 0; transform: translateY(12px) scale(.97); }
</style>
</head>
<body class="bg-gray-950 text-gray-100 min-h-screen">

<div class="max-w-2xl mx-auto px-4 py-10 fade-in">
  <!-- Header -->
  <div class="flex items-center justify-between mb-8">
    <div>
      <h1 class="text-2xl font-bold tracking-tight">Xiaozhi Admin</h1>
      <p class="text-sm text-gray-400 mt-1">Configure your voice assistant</p>
    </div>
    <div id="status-badge" class="flex items-center gap-2 text-sm px-3 py-1.5 rounded-full bg-gray-800">
      <span id="status-dot" class="w-2 h-2 rounded-full bg-gray-500"></span>
      <span id="status-text">Loading…</span>
    </div>
  </div>

  <!-- Form -->
  <form id="config-form" class="space-y-6" onsubmit="return false;">

    <!-- Agent Name (wake word = "Hi [name]") -->
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1.5" for="agent_name">Agent Name</label>
      <input id="agent_name" type="text" placeholder="e.g. Xiaozhi"
        class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent">
      <p class="text-xs text-gray-500 mt-1">Wake word will be "Hi [name]"</p>
    </div>

    <!-- Custom Personality -->
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1.5" for="personality">Custom Personality</label>
      <textarea id="personality" rows="4" placeholder="e.g. You can help with IoT projects and casual conversation. You love dad jokes."
        class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"></textarea>
      <p class="text-xs text-gray-500 mt-1">Extra personality traits. Language rules and exit behavior are set automatically.</p>
    </div>

    <!-- API Keys — status chips + settings button -->
    <div>
      <div class="flex items-center justify-between mb-2">
        <label class="block text-sm font-medium text-gray-300">API Keys</label>
        <button type="button" onclick="openKeysModal()"
          class="text-xs text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><circle cx="12" cy="12" r="3"/></svg>
          Configure
        </button>
      </div>
      <div id="keys-status" class="flex flex-wrap gap-2">
        <span id="key-chip-openai" class="key-chip inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-gray-800 text-gray-500">
          <span class="w-1.5 h-1.5 rounded-full bg-gray-600"></span>OpenAI
        </span>
        <span id="key-chip-anthropic" class="key-chip inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-gray-800 text-gray-500">
          <span class="w-1.5 h-1.5 rounded-full bg-gray-600"></span>Anthropic
        </span>
        <span id="key-chip-gemini" class="key-chip inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-gray-800 text-gray-500">
          <span class="w-1.5 h-1.5 rounded-full bg-gray-600"></span>Google
        </span>
        <span id="key-chip-groq" class="key-chip inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-gray-800 text-gray-500">
          <span class="w-1.5 h-1.5 rounded-full bg-gray-600"></span>Groq
        </span>
      </div>
    </div>

    <!-- LLM Model -->
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1.5" for="llm_model">LLM Model</label>
      <select id="llm_model"
        class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent">
        <optgroup label="OpenAI — GPT-5">
          <option value="gpt-5.2">gpt-5.2 (Best overall)</option>
          <option value="gpt-5.1">gpt-5.1</option>
          <option value="gpt-5">gpt-5</option>
          <option value="gpt-5-mini">gpt-5-mini (Fast)</option>
          <option value="gpt-5-nano">gpt-5-nano (Cheapest)</option>
        </optgroup>
        <optgroup label="OpenAI — GPT-4.1">
          <option value="gpt-4.1">gpt-4.1</option>
          <option value="gpt-4.1-mini">gpt-4.1-mini</option>
        </optgroup>
        <optgroup label="OpenAI — Reasoning">
          <option value="o3">o3</option>
          <option value="o4-mini">o4-mini (Fast reasoning)</option>
        </optgroup>
        <optgroup label="OpenAI — Legacy">
          <option value="gpt-4o">gpt-4o</option>
          <option value="gpt-4o-mini">gpt-4o-mini</option>
        </optgroup>
        <optgroup label="Anthropic — Claude">
          <option value="claude-opus-4-6">Claude Opus 4.6 (Most capable)</option>
          <option value="claude-sonnet-4-6">Claude Sonnet 4.6 (Balanced)</option>
          <option value="claude-haiku-4-5">Claude Haiku 4.5 (Fast)</option>
        </optgroup>
        <optgroup label="Google — Gemini">
          <option value="gemini-3.1-pro-preview">Gemini 3.1 Pro Preview</option>
          <option value="gemini-3-flash-preview">Gemini 3 Flash Preview</option>
          <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
          <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
          <option value="gemini-2.0-flash">Gemini 2.0 Flash</option>
        </optgroup>
        <optgroup label="Groq — Ultra Fast">
          <option value="llama-3.3-70b-versatile">Llama 3.3 70B (Best balance)</option>
          <option value="llama-3.1-8b-instant">Llama 3.1 8B Instant (Fastest)</option>
          <option value="llama-4-scout-17b-16e-instruct">Llama 4 Scout (Preview)</option>
          <option value="qwen3-32b">Qwen3 32B (Preview)</option>
          <option value="kimi-k2-instruct-0905">Kimi K2 (Preview)</option>
          <option value="gpt-oss-120b">GPT-OSS 120B</option>
          <option value="gpt-oss-20b">GPT-OSS 20B</option>
        </optgroup>
      </select>
    </div>

    <!-- TTS Voice -->
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1.5" for="tts_voice">TTS Voice</label>
      <select id="tts_voice"
        class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent">
        <!-- English -->
        <optgroup label="English (US)">
          <option value="en-US-AriaNeural">Aria (Female)</option>
          <option value="en-US-JennyNeural">Jenny (Female)</option>
          <option value="en-US-AnaNeural">Ana (Female, Young)</option>
          <option value="en-US-MichelleNeural">Michelle (Female)</option>
          <option value="en-US-MonicaNeural">Monica (Female)</option>
          <option value="en-US-GuyNeural">Guy (Male)</option>
          <option value="en-US-ChristopherNeural">Christopher (Male)</option>
          <option value="en-US-EricNeural">Eric (Male)</option>
          <option value="en-US-SteffanNeural">Steffan (Male)</option>
          <option value="en-US-RogerNeural">Roger (Male)</option>
        </optgroup>
        <optgroup label="English (UK)">
          <option value="en-GB-SoniaNeural">Sonia (Female)</option>
          <option value="en-GB-LibbyNeural">Libby (Female)</option>
          <option value="en-GB-MaisieNeural">Maisie (Female, Young)</option>
          <option value="en-GB-RyanNeural">Ryan (Male)</option>
          <option value="en-GB-ThomasNeural">Thomas (Male)</option>
        </optgroup>
        <optgroup label="English (Australia)">
          <option value="en-AU-NatashaNeural">Natasha (Female)</option>
          <option value="en-AU-WilliamNeural">William (Male)</option>
        </optgroup>
        <optgroup label="English (Ireland)">
          <option value="en-IE-EmilyNeural">Emily (Female)</option>
          <option value="en-IE-ConnorNeural">Connor (Male)</option>
        </optgroup>
        <optgroup label="English (India)">
          <option value="en-IN-NeerjaNeural">Neerja (Female)</option>
          <option value="en-IN-PrabhatNeural">Prabhat (Male)</option>
        </optgroup>
        <optgroup label="English (South Africa)">
          <option value="en-ZA-LeahNeural">Leah (Female)</option>
          <option value="en-ZA-LukeNeural">Luke (Male)</option>
        </optgroup>
        <optgroup label="English (Canada)">
          <option value="en-CA-ClaraNeural">Clara (Female)</option>
          <option value="en-CA-LiamNeural">Liam (Male)</option>
        </optgroup>
        <!-- Spanish -->
        <optgroup label="Spanish (Mexico)">
          <option value="es-MX-DaliaNeural">Dalia (Female)</option>
          <option value="es-MX-JorgeNeural">Jorge (Male)</option>
        </optgroup>
        <optgroup label="Spanish (Spain)">
          <option value="es-ES-ElviraNeural">Elvira (Female)</option>
          <option value="es-ES-AlvaroNeural">Alvaro (Male)</option>
        </optgroup>
        <optgroup label="Spanish (Argentina)">
          <option value="es-AR-ElenaNeural">Elena (Female)</option>
          <option value="es-AR-TomasNeural">Tomas (Male)</option>
        </optgroup>
        <optgroup label="Spanish (Colombia)">
          <option value="es-CO-SalomeNeural">Salome (Female)</option>
          <option value="es-CO-GonzaloNeural">Gonzalo (Male)</option>
        </optgroup>
        <optgroup label="Spanish (Chile)">
          <option value="es-CL-CatalinaNeural">Catalina (Female)</option>
          <option value="es-CL-LorenzoNeural">Lorenzo (Male)</option>
        </optgroup>
        <optgroup label="Spanish (Peru)">
          <option value="es-PE-CamilaNeural">Camila (Female)</option>
          <option value="es-PE-AlexNeural">Alex (Male)</option>
        </optgroup>
        <!-- French -->
        <optgroup label="French (France)">
          <option value="fr-FR-DeniseNeural">Denise (Female)</option>
          <option value="fr-FR-EloiseNeural">Eloise (Female, Young)</option>
          <option value="fr-FR-HenriNeural">Henri (Male)</option>
        </optgroup>
        <optgroup label="French (Canada)">
          <option value="fr-CA-SylvieNeural">Sylvie (Female)</option>
          <option value="fr-CA-JeanNeural">Jean (Male)</option>
          <option value="fr-CA-AntoineNeural">Antoine (Male)</option>
        </optgroup>
        <!-- Portuguese -->
        <optgroup label="Portuguese (Brazil)">
          <option value="pt-BR-FranciscaNeural">Francisca (Female)</option>
          <option value="pt-BR-AntonioNeural">Antonio (Male)</option>
        </optgroup>
        <optgroup label="Portuguese (Portugal)">
          <option value="pt-PT-RaquelNeural">Raquel (Female)</option>
          <option value="pt-PT-DuarteNeural">Duarte (Male)</option>
        </optgroup>
        <!-- German -->
        <optgroup label="German">
          <option value="de-DE-KatjaNeural">Katja (Female)</option>
          <option value="de-DE-AmalaNeural">Amala (Female)</option>
          <option value="de-DE-ConradNeural">Conrad (Male)</option>
          <option value="de-DE-KillianNeural">Killian (Male)</option>
        </optgroup>
        <!-- Italian -->
        <optgroup label="Italian">
          <option value="it-IT-ElsaNeural">Elsa (Female)</option>
          <option value="it-IT-IsabellaNeural">Isabella (Female)</option>
          <option value="it-IT-DiegoNeural">Diego (Male)</option>
          <option value="it-IT-GiuseppeNeural">Giuseppe (Male)</option>
        </optgroup>
        <!-- Japanese -->
        <optgroup label="Japanese">
          <option value="ja-JP-NanamiNeural">Nanami (Female)</option>
          <option value="ja-JP-KeitaNeural">Keita (Male)</option>
        </optgroup>
        <!-- Korean -->
        <optgroup label="Korean">
          <option value="ko-KR-SunHiNeural">SunHi (Female)</option>
          <option value="ko-KR-InJoonNeural">InJoon (Male)</option>
        </optgroup>
        <!-- Chinese -->
        <optgroup label="Chinese (Mandarin)">
          <option value="zh-CN-XiaoxiaoNeural">Xiaoxiao (Female)</option>
          <option value="zh-CN-XiaoyiNeural">Xiaoyi (Female)</option>
          <option value="zh-CN-YunjianNeural">Yunjian (Male)</option>
          <option value="zh-CN-YunxiNeural">Yunxi (Male)</option>
        </optgroup>
        <!-- Hindi -->
        <optgroup label="Hindi">
          <option value="hi-IN-SwaraNeural">Swara (Female)</option>
          <option value="hi-IN-MadhurNeural">Madhur (Male)</option>
        </optgroup>
        <!-- Arabic -->
        <optgroup label="Arabic (Saudi Arabia)">
          <option value="ar-SA-ZariyahNeural">Zariyah (Female)</option>
          <option value="ar-SA-HamedNeural">Hamed (Male)</option>
        </optgroup>
        <!-- Dutch -->
        <optgroup label="Dutch">
          <option value="nl-NL-ColetteNeural">Colette (Female)</option>
          <option value="nl-NL-FennaNeural">Fenna (Female)</option>
          <option value="nl-NL-MaartenNeural">Maarten (Male)</option>
        </optgroup>
        <!-- Russian -->
        <optgroup label="Russian">
          <option value="ru-RU-SvetlanaNeural">Svetlana (Female)</option>
          <option value="ru-RU-DmitryNeural">Dmitry (Male)</option>
        </optgroup>
        <!-- Turkish -->
        <optgroup label="Turkish">
          <option value="tr-TR-EmelNeural">Emel (Female)</option>
          <option value="tr-TR-AhmetNeural">Ahmet (Male)</option>
        </optgroup>
        <!-- Polish -->
        <optgroup label="Polish">
          <option value="pl-PL-AgnieszkaNeural">Agnieszka (Female)</option>
          <option value="pl-PL-MarekNeural">Marek (Male)</option>
        </optgroup>
        <!-- Swedish -->
        <optgroup label="Swedish">
          <option value="sv-SE-SofieNeural">Sofie (Female)</option>
          <option value="sv-SE-MattiasNeural">Mattias (Male)</option>
        </optgroup>
      </select>
    </div>

    <!-- Language -->
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1.5" for="language">Language</label>
      <select id="language"
        class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent">
        <option value="en">English</option>
        <option value="es">Spanish</option>
        <option value="bilingual">Bilingual (EN + ES)</option>
      </select>
    </div>

    <!-- Buttons -->
    <div class="flex gap-3 pt-2">
      <button id="save-btn" onclick="saveConfig()"
        class="flex-1 bg-blue-600 hover:bg-blue-500 text-white font-medium text-sm rounded-lg px-4 py-2.5 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-400">
        Save &amp; Restart
      </button>
      <button onclick="loadConfig()" type="button"
        class="bg-gray-800 hover:bg-gray-700 text-gray-300 font-medium text-sm rounded-lg px-4 py-2.5 transition-colors focus:outline-none focus:ring-2 focus:ring-gray-500">
        Reload
      </button>
    </div>
  </form>

<!-- API Keys Modal -->
<div id="keys-modal" class="modal-backdrop hidden fixed inset-0 z-50 flex items-center justify-center bg-black/60" onclick="if(event.target===this)closeKeysModal()">
  <div class="modal-panel bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-md mx-4 p-6">
    <div class="flex items-center justify-between mb-5">
      <h2 class="text-lg font-semibold text-gray-100">API Keys</h2>
      <button onclick="closeKeysModal()" class="text-gray-500 hover:text-gray-300 transition-colors">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
      </button>
    </div>
    <div class="space-y-4">
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="text-sm text-gray-300" for="openai_key">OpenAI</label>
          <span id="modal-status-openai" class="text-xs text-gray-500"></span>
        </div>
        <input id="openai_key" type="password" placeholder="sk-..."
          class="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono">
      </div>
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="text-sm text-gray-300" for="anthropic_key">Anthropic</label>
          <span id="modal-status-anthropic" class="text-xs text-gray-500"></span>
        </div>
        <input id="anthropic_key" type="password" placeholder="sk-ant-..."
          class="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono">
      </div>
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="text-sm text-gray-300" for="gemini_key">Google (Gemini)</label>
          <span id="modal-status-gemini" class="text-xs text-gray-500"></span>
        </div>
        <input id="gemini_key" type="password" placeholder="AIza..."
          class="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono">
      </div>
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="text-sm text-gray-300" for="groq_key">Groq</label>
          <span id="modal-status-groq" class="text-xs text-gray-500"></span>
        </div>
        <input id="groq_key" type="password" placeholder="gsk_..."
          class="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono">
      </div>
    </div>
    <p class="text-xs text-gray-500 mt-4">Keys are saved when you click Save &amp; Restart.</p>
    <button onclick="closeKeysModal()" class="mt-5 w-full bg-gray-800 hover:bg-gray-700 text-gray-200 font-medium text-sm rounded-lg px-4 py-2.5 transition-colors">Done</button>
  </div>
</div>

  <!-- Toast -->
  <div id="toast" class="fixed bottom-6 right-6 max-w-sm px-4 py-3 rounded-lg text-sm font-medium shadow-lg transition-all duration-300 translate-y-20 opacity-0 pointer-events-none"></div>

  <!-- Logs -->
  <details class="mt-10">
    <summary class="text-sm text-gray-400 cursor-pointer hover:text-gray-200 transition-colors">Container Logs</summary>
    <div class="mt-3 flex justify-end">
      <button onclick="loadLogs()" class="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded px-3 py-1 transition-colors">Refresh Logs</button>
    </div>
    <pre id="logs" class="mt-2 bg-gray-900 border border-gray-800 rounded-lg p-4 text-xs text-gray-400 overflow-x-auto max-h-80 overflow-y-auto whitespace-pre-wrap">Click "Refresh Logs" to load…</pre>
  </details>
</div>

<script>
const FIELDS = ['agent_name', 'prompt', 'llm_model', 'tts_voice', 'language'];

function el(id) { return document.getElementById(id); }

function toast(msg, ok) {
  const t = el('toast');
  t.textContent = msg;
  t.className = `fixed bottom-6 right-6 max-w-sm px-4 py-3 rounded-lg text-sm font-medium shadow-lg transition-all duration-300 ${ok ? 'bg-green-600 text-white' : 'bg-red-600 text-white'}`;
  setTimeout(() => { t.className += ' translate-y-20 opacity-0 pointer-events-none'; }, 3000);
}

function setStatus(status) {
  const dot = el('status-dot');
  const txt = el('status-text');
  txt.textContent = status;
  dot.className = 'w-2 h-2 rounded-full ' + (status === 'running' ? 'bg-green-400' : status === 'unknown' ? 'bg-gray-500' : 'bg-yellow-400');
}

function openKeysModal() {
  el('keys-modal').classList.remove('hidden');
  updateModalStatus();
}

function closeKeysModal() {
  el('keys-modal').classList.add('hidden');
  updateKeyChips();
}

function updateKeyChips() {
  const providers = [
    { id: 'openai', input: 'openai_key', label: 'OpenAI' },
    { id: 'anthropic', input: 'anthropic_key', label: 'Anthropic' },
    { id: 'gemini', input: 'gemini_key', label: 'Google' },
    { id: 'groq', input: 'groq_key', label: 'Groq' },
  ];
  providers.forEach(p => {
    const chip = el('key-chip-' + p.id);
    const hasKey = !!el(p.input).value;
    const dot = chip.querySelector('span');
    if (hasKey) {
      chip.className = 'key-chip inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-green-950 text-green-400 border border-green-800/50';
      dot.className = 'w-1.5 h-1.5 rounded-full bg-green-400';
    } else {
      chip.className = 'key-chip inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-gray-800 text-gray-500';
      dot.className = 'w-1.5 h-1.5 rounded-full bg-gray-600';
    }
  });
}

function updateModalStatus() {
  const providers = [
    { id: 'openai', input: 'openai_key' },
    { id: 'anthropic', input: 'anthropic_key' },
    { id: 'gemini', input: 'gemini_key' },
    { id: 'groq', input: 'groq_key' },
  ];
  providers.forEach(p => {
    const label = el('modal-status-' + p.id);
    const hasKey = !!el(p.input).value;
    label.textContent = hasKey ? 'Configured' : 'Not set';
    label.className = 'text-xs ' + (hasKey ? 'text-green-400' : 'text-gray-500');
  });
}

async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    const data = await res.json();
    if (data.error) { toast(data.error, false); return; }

    const c = data.config || {};
    el('agent_name').value = c.agent_name || '';
    el('personality').value = c.personality || '';
    el('llm_model').value = (c.LLM && c.LLM.OpenAILLM && c.LLM.OpenAILLM.model_name) || 'gpt-4o-mini';
    el('tts_voice').value = (c.TTS && c.TTS.EdgeTTS && c.TTS.EdgeTTS.voice) || 'en-US-AriaNeural';
    el('language').value = c.language || 'en';

    // API keys
    const keys = data.api_keys || {};
    el('openai_key').value = keys.OPENAI_API_KEY || '';
    el('anthropic_key').value = keys.ANTHROPIC_API_KEY || '';
    el('gemini_key').value = keys.GEMINI_API_KEY || '';
    el('groq_key').value = keys.GROQ_API_KEY || '';
    updateKeyChips();

    setStatus(data.status || 'unknown');
  } catch (e) {
    toast('Failed to load config: ' + e.message, false);
  }
}

async function saveConfig() {
  const btn = el('save-btn');
  btn.disabled = true;
  btn.textContent = 'Saving…';

  try {
    const payload = {
      config: {
        agent_name: el('agent_name').value,
        personality: el('personality').value,
        llm_model: el('llm_model').value,
        tts_voice: el('tts_voice').value,
        language: el('language').value,
      },
      api_keys: {
        OPENAI_API_KEY: el('openai_key').value,
        ANTHROPIC_API_KEY: el('anthropic_key').value,
        GEMINI_API_KEY: el('gemini_key').value,
        GROQ_API_KEY: el('groq_key').value,
      }
    };

    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (data.error) { toast(data.error, false); }
    else { toast(data.message, true); setStatus(data.status || 'running'); }
  } catch (e) {
    toast('Save failed: ' + e.message, false);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save & Restart';
  }
}

async function loadLogs() {
  try {
    const res = await fetch('/api/logs');
    const data = await res.json();
    el('logs').textContent = data.logs || 'No logs available.';
  } catch (e) {
    el('logs').textContent = 'Error: ' + e.message;
  }
}

loadConfig();
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/config", handle_get_config)
    app.router.add_post("/api/config", handle_post_config)
    app.router.add_get("/api/logs", handle_get_logs)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    log.info("Starting Xiaozhi Admin on port %d", port)
    web.run_app(create_app(), host="0.0.0.0", port=port)
