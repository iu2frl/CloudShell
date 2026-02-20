"""
Key management endpoints.

POST /api/keys/generate  — generate a fresh RSA-4096 key pair and return both halves.
                           The private key is returned once and never stored server-side
                           until the user submits it via the device form.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.routers.auth import get_current_user
from backend.services.crypto import generate_key_pair

router = APIRouter(prefix="/keys", tags=["keys"])


class KeyPairOut(BaseModel):
    private_key: str   # OpenSSH PEM  — user must save this
    public_key: str    # OpenSSH pubkey — goes into authorized_keys on the target


@router.post("/generate", response_model=KeyPairOut)
async def generate(_: str = Depends(get_current_user)):
    """
    Generate a fresh RSA-4096 SSH key pair.

    The private key is returned **once** in the response.
    CloudShell never stores it until the user submits it as part of a device.
    """
    private_pem, public_openssh = generate_key_pair()
    return KeyPairOut(private_key=private_pem, public_key=public_openssh)
