# API & Permissions

Base path `/api`. Full schema: `/api/docs`.

**Authentication.** `POST /api/auth/login` takes the form fields `username` and `password`.

* **Browser app:** the response sets an httpOnly, `SameSite=Strict` session cookie
  (`ota_session`, path `/api`), so page scripts can't read the token. It also sets a readable
  `ota_csrf` cookie. Every write (POST, PUT, PATCH, DELETE) sent with the cookie must echo that
  value in an `X-CSRF-Token` header (double-submit); otherwise it gets 403 `csrf_failed`.
  `POST /api/auth/logout` clears both cookies.
* **API clients and Swagger:** the response body also contains `access_token`. Send it as
  `Authorization: Bearer <token>`. Bearer requests need no CSRF header, because browsers never
  attach that header on their own.

The session cookie is marked `Secure` whenever the request arrived over HTTPS
(`COOKIE_SECURE=auto`).

## Conventions

* **Money and quantities are JSON strings** (`"7875.00"`, `"10.5000"`), so
  no client ever turns them into floats. Input with more decimals than the
  column allows (e.g. `"10.555"` rupees) is rejected rather than rounded.
* **Errors** always look like this:
  `{"error": {"code": "...", "message": "...", "details": {...}}}`

  | Status | code | Meaning |
  |---|---|---|
  | 401 | `not_authenticated` | missing / invalid / expired token, inactive user |
  | 403 | `permission_denied` | role not allowed (details list allowed roles) |
  | 404 | `not_found` | missing, or outside your scope (e.g. another salesman's customer) |
  | 409 | `conflict` / `integrity_error` | duplicate code, database rule |
  | 422 | `validation_error` | malformed input (details list fields) |
  | 422 | `business_rule_violation` | valid input that breaks a rule (GSTIN/state mismatch…) |
* **Lists** return `{"items": [...], "total", "limit", "offset"}` and accept
  `q`, `active`, `limit` (≤ 200) and `offset`.
* **No hard deletes for masters.** Set `is_active: false` instead, because
  invoices and the stock ledger reference them.
* **PATCH semantics.** Omitted fields are left unchanged. An explicit `null`
  on a required field is refused.

## How authorization works

1. `get_current_user` decodes the JWT (HS256 is pinned, so `alg: none` is
   refused) and **reloads the user from the database**. A deactivated user's
   token stops working immediately. The role claim inside the token is never
   trusted.
2. Each endpoint declares `require_roles(...)` (`app/api/deps.py`). The role
   groups are defined in one place there.
3. Row-level scope lives in services. A salesman's customer queries are
   filtered to `assigned_salesman_id = me`.
4. Escalation guard: only an OWNER can create an owner or modify an owner's
   account. Nobody can deactivate themselves or change their own role.

## Permission matrix

| Endpoint | Salesman | Admin | Production | Owner | Auditor |
|---|:-:|:-:|:-:|:-:|:-:|
| `GET /users`, `POST/PATCH /users` | | ✔ | | ✔ | |
| `GET /users/salesmen` | | ✔ | | ✔ | ✔ |
| `GET /customers` | own only | ✔ | | ✔ | ✔ |
| `POST/PATCH /customers` | | ✔ | | | |
| `GET /suppliers` | | ✔ | ✔ | ✔ | ✔ |
| `POST/PATCH /suppliers` | | ✔ | | | |
| `GET /raw-materials`, `/packaging-materials` | | ✔ | ✔ | ✔ | ✔ |
| `POST/PATCH /raw-materials`, `/packaging-materials` | | ✔ | ✔ | | |
| `GET /products` (price list) | ✔ | ✔ | ✔ | ✔ | ✔ |
| `POST/PATCH /products` | | ✔ | | | |
| `GET /states`, `/units`, `/unit-conversions`, `/company` | ✔ | ✔ | ✔ | ✔ | ✔ |
| `POST /unit-conversions` | | ✔ | ✔ | | |
| `PATCH /company`, `PUT /settings/{key}` | | ✔ | | ✔ | |
| `GET /settings` | | ✔ | ✔ | ✔ | ✔ |
| `GET /audit-logs` | | ✔ | | ✔ | ✔ |
| `GET /inventory/balances`, `/movements`, `/items/{id}/ledger` | | ✔ | ✔ | ✔ | ✔ |
| `POST /inventory/opening-stock` | | ✔ | | | |
| `POST /inventory/adjustments` (DAMAGE) | | ✔ | ✔ | | |
| `POST /inventory/adjustments` (ADJUSTMENT) | | ✔ | | | |
| `GET /purchases` | | ✔ | ✔ | ✔ | ✔ |
| `POST/PUT /purchases`, `/post`, `/cancel`, `/purchases/{id}/returns` | | ✔ | ✔ | | |
| `GET /boms`, `GET /production-runs` (incl. `alerts_only`) | | ✔ | ✔ | ✔ | ✔ |
| `POST /boms`, `/boms/{id}/activate` | | ✔ | ✔ | | |
| `POST /production-runs`, `PUT …/actuals`, `POST …/post`, `…/cancel` | | ✔ | ✔ | | |
| `GET /catalog` (price list + available stock) | ✔ | ✔ | ✔ | ✔ | ✔ |
| `GET /sales-orders` | own only | ✔ | | ✔ | ✔ |
| `POST/PUT /sales-orders`, `…/submit` | own | | | | |
| `POST /sales-orders/{id}/approve`, `…/reject` | | ✔ | | | |
| `POST /sales-orders/{id}/cancel` | own draft/submitted | ✔ | | | |
| `GET /invoices`, `/invoices/{id}/pdf`, `/dispatches`, `/payments`, `/receivables` | | ✔ | | ✔ | ✔ |
| `POST /invoices`, `/invoices/{id}/credit-notes`, `/dispatches`, `/payments`, `/payments/{id}/reverse`, `/payments/{id}/reallocate` | | ✔ | | | |
| `GET /reports`, `/reports/{key}` | customer-sales (own) | ✔ | stock & production | ✔ | ✔ |

`tests/test_permissions.py` checks **every cell** of this table: each role
against each endpoint, 80 cases in total.

## Master-data rules enforced by services

* GSTIN: format, check digit (mod-36), and first two digits = party state.
  This is re-checked after every PATCH, so changing a customer's state
  without fixing the GSTIN is refused.
* Codes are trimmed and upper-cased, and item codes are unique across raw
  materials, packaging and products.
* A product's base unit must be a count unit (PKT/PCS/CTN).
* An item's base unit is locked once any stock movement exists, because
  ledger quantities are stored in that unit.
* Unit conversions: a global conversion must stay within one dimension
  (kg↔g, L↔ml). Cross-dimension and packing conversions (1 CTN = 20 PKT)
  must name an item. A pair that already exists in either direction is
  refused, because the converter derives the inverse.
* Settings are whitelisted and validated: `variance_tolerance_pct` (0–100,
  default 3), `default_gst_rate` (0–28), `receivable_ageing_buckets`
  (e.g. `30,60,90`).
* Every create/update writes an `audit_logs` row. Updates log only the
  fields that changed (before → after). Logins are logged too. Password
  hashes are never logged.
