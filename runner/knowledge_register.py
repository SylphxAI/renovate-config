"""Read the authoritative STO section once at fleet-pass startup."""
from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from github_io import Refused
from pin_plan import parse_active_portfolio

NAMESPACE = 'org:governance'
TOPIC = 'group-state-registers'
STO_SECTION = 'register-2-sto-product-engine-repository-store-id-domain-ownership-register'
MAX_BODY_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_TOKEN_BYTES = 16 * 1024


@dataclass(frozen=True)
class Register:
    version: int
    repos: tuple[str, ...]


def read_sto_register(*, required=True) -> Register | None:
    # Consume these before creating a GitHub adapter or launching any child.
    token_file = os.environ.pop('ANYAGENTS_TOKEN_FILE', None)
    token = os.environ.pop('ANYAGENTS_TOKEN', None)
    if not required:
        return None

    url = os.environ.get('ANYAGENTS_API_URL', '')
    try:
        origin = urlsplit(url)
        port = origin.port
    except ValueError:
        raise Refused('knowledge-api-origin-invalid') from None
    if (origin.scheme != 'https' or not origin.hostname or origin.username is not None
            or origin.path not in ('', '/') or origin.query or origin.fragment
            or '\\' in url or any(c.isspace() or ord(c) < 32 for c in url)):
        raise Refused('knowledge-api-origin-invalid')

    if token_file is not None:
        try:
            path = Path(token_file)
            if not path.is_absolute():
                raise ValueError
            with path.open('rb') as stream:
                secret = stream.read(MAX_TOKEN_BYTES + 1)
            if len(secret) > MAX_TOKEN_BYTES:
                raise ValueError
            token = secret.decode('ascii')
        except (OSError, ValueError):
            raise Refused('knowledge-token-file-unreadable') from None
    token = (token or '').strip()
    if len(token) > MAX_TOKEN_BYTES or not re.fullmatch(r'[A-Za-z0-9._~+/-]+=*', token):
        raise Refused('knowledge-token-unavailable')

    payload = json.dumps({'action': 'read', 'namespace': NAMESPACE, 'topic': TOPIC,
                          'section': STO_SECTION, 'max_bytes': MAX_BODY_BYTES})
    # HTTPSConnection verifies TLS and does not follow redirects. Never send
    # the bearer to a different origin or include provider bodies in errors.
    conn = http.client.HTTPSConnection(origin.hostname, port, timeout=15)
    try:
        conn.request('POST', '/v1/knowledge', body=payload, headers={
            'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
            'Accept': 'application/json',
        })
        response = conn.getresponse()
        if response.status != 200:
            raise Refused(f'knowledge-http-{response.status}')
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES or response.length not in (None, 0):
            raise Refused('knowledge-response-incomplete')
    except (OSError, http.client.HTTPException, ValueError):
        raise Refused('knowledge-request-failed') from None
    finally:
        conn.close()

    try:
        doc = json.loads(raw.decode('utf-8'))
    except (ValueError, RecursionError):
        raise Refused('knowledge-response-invalid') from None
    if (not isinstance(doc, dict) or doc.get('namespace') != NAMESPACE or doc.get('topic') != TOPIC
            or doc.get('truncated') is not False or doc.get('deleted_at_ms') is not None
            or type(doc.get('version')) is not int or doc['version'] < 1
            or not isinstance(doc.get('body'), str)):
        raise Refused('knowledge-document-invalid')
    try:
        repos = parse_active_portfolio(doc['body'], sto_only=True)
    except ValueError:
        raise Refused('knowledge-sto-invalid') from None
    return Register(doc['version'], tuple(repos))
