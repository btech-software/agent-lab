import json
import time
from unittest.mock import MagicMock, patch

import pytest
from jwcrypto import jwk, jwt

from agent_lab.app_factory import setup_auth

AUTH_URL = "http://keycloak.test"
REALM = "agent-lab"
ISSUER = f"{AUTH_URL}/realms/{REALM}"
CLIENT_ID = "agent-lab-platform"


def _keycloak_configuration():
    container = MagicMock()
    container.config.return_value = {
        "auth": {
            "enabled": True,
            "url": AUTH_URL,
            "realm": REALM,
            "client_id": CLIENT_ID,
            "client_secret": "secret",
        },
        "static": {},
    }
    with patch("fastapi_keycloak_middleware.setup_keycloak_middleware") as setup:
        setup_auth(container, MagicMock(), [])
    return setup.call_args.kwargs["keycloak_configuration"]


def _signed_token(key, **claims):
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "azp": CLIENT_ID,
        "aud": "account",
        "sub": "user-1",
        "iat": now,
        "exp": now + 300,
    }
    payload.update(claims)
    token = jwt.JWT(header={"alg": "RS256"}, claims=json.dumps(payload))
    token.make_signed_token(key)
    return token.serialize()


def _decode(token, key, validation_options):
    # the middleware hands validation_options to jwcrypto's JWT unchanged
    return jwt.JWT(jwt=token, key=key, **validation_options)


class TestSetupAuthClaimBinding:
    @pytest.fixture
    def key(self):
        return jwk.JWK.generate(kty="RSA", size=2048)

    def test_accepts_token_issued_to_this_client_by_this_realm(self, key):
        options = _keycloak_configuration().validation_options

        decoded = _decode(_signed_token(key), key, options)

        assert json.loads(decoded.claims)["sub"] == "user-1"

    def test_rejects_token_issued_to_another_client(self, key):
        options = _keycloak_configuration().validation_options

        with pytest.raises(jwt.JWTInvalidClaimValue):
            _decode(_signed_token(key, azp="langfuse"), key, options)

    def test_rejects_token_from_another_issuer(self, key):
        options = _keycloak_configuration().validation_options

        with pytest.raises(jwt.JWTInvalidClaimValue):
            _decode(_signed_token(key, iss=f"{AUTH_URL}/realms/other"), key, options)

    def test_still_rejects_expired_token(self, key):
        options = _keycloak_configuration().validation_options

        with pytest.raises(jwt.JWTExpired):
            _decode(_signed_token(key, exp=int(time.time()) - 600), key, options)
