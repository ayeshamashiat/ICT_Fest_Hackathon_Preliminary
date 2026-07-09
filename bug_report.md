# CoWork API Complete Bug Report

This document combines all identified bug reports.

---

# CoWork API Bug Report

## Bug #1: Access Token Expiration Time Incorrect (Easy)

**File(s):** `app/auth.py:50`

**Issue:**
The access token lifetime is calculated by multiplying `ACCESS_TOKEN_EXPIRE_MINUTES` (which is 15) by 60, resulting in 900 minutes (15 hours) instead of the required 900 seconds (15 minutes).

**Code:**
```python
lifetime = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES * 60)
```

**Expected Behavior (Business Rule 8):**
"Access tokens expire in exactly 900 seconds" (15 minutes)

**Why It's Wrong:**
- `ACCESS_TOKEN_EXPIRE_MINUTES = 15` is already in minutes
- Multiplying by 60 converts it to 900 minutes, which equals 54,000 seconds
- This makes access tokens valid for 15 hours instead of 15 minutes

**Fix:**
Remove the `* 60` multiplication since the value is already in minutes:
```python
lifetime = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
```

---

## Bug #2: Logout Never Actually Revokes Access Token (Easy)

**File(s):** `app/auth.py:97`

**Issue:**
The revocation check checks if the user's `sub` is in `_revoked_tokens`, but logout stores the token's `jti`.

**Code:**
```python
def revoke_access_token(payload: dict) -> None:
    _revoked_tokens.add(payload["jti"])  # Stores JTI
```
and:
```python
if payload.get("sub") in _revoked_tokens:  # Checks SUB
    raise AppError(401, "UNAUTHORIZED", "Token has been revoked")
```

**Expected Behavior (Business Rule 8):**
"Logout immediately invalidates the presented access token (subsequent use → 401)"

**Why It's Wrong:**
- After logout, the token's JTI is added to `_revoked_tokens` set
- On subsequent request, the code checks if `sub` (user ID) is in the set
- Since SUB and JTI are different values, the check always fails
- Revoked tokens are never actually rejected

**Fix:**
Check the JTI instead of SUB:
```python
if payload.get("jti") in _revoked_tokens:
    raise AppError(401, "UNAUTHORIZED", "Token has been revoked")
```

---

## Bug #3: Refresh Tokens Infinitely Reusable (Medium)

**File(s):** `app/routers/auth.py:81-93`

**Issue:**
The refresh endpoint doesn't invalidate the old refresh token, allowing it to be reused indefinitely.

**Code:**
```python
@router.post("/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    data = decode_token(payload.refresh_token)
    if data.get("type") != "refresh":
        raise AppError(401, "UNAUTHORIZED", "Wrong token type")
    user = db.query(User).filter(User.id == int(data["sub"])).first()
    if user is None:
        raise AppError(401, "UNAUTHORIZED", "Unknown user")
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "token_type": "bearer",
    }
```

**Expected Behavior (Business Rule 8):**
"Refresh tokens are single-use: refreshing returns a new access and refresh token and invalidates the presented refresh token (reuse → 401)"

**Why It's Wrong:**
The endpoint generates new tokens but never invalidates the old refresh token. An attacker who intercepts a refresh token can obtain new access/refresh tokens indefinitely.

**Fix:**
Add refresh token revocation similar to access token logout. Need to track refresh tokens separately since they have different semantics:
```python
_revoked_refresh_tokens: set[str] = set()

@router.post("/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    data = decode_token(payload.refresh_token)
    if data.get("type") != "refresh":
        raise AppError(401, "UNAUTHORIZED", "Wrong token type")
    
    # Check if refresh token was already used
    if data.get("jti") in _revoked_refresh_tokens:
        raise AppError(401, "UNAUTHORIZED", "Refresh token has already been used")
    
    user = db.query(User).filter(User.id == int(data["sub"])).first()
    if user is None:
        raise AppError(401, "UNAUTHORIZED", "Unknown user")
    
    # Invalidate the presented refresh token
    _revoked_refresh_tokens.add(data.get("jti"))
    
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "token_type": "bearer",
    }
```

---

## Bug #4: Duplicate Username Registration Returns Existing User Instead of Error (Easy)

**File(s):** `app/routers/auth.py:37-43`

**Issue:**
When registering with a duplicate username in the same organization, the endpoint returns the existing user's details with status 201 instead of raising a 409 error.

**Code:**
```python
if existing is not None:
    return {
        "user_id": existing.id,
        "org_id": org.id,
        "username": existing.username,
        "role": existing.role,
    }
```

**Expected Behavior (Business Rule 15):**
"A duplicate username within the org → 409 USERNAME_TAKEN"

**Why It's Wrong:**
The function silently allows duplicate usernames by returning the existing user instead of raising an error. This violates the API contract.

**Fix:**
Raise an error when username already exists:
```python
if existing is not None:
    raise AppError(409, "USERNAME_TAKEN", "Username already taken in this organization")
```

---

## Bug #5: UTC-Offset Datetimes Stored With Wrong Absolute Time (Easy)

**File(s):** `app/timeutils.py:11-13`

**Issue:**
The `parse_input_datetime` function removes timezone info without converting to UTC first. This means offsets are silently discarded.

**Code:**
```python
if dt.tzinfo is not None:
    dt = dt.replace(tzinfo=None)
return dt
```

**Expected Behavior (Business Rule 1):**
"Input datetimes carrying a UTC offset must be converted to UTC before storage or comparison; naive input is treated as UTC"

**Why It's Wrong:**
- Input: "2024-01-01T12:00:00+05:00" (noon in UTC+5)
- Current behavior: Strips offset, stores as "2024-01-01T12:00:00" (treated as UTC noon)
- Correct behavior: Should convert to UTC "2024-01-01T07:00:00Z" (7am UTC)

**Fix:**
Convert to UTC before removing timezone:
```python
from datetime import timezone

if dt.tzinfo is not None:
    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
return dt
```

---

## Bug #6: No Minimum-Duration / End-After-Start Check (Medium)

**File(s):** `app/routers/bookings.py:89-94`

**Issue:**
The code checks for maximum duration but not minimum duration. If `end_time <= start_time`, the check passes.

**Code:**
```python
duration_hours = (end - start).total_seconds() / 3600
if duration_hours != int(duration_hours):
    raise AppError(400, "INVALID_BOOKING_WINDOW", "duration must be a whole number of hours")
duration_hours = int(duration_hours)
if duration_hours > MAX_DURATION_HOURS:
    raise AppError(400, "INVALID_BOOKING_WINDOW", "duration out of range")
```

**Expected Behavior (Business Rule 2):**
"Duration must be a whole number of hours, minimum 1, maximum 8"

**Why It's Wrong:**
- If `end_time == start_time`: `duration_hours = 0`, which equals `int(0)`, so the whole-number check passes.
- If `end_time < start_time`: `duration_hours < 0`, same issue.
- Only max is checked, not min.

**Fix:**
Add minimum duration validation:
```python
duration_hours = (end - start).total_seconds() / 3600
if duration_hours != int(duration_hours):
    raise AppError(400, "INVALID_BOOKING_WINDOW", "duration must be a whole number of hours")
duration_hours = int(duration_hours)
if duration_hours < MIN_DURATION_HOURS or duration_hours > MAX_DURATION_HOURS:
    raise AppError(400, "INVALID_BOOKING_WINDOW", "duration out of range")
```

---

## Bug #7: 5-Minute Past-Start Grace Window (Easy)

**File(s):** `app/routers/bookings.py:86`

**Issue:**
The code allows a 300-second (5-minute) grace window for bookings in the past, when the rule specifies no grace window.

**Code:**
```python
if start <= now - timedelta(seconds=300):
    raise AppError(400, "INVALID_BOOKING_WINDOW", "start_time must be in the future")
```

**Expected Behavior (Business Rule 2):**
"start_time must be strictly in the future at request time - no grace window"

**Why It's Wrong:**
A booking with `start_time = now - 4 minutes` would be allowed, violating the "strictly in the future" requirement.

**Fix:**
Remove the grace window:
```python
if start <= now:
    raise AppError(400, "INVALID_BOOKING_WINDOW", "start_time must be in the future")
```

---

## Bug #8: Malformed DateTime String Returns Raw 500 (Easy)

**File(s):** `app/routers/bookings.py:82-83`

**Issue:**
`parse_input_datetime` raises `ValueError` on malformed input, and nothing catches it in `create_booking`, resulting in an unhandled 500 Internal Server Error.

**Code:**
```python
start = parse_input_datetime(payload.start_time)
end = parse_input_datetime(payload.end_time)
```

**Expected Behavior:**
The API contract promises appropriate validation (400 or 422 HTTP response status code) for malformed datetimes, not a 500 Internal Server Error.

**Why It's Wrong:**
If a user submits a malformed ISO 8601 string, the app crashes with an unhandled exception, failing to return a user-friendly 400 error.

**Fix:**
Wrap datetime parsing in a try-except block and raise an `AppError`:
```python
try:
    start = parse_input_datetime(payload.start_time)
    end = parse_input_datetime(payload.end_time)
except ValueError:
    raise AppError(400, "INVALID_BOOKING_WINDOW", "start_time and end_time must be valid ISO 8601 datetimes")
```

---

## Bug #9: Conflict Check Uses `<=` Instead of `<` (Medium)

**File(s):** `app/routers/bookings.py:50`

**Issue:**
The overlap detection uses `<=` operators when the business rule specifies strict `<` comparison.

**Code:**
```python
if b.start_time <= end and start <= b.end_time:
    return True
```

**Expected Behavior (Business Rule 3):**
"Two confirmed bookings for the same room overlap iff `existing.start < new.end AND new.start < existing.end`. Back-to-back bookings are allowed."

**Why It's Wrong:**
Using `<=` causes back-to-back bookings to be rejected. For example:
- Existing booking: 10:00 - 11:00
- New booking: 11:00 - 12:00
- With `<=`: `10:00 <= 12:00 AND 11:00 <= 11:00` → true (conflict detected, but shouldn't be)
- With `<`: `10:00 < 12:00 AND 11:00 < 11:00` → false (no conflict, correct)

**Fix:**
Use strict less-than operators:
```python
if b.start_time < end and start < b.end_time:
    return True
```

---

## Bug #10: Double-Booking Race Condition (Hard)

**File(s):** `app/routers/bookings.py:42-116`

**Issue:**
The booking creation conflict check and insertion are not performed atomically, allowing concurrent booking requests to reserve the same slot.

**Code:**
```python
if _has_conflict(db, room.id, start, end):
    raise AppError(409, "ROOM_CONFLICT", "Room already booked for this interval")
# ... later ...
db.add(booking)
db.commit()
```

**Expected Behavior (Business Rule 3):**
"Two confirmed bookings for the same room overlap iff `existing.start < new.end AND new.start < existing.end` ... Must hold under concurrent creation"

**Why It's Wrong:**
Because there is no locking or serializable isolation between checking for a conflict and inserting the booking (especially with `_pricing_warmup` introducing a sleep), concurrent requests can both read "no conflict" and insert overlapping bookings.

**Fix:**
Wrap the conflict check and insertion in a lock or use database serialization:
```python
import threading
_booking_creation_lock = threading.Lock()

with _booking_creation_lock:
    if _has_conflict(db, room.id, start, end):
        raise AppError(409, "ROOM_CONFLICT", "Room already booked for this interval")
    # ...
    db.add(booking)
    db.commit()
```

---

## Bug #11: Booking Quota Race Condition (Hard)

**File(s):** `app/routers/bookings.py:55-103`

**Issue:**
The quota limit check is not thread-safe, letting a single user exceed their limit of 3 active bookings within a 24-hour window under concurrent booking requests.

**Code:**
```python
_check_quota(db, user.id, now, start)
# ... later ...
db.add(booking)
db.commit()
```

**Expected Behavior (Business Rule 4):**
"A user may have at most 3 confirmed bookings that start within any rolling 24-hour window ... Must hold under concurrent booking requests."

**Why It's Wrong:**
Concurrent requests can check the quota before any of them commit the new booking. They all see fewer than 3 bookings and proceed, exceeding the quota.

**Fix:**
Protect the quota check and reservation step with the same booking creation lock:
```python
with _booking_creation_lock:
    _check_quota(db, user.id, now, start)
    # ...
    db.add(booking)
    db.commit()
```

---

## Bug #12: Rate Limiter Race Condition (Hard)

**File(s):** `app/services/ratelimit.py:18-26`

**Issue:**
The rate limiting bucket is updated non-atomically, allowing concurrent requests to bypass the limits.

**Code:**
```python
def record_and_check(user_id: int) -> None:
    now = time.time()
    bucket = _buckets.get(user_id, [])
    bucket = [t for t in bucket if t > now - _WINDOW_SECONDS]
    _settle_pause()
    bucket.append(now)
    _buckets[user_id] = bucket
    if len(bucket) > _MAX_REQUESTS:
        raise AppError(429, "RATE_LIMITED", "Too many booking requests")
```

**Expected Behavior (Business Rule 5):**
"POST /bookings is limited to 20 requests per rolling 60 seconds per user (all requests count). Excess → 429 RATE_LIMITED. Must hold under concurrent requests."

**Why It's Wrong:**
Concurrent requests from the same user can execute checking code before previous requests write back their updated timestamp arrays, allowing excess requests to pass through.

**Fix:**
Protect checking and updates with a per-user thread lock:
```python
import threading
_buckets: dict[int, list[float]] = {}
_bucket_locks: dict[int, threading.Lock] = {}
_bucket_locks_lock = threading.Lock()

def record_and_check(user_id: int) -> None:
    with _bucket_locks_lock:
        if user_id not in _bucket_locks:
            _bucket_locks[user_id] = threading.Lock()
        user_lock = _bucket_locks[user_id]
    
    with user_lock:
        now = time.time()
        bucket = _buckets.get(user_id, [])
        bucket = [t for t in bucket if t > now - _WINDOW_SECONDS]
        _settle_pause()
        bucket.append(now)
        _buckets[user_id] = bucket
        if len(bucket) > _MAX_REQUESTS:
            raise AppError(429, "RATE_LIMITED", "Too many booking requests")
```

---

## Bug #13: Reference Code Not Protected as Unique (Hard)

**File(s):** `app/services/reference.py:17-21`

**Issue:**
Reference codes have an index but no UNIQUE constraint in the database. Additionally, the code that generates reference codes is not thread-safe.

**Code:**
```python
def next_reference_code() -> str:
    current = _counter["value"]
    _format_pause()
    _counter["value"] = current + 1
    return f"CW-{current:06d}"
```

**Expected Behavior (Business Rule 7):**
"Every booking's `reference_code` is unique, including under concurrent creation"

**Why It's Wrong:**
- No database constraint allows SQLite to accept duplicate reference codes.
- It is not thread-safe: multiple threads can read the same current count and generate identical codes.

**Fix:**
Add UNIQUE constraint to database and make reference code generation thread-safe:
```python
# In models.py:
reference_code = Column(String, nullable=False, unique=True, index=True)

# In reference.py:
import threading
_counter_lock = threading.Lock()

def next_reference_code() -> str:
    with _counter_lock:
        current = _counter["value"]
        _format_pause()
        _counter["value"] = current + 1
    return f"CW-{current:06d}"
```

---

## Bug #14: Refund 48h Boundary Off by One Hour (Medium)

**File(s):** `app/routers/bookings.py:200-202`

**Issue:**
The refund calculation has logic errors where it uses `>` instead of `>=` for the 48-hour threshold, causing the exact 48-hour boundary to fail.

**Code:**
```python
if notice_hours > 48:
    refund_percent = 100
```

**Expected Behavior (Business Rule 6):**
- notice ≥ 48 hours → 100% refund

**Why It's Wrong:**
`notice_hours > 48` should be `>=` to include exactly 48 hours notice.

**Fix:**
Use `>=` operator:
```python
if notice_hours >= 48:
    refund_percent = 100
```

---

## Bug #15: 0%-Refund Tier is Dead Code (Easy)

**File(s):** `app/routers/bookings.py:203-206`

**Issue:**
The refund calculation returns 50% for notice less than 24 hours, instead of 0% as required.

**Code:**
```python
elif notice >= timedelta(hours=24):
    refund_percent = 50
else:
    refund_percent = 50
```

**Expected Behavior (Business Rule 6):**
- notice < 24 hours → 0% refund

**Why It's Wrong:**
Both the `elif` and `else` branches return `50`, meaning a 0% refund tier is never reached.

**Fix:**
Set the `else` branch to return 0%:
```python
else:
    refund_percent = 0
```

---

## Bug #16: Refund Amount Computed Twice, Can Diverge (Medium)

**File(s):** `app/routers/bookings.py:208` + `app/services/refunds.py:15-17`

**Issue:**
The cancel response uses Python's banker's rounding `round()` while the database `RefundLog` uses float math and truncates with `int()`, leading to diverging calculations.

**Code:**
```python
refund_amount_cents = round(booking.price_cents * (refund_percent / 100.0))
```
and:
```python
amount_cents = int(refund_dollars * 100)
```

**Expected Behavior (Business Rule 6):**
"Refund amount rounds to the nearest cent, half-cents rounding up... the amount returned by the cancel response must equal the amount stored in the RefundLog"

**Why It's Wrong:**
Differences in rounding mechanisms cause the API response and database logs to store/return different values.

**Fix:**
Use standard half-up rounding consistently and compute the value only once:
```python
amount_cents = int(refund_dollars * 100 + 0.5)
```

---

## Bug #17: Cancel Race Condition / Duplicate RefundLog Entries (Hard)

**File(s):** `app/routers/bookings.py:184-214`

**Issue:**
The `cancel_booking` endpoint is not thread-safe. Multiple cancellations processed concurrently can bypass status checks and create multiple `RefundLog` entries.

**Code:**
```python
if booking.status == "cancelled":
    raise AppError(409, "ALREADY_CANCELLED", "Booking already cancelled")
# ...
log_refund(db, booking, refund_percent)
booking.status = "cancelled"
db.commit()
```

**Expected Behavior (Business Rule 6):**
"A cancelled booking has exactly one RefundLog entry, and the amount returned by the cancel response must equal the amount stored in the RefundLog"

**Why It's Wrong:**
Since the check and the status transition are non-atomic, multiple threads can execute the cancel process simultaneously, generating multiple refund logs.

**Fix:**
Ensure uniqueness in the database and synchronize status updates using a thread lock:
```python
booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, index=True, unique=True)
```

---

## Bug #18: Get Booking Allows Unauthorized Member Visibility (Medium)

**File(s):** `app/routers/bookings.py:156-163`

**Issue:**
The endpoint filters by room organization but fails to check if the requesting member owns the booking.

**Code:**
```python
booking = (
    db.query(Booking)
    .join(Room, Booking.room_id == Room.id)
    .filter(Booking.id == booking_id, Room.org_id == user.org_id)
    .first()
)
```

**Expected Behavior (Business Rule 10):**
"Members may read and cancel only their own bookings (another member's booking id → 404 BOOKING_NOT_FOUND). Admins may read and cancel any booking in their org."

**Why It's Wrong:**
A member can query bookings belonging to other members in the same organization, violating data isolation.

**Fix:**
Check that the requesting user is either an administrator or the owner:
```python
if user.role != "admin" and booking.user_id != user.id:
    raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")
```

---

## Bug #19: Get Booking Returns Wrong DateTime Field (Easy)

**File(s):** `app/routers/bookings.py:165-166`

**Issue:**
The response payload replaces the booking's actual `start_time` with its `created_at` timestamp.

**Code:**
```python
response = serialize_booking(booking)
response["start_time"] = iso_utc(booking.created_at)
```

**Why It's Wrong:**
The API client receives the booking creation time instead of the reserved slot time.

**Fix:**
Remove the incorrect assignment (the serialization function already parses `start_time` correctly):
```python
response = serialize_booking(booking)
```

---

## Bug #20: Cross-Org Data Leak in CSV Export (Medium)

**File(s):** `app/services/export.py:22-52`

**Issue:**
The CSV export helper queries database entries directly by `room_id` without confirming organization ownership.

**Code:**
```python
if include_all:
    if room_id is not None:
        rows = fetch_bookings_raw(db, room_id)
```

**Expected Behavior (Business Rule 9):**
"A user (including admins) may only ever read or act on data belonging to their own organization, on every code path. Cross-org resource IDs behave as non-existent (→ 404)."

**Why It's Wrong:**
An administrator can request reports containing private booking records of rooms owned by other organizations.

**Fix:**
Check organizational tenancy or restrict the query:
```python
if room_id is not None:
    room = db.query(Room).filter(Room.id == room_id, Room.org_id == admin.org_id).first()
    if room is None:
        raise AppError(404, "ROOM_NOT_FOUND", "Room not found")
```

---

## Bug #21: Pagination Sort Order Wrong (Easy)

**File(s):** `app/routers/bookings.py:137`

**Issue:**
Bookings returned by the paginated list endpoint are sorted in descending order instead of ascending.

**Code:**
```python
.order_by(Booking.start_time.desc(), Booking.id.asc())
```

**Expected Behavior (Business Rule 11):**
"Items are the caller's own bookings sorted ascending by start_time (ties by ascending id)"

**Why It's Wrong:**
Returns bookings in reverse chronological order, violating pagination order specifications.

**Fix:**
Change order direction to ascending:
```python
.order_by(Booking.start_time.asc(), Booking.id.asc())
```

---

## Bug #22: Pagination Offset Formula Off by One Page (Easy)

**File(s):** `app/routers/bookings.py:138`

**Issue:**
The offset is calculated using `page * limit` which skips the entire first page of results.

**Code:**
```python
.offset(page * limit)
```

**Expected Behavior (Business Rule 11):**
"Sequential pages never skip or repeat items." Page 1 should return items from index 0.

**Why It's Wrong:**
Page 1 with limit 10 returns items starting from index 10, skipping the first 10 results.

**Fix:**
Use correct offset calculation:
```python
.offset((page - 1) * limit)
```

---

## Bug #23: Pagination limit Query Param Ignored (Easy)

**File(s):** `app/routers/bookings.py:139`

**Issue:**
The database query enforces a hardcoded limit of 10 instead of using the caller's requested `limit`.

**Code:**
```python
.limit(10)
```

**Expected Behavior (Business Rule 11):**
The endpoint should respect the caller-provided `limit` parameter.

**Why It's Wrong:**
Requesters receive a fixed page size of 10 regardless of what limit value they provide.

**Fix:**
Replace hardcoded limit with parameter:
```python
.limit(limit)
```

---

## Bug #24: Usage-Report Cache Not Invalidated on Booking Creation (Medium)

**File(s):** `app/routers/bookings.py:105-124`

**Issue:**
Creating a booking invalidates availability cache but fails to invalidate the usage-report cache, causing the usage report to serve stale, cached data.

**Code:**
```python
cache.invalidate_availability(...)
```

**Expected Behavior (Business Rule 12):**
"GET /admin/usage-report ... serves cached results ... but must reflect the current state immediately if a booking is created or cancelled."

**Why It's Wrong:**
Because `invalidate_report` is not called, the usage-report cache continues to return outdated stats until it naturally expires.

**Fix:**
Invalidate the report cache on booking creation:
```python
cache.invalidate_availability(...)
cache.invalidate_report(room.org_id)
```

---

## Bug #25: Availability Cache Not Invalidated on Cancellation (Medium)

**File(s):** `app/routers/bookings.py:178-225`

**Issue:**
Cancelling a booking invalidates the usage-report cache but fails to invalidate the availability cache, leaving the cancelled slot marked as occupied in the cache.

**Code:**
```python
cache.invalidate_report(room.org_id)
```

**Expected Behavior (Business Rule 13):**
"GET /rooms/{id}/availability ... serves cached results ... must reflect the current state immediately if a booking is created or cancelled."

**Why It's Wrong:**
The availability cache remains stale, indicating the room is still booked for the cancelled time slot.

**Fix:**
Invalidate the availability cache when a booking is cancelled:
```python
cache.invalidate_report(room.org_id)
cache.invalidate_availability(booking.room_id, booking.start_time.date().isoformat())
```

---

## Bug #26: Room Stats Not Thread-Safe and Not Restart-Durable (Hard)

**File(s):** `app/services/stats.py:15-26`

**Issue:**
The stats tracking updates process-local memory arrays non-atomically, causing lost updates under concurrent updates.

**Code:**
```python
def record_create(room_id: int, price_cents: int) -> None:
    current = _stats.get(room_id, {"count": 0, "revenue": 0})
    count, revenue = current["count"], current["revenue"]
    _aggregate_pause()
    _stats[room_id] = {"count": count + 1, "revenue": revenue + price_cents}
```

**Expected Behavior (Business Rule 14):**
"Room stats. GET /rooms/{id}/stats returns the room's current count of confirmed bookings and their summed price_cents...Always equals the values derivable from the bookings themselves"

**Why It's Wrong:**
Lost updates occur when concurrent booking requests read the same initial counts, and restarting the service clears all memory stats.

**Fix:**
Ensure thread safety with locks, and ideally compute/load dynamically from the database:
```python
import threading
_stats_lock = threading.Lock()

def record_create(room_id: int, price_cents: int) -> None:
    with _stats_lock:
        current = _stats.get(room_id, {"count": 0, "revenue": 0})
        # ... update dict atomically ...
```

---

## Bug #27: Notification Lock-Ordering Deadlock (Hard)

**File(s):** `app/services/notifications.py:24-35`

**Issue:**
Nested lock acquisition order is inverted in create vs cancel, leading to lock deadlocks under concurrent bookings and cancellations.

**Code:**
```python
# notify_created acquires: email lock -> audit lock
# notify_cancelled acquires: audit lock -> email lock
```

**Expected Behavior (Business Rule 16):**
"No combination of concurrent valid requests may hang the service."

**Why It's Wrong:**
If a creation and cancellation execute simultaneously, they can dead lock the application process permanently.

**Fix:**
Acquire both locks in the same sequence:
```python
def notify_cancelled(booking) -> None:
    with _email_lock:
        with _audit_lock:
            # ...
```

---

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
