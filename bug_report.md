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
