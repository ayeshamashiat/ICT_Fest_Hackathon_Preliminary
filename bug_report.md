# CoWork API Complete Bug Report

This document combines the original bug report and the subtle bugs report.

---

# CoWork API Bug Report

## Bug #1: Access Token Expiration Time Incorrect (HARD)

**File(s):** `app/auth.py`, line 50

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

## Bug #2: Duplicate Username Registration Returns Existing User Instead of Error (EASY)

**File(s):** `app/routers/auth.py`, lines 35-42

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

## Bug #3: Booking Overlap Detection Uses Incorrect Comparison Operators (HARD)

**File(s):** `app/routers/bookings.py`, line 90

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

## Bug #4: Booking Start Time Grace Window When None Allowed (MEDIUM)

**File(s):** `app/routers/bookings.py`, line 84

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

## Bug #5: Pagination Offset Calculation Wrong (MEDIUM)

**File(s):** `app/routers/bookings.py`, line 127

**Issue:**
The offset calculation uses `page * limit` instead of `(page - 1) * limit`, causing the first page to skip items.

**Code:**
```python
.offset(page * limit)
.limit(10)
```

**Expected Behavior (Business Rule 11):**
"Pagination & ordering. GET /bookings takes page (default 1) and limit (default 10, max 100). Items are the caller's own bookings sorted ascending by start_time (ties by ascending id). Sequential pages never skip or repeat items."

**Why It's Wrong:**
- Page 1 with limit 10: offset = 1 * 10 = 10 (skips first 10 items)
- Page 2 with limit 10: offset = 2 * 10 = 20 (skips first 20 items)
- Should be: Page 1 offset = 0, Page 2 offset = 10

**Fix:**
Correct the offset calculation:
```python
.offset((page - 1) * limit)
.limit(limit)  # Also fix the hardcoded limit value
```

---

## Bug #6: Pagination Limit Hardcoded (MEDIUM)

**File(s):** `app/routers/bookings.py`, line 128

**Issue:**
The limit is hardcoded to 10 instead of using the `limit` parameter from the query.

**Code:**
```python
.limit(10)
```

**Expected Behavior (Business Rule 11):**
The endpoint should respect the caller-provided `limit` parameter (default 10, max 100).

**Why It's Wrong:**
Users cannot request a different page size; they're stuck with 10 items per page regardless of what they request.

**Fix:**
Use the `limit` parameter:
```python
.limit(limit)
```

---

## Bug #7: Pagination Sort Order Wrong (MEDIUM)

**File(s):** `app/routers/bookings.py`, line 126

**Issue:**
Bookings are sorted in descending order by `start_time` when the rule requires ascending order.

**Code:**
```python
.order_by(Booking.start_time.desc(), Booking.id.asc())
```

**Expected Behavior (Business Rule 11):**
"Items are the caller's own bookings sorted ascending by start_time (ties by ascending id)"

**Why It's Wrong:**
Newest bookings appear first instead of earliest bookings, breaking pagination order expectations.

**Fix:**
Change to ascending order:
```python
.order_by(Booking.start_time.asc(), Booking.id.asc())
```

---

## Bug #8: Get Booking Returns Wrong DateTime Field (MEDIUM)

**File(s):** `app/routers/bookings.py`, line 152

**Issue:**
The `start_time` field in the response is set to `booking.created_at` instead of `booking.start_time`.

**Code:**
```python
response = serialize_booking(booking)
response["start_time"] = iso_utc(booking.created_at)
```

**Why It's Wrong:**
The response overwrites the correctly serialized `start_time` with `created_at`, giving clients the wrong booking time.

**Fix:**
Remove the incorrect line or use the correct field:
```python
# Either remove the line entirely (serialize_booking already sets it correctly)
# Or if you need to modify it, use:
response["start_time"] = iso_utc(booking.start_time)
```

---

## Bug #9: Get Booking Doesn't Enforce Member Visibility (HARD)

**File(s):** `app/routers/bookings.py`, line 145-160

**Issue:**
The endpoint filters by `Room.org_id == user.org_id` but doesn't check if a member is viewing their own booking. Members can read any booking in their organization.

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
A member can query another member's booking ID and retrieve it, violating the visibility rule.

**Fix:**
Add check for member role:
```python
booking = (
    db.query(Booking)
    .join(Room, Booking.room_id == Room.id)
    .filter(Booking.id == booking_id, Room.org_id == user.org_id)
    .first()
)
if booking is None:
    raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")

# Add member visibility check
if user.role != "admin" and booking.user_id != user.id:
    raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")
```

---

## Bug #10: Refund Percentage Logic Incorrect (HARD)

**File(s):** `app/routers/bookings.py`, lines 204-209

**Issue:**
The refund calculation has multiple logic errors:
1. Uses `>` instead of `>=` for the 48-hour threshold
2. Mixes int and timedelta comparisons
3. Returns 50% for notice < 24 hours instead of 0%

**Code:**
```python
if notice_hours > 48:
    refund_percent = 100
elif notice >= timedelta(hours=24):
    refund_percent = 50
else:
    refund_percent = 50
```

**Expected Behavior (Business Rule 6):**
```
- notice ≥ 48 hours → 100% refund
- 24 hours ≤ notice < 48 hours → 50% refund
- notice < 24 hours → 0% refund
```

**Why It's Wrong:**
1. Line 204: `notice_hours > 48` should be `>=` (≥48 means include exactly 48)
2. Lines 206 & 209: Both return 50%, but the else case should return 0%
3. Line 206: Comparing `notice` (timedelta) directly instead of using converted `notice_hours`

**Fix:**
```python
if notice_hours >= 48:
    refund_percent = 100
elif notice_hours >= 24:
    refund_percent = 50
else:
    refund_percent = 0
```

---

## Bug #11: Refund Amount Rounding Wrong (MEDIUM)

**File(s):** `app/services/refunds.py`, line 14

**Issue:**
The refund amount uses `int()` which truncates instead of rounding, violating the rounding rule.

**Code:**
```python
amount_cents = int(refund_dollars * 100)
```

**Expected Behavior (Business Rule 6):**
"Refund amount rounds to the nearest cent, half-cents rounding up"

**Why It's Wrong:**
- For a refund of $10.125 (50% of $20.25):
  - With `int()`: `10.125 * 100 = 1012.5 → 1012` cents ($10.12) - incorrect
  - With `round()`: `1012.5 → 1012` cents (banker's rounding, not half-up)
  - Need proper half-up rounding: `1013` cents ($10.13)

**Fix:**
Use proper rounding (half up):
```python
from decimal import Decimal, ROUND_HALF_UP
amount_cents = int(Decimal(str(refund_dollars * 100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
```

Or simpler approach:
```python
amount_cents = int(refund_dollars * 100 + 0.5)  # Standard half-up rounding
```

---

## Bug #12: DateTime UTC Conversion Incorrect (HARD)

**File(s):** `app/timeutils.py`, line 10

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

## Summary by Difficulty

### Easy (3 points)
- Bug #2: Duplicate username registration

### Medium (5 points each)
- Bug #4: Booking grace window
- Bug #5: Pagination offset
- Bug #6: Pagination hardcoded limit
- Bug #7: Pagination sort order
- Bug #8: Wrong datetime field
- Bug #11: Refund rounding

### Hard (10 points each)
- Bug #1: Access token expiration
- Bug #3: Overlap detection operators
- Bug #9: Member booking visibility
- Bug #10: Refund percentage logic
- Bug #12: DateTime UTC conversion

**Total: 1 Easy (3 pts) + 6 Medium (30 pts) + 5 Hard (50 pts) = 83 points**

## More Subtle Bugs:
## Bug #13: Token Revocation Uses Wrong Field (HARD)

**File(s):** `app/auth.py`, lines 45 and 100

**Issue:**
The revocation system stores tokens by `jti` but checks by `sub`, causing the revocation to never work.

**Code - Adding to revoked set (line 45):**
```python
def revoke_access_token(payload: dict) -> None:
    _revoked_tokens.add(payload["jti"])  # Stores JTI
```

**Code - Checking revocation (line 100):**
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

## Bug #14: Refresh Token Not Single-Use (HARD)

**File(s):** `app/routers/auth.py`, lines 76-87

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
The endpoint generates new tokens but never invalidates the old refresh token. An attacker who intercepts a refresh token can:
1. Use it to get new tokens
2. Use the same refresh token again to get another set of tokens
3. Repeat indefinitely, potentially for account takeover if the original token is compromised

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

Also need to update `get_token_payload` to check refresh token revocation if appropriate.

---

## Bug #15: Duration Minimum Not Validated (EASY)

**File(s):** `app/routers/bookings.py`, lines 92-96

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
- If `end_time == start_time`: `duration_hours = 0`, which equals `int(0)`, so the whole-number check passes
- If `end_time < start_time`: `duration_hours < 0`, same issue
- Only max is checked, not min

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

## Bug #16: Refund Rounding Uses Banker's Rounding (MEDIUM)

**File(s):** `app/routers/bookings.py`, line 206

**Issue:**
Uses Python's `round()` function which uses banker's rounding (round half to even), not the required half-up rounding.

**Code:**
```python
refund_amount_cents = round(booking.price_cents * (refund_percent / 100.0))
```

**Expected Behavior (Business Rule 6):**
"Refund amount rounds to the nearest cent, half-cents rounding up"

**Why It's Wrong:**
Python's `round()` uses banker's rounding:
- `round(0.5)` → 0 (rounds to even)
- `round(1.5)` → 2 (rounds to even)
- `round(2.5)` → 2 (rounds to even)

For example, 50% of $10.25 (1025 cents):
- Expected: `1025 * 0.5 = 512.5` → round up to `513` cents
- With `round()`: `round(512.5)` → `512` cents (banker's rounding)

**Fix:**
Use proper half-up rounding:
```python
refund_amount_cents = int(booking.price_cents * (refund_percent / 100.0) + 0.5)
```

Note: The fix was already applied to `app/services/refunds.py` but this line in `cancel_booking` still uses the wrong rounding.

---

## Bug #17: Reference Code Not Protected as Unique (HARD)

**File(s):** `app/models.py`, line 51 and `app/services/reference.py`, line 17

**Issue:**
Reference codes have an index but no UNIQUE constraint. Additionally, the code that generates reference codes is not thread-safe.

**Database Model (line 51):**
```python
reference_code = Column(String, nullable=False, index=True)
```

**Reference Code Generator (line 17):**
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
1. **No database constraint**: Even if the code is correct, SQLite doesn't prevent duplicate reference codes
2. **Not thread-safe**: Race condition between threads:
   - Thread A: reads current = 1000
   - Thread B: reads current = 1000
   - Thread A: increments to 1001, returns "CW-001000"
   - Thread B: increments to 1001, returns "CW-001000"
   - Both bookings get the same reference code!

**Fix:**
Add UNIQUE constraint to database and make reference code generation thread-safe:

```python
# In models.py:
reference_code = Column(String, nullable=False, unique=True, index=True)

# In reference.py:
import threading

_counter = {"value": 1000}
_counter_lock = threading.Lock()

def next_reference_code() -> str:
    with _counter_lock:
        current = _counter["value"]
        _format_pause()
        _counter["value"] = current + 1
    return f"CW-{current:06d}"
```

---

## Bug #18: Stats Not Thread-Safe (HARD)

**File(s):** `app/services/stats.py`, lines 19-23 and 26-30

**Issue:**
The stats tracking uses non-atomic read-modify-write operations, causing lost updates under concurrency.

**Code:**
```python
def record_create(room_id: int, price_cents: int) -> None:
    current = _stats.get(room_id, {"count": 0, "revenue": 0})
    count, revenue = current["count"], current["revenue"]
    _aggregate_pause()
    _stats[room_id] = {"count": count + 1, "revenue": revenue + price_cents}
```

**Expected Behavior (Business Rule 14):**
"Room stats. `GET /rooms/{id}/stats` returns the room's current count of `confirmed` bookings and their summed `price_cents`...Always equals the values derivable from the bookings themselves"

**Why It's Wrong:**
Classic race condition between concurrent bookings:
- Thread A: reads count = 5
- Thread B: reads count = 5
- Thread A: sleeps 0.1s
- Thread B: sleeps 0.1s  
- Thread A: writes count = 6
- Thread B: writes count = 6 (overwrites A's update)
- Final count should be 7, but it's 6 (lost update)

**Fix:**
Use thread-safe operations:
```python
import threading

_stats: dict[int, dict] = {}
_stats_lock = threading.Lock()

def record_create(room_id: int, price_cents: int) -> None:
    with _stats_lock:
        current = _stats.get(room_id, {"count": 0, "revenue": 0})
        count, revenue = current["count"], current["revenue"]
        _aggregate_pause()
        _stats[room_id] = {"count": count + 1, "revenue": revenue + price_cents}

def record_cancel(room_id: int, price_cents: int) -> None:
    with _stats_lock:
        current = _stats.get(room_id, {"count": 0, "revenue": 0})
        count, revenue = current["count"], current["revenue"]
        _aggregate_pause()
        _stats[room_id] = {"count": max(0, count - 1), "revenue": revenue - price_cents}
```

---

## Bug #19: Rate Limiter Not Thread-Safe (HARD)

**File(s):** `app/services/ratelimit.py`, lines 20-24

**Issue:**
The rate limiting bucket is updated non-atomically, allowing requests to slip through the limit under concurrency.

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
"`POST /bookings` is limited to 20 requests per rolling 60 seconds per user (all requests count). Excess → 429 RATE_LIMITED. Must hold under concurrent requests."

**Why It's Wrong:**
Race condition allows exceeding the limit:
- Requests 1-20 come in from same user, all see count < 20
- All 20 threads pass the check
- All 20 threads append to bucket
- Bucket now has 21+ items, but no request was rejected
- Result: 21 requests allowed instead of 20

**Fix:**
Make the check atomic:
```python
import threading

_buckets: dict[int, list[float]] = {}
_bucket_locks: dict[int, threading.Lock] = {}
_bucket_locks_lock = threading.Lock()

def record_and_check(user_id: int) -> None:
    # Get or create lock for this user
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

## Bug #20: RefundLog Allows Duplicate Cancellations (MEDIUM)

**File(s):** `app/models.py`, line 63 and `app/services/refunds.py`

**Issue:**
RefundLog table has no uniqueness constraint on `booking_id`, allowing multiple refund entries for the same booking.

**Database Model (line 63):**
```python
booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, index=True)
```

**Expected Behavior (Business Rule 6):**
"A cancelled booking has exactly one RefundLog entry, and the amount returned by the cancel response must equal the amount stored in the RefundLog"

**Why It's Wrong:**
- No UNIQUE constraint on `booking_id`
- If cancel endpoint is called twice on the same booking (race condition between first and second cancel check), two RefundLog entries could be created
- "Exactly one RefundLog entry" requirement is violated

**Fix:**
Add UNIQUE constraint:
```python
# In models.py:
booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, index=True, unique=True)
```

---

## Bug #21: Multi-Tenancy Data Leak in Admin Export (HARD)

**File(s):** `app/routers/admin.py`, lines 65-74 and `app/services/export.py`, lines 48-50

**Issue:**
The admin export endpoint `/admin/export` fails to validate whether the optional query parameter `room_id` belongs to the requesting administrator's organization. This allows an administrator to bypass tenant isolation and export all booking data from rooms belonging to other organizations.

**Expected Behavior (Business Rule 9):**
"A user (including admins) may only ever read or act on data belonging to their own organization, on every code path. Cross-org resource IDs behave as non-existent (→ 404)."

**Why It's Wrong:**
- If an admin passes `room_id=X` where room `X` belongs to another tenant organization, and `include_all=True`, `generate_export` calls `fetch_bookings_raw(db, room_id)` which retrieves all bookings for room `X` directly, leaking sensitive cross-tenant data.
- It fails to raise `404 ROOM_NOT_FOUND` as mandated by Business Rule 9.

**Fix:**
Validate that the `room_id` belongs to the admin's organization:
```python
    if room_id is not None:
        room = db.query(Room).filter(Room.id == room_id, Room.org_id == admin.org_id).first()
        if room is None:
            raise AppError(404, "ROOM_NOT_FOUND", "Room not found")
```

---

## Summary by Difficulty

### Easy (3 points)
- Subtle Bug #3: Duration minimum not validated

### Medium (5 points each)
- Subtle Bug #4: Refund rounding uses banker's rounding
- Subtle Bug #8: RefundLog allows duplicates

### Hard (10 points each)
- Subtle Bug #1: Token revocation uses wrong field
- Subtle Bug #2: Refresh token not single-use
- Subtle Bug #5: Reference code not unique + race condition
- Subtle Bug #6: Stats not thread-safe
- Subtle Bug #7: Rate limiter not thread-safe
- Subtle Bug #9: Multi-Tenancy Data Leak in Admin Export

**Total: 1 Easy (3 pts) + 2 Medium (10 pts) + 6 Hard (60 pts) = 73 points**

These are production-critical bugs related to security, concurrency, and data integrity.
