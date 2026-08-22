from typing import Annotated

from fastapi import Header, HTTPException, status


async def get_current_user_id(
    x_user_id: Annotated[str | None, Header(alias="X-User-ID")] = None,
) -> str:
    """Temporary local identity seam, replaced by Google OAuth in Milestone 4."""
    if not x_user_id or not x_user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-User-ID is required during local development",
        )
    return x_user_id.strip()
