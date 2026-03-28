# Changelog

## Unreleased

### Security
- Switched password hashing to bcrypt (cost 12) with secure migration path from legacy SHA-256 hashes.
- Added password strength validation (min length + character class requirements).
- Added 2FA backup code support (stored as hashes, one-time consumption).
- Added strict 2FA code format validation and clock-drift tolerant verification.
- Implemented login pending-2FA state to enforce password-first second-factor flow.
- Upgraded brute-force protection to exponential lockout (with cap).
- Hardened password recovery tokens:
  - digest storage (`sha256$...`) instead of plaintext
  - 1 hour expiration
  - single-use invalidation
  - rate limit (3 requests/hour)

### Admin / UX
- Wired admin router into main dispatcher.
- Added command-list entries for security/admin commands in bot menu.
- Refactored admin handlers:
  - centralized admin checks and input validation
  - paginated `/users` and `/logs`
  - confirmation callbacks for `/reject`, `/ban`, `/reset_2fa`
  - self-ban/self-reject protection
- Added callbacks for admin quick-log and settings buttons.

### Database / Reliability
- Added indexes for high-frequency security queries.
- Added compatibility migration in `init_db` for existing SQLite DBs (including new `two_factor_backup_codes` column).
- Reused SQLAlchemy engine/sessionmaker across repository instances for better performance.
- Fixed `update_user_password` to return boolean consistently.

### Testing / Tooling
- Added `pytest.ini`.
- Added focused security unit tests in `tests/test_security.py`.
- Added quality/testing dependencies to `requirements.txt`.

### Docs
- Updated `SECURITY.md` with current security model and operational notes.
- Updated `README.md` security/admin command sections and test commands.
