import logging
from typing import Optional

import httpx
import jwt
from chat_agent.config import settings
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# Auth0 Configuration
AUTH0_DOMAIN = settings.AUTH0_DOMAIN
AUTH0_AUDIENCE = settings.AUTH0_AUDIENCE
JWKS_URL = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"

# Global Caches
_jwks_cache = None
_key_cache = {}


async def get_jwks():
    """Fetch and cache JWKS from Auth0."""
    global _jwks_cache
    if _jwks_cache is None:
        try:
            async with httpx.AsyncClient() as client:
                logger.info(f"Fetching JWKS from {JWKS_URL}")
                resp = await client.get(JWKS_URL, timeout=5)
                resp.raise_for_status()
                _jwks_cache = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch JWKS: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not verify authentication token",
            )
    return _jwks_cache


async def verify_token(token: Optional[HTTPAuthorizationCredentials] = Security(HTTPBearer(auto_error=False))) -> dict:
    """
    Custom dependency to verify Auth0 tokens with JWKS caching.
    Replaces Auth0FastAPI to eliminate per-request JWKS fetching latency.
    """
    if not settings.REQUIRE_AUTH:
        return {"payload": {}, "permissions": []}

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
        )

    global _key_cache
    try:
        header = jwt.get_unverified_header(token.credentials)
        kid = header.get("kid")
        if not kid:
            raise jwt.InvalidTokenError("Missing 'kid' in token header")

        # Check in-memory key object cache first
        key = _key_cache.get(kid)

        if not key:
            jwks_data = await get_jwks()
            # Find the correct key in the JWKS and convert to object
            for jwk_dict in jwks_data.get("keys", []):
                if jwk_dict.get("kid") == kid:
                    key = jwt.PyJWK.from_dict(jwk_dict)
                    _key_cache[kid] = key
                    break

        if not key:
            raise jwt.InvalidTokenError(f"Key with kid {kid} not found in JWKS")

        payload = jwt.decode(
            token.credentials,
            key.key,
            algorithms=["RS256"],
            audience=AUTH0_AUDIENCE,
            issuer=f"https://{AUTH0_DOMAIN}/",
        )

        permissions = payload.get("permissions", [])
        logging.info(f"### Token verified. Permissions found: {permissions}")

        return {
            "payload": payload,
            "permissions": permissions
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed")


async def get_user_profile(access_token: str, decoded_payload: dict = None):
    """
    Fetch user profile. First checks the decoded payload for OIDC claims 
    to avoid network latency, then falls back to the /userinfo endpoint.
    """
    user_info = {'name': '', 'email': ''}

    # 1. Try to extract from already decoded payload (Fastest)
    if decoded_payload:
        sub = decoded_payload.get('sub') or ''
        if decoded_payload.get('gty') == "client-credentials" or sub.endswith("@clients"):
            user_info['name'] = 'M2M'
            user_info['email'] = 'M2M@auth0.com'
            logging.info(f"userinfo (from token): {user_info['name']}, {user_info['email']}")
            return user_info
        user_info['name'] = decoded_payload.get('name') or decoded_payload.get('nickname') or ''
        user_info['email'] = decoded_payload.get('email') or ''

        if user_info['name'] and user_info['email']:
            if settings.LOG_USER_INFO:
                logging.info(f"userinfo (from token): {user_info['name']}, {user_info['email']}")
            await verify_allowed_users(user_info)
            return user_info

    # 2. Fallback to network call if info missing
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"https://{AUTH0_DOMAIN}/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=5
            )
            if r.status_code == 401:
                logger.warning(
                    "Auth0 /userinfo rejected the token (401). Ensure 'openid profile email' scopes are granted.")
                return user_info

            r.raise_for_status()
            data = r.json()
            user_info['name'] = data.get('name') or data.get('nickname') or ''
            user_info['email'] = data.get('email') or ''
            if settings.LOG_USER_INFO:
                logging.info(f"userinfo (from endpoint): {user_info.get('name')}, {user_info.get('email')}")
            await verify_allowed_users(user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Could not fetch user profile: {e}")
    return user_info


async def verify_allowed_users(user_info: dict):
    email = (user_info.get('email') or '').lower()
    if "amrit" not in email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not authorized")


# Mock object to maintain backward compatibility for imports if needed
class LegacyAuth0:
    def require_auth(self):
        return verify_token


auth0 = LegacyAuth0()
