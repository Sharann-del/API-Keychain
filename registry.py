"""Model tier registry and provider base URLs.

Each model is identified by a canonical id of the form "<provider>/<model>"
(or just "<model>" for providers with a single obvious id space). The helper
``parse_model`` splits an entry into (provider, upstream_model_name) where
``upstream_model_name`` is what we actually send to the provider's API.
"""

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# Provider catalog — the single source of truth for provider metadata. Kept as
# a per-provider dict (not just a URL) so it can be partially overridden per-user
# later (e.g. a user-supplied base_url) without changing this structure.
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "openai_compatible": True,
    },
    "groq": {"base_url": "https://api.groq.com/openai/v1", "openai_compatible": True},
    "cerebras": {"base_url": "https://api.cerebras.ai/v1", "openai_compatible": True},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "openai_compatible": True},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "openai_compatible": True},
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "openai_compatible": True,
    },
    "together": {"base_url": "https://api.together.xyz/v1", "openai_compatible": True},
    "cohere": {
        "base_url": "https://api.cohere.ai/compatibility/v1",
        "openai_compatible": True,
    },
    "nim": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "openai_compatible": True,
    },
    "sambanova": {"base_url": "https://api.sambanova.ai/v1", "openai_compatible": True},
    "hf": {"base_url": "https://router.huggingface.co/v1", "openai_compatible": True},
    "cf": {
        "base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "openai_compatible": True,
    },
}

# Convenience map provider -> base_url, derived from the catalog. Kept for the
# router and existing callers.
PROVIDER_BASE_URLS: Dict[str, str] = {p: m["base_url"] for p, m in PROVIDERS.items()}

# The set of providers a user may register keys for.
SUPPORTED_PROVIDERS = sorted(PROVIDERS.keys())


def provider_catalog(
    overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Provider metadata, with optional per-user overrides merged in.

    ``overrides`` (future per-user customization) is a ``{provider: {field: val}}``
    map shallow-merged onto the defaults. Passing ``None`` returns the defaults.
    """
    overrides = overrides or {}
    out: Dict[str, Dict[str, Any]] = {}
    for provider, meta in PROVIDERS.items():
        merged = dict(meta)
        merged.update(overrides.get(provider, {}))
        out[provider] = merged
    return out


# Effort tier -> ordered list of model entries to try.
#
# Each entry is "<provider>" implicit by prefix:
#   - "gemini-2.0-flash"            -> provider gemini,  model "gemini-2.0-flash"
#   - "groq/llama-3.1-8b-instant"   -> provider groq,    model "llama-3.1-8b-instant"
#   - "mistral-small-latest"        -> provider mistral, model "mistral-small-latest"
MODEL_TIERS: Dict[str, List[str]] = {
    "low": [
        "gemini-2.0-flash",
        "groq/llama-3.1-8b-instant",
        "cerebras/llama3.1-8b",
        "nim/meta/llama-3.1-8b-instruct",
        "sambanova/Meta-Llama-3.1-8B-Instruct",
        "openrouter/nvidia/llama-nemotron-nano-9b-v2:free",
        "openrouter/google/gemma-4-26b-a4b:free",
        "openrouter/openai/gpt-oss-20b:free",
    ],
    "medium": [
        "gemini-2.0-flash",
        "groq/llama-3.3-70b-versatile",
        "mistral-small-latest",
        "nim/meta/llama-3.3-70b-instruct",
        "sambanova/Meta-Llama-3.3-70B-Instruct",
        "openrouter/google/gemma-4-31b:free",
        "openrouter/nvidia/nemotron-3-super:free",
        "openrouter/openai/gpt-oss-120b:free",
    ],
    "high": [
        "gemini-2.5-pro",
        "deepseek/deepseek-r1",
        "groq/llama-3.3-70b-versatile",
        "nim/nvidia/llama-3.1-nemotron-70b-instruct",
        "openrouter/nvidia/nemotron-3-ultra:free",
        "openrouter/poolside/laguna-m.1:free",
        "openrouter/tngtech/deepseek-r1t2-chimera:free",
    ],
}

# Capability order, highest first. A request for a given effort cascades down
# through this list: high -> medium -> low.
_TIER_ORDER: List[str] = ["high", "medium", "low"]

# Map a model entry's leading token to its provider when there's no "/" prefix.
# These are the "bare" model name prefixes that imply a provider.
_BARE_PREFIX_TO_PROVIDER = {
    "gemini": "gemini",
    "mistral": "mistral",
}


def parse_model(entry: str) -> Tuple[str, str]:
    """Return (provider, upstream_model_name) for a registry entry.

    Entries with an explicit "<provider>/<model>" form are split on the first
    slash. The provider prefix is stripped; everything after it is forwarded
    upstream verbatim. For OpenRouter this means the full vendor path and the
    ``:free`` suffix are preserved (e.g. "openrouter/openai/gpt-oss-20b:free"
    -> provider "openrouter", model "openai/gpt-oss-20b:free"), which is exactly
    what OpenRouter's API expects.

    Bare entries are mapped to a provider by their leading token.
    """
    if "/" in entry:
        provider, model = entry.split("/", 1)
        if provider in PROVIDER_BASE_URLS:
            return provider, model

    leading = entry.split("-", 1)[0]
    provider = _BARE_PREFIX_TO_PROVIDER.get(leading)
    if provider is None:
        raise ValueError(f"Cannot resolve provider for model entry: {entry!r}")
    return provider, entry


def models_for_effort(effort: str) -> List[str]:
    if effort not in MODEL_TIERS:
        raise ValueError(
            f"Unknown effort {effort!r}; expected one of {sorted(MODEL_TIERS)}"
        )
    return MODEL_TIERS[effort]


def cascade_models(effort: str) -> List[str]:
    """Flattened, ordered model list starting at ``effort`` and cascading down.

    A "high" request yields high -> medium -> low; "medium" yields medium ->
    low; "low" yields just low. Duplicate entries that appear in more than one
    tier (e.g. a model shared by high and medium) are kept only at their first,
    highest-priority occurrence so we never call the same model twice.
    """
    if effort not in MODEL_TIERS:
        raise ValueError(
            f"Unknown effort {effort!r}; expected one of {sorted(MODEL_TIERS)}"
        )
    start = _TIER_ORDER.index(effort)
    seen: set[str] = set()
    ordered: List[str] = []
    for tier in _TIER_ORDER[start:]:
        for entry in MODEL_TIERS[tier]:
            if entry not in seen:
                seen.add(entry)
                ordered.append(entry)
    return ordered


def all_models() -> List[Dict[str, str]]:
    """The full global registry as a flat list of {model_entry, provider, tier}."""
    out: List[Dict[str, str]] = []
    for tier in _TIER_ORDER:
        for entry in MODEL_TIERS[tier]:
            out.append(
                {"model_entry": entry, "provider": parse_model(entry)[0], "tier": tier}
            )
    return out


def models_by_tier() -> Dict[str, List[Dict[str, str]]]:
    """The global registry grouped by tier, each entry resolved to its provider."""
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for tier in _TIER_ORDER:
        grouped[tier] = [
            {
                "model_entry": entry,
                "provider": parse_model(entry)[0],
                "upstream_model": parse_model(entry)[1],
            }
            for entry in MODEL_TIERS[tier]
        ]
    return grouped


# --------------------------------------------------------------------------- #
# Per-user effective model list
# --------------------------------------------------------------------------- #
def build_effective_table(
    overrides: Dict[Tuple[str, str], Dict[str, Any]],
    customs: Sequence[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Merge a user's overrides + custom models onto the registry defaults.

    ``overrides`` maps ``(model_entry, tier) -> {"enabled": bool, "priority": int}``
    for registry models the user has tweaked. ``customs`` is a list of
    ``{"model_entry", "tier", "enabled", "priority"}`` dicts the user added.

    Returns ``{tier: [entry, ...]}`` where each entry is a dict with model_entry,
    provider, tier, enabled, priority, is_custom — sorted by priority within tier.
    """
    table: Dict[str, List[Dict[str, Any]]] = {tier: [] for tier in _TIER_ORDER}

    for tier in _TIER_ORDER:
        for idx, entry in enumerate(MODEL_TIERS[tier]):
            ov = overrides.get((entry, tier), {})
            table[tier].append(
                {
                    "model_entry": entry,
                    "provider": parse_model(entry)[0],
                    "tier": tier,
                    "enabled": ov.get("enabled", True),
                    "priority": ov.get("priority", idx),
                    "is_custom": False,
                }
            )

    for c in customs:
        tier = c["tier"]
        if tier not in table:
            continue
        table[tier].append(
            {
                "model_entry": c["model_entry"],
                "provider": parse_model(c["model_entry"])[0],
                "tier": tier,
                "enabled": c.get("enabled", True),
                "priority": c.get("priority", 1000),
                "is_custom": True,
            }
        )

    for tier in table:
        table[tier].sort(key=lambda m: (m["priority"], m["model_entry"]))
    return table


def effective_cascade(
    table: Dict[str, List[Dict[str, Any]]],
    effort: str,
    excluded_models: Optional[Set[str]] = None,
    excluded_providers: Optional[Set[str]] = None,
    preferred_providers: Sequence[str] = (),
) -> List[str]:
    """Ordered, deduped model_entry list for a request, honoring preferences.

    Cascades from ``effort`` down through lower tiers (like :func:`cascade_models`),
    dropping disabled, excluded-model, and excluded-provider entries. Models served
    by ``preferred_providers`` are then floated to the front (stable, in the given
    provider order).
    """
    if effort not in MODEL_TIERS:
        raise ValueError(f"Unknown effort {effort!r}")
    excluded_models = excluded_models or set()
    excluded_providers = excluded_providers or set()

    start = _TIER_ORDER.index(effort)
    seen: Set[str] = set()
    ordered: List[str] = []
    for tier in _TIER_ORDER[start:]:
        for m in table[tier]:
            entry = m["model_entry"]
            if not m["enabled"] or entry in seen:
                continue
            if entry in excluded_models or m["provider"] in excluded_providers:
                continue
            seen.add(entry)
            ordered.append(entry)

    if preferred_providers:
        rank = {p: i for i, p in enumerate(preferred_providers)}
        # Stable sort keeps cascade order within each preference rank; unlisted
        # providers sort after all preferred ones.
        ordered.sort(key=lambda e: rank.get(parse_model(e)[0], len(rank)))
    return ordered
