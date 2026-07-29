# Admin User Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate existing JSON users once into a runtime SQLite database and provide secure administrator CRUD, enable/disable, role assignment, and password reset from the unified frontend.

**Architecture:** `auth/user_store.py` owns SQLite schema, one-time migration, validation, and transactional mutations. `auth/auth.py` keeps JWT/password orchestration and delegates persistence to the store; unified backend routes expose admin-only operations. A lazy-loaded React section uses a focused API client and the existing navigation/permission system.

**Tech Stack:** Python 3.11 stdlib SQLite, FastAPI/Pydantic, pytest, React 19, TypeScript, existing shadcn/Radix components

---

### Task 1: SQLite user store and one-time migration

**Files:**
- Create: `auth/user_store.py`
- Create: `unified_backend/tests/test_user_store.py`

- [ ] **Step 1: Write failing migration and mutation tests**

Create tests using `tmp_path` and explicit store paths that require:

```python
store = UserStore(database_path=db_path, legacy_json_path=json_path)
assert [user["employee_id"] for user in store.list_users()] == ["10001"]
json_path.write_text('[{"employee_id":"changed"}]')
assert [user["employee_id"] for user in store.list_users()] == ["10001"]
```

Also require create, update, enable/disable, reset-hash/version, delete, duplicate
rejection, current-user protection, and last-enabled-admin protection.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest unified_backend/tests/test_user_store.py -q
```

Expected: import failure because `auth.user_store` does not exist.

- [ ] **Step 3: Implement the store**

Implement:

```python
class UserStore:
    def initialize(self) -> None: ...
    def list_users(self) -> list[dict[str, Any]]: ...
    def find_enabled_user(self, identifier: str) -> dict[str, Any] | None: ...
    def create_user(self, *, employee_id: str, name: str, role: str,
                    department: str | None, password_hash: str) -> dict[str, Any]: ...
    def update_user(self, employee_id: str, *, actor_employee_id: str,
                    name: str, role: str, department: str | None,
                    enabled: bool) -> dict[str, Any]: ...
    def update_password_hash(self, employee_id: str, password_hash: str) -> dict[str, Any]: ...
    def delete_user(self, employee_id: str, *, actor_employee_id: str) -> None: ...
```

Use `BEGIN IMMEDIATE`, WAL, busy timeout, unique employee/name constraints,
metadata key `legacy_json_imported`, and default paths
`runtime/auth/auth_users.db` plus `auth/auth_users.json`.

- [ ] **Step 4: Run tests and verify GREEN**

```bash
python -m pytest unified_backend/tests/test_user_store.py -q
```

Expected: all store tests pass and no database appears in Git status.

### Task 2: Authentication integration and token versioning

**Files:**
- Modify: `auth/auth.py`
- Create: `unified_backend/tests/test_auth_database.py`

- [ ] **Step 1: Write failing auth tests**

Set `AUTH_USERS_DB` and `AUTH_USERS_FILE` to temporary paths, then assert:

```python
user = verify_login("10001", "initial-password")
token = create_token(user)
assert get_current_user_from_request(request_with_cookie(token))["employee_id"] == "10001"
change_own_password("10001", "initial-password", "new-password")
with pytest.raises(AuthError):
    get_current_user_from_request(request_with_cookie(token))
```

Also prove migrated users without `password_hash` keep
`AUTH_DEFAULT_PASSWORD` behavior.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest unified_backend/tests/test_auth_database.py -q
```

Expected: old JSON implementation does not invalidate the token.

- [ ] **Step 3: Delegate persistence to UserStore**

Replace direct JSON reads/writes in `auth/auth.py` with a cached store created
from environment paths. Include `auth_version` in public user/token data,
compare token version to the current database record, and increment version on
password change. Preserve public response fields and compatibility with version
1 tokens.

- [ ] **Step 4: Run auth and store tests**

```bash
python -m pytest unified_backend/tests/test_user_store.py unified_backend/tests/test_auth_database.py -q
```

Expected: all tests pass.

### Task 3: Admin-only unified backend API

**Files:**
- Modify: `unified_backend/app.py`
- Create: `unified_backend/tests/test_admin_users_api.py`

- [ ] **Step 1: Write failing route tests**

Build the FastAPI app against temporary auth paths and assert:

```text
GET /api/admin/users                         admin=200 viewer=403
POST /api/admin/users                        admin=200
PATCH /api/admin/users/{employee_id}         admin=200
POST /api/admin/users/{id}/reset-password    admin=200
DELETE /api/admin/users/{employee_id}        admin=200
```

Assert response bodies never contain `password` or `password_hash`, and safety
violations return 409.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest unified_backend/tests/test_admin_users_api.py -q
```

Expected: 404 for the missing admin routes.

- [ ] **Step 3: Add Pydantic request models and routes**

Add create/update/reset request models with enum-like validation and routes
using `Depends(require_admin)`. Map input errors to 400, duplicate/protection
conflicts to 409, and missing users to 404. Hash passwords in `auth/auth.py`,
not in the route body.

- [ ] **Step 4: Run unified backend tests**

```bash
python -m pytest unified_backend/tests -q
```

Expected: all existing and new tests pass.

### Task 4: Administrator frontend

**Files:**
- Create: `unified_frontend/src/lib/admin-users.ts`
- Create: `unified_frontend/src/sections/UserManagementSection.tsx`
- Modify: `unified_frontend/src/auth/permissions.ts`
- Modify: `unified_frontend/src/auth/permissions.test.ts`
- Modify: `unified_frontend/src/lib/nav.ts`
- Modify: `unified_frontend/src/App.tsx`

- [ ] **Step 1: Add the permission regression case**

Extend `permissions.test.ts` with assertions that `user-management` is
accessible to admins and rejected for viewers. Since the repository does not
currently install a TypeScript test runner, validate the new union and calls
first with:

```bash
npm run build
```

Expected before implementation: TypeScript fails because
`user-management` is not a `PageId`.

- [ ] **Step 2: Add typed API client**

Implement list/create/update/reset/delete requests in `admin-users.ts`. Send
password only in create/reset bodies and convert non-2xx JSON details into
displayable errors.

- [ ] **Step 3: Build the page**

Implement a lazy-loaded `UserManagementSection` with:

- responsive user table/cards;
- add/edit dialogs;
- role/department linkage;
- enable/disable action;
- reset-password dialog;
- permanent-delete confirmation;
- current-account UI protection;
- refreshed list and toast feedback after mutations.

- [ ] **Step 4: Wire navigation and permissions**

Add `user-management` to `PageId`, admin navigation, and `App.tsx`. Keep it out
of all department permission lists so viewers cannot navigate to it.

- [ ] **Step 5: Verify frontend**

```bash
cd unified_frontend
npm run lint
npm run build
```

Expected: zero lint errors and successful production build; pre-existing
warnings are reported separately.

### Task 5: Migration/startup documentation and final verification

**Files:**
- Modify: `run_guide.txt`
- Modify: `unified_backend/.env.example`

- [ ] **Step 1: Document one-time migration and backup**

Document the default database path, one-time import, no manual user editing,
backup of `runtime/auth/auth_users.db`, and admin UI operations. Add optional
`AUTH_USERS_DB` to `.env.example`.

- [ ] **Step 2: Run complete verification**

```bash
python -m pytest unified_backend/tests -q
python -m compileall -q auth unified_backend
cd unified_frontend && npm run lint && npm run build
git diff --check
```

- [ ] **Step 3: Review and publish**

Review status/diff and sensitive data, commit only task files, update only V4,
push only the V4 tag, and verify local HEAD, local V4, and remote V4 share one
SHA.
