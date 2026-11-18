from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query


@dataclass
class ListParams:
    q: str | None
    active: bool | None
    limit: int
    offset: int


def list_params(
    q: Annotated[str | None, Query(max_length=100, description="Search code/name")] = None,
    active: Annotated[bool | None, Query(description="Filter by active flag")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ListParams:
    return ListParams(q=q, active=active, limit=limit, offset=offset)


Listing = Annotated[ListParams, Depends(list_params)]
