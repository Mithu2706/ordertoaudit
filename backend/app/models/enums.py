"""Domain enumerations shared by models, schemas and services."""
import enum


class RoleCode(str, enum.Enum):
    SALESMAN = "SALESMAN"
    ADMIN = "ADMIN"
    PRODUCTION = "PRODUCTION"
    OWNER = "OWNER"
    AUDITOR = "AUDITOR"  # accountant / auditor: read-only


class ItemType(str, enum.Enum):
    RAW_MATERIAL = "RAW_MATERIAL"
    PACKAGING = "PACKAGING"
    FINISHED_GOOD = "FINISHED_GOOD"


class UnitDimension(str, enum.Enum):
    MASS = "MASS"
    VOLUME = "VOLUME"
    COUNT = "COUNT"


class MovementType(str, enum.Enum):
    OPENING = "OPENING"
    PURCHASE_RECEIPT = "PURCHASE_RECEIPT"
    PRODUCTION_ISSUE = "PRODUCTION_ISSUE"
    PRODUCTION_OUTPUT = "PRODUCTION_OUTPUT"
    SALES_DISPATCH = "SALES_DISPATCH"
    DAMAGE = "DAMAGE"
    SALES_RETURN = "SALES_RETURN"
    PURCHASE_RETURN = "PURCHASE_RETURN"
    ADJUSTMENT = "ADJUSTMENT"


INBOUND_MOVEMENTS = frozenset(
    {MovementType.OPENING, MovementType.PURCHASE_RECEIPT, MovementType.PRODUCTION_OUTPUT, MovementType.SALES_RETURN}
)
OUTBOUND_MOVEMENTS = frozenset(
    {MovementType.PRODUCTION_ISSUE, MovementType.SALES_DISPATCH, MovementType.DAMAGE, MovementType.PURCHASE_RETURN}
)


class PackagingKind(str, enum.Enum):
    POUCH = "POUCH"
    CARTON = "CARTON"
    LABEL = "LABEL"
    OTHER = "OTHER"


class CustomerType(str, enum.Enum):
    RETAILER = "RETAILER"
    DISTRIBUTOR = "DISTRIBUTOR"
    OTHER = "OTHER"


class DocumentStatus(str, enum.Enum):
    """Purchases and production runs: draft until posted to the ledger."""
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    CANCELLED = "CANCELLED"


class OrderStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVOICED = "INVOICED"
    PARTIALLY_DISPATCHED = "PARTIALLY_DISPATCHED"
    DISPATCHED = "DISPATCHED"
    CANCELLED = "CANCELLED"


class SupplyType(str, enum.Enum):
    INTRA_STATE = "INTRA_STATE"  # CGST + SGST
    INTER_STATE = "INTER_STATE"  # IGST


class InvoiceStatus(str, enum.Enum):
    ISSUED = "ISSUED"
    PARTIALLY_CREDITED = "PARTIALLY_CREDITED"
    CANCELLED = "CANCELLED"  # fully reversed by a credit note


class CreditNoteReason(str, enum.Enum):
    CANCELLATION = "CANCELLATION"
    SALES_RETURN = "SALES_RETURN"
    PRICE_ADJUSTMENT = "PRICE_ADJUSTMENT"


class DispatchStatus(str, enum.Enum):
    DISPATCHED = "DISPATCHED"
    CANCELLED = "CANCELLED"


class PaymentMode(str, enum.Enum):
    CASH = "CASH"
    UPI = "UPI"
    BANK_TRANSFER = "BANK_TRANSFER"
    CHEQUE = "CHEQUE"


class DocumentType(str, enum.Enum):
    """Numbering series kept in document_sequences."""
    SALES_ORDER = "SALES_ORDER"
    INVOICE = "INVOICE"
    CREDIT_NOTE = "CREDIT_NOTE"
    DISPATCH = "DISPATCH"
    PURCHASE = "PURCHASE"
    PRODUCTION_RUN = "PRODUCTION_RUN"
    RECEIPT = "RECEIPT"
    STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT"  # added in migration 0002
    DEBIT_NOTE = "DEBIT_NOTE"  # purchase returns, added in migration 0004
