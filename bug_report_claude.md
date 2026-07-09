# CoWork API — Bug Report

Audit of the `CoWork` coworking-space booking API against the business rules and
API contract in the problem statement (`ICT_Fest_Hackathon_Preliminary.pdf`,
Sections 3–4 / mirrored in `README.md`).

**Method:** read every file in `app/`, then built and ran the real container
(`docker compose up --build`, port remapped locally to avoid a clash with an
unrelated container already using 8000) and drove it with `curl`/Python
scripts hitting the live API — including concurrent request bursts — to
confirm each bug is real and not a misreading of the code. Every bug below is
marked with how it was confirmed. **Nothing has been fixed yet** — this is a
diagnosis-only pass, fixes are described but not applied.

27 distinct bugs found. Difficulty tags (Easy/Medium/Hard) are my own estimate
of the grading rubric mentioned in the PDF, not official.

## Summary table

| # | Bug | Location | Rule | Difficulty |
|---|-----|----------|------|------------|
| 1 | Access token lives 15 hours, not 900s | `app/auth.py:50` | 8 | Easy |
| 2 | Logout never actually revokes the token | `app/auth.py:97` | 8 | Easy |
| 3 | Refresh tokens are infinitely reusable | `app/routers/auth.py:81-93` | 8 | Medium |
| 4 | Duplicate registration returns 200-ish instead of 409 | `app/routers/auth.py:37-43` | 15 | Easy |
| 5 | UTC-offset datetimes stored with wrong absolute time | `app/timeutils.py:11-13` | 1 | Easy |
| 6 | No minimum-duration / end-after-start check | `app/routers/bookings.py:89-94` | 2 | Medium |
| 7 | 5-minute past-start grace window | `app/routers/bookings.py:86` | 2 | Easy |
| 8 | Malformed datetime crashes with 500 | `app/routers/bookings.py:82-83` | contract | Easy |
| 9 | Conflict check uses `<=` instead of `<` | `app/routers/bookings.py:50` | 3 | Medium |
| 10 | Double-booking race (no locking) | `app/routers/bookings.py:42-116` | 3 | Hard |
| 11 | Booking quota race (no locking) | `app/routers/bookings.py:55-103` | 4 | Hard |
| 12 | Rate limiter race (lost updates) | `app/services/ratelimit.py:18-26` | 5 | Hard |
| 13 | Reference-code race (duplicate codes) | `app/services/reference.py:17-21` | 7 | Hard |
| 14 | Refund 48h boundary off by one bucket-hour | `app/routers/bookings.py:200-202` | 6 | Medium |
| 15 | 0%-refund tier is dead code (always 50%) | `app/routers/bookings.py:203-206` | 6 | Easy |
| 16 | Refund amount computed twice, can diverge | `app/routers/bookings.py:208` + `app/services/refunds.py:15-17` | 6 | Medium |
| 17 | Cancel race → duplicate RefundLog entries | `app/routers/bookings.py:184-214` | 6 | Hard |
| 18 | `GET /bookings/{id}` leaks other members' bookings | `app/routers/bookings.py:156-163` | 10 | Medium |
| 19 | `GET /bookings/{id}` returns `created_at` as `start_time` | `app/routers/bookings.py:165-166` | contract | Easy |
| 20 | Cross-org data leak in CSV export | `app/services/export.py:22-52` | 9 | Medium |
| 21 | Pagination sorted descending, not ascending | `app/routers/bookings.py:137` | 11 | Easy |
| 22 | Pagination offset formula off by one page | `app/routers/bookings.py:138` | 11 | Easy |
| 23 | Pagination `limit` query param ignored (hardcoded 10) | `app/routers/bookings.py:139` | 11 | Easy |
| 24 | Usage-report cache never invalidated on new booking | `app/routers/bookings.py:105-124` | 12 | Medium |
| 25 | Availability cache never invalidated on cancel | `app/routers/bookings.py:178-225` | 13 | Medium |
| 26 | Room-stats race + not restart-durable | `app/services/stats.py:15-26` | 14 | Hard |
| 27 | Notification lock-ordering deadlock | `app/services/notifications.py:24-35` | 16 | Hard |

---

## 1. Authentication & sessions (Rule 8)

### Bug 1 — Access token lives 15 hours instead of 900 seconds
**Location:** `app/auth.py:50`
```python
lifetime = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES * 60)
```
`ACCESS_TOKEN_EXPIRE_MINUTES` (`app/config.py:11`) is already `15`, i.e. minutes.
Multiplying by 60 turns it into `timedelta(minutes=900)` = 54,000 seconds =
15 hours, not the spec-mandated **exactly 900 seconds**.

**Confirmed live:** decoded a real access token — `exp - iat = 54000`.

**Fix:** `lifetime = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)`.

---

### Bug 2 — Logout never actually revokes the token
**Location:** `app/auth.py:97` (compare with `app/auth.py:86`)
```python
def revoke_access_token(payload: dict) -> None:
    _revoked_tokens.add(payload["jti"])          # stores jti
...
def get_token_payload(request: Request) -> dict:
    ...
    if payload.get("sub") in _revoked_tokens:     # checks sub!
        raise AppError(401, "UNAUTHORIZED", "Token has been revoked")
```
Revocation stores the token's `jti` (a uuid4 hex string) but the check looks
up the user id (`sub`, e.g. `"2"`) in that same set. They never match, so a
"logged out" access token keeps working for every subsequent request until it
naturally expires (which, combined with Bug 1, is up to 15 hours later).

**Confirmed live:** called `/auth/logout` (200 OK), then reused the same
access token on `GET /rooms` → got `200 []` instead of `401`.

**Fix:** `if payload.get("jti") in _revoked_tokens:`.

---

### Bug 3 — Refresh tokens are infinitely reusable
**Location:** `app/routers/auth.py:81-93`

The spec requires refresh tokens to be single-use (reuse → 401). The
`/auth/refresh` handler decodes the token, looks up the user, and issues a new
pair — but never records the presented refresh token's `jti` anywhere, so
there is no way for a second use of the same token to be rejected. Unlike
access-token revocation (which at least has a — broken — mechanism), there is
no revoked-refresh-token tracking at all.

**Confirmed live:** refreshed once, then reused the *original* refresh token
again → got a brand new token pair (200) instead of 401.

**Fix:** track used refresh-token `jti`s (e.g. a `_revoked_refresh_jtis` set,
checked/populated in `/auth/refresh` the same way access tokens attempt to)
and reject reuse with 401.

---

## 2. Registration (Rule 15)

### Bug 4 — Duplicate username returns existing user data instead of 409
**Location:** `app/routers/auth.py:37-43`
```python
if existing is not None:
    return {
        "user_id": existing.id,
        "org_id": org.id,
        "username": existing.username,
        "role": existing.role,
    }
```
Spec: "a duplicate username within the org → `409 USERNAME_TAKEN`." Instead
the handler silently returns the *existing* user's id/role with a 201 status
(the route decorator fixes `status_code=201` for every return path). This is
also a minor information-disclosure issue: an unauthenticated caller can
probe usernames and learn a user's `user_id`/`role` without a password.

**Confirmed live:** re-registered `alice` with a different password → `201`
with alice's existing `user_id`/`role`, not `409 USERNAME_TAKEN`.

**Fix:** `raise AppError(409, "USERNAME_TAKEN", "Username already taken in this organization")`.

Note: once fixed, two *concurrent* first-time registrations of the same
org+username will race past the `existing is None` check and both attempt to
insert; the `uq_user_org_username` constraint will reject the second with a
raw `IntegrityError` (500) unless that's also caught and translated to 409.

---

## 3. Datetime handling (Rule 1)

### Bug 5 — UTC-offset datetimes are stored with the wrong absolute time
**Location:** `app/timeutils.py:11-13`
```python
dt = datetime.fromisoformat(value)
if dt.tzinfo is not None:
    dt = dt.replace(tzinfo=None)
```
`.replace(tzinfo=None)` strips the offset without converting to UTC first —
it keeps the wall-clock numbers and just relabels them as UTC. Spec: "Input
datetimes carrying a UTC offset must be converted to UTC before storage or
comparison."

**Confirmed live:** sent `start_time = "2026-07-11T06:00:00+05:00"` (which is
`2026-07-11T01:00:00Z`). The booking was created and `GET
/rooms/{id}/availability` returned the busy interval as
`2026-07-11T06:00:00+00:00` — five hours later than the real UTC instant. This
silently corrupts every downstream computation on that booking: conflict
detection, quota-window membership, availability, and usage reports.

**Fix:** `dt = dt.astimezone(timezone.utc).replace(tzinfo=None)`.

---

## 4. Booking window validation (Rule 2)

### Bug 6 — No minimum-duration / end-after-start check
**Location:** `app/routers/bookings.py:89-94`
```python
duration_hours = (end - start).total_seconds() / 3600
if duration_hours != int(duration_hours):
    raise AppError(400, "INVALID_BOOKING_WINDOW", ...)
duration_hours = int(duration_hours)
if duration_hours > MAX_DURATION_HOURS:
    raise AppError(400, "INVALID_BOOKING_WINDOW", ...)
```
`MIN_DURATION_HOURS = 1` is defined at line 21 and never referenced anywhere
in the file. There is no check that `duration_hours >= 1`, and no explicit
`end_time > start_time` check. `0` passes the whole-number check (`0.0 ==
int(0.0)`) and isn't `> 8`; negative durations behave the same way.

**Confirmed live:**
- `end_time == start_time` → `201 Created` with `price_cents: 0`.
- `end_time` two hours *before* `start_time` → `201 Created` with
  `price_cents: -1998`.

**Fix:** add `if duration_hours < MIN_DURATION_HOURS: raise AppError(400,
"INVALID_BOOKING_WINDOW", ...)` right after the whole-number check (this also
subsumes `end_time <= start_time`, since that yields `duration_hours <= 0 <
MIN_DURATION_HOURS`).

---

### Bug 7 — 5-minute past-start grace window
**Location:** `app/routers/bookings.py:86`
```python
if start <= now - timedelta(seconds=300):
    raise AppError(400, "INVALID_BOOKING_WINDOW", ...)
```
Spec: "`start_time` must be strictly in the future at request time — no grace
window of any size." This accepts any `start_time` up to 299 seconds in the
past.

**Confirmed live:** booked with `start_time` 100 seconds in the past →
`201 Created`.

**Fix:** `if start <= now:`.

---

### Bug 8 — Malformed datetime string crashes with a raw 500
**Location:** `app/routers/bookings.py:82-83`
```python
start = parse_input_datetime(payload.start_time)
end = parse_input_datetime(payload.end_time)
```
`parse_input_datetime` calls `datetime.fromisoformat(value)`, which raises
`ValueError` on malformed input. Nothing catches it here (compare
`app/routers/rooms.py:73-76` and `app/routers/admin.py:29-33`, which both
wrap their date parsing in `try/except ValueError`). The error contract
promises 400/422 for bad input, never an unhandled 500.

**Confirmed live:** `POST /bookings` with `start_time: "not-a-date"` →
`500 Internal Server Error`.

**Fix:** wrap both `parse_input_datetime` calls in `try/except ValueError:
raise AppError(400, "INVALID_BOOKING_WINDOW", ...)`.

---

## 5. Double-booking conflict detection (Rule 3)

### Bug 9 — Conflict check uses `<=` instead of `<`, rejecting back-to-back bookings
**Location:** `app/routers/bookings.py:50`
```python
if b.start_time <= end and start <= b.end_time:
    return True
```
Spec overlap formula is `existing.start < new.end AND new.start <
existing.end` (strict), specifically so back-to-back bookings are allowed.
Using `<=` on both sides means a booking that starts exactly when another
ends is flagged as a conflict.

**Confirmed live:** booked `[T+40h, T+41h)`, then `[T+41h, T+42h)` on the same
room → the second call got `409 ROOM_CONFLICT` instead of `201`.

**Fix:** `if b.start_time < end and start < b.end_time:`.

---

### Bug 10 — Double-booking race: two concurrent requests can both win the same slot
**Location:** `app/routers/bookings.py:42-116` (`_has_conflict` at line 100,
insert at lines 106-117), widened by the `time.sleep(0.12)` in
`_pricing_warmup()` (line 48/28-29)

The conflict check reads all existing bookings, and only much later does the
code insert the new row — with no row/interval locking, no `SELECT ... FOR
UPDATE`, and no serializable transaction in between. Two concurrent requests
for the same room/slot both read "no conflict" before either has committed.
The `_pricing_warmup()` sleep sitting right after the read makes the race
window trivially easy to hit under normal concurrent load, not just adversarial
timing.

**Confirmed live:** fired 6 concurrent `POST /bookings` from 6 different users
for the *identical* time slot on the same room → **all 6 got `201 Created`**,
zero got `409`.

**Fix:** serialize on the room, e.g. take a DB-level lock scoped to
`room_id` (`SELECT ... FOR UPDATE` on a row representing the room, or a
`SERIALIZABLE`/`IMMEDIATE` transaction) spanning the conflict check through
the insert, or add a DB exclusion constraint on overlapping intervals per
room and catch the violation as `ROOM_CONFLICT`.

---

## 6. Booking quota (Rule 4)

### Bug 11 — Quota race: same TOCTOU pattern as the conflict check
**Location:** `app/routers/bookings.py:55-103` (`_check_quota`), widened by
`_quota_audit()`'s `time.sleep(0.1)`

Same shape as Bug 10: `_check_quota` counts existing confirmed bookings in the
(now, now+24h] window and returns without error if under the limit, but the
actual insert happens later in the caller with no lock held across the
check-then-insert sequence.

**Confirmed live:** one user fired 6 concurrent bookings on 6 different rooms,
all with `start_time` inside the next 24h (quota limit is 3) → **all 6
succeeded**, none got `409 QUOTA_EXCEEDED`.

**Fix:** same remedy family as Bug 10 — lock per-user (or use a
serializable transaction) across the count-then-insert.

---

## 7. Rate limiting (Rule 5)

### Bug 12 — Rate limiter race: concurrent requests overwrite each other's bucket
**Location:** `app/services/ratelimit.py:18-26`
```python
bucket = _buckets.get(user_id, [])
bucket = [t for t in bucket if t > now - _WINDOW_SECONDS]
_settle_pause()                    # sleep 0.1s
bucket.append(now)
_buckets[user_id] = bucket
if len(bucket) > _MAX_REQUESTS:
    raise AppError(429, ...)
```
Each request reads the bucket into a local list, sleeps, appends locally, then
overwrites the shared dict entry — last writer wins. Concurrent requests each
see a small (stale) bucket length and each think they're under the limit,
and each overwrite wipes out the others' recorded timestamps.

**Confirmed live:** fired 30 concurrent `POST /bookings` for one user (limit
is 20/60s, so 10 of the 30 should get `429`) → **0 of 30 were rate-limited.**

**Fix:** protect the read-modify-write with a per-user lock (or a single
process-wide lock given the low contention cost), or use an atomic structure
(e.g. a `collections.deque` behind a lock, or move to a DB/Redis-backed
counter).

---

## 8. Reference codes (Rule 7)

### Bug 13 — Reference-code race produces duplicate codes
**Location:** `app/services/reference.py:17-21`
```python
def next_reference_code() -> str:
    current = _counter["value"]
    _format_pause()                 # sleep 0.12s
    _counter["value"] = current + 1
    return f"CW-{current:06d}"
```
Classic unprotected read-then-write counter, with a sleep sitting in the
window between the read and the write.

**Confirmed live:** fired 10 concurrent booking creations (different rooms, no
conflict) → **all 10 got the exact same reference code**, `CW-001018`.

**Fix:** guard with a `threading.Lock`, or use a DB sequence /
`UPDATE ... RETURNING` so incrementing is atomic at the database level.

---

## 9. Cancellation & refunds (Rule 6)

### Bug 14 — 48-hour refund boundary is wrong (off by up to one hour)
**Location:** `app/routers/bookings.py:200-202`
```python
notice_hours = int(notice.total_seconds() // 3600)
if notice_hours > 48:
    refund_percent = 100
```
Two compounding issues: (a) `notice_hours` truncates to whole hours *before*
comparing, and (b) the comparison is `>` where the spec says `≥`. Together,
any notice period in `[48h00m00s, 49h00m00s)` truncates to `48` and fails
`48 > 48`, falling through to the 50% tier — a full hour-wide band of
under-refunding, not just the instant at exactly 48:00:00.

**Confirmed live:** cancelled a booking with ~48h20m notice → got
`refund_percent: 50` instead of the spec-correct `100`.

**Fix:** compare the actual `timedelta` without truncating first:
`if notice >= timedelta(hours=48): refund_percent = 100`.

---

### Bug 15 — 0%-refund tier is dead code; always pays 50%
**Location:** `app/routers/bookings.py:203-206`
```python
elif notice >= timedelta(hours=24):
    refund_percent = 50
else:
    refund_percent = 50
```
The `else` branch (meant for "notice < 24 hours → 0% refund") is a
copy-paste of the `elif` branch. Every cancellation with less than 24 hours'
notice — including cancelling a booking that has already started — pays out
50% instead of 0%.

**Confirmed live:** cancelled a booking with ~20h notice → got
`refund_percent: 50` instead of the spec-correct `0`.

**Fix:** `else: refund_percent = 0`.

---

### Bug 16 — Refund amount computed twice, independently, and can disagree
**Location:** `app/routers/bookings.py:208` and `app/services/refunds.py:15-17`

The cancel response computes the refund amount one way:
```python
refund_amount_cents = round(booking.price_cents * (refund_percent / 100.0))
```
and the persisted `RefundLog` (written by `log_refund`) computes it a
*different* way:
```python
dollars = booking.price_cents / 100.0
refund_dollars = dollars * (percent / 100.0)
amount_cents = int(refund_dollars * 100)
```
`round()` uses Python's banker's-rounding (round-half-to-even), and the
service uses a dollars-roundtrip plus `int()` truncation — neither implements
the spec's "round to nearest cent, half-cents rounding up," and because
they're two separate computations they can flat-out disagree with each other,
directly violating "the amount returned by the cancel response must equal the
amount stored in the RefundLog."

**Confirmed live:** `price_cents = 999`, 50% tier → cancel response
`refund_amount_cents: 500`, but the `RefundLog` entry (visible via `GET
/bookings/{id}`) stored `amount_cents: 499`. Spec-correct answer (999 × 0.5 =
499.5, half-cents round up) is 500 — so the response happens to be right here
and the log is wrong, but both are wrong for other inputs, and they disagree
with *each other* regardless.

**Fix:** compute the refund amount once (e.g. in `refunds.py`, using proper
half-up rounding — `math.floor(price_cents * percent / 100 + 0.5)` on
integers, no float dollar round-trip) and have the router use the value
`log_refund` returns instead of recomputing it.

---

### Bug 17 — Concurrent cancel requests can create duplicate refunds
**Location:** `app/routers/bookings.py:184-214`, widened by
`_settlement_pause()`'s `time.sleep(0.12)` (line 212)

`cancel_booking` reads `booking.status`, checks it isn't already `"cancelled"`,
calls `log_refund` (which inserts a `RefundLog` and commits), sleeps, *then*
sets `booking.status = "cancelled"` and commits. There is no row lock or
optimistic-concurrency check, so two concurrent cancel calls for the same
booking can both pass the `ALREADY_CANCELLED` check before either writes the
new status, and both create a `RefundLog` row.

**Confirmed live:** this is the same TOCTOU shape empirically confirmed for
Bugs 10–13 (sleep-widened read-then-write with no lock); not independently
stress-tested in isolation this run, but the code path is identical in
structure and directly contradicts the explicit spec requirement "a cancelled
booking has exactly one RefundLog entry ... must hold under concurrent cancel
requests for the same booking."

**Fix:** lock the booking row for the duration of the cancel (`SELECT ...
FOR UPDATE`, or re-check `status` immediately before the final commit inside
the same transaction/lock that performed the initial check), so only one
concurrent request can transition `confirmed → cancelled`.

---

## 10. Booking visibility & multi-tenancy (Rules 9–10)

### Bug 18 — `GET /bookings/{id}` lets any org member read any other member's booking
**Location:** `app/routers/bookings.py:156-163`
```python
booking = (
    db.query(Booking)
    .join(Room, Booking.room_id == Room.id)
    .filter(Booking.id == booking_id, Room.org_id == user.org_id)
    .first()
)
```
This only scopes by organization, not by owner. Spec: "Members may read...
only their own bookings (another member's booking id → 404
BOOKING_NOT_FOUND)." The correct owner-check already exists two functions
down in `cancel_booking` (`app/routers/bookings.py:192-193`) but was never
applied here.

**Confirmed live:** `bob` created a booking; `carol` (a different member of
the same org, not an admin) called `GET /bookings/{bob's id}` → `200` with
bob's full booking details, instead of `404`.

**Fix:** add the same guard used in `cancel_booking`:
`if user.role != "admin" and booking.user_id != user.id: raise
AppError(404, "BOOKING_NOT_FOUND", ...)`.

---

### Bug 19 — `GET /bookings/{id}` returns `created_at` in the `start_time` field
**Location:** `app/routers/bookings.py:165-166`
```python
response = serialize_booking(booking)
response["start_time"] = iso_utc(booking.created_at)
```
`serialize_booking` already sets `start_time` correctly; the very next line
overwrites it with the booking's *creation* timestamp instead of its actual
slot start time. Every single-booking lookup returns a wrong `start_time`.

**Confirmed live:** created a booking for `T+60h`; `GET /bookings/{id}`
returned `start_time` equal to `created_at` (i.e. "now"), not `T+60h`.

**Fix:** delete line 166 entirely.

---

### Bug 20 — Cross-org data leak in CSV export
**Location:** `app/services/export.py:22-52`
```python
def fetch_bookings_raw(db: Session, room_id: int) -> list[Booking]:
    return (
        db.query(Booking)
        .filter(Booking.room_id == room_id)
        .order_by(Booking.id.asc())
        .all()
    )
...
if include_all:
    if room_id is not None:
        rows = fetch_bookings_raw(db, room_id)   # no org check at all
```
`generate_export`'s `include_all=true, room_id=<id>` branch calls
`fetch_bookings_raw`, which filters only by `room_id` — it never checks the
room belongs to the caller's org. Spec: "A user (including admins) may only
ever read or act on data belonging to their own organization, on every code
path. Cross-org resource IDs behave as non-existent (→404)."

**Confirmed live:** created org2 with its own room and a booking; then, as
org1's admin, called `GET /admin/export?room_id=<org2's room>&include_all=true`
and got back **org2's actual booking row** (reference code, user id, price,
times) in the CSV, status `200`.

**Fix:** route this branch through the org-scoped query too (e.g. reuse
`_fetch_scoped(db, org_id, None, room_id)`, or add an explicit
`Room.org_id == org_id` check before calling `fetch_bookings_raw`, 404'ing if
the room isn't in the caller's org).

---

## 11. Pagination & ordering (Rule 11)

All three of the following live in the same query, `app/routers/bookings.py:136-141`:
```python
items = (
    base.order_by(Booking.start_time.desc(), Booking.id.asc())
    .offset(page * limit)
    .limit(10)
    .all()
)
```

### Bug 21 — Sorted descending instead of ascending
Spec: "sorted ascending by start_time." Code sorts `.desc()`.
**Fix:** `Booking.start_time.asc()`.

### Bug 22 — Offset formula skips an entire extra page
Spec formula: page N returns items `[(N−1)·L, N·L)`, i.e. offset
`(page-1)*limit`. Code uses `page * limit`, which means **page 1 always skips
the first `limit` items** — the true first page is never reachable at all.
**Fix:** `.offset((page - 1) * limit)`.

### Bug 23 — `limit` query parameter is ignored
The query always applies `.limit(10)` regardless of the caller's requested
`limit`. A caller asking for `limit=1` or `limit=50` still gets whatever a
hardcoded 10-row window (after the broken offset) happens to contain.
**Fix:** `.limit(limit)`.

**Confirmed live (all three at once):** created 5 bookings with distinct,
known `start_time`s and called `GET /bookings?page=1&limit=1`: got back **4**
items (not 1), in **descending** order, starting from the item that offset
`page*limit=1` happened to leave over — none of which was the earliest
booking a correct page 1 should return. With `limit=100` (5 total items),
`page=1` returned **zero** items, because `offset = 1*100 = 100` skips past
every row that exists.

---

## 12. Live-read consistency: caching (Rules 12–13)

`app/cache.py` provides `invalidate_report(org_id)` and
`invalidate_availability(room_id, date)`, but each mutating endpoint only
calls **one** of the two — the matrix is incomplete in both directions:

### Bug 24 — Creating a booking never invalidates the usage-report cache
**Location:** `app/routers/bookings.py:105-124` — calls
`cache.invalidate_availability(...)` (line 121) but never
`cache.invalidate_report(...)`.

**Confirmed live:** called `GET /admin/usage-report?from=<today>&to=<today>`
(cached: 0 bookings, 0 revenue), created a new same-day booking, called the
same report again → **identical stale response**, still showing 0/0, despite
spec requiring the report to "reflect the current state immediately."

**Fix:** add `cache.invalidate_report(room.org_id)` alongside the existing
`cache.invalidate_availability` call in `create_booking`.

### Bug 25 — Cancelling a booking never invalidates the availability cache
**Location:** `app/routers/bookings.py:178-225` — calls
`cache.invalidate_report(...)` (line 217) but never
`cache.invalidate_availability(...)`.

If a room's availability for a given date was already cached, cancelling a
booking on that date leaves the cache showing the now-cancelled slot as still
busy, violating "reflecting the current state immediately" for Rule 13. Same
mechanism as Bug 24, mirrored to the other cache/endpoint pair — not
independently re-verified live this run, but the missing call is directly
visible in the code (contrast the two invalidation calls present vs. absent
across both handlers).

**Fix:** add `cache.invalidate_availability(booking.room_id,
booking.start_time.date().isoformat())` in `cancel_booking`.

---

## 13. Room stats (Rule 14)

### Bug 26 — Stats race under concurrency, and not derived from the DB
**Location:** `app/services/stats.py:15-26`
```python
def record_create(room_id: int, price_cents: int) -> None:
    current = _stats.get(room_id, {"count": 0, "revenue": 0})
    count, revenue = current["count"], current["revenue"]
    _aggregate_pause()                # sleep 0.1s
    _stats[room_id] = {"count": count + 1, "revenue": revenue + price_cents}
```
Same unprotected read-modify-write shape as Bugs 12/13, sleep included. In
addition, `_stats` is a process-local in-memory dict rather than a value
derived from the `bookings` table, so — independent of the race — a container
restart resets every room's stats to zero even though the (persisted,
volume-backed) SQLite data still has the real bookings. Spec: "Always equals
the values derivable from the bookings themselves."

**Confirmed live:** fired 10 concurrent non-overlapping bookings on one room
(all 10 succeeded, `201`) → `GET /rooms/{id}/stats` reported
`total_confirmed_bookings: 2`, not 10. 8 of 10 increments were lost.

**Fix:** either guard `_stats` mutation with a lock, or (more robust, and
fixes the restart issue too) compute stats with a live `COUNT`/`SUM` query
against `bookings` filtered by `room_id` and `status = 'confirmed'` instead
of maintaining a separate counter.

---

## 14. Liveness (Rule 16)

### Bug 27 — Notification lock-ordering deadlock hangs the service
**Location:** `app/services/notifications.py:24-35`
```python
def notify_created(booking) -> None:
    with _email_lock:
        _send_email("created", booking)      # sleep 0.12s, holding email_lock
        with _audit_lock:                     # then take audit_lock
            _write_audit("created", booking)

def notify_cancelled(booking) -> None:
    with _audit_lock:
        _write_audit("cancelled", booking)    # sleep 0.1s, holding audit_lock
        with _email_lock:                     # then take email_lock
            _send_email("cancelled", booking)
```
`notify_created` acquires `email_lock` → `audit_lock`; `notify_cancelled`
acquires `audit_lock` → `email_lock` — the two orders are inverted. If a
create and a cancel run concurrently (both plausible under normal load: two
different users, one booking, one cancelling), one thread can hold
`email_lock` while waiting for `audit_lock`, and the other holds `audit_lock`
while waiting for `email_lock`. Neither `threading.Lock` has a timeout —
**this is a permanent deadlock**, and it's the direct, explicit case Rule 16
("no combination of concurrent valid requests may hang the service") is
guarding against.

**Confirmed live — and worse than a two-request hang:** fired concurrent
create+cancel pairs. The very first overlapping pair deadlocked; from that
point on, **both locks are permanently held forever**, so *every subsequent*
`POST /bookings` and `POST /bookings/{id}/cancel` call also hangs trying to
acquire them — 6 of 7 subsequent requests in the test all timed out (>8s, no
response at all). Meanwhile `GET /health` kept responding `200 {"status":
"ok"}` throughout, and unrelated endpoints (e.g. `GET /rooms`) also kept
responding — so this failure is **silent**: the process looks alive and a
naive health check would never catch that booking creation and cancellation
are permanently wedged. Had to restart the container to recover.

**Fix:** make both functions acquire the locks in the same order (e.g. always
`_email_lock` then `_audit_lock`), or eliminate the nested-lock pattern
entirely (e.g. two independent `with` blocks that don't nest, since email and
audit logging don't actually need to be mutually exclusive of each other).

---

## Additional observations (not counted as scored bugs)

- `requirements.txt` doesn't list `pytest`, but `README.md`'s local dev
  instructions say to `pip install -r requirements.txt` and then run
  `pytest` — following those steps literally fails with "command not found."
  `tests/test_smoke.py` only covers a single happy path (register → login →
  create room → create booking → list), so it doesn't exercise any of the 27
  bugs above.
- `docker-compose.yml` hardcodes `JWT_SECRET=cowork-dev-secret-change-me`,
  the same value as the code's own default — fine for local dev (and
  presumably overridden by the grader), just flagging it's not doing
  anything beyond what the code default already does.
- SQLite is opened with `timeout: 30` (`app/database.py:9`), which bounds
  (but doesn't eliminate) `database is locked` errors under heavy concurrent
  writes from multiple worker threads; given the sleep-widened races above
  are already the dominant concurrency problem, this wasn't separately
  stress-tested.

## How this was run/verified

Built and ran the real container: `docker compose up --build` (host port
remapped to 8001 locally since 8000 was already bound by an unrelated
container on this machine — no change needed to `docker-compose.yml` itself).
`pytest` (installed ad hoc, since it's missing from `requirements.txt`)
passes its one smoke test. Everything else above was driven live against
`http://localhost:8001` with small Python scripts (stdlib `urllib`, plus
`concurrent.futures.ThreadPoolExecutor` for the race conditions) — each
"Confirmed live" note reflects an actual request/response observed against
the running app, not just a code reading.
