# System Design — Last-Mile Delivery Tracker

## 1. Rate Calculation Engine

The rate engine (`backend/services/rate_engine.py`) is a standalone async module that accepts a Motor database handle as an explicit parameter. This design choice makes it independently unit-testable with a mock DB — no FastAPI context, no HTTP server, no real MongoDB connection required.

**Design principles:**
- **No hardcoded values.** Every rate (base rate, per-kg rate, COD surcharge) is fetched from MongoDB at runtime. Admin users update these values via API — the engine always reflects the current configuration.
- **Clear input/output contract.** The function takes primitive inputs (addresses, dimensions, weights, payment type) and returns a `ChargeBreakdown` dataclass with every intermediate calculation exposed — not just the final number. This allows the frontend to show a detailed breakdown to the customer *before* they confirm an order.
- **Isolated from routing.** The function is imported by route handlers, never the reverse. It raises domain-specific exceptions (`ZoneNotFoundError`, `RateCardNotFoundError`) that route handlers catch and convert to HTTP 422 responses.

**Calculation sequence:**
1. Zone detection on both addresses
2. Volumetric weight = (L × B × H) / 5000
3. Billable weight = max(actual, volumetric)
4. Zone relation = "intra" if zones match, else "inter"
5. Rate card lookup (also tries reverse direction for inter-zone symmetry)
6. Base charge = base_rate + (billable_weight × per_kg_rate)
7. COD surcharge lookup and addition if applicable

## 2. Zone Detection Approach

Zone detection uses **substring matching**: for each zone in the `zones` collection, the engine checks whether any area string (pincode or locality name) appears anywhere in the address string (case-insensitive). The first matching zone wins.

**Why this approach:**
- No external geocoding API — zero cost, zero network dependency at calculation time
- Admin-configurable: adding a new locality to a zone's `areas` array immediately enables detection for that area
- Handles both numeric pincodes (`"110001"`) and named localities (`"Karol Bagh"`) in the same mechanism

**Trade-off:** Substring matching can produce false positives on ambiguous short strings. In practice, pincodes (6-digit numbers) are highly specific. For localities, admins should use unambiguous names. A production system might layer on geocoding as a fallback.

**Failure mode:** If neither address matches any zone, a `ZoneNotFoundError` is raised with a descriptive message identifying the unmatched address. The order is rejected at the calculation stage — no partial data is written.

## 3. Auto-Assignment Logic

Agent assignment runs automatically when an order is placed and on reschedule. The algorithm:

1. **Filter candidates:** `role == "delivery_agent"` AND `agent_status == "available"` AND `zone == order.pickup_zone_id`
2. **Load-balance:** For each candidate, count active (non-terminal) orders — orders where `current_status` is not "Delivered" or "Failed". The agent with the fewest active orders is selected. In case of a tie, the first agent returned by MongoDB is chosen (deterministic given stable sort).
3. **Persist assignment:** The selected agent's `agent_status` is set to "busy" and the order's `assigned_agent_id` is updated atomically in sequence (not a transaction — acceptable trade-off for the free tier).
4. **No agent available:** Rather than silently failing, a `NoAgentAvailableError` is raised. The order is still created and set to "Created" status. A warning is returned in the API response. The admin can manually assign an agent later.

**Agent release:** When an order reaches a terminal status ("Delivered" or "Failed"), `order_service.update_order_status()` calls `assignment_service.release_agent()`, which sets `agent_status = "available"`. This happens within the same status-update transaction as the tracking history write.

**Manual assignment:** Admin can always override auto-assignment via `POST /admin/orders/{id}/assign`. The same persistence helper is used, ensuring consistency.

## 4. Failed Delivery and Reschedule Handling

**Failed delivery flow:**
1. Agent marks order as "Failed" via `PATCH /api/agent/orders/{id}/status` with `new_status: "Failed"` and an optional notes field
2. `order_service.update_order_status()` validates the transition (only valid from "Picked Up", "In Transit", or "Out for Delivery")
3. A `tracking_history` document is appended: `{status: "Failed", actor_id: agent_id, actor_role: "delivery_agent", notes: reason}`
4. The assigned agent's `agent_status` is set back to "available"
5. `notification_service.send_failed_delivery_email()` is called with the failure reason

**Reschedule flow:**
1. Customer submits `POST /api/customer/orders/{id}/reschedule` with a new `reschedule_date`
2. Only orders in "Failed" status can be rescheduled (enforced in the route)
3. `reschedule_date` is written to the order document
4. Status transitions: Failed → Rescheduled (via state machine)
5. Auto-assignment runs immediately for the rescheduled order — it re-enters the normal flow (Rescheduled → Assigned → Picked Up → ...)
6. A reschedule confirmation email is sent to the customer

**Tracking history integrity:** Every step above (Failed, Rescheduled, Assigned for reschedule) appends a separate document to `tracking_history`. The collection is strictly write-once — no UPDATE or DELETE operations exist anywhere in the codebase. This gives a complete, tamper-evident audit trail of every status change, who made it, and when.

**State machine enforcement:** The `VALID_TRANSITIONS` dict in `order_service.py` is the single source of truth for legal transitions. Any attempt to jump states (e.g., "Created" → "Delivered") raises `InvalidTransitionError` before any DB write occurs, keeping the order state consistent.
