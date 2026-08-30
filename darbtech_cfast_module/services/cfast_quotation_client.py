# Part of darbtech_cfast_module. See LICENSE file for full copyright and licensing details.
"""HTTP client for CFAST quotations listing (no Odoo imports — safe for reuse/tests)."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

_logger = logging.getLogger(__name__)


def _response_preview(response: requests.Response, max_len: int = 400) -> str:
    raw = (response.text or "").replace("\r", " ").replace("\n", " ").strip()
    if not raw:
        return ""
    if len(raw) > max_len:
        return raw[:max_len] + "…"
    return raw


def _explain_non_json_response(response: requests.Response) -> str:
    """Message détaillé quand le corps n'est pas du JSON (HTML, texte, vide…)."""
    status = response.status_code
    ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    preview = _response_preview(response, 350)
    bits = [f"code HTTP {status}"]
    if ctype:
        bits.append(f"Content-Type « {ctype} »")
    if not preview:
        bits.append("corps de réponse vide")
    else:
        bits.append(f"extrait : {preview!r}")

    hints: list[str] = []
    if status in (401, 403):
        hints.append(
            "Vérifiez le token (rafraîchir depuis les paramètres CFAST) et les droits API."
        )
    if status == 404:
        hints.append(
            "L’URL appelée est peut‑être incorrecte (Base URL ou chemin /api/quotations/)."
        )
    low = (response.text or "").lstrip().lower()
    if "text/html" in ctype or low.startswith("<!doctype") or low.startswith("<html"):
        hints.append(
            "Le serveur renvoie du HTML (page web d’erreur ou de login), pas l’API JSON."
        )

    detail = " — ".join(bits)
    if hints:
        detail += ". " + " ".join(hints)
    return detail

CFAST_QUOTATIONS_PATH = "/api/quotations"
DEFAULT_TIMEOUT = 30.0


def extract_quotation_payloads(body: Any) -> list[dict]:
    """Normalize API JSON into a list of quotation dicts."""
    if body is None:
        return []
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if not isinstance(body, dict):
        return []
    for key in ("items", "quotations", "data", "results", "value"):
        nested = body.get(key)
        if isinstance(nested, list):
            return [x for x in nested if isinstance(x, dict)]
    # Single-object payload
    if any(k in body for k in ("id", "quotationId", "quotation_id")):
        return [body]
    return []


def fetch_quotations(
    base_url: str,
    bearer_token: str,
    customer_ref: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[Any | None, int | None, str | None]:
    """
    GET {base_url}/api/quotations/?customer_id=<customer_ref>&status=stat-accepted

    Returns:
        (parsed_json_or_none, http_status_or_none, error_message_or_none)
    """
    root = (base_url or "").strip().rstrip("/")
    if not root:
        return None, None, "CFAST base URL is not configured."

    url = f"{root}{CFAST_QUOTATIONS_PATH}"
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Accept": "application/json",
    }
    params = {
        "status": "stat-accepted",
        "customer_id": customer_ref
        }

    try:

        
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
    except requests.RequestException as exc:
        _logger.exception("CFAST quotations request failed: %s", exc)
        return None, None, str(exc)

    # Succès sans corps (ex. rare) → liste vide
    body_text = response.text or ""
    if not body_text.strip() and 200 <= response.status_code < 300:
        return [], response.status_code, None

    try:
        payload = response.json()
    except ValueError:
        detail = _explain_non_json_response(response)
        _logger.warning(
            "CFAST quotations: réponse non-JSON (%s) URL=%s customerId=%s",
            detail,
            url,
            customer_ref,
        )
        return (
            None,
            response.status_code,
            "La réponse CFAST n'est pas du JSON valide. %s" % detail,
        )

    if response.status_code >= 400:
        err_hint = ""
        if isinstance(payload, dict):
            err_hint = payload.get("message") or payload.get("error") or ""
        if not err_hint and isinstance(payload, str):
            err_hint = payload
        if not err_hint:
            err_hint = json.dumps(payload, ensure_ascii=False)[:300]
        _logger.warning(
            "CFAST quotations HTTP %s for customerId=%s: %s",
            response.status_code,
            customer_ref,
            err_hint,
        )
        return payload, response.status_code, err_hint or f"HTTP {response.status_code}"

    return payload, response.status_code, None
