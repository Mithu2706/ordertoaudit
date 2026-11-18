from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import (
    MASTER_READERS,
    MATERIAL_READERS,
    SALES_MASTER_WRITERS,
    DbSession,
    client_ip,
    require_roles,
)
from app.api.routers._params import Listing
from app.models import Supplier, User
from app.models.enums import RoleCode
from app.services.common import get_or_404
from app.schemas.common import Page
from app.schemas.parties import (
    CustomerCreate,
    CustomerOut,
    CustomerUpdate,
    SupplierCreate,
    SupplierOut,
    SupplierUpdate,
)
from app.services import parties as svc

customers = APIRouter(prefix="/customers", tags=["customers"])
suppliers = APIRouter(prefix="/suppliers", tags=["suppliers"])

# Salesmen may read customers, but the service restricts them to their own assignments.
CustomerReader = Annotated[User, Depends(require_roles(*MASTER_READERS, RoleCode.SALESMAN))]
Writer = Annotated[User, Depends(require_roles(*SALES_MASTER_WRITERS))]
SupplierReader = Annotated[User, Depends(require_roles(*MATERIAL_READERS))]


@customers.get("", response_model=Page[CustomerOut])
def list_customers(db: DbSession, actor: CustomerReader, params: Listing):
    rows, total = svc.list_customers(db, actor, params.q, params.active, params.limit, params.offset)
    return Page(items=rows, total=total, limit=params.limit, offset=params.offset)


@customers.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, db: DbSession, actor: CustomerReader):
    return svc.get_customer(db, customer_id, actor)


@customers.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(data: CustomerCreate, db: DbSession, actor: Writer, request: Request):
    return svc.create_customer(db, data, actor, client_ip(request))


@customers.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, data: CustomerUpdate, db: DbSession, actor: Writer, request: Request):
    return svc.update_customer(db, customer_id, data, actor, client_ip(request))


@suppliers.get("", response_model=Page[SupplierOut])
def list_suppliers(db: DbSession, _: SupplierReader, params: Listing):
    rows, total = svc.list_suppliers(db, params.q, params.active, params.limit, params.offset)
    return Page(items=rows, total=total, limit=params.limit, offset=params.offset)


@suppliers.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: int, db: DbSession, _: SupplierReader):
    return get_or_404(db, Supplier, supplier_id, "Supplier")


@suppliers.post("", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier(data: SupplierCreate, db: DbSession, actor: Writer, request: Request):
    return svc.create_supplier(db, data, actor, client_ip(request))


@suppliers.patch("/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: int, data: SupplierUpdate, db: DbSession, actor: Writer, request: Request):
    return svc.update_supplier(db, supplier_id, data, actor, client_ip(request))
