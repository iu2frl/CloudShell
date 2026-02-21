"""
tests/test_keys_api.py — integration tests for the SSH key-pair generation API.

Tests cover:
- POST /api/keys/generate  requires authentication
- POST /api/keys/generate  returns private_key and public_key fields
- The private key is a valid OpenSSH / PEM-encoded private key
- The public key is a valid OpenSSH public key (starts with 'ssh-rsa')
- Two consecutive calls return different key pairs (randomness check)
"""


async def test_generate_key_requires_auth(client):
    """Unauthenticated POST /api/keys/generate must return 401."""
    resp = await client.post("/api/keys/generate")
    assert resp.status_code == 401


async def test_generate_key_returns_200(auth_client):
    """Authenticated POST /api/keys/generate must return 200."""
    resp = await auth_client.post("/api/keys/generate")
    assert resp.status_code == 200


async def test_generate_key_response_fields(auth_client):
    """Response must include private_key and public_key fields."""
    resp = await auth_client.post("/api/keys/generate")
    assert resp.status_code == 200
    body = resp.json()
    assert "private_key" in body
    assert "public_key" in body


async def test_generate_key_private_key_is_pem(auth_client):
    """The private_key in the response must be a PEM-formatted private key."""
    resp = await auth_client.post("/api/keys/generate")
    private_key = resp.json()["private_key"]
    assert "-----BEGIN OPENSSH PRIVATE KEY-----" in private_key
    assert "-----END OPENSSH PRIVATE KEY-----" in private_key


async def test_generate_key_public_key_is_openssh(auth_client):
    """The public_key must be an OpenSSH-formatted RSA public key."""
    resp = await auth_client.post("/api/keys/generate")
    public_key = resp.json()["public_key"].strip()
    assert public_key.startswith("ssh-rsa ")


async def test_generate_key_pairs_are_unique(auth_client):
    """Two key generation calls must produce different key pairs."""
    resp1 = await auth_client.post("/api/keys/generate")
    resp2 = await auth_client.post("/api/keys/generate")
    assert resp1.json()["private_key"] != resp2.json()["private_key"]
    assert resp1.json()["public_key"] != resp2.json()["public_key"]


async def test_generated_key_usable_for_device(auth_client):
    """A generated key pair should be accepted when creating a key-based device."""
    # Generate the key pair
    key_resp = await auth_client.post("/api/keys/generate")
    assert key_resp.status_code == 200
    private_key = key_resp.json()["private_key"]

    # Use the private key to create a device
    device_resp = await auth_client.post(
        "/api/devices/",
        json={
            "name": "key-device",
            "hostname": "10.0.0.5",
            "port": 22,
            "username": "ops",
            "auth_type": "key",
            "private_key": private_key,
        },
    )
    assert device_resp.status_code == 201
    assert device_resp.json()["auth_type"] == "key"
