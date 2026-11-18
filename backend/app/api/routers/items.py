"""Raw-material, packaging-material and product endpoints, generated from one factory
so the three masters behave identically and their permissions are declared side by side."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import (
    ALL_ROLES,
    MATERIAL_READERS,
    MATERIAL_WRITERS,
    SALES_MASTER_WRITERS,
    DbSession,
    client_ip,
    require_roles,
)
from app.api.routers._params import Listing
from app.models import User
from app.models.enums import ItemType, RoleCode
from app.schemas.common import Page
from app.schemas.items import (
    PackagingMaterialCreate,
    PackagingMaterialOut,
    PackagingMaterialUpdate,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    RawMaterialCreate,
    RawMaterialOut,
    RawMaterialUpdate,
)
from app.services import items as svc


def _build(prefix: str, tag: str, item_type: ItemType, create_s, update_s, out_s,
           readers: tuple[RoleCode, ...], writers: tuple[RoleCode, ...]) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])
    Reader = Annotated[User, Depends(require_roles(*readers))]
    Writer = Annotated[User, Depends(require_roles(*writers))]

    @router.get("", response_model=Page[out_s], name=f"list_{tag}")
    def list_(db: DbSession, _: Reader, params: Listing):
        rows, total = svc.list_items(db, item_type, params.q, params.active, params.limit, params.offset)
        return Page(items=[out_s.of(r) for r in rows], total=total, limit=params.limit, offset=params.offset)

    @router.get("/{item_id}", response_model=out_s, name=f"get_{tag}")
    def get_(item_id: int, db: DbSession, _: Reader):
        return out_s.of(svc.get_item(db, item_type, item_id))

    @router.post("", response_model=out_s, status_code=status.HTTP_201_CREATED, name=f"create_{tag}")
    def create_(data: create_s, db: DbSession, actor: Writer, request: Request):  # type: ignore[valid-type]
        return out_s.of(svc.create_item(db, item_type, data, actor, client_ip(request)))

    @router.patch("/{item_id}", response_model=out_s, name=f"update_{tag}")
    def update_(item_id: int, data: update_s, db: DbSession, actor: Writer, request: Request):  # type: ignore[valid-type]
        return out_s.of(svc.update_item(db, item_type, item_id, data, actor, client_ip(request)))

    return router


raw_materials = _build("/raw-materials", "raw_materials", ItemType.RAW_MATERIAL, RawMaterialCreate,
                       RawMaterialUpdate, RawMaterialOut, MATERIAL_READERS, MATERIAL_WRITERS)
packaging_materials = _build("/packaging-materials", "packaging_materials", ItemType.PACKAGING,
                             PackagingMaterialCreate, PackagingMaterialUpdate, PackagingMaterialOut,
                             MATERIAL_READERS, MATERIAL_WRITERS)
# Everyone can read products (salesmen need the price list); only admin changes prices.
products = _build("/products", "products", ItemType.FINISHED_GOOD, ProductCreate, ProductUpdate, ProductOut,
                  ALL_ROLES, SALES_MASTER_WRITERS)
