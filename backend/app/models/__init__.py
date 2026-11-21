"""Import every model so Base.metadata knows all tables (Alembic + tests rely on this)."""
from app.models.audit import AuditLog
from app.models.auth import Role, User
from app.models.base import Base
from app.models.billing import CreditNote, CreditNoteItem, Invoice, InvoiceItem
from app.models.bom import Bom, BomItem
from app.models.inventory import StockMovement
from app.models.items import Item, PackagingMaterial, Product, RawMaterial
from app.models.parties import Customer, Supplier
from app.models.payments import Payment, PaymentAllocation
from app.models.production import ProductionConsumption, ProductionRun
from app.models.purchasing import Purchase, PurchaseItem, PurchaseReturn, PurchaseReturnItem
from app.models.reference import AppSetting, CompanyProfile, DocumentSequence, State, Unit, UnitConversion
from app.models.sales import Dispatch, DispatchItem, SalesOrder, SalesOrderItem

__all__ = [
    "AppSetting", "AuditLog", "Base", "Bom", "BomItem", "CompanyProfile", "CreditNote", "CreditNoteItem",
    "Customer", "Dispatch", "DispatchItem", "DocumentSequence", "Invoice", "InvoiceItem", "Item",
    "PackagingMaterial", "Payment", "PaymentAllocation", "Product", "ProductionConsumption", "ProductionRun",
    "Purchase", "PurchaseItem", "PurchaseReturn", "PurchaseReturnItem", "RawMaterial", "Role", "SalesOrder", "SalesOrderItem", "State",
    "StockMovement", "Supplier", "Unit", "UnitConversion", "User",
]
