# Telegram PC Controller Bot - Security Model

## Security Overview

The project includes a layered authentication and authorization model for Telegram users:
- password-based authentication
- optional TOTP-based 2FA
- brute-force protection with exponential lockouts
- one-time password recovery tokens
- admin-only management commands
- structured audit logging

## Установка

```bash
pip install -r requirements.txt
```

## Функции безопасности

### 1. Password Hashing
- Passwords are stored with `bcrypt` (cost factor 12)
- Salt is generated automatically by bcrypt for every password
- Legacy SHA-256 hashes are still readable for migration and are transparently re-hashed after successful login
- Password policy validation:
  - minimum length 8
  - at least 3 character groups (lower/upper/digit/symbol)

### 2. Two-Factor Authentication (2FA)
- TOTP (RFC 6238) using `pyotp`
- QR setup URI support and manual secret fallback
- Input validation for code format (digits and expected length)
- Clock drift tolerance (`valid_window=1`)
- One-time backup codes are generated and stored as hashes

**Команды:**
- `/2fa_setup` - Настроить 2FA
- `/2fa_verify CODE` - Подтвердить и включить 2FA
- `/2fa_disable CODE` - Отключить 2FA
- `/2fa CODE` - Вход с 2FA кодом

### 3. Login and Brute-Force Protection
- Account lock starts after 5 failed attempts
- Exponential backoff lockout:
  - 5 failures: 5 minutes
  - 6 failures: 10 minutes
  - 7 failures: 20 minutes
  - up to 1 hour cap
- Failed counters are reset only on successful authentication
- Password + 2FA flow uses pending challenge state to prevent direct `/2fa` bypass

**Команды:**
- `/login PASSWORD` - Войти с паролем

### 4. Password Recovery
- Cryptographically secure token generation (`secrets.token_urlsafe`)
- Recovery tokens are stored as SHA-256 digests (not plaintext)
- Token expiration: 1 hour
- Token is single-use and invalidated after successful reset
- Recovery request rate limit: 3 requests/hour per user

**Команды:**
- `/recover` - Получить токен восстановления
- `/reset_password TOKEN NEW_PASSWORD` - Сбросить пароль

### 5. Admin Controls
- Admin-only commands are protected by `ADMIN_IDS`
- User moderation: approve/reject/ban/unban
- 2FA reset and password set commands
- Confirmation callbacks for destructive actions
- Paginated `/users` and `/logs` output

**Команды (только для админов):**
- `/admin` - Панель администратора
- `/users` - Список всех пользователей
- `/user USER_ID` - Информация о пользователе
- `/approve USER_ID` - Одобрить пользователя
- `/reject USER_ID` - Отклонить пользователя
- `/ban USER_ID` - Забанить пользователя
- `/unban USER_ID` - Разбанить пользователя
- `/reset_2fa USER_ID` - Сбросить 2FA
- `/set_password USER_ID PASSWORD` - Установить пароль
- `/logs [USER_ID]` - Просмотр логов

## Security Dependencies

```
bcrypt==4.1.2
pyotp==2.9.0
qrcode[pil]==7.4.2
```

## Database Fields

Добавлены новые поля в модель пользователя:

```python
password_hash: str                  # bcrypt hash
is_2fa_enabled: bool
two_factor_secret: str
two_factor_backup_codes: str        # JSON of hashed backup codes
failed_login_attempts: int
locked_until: datetime
recovery_token: str                 # SHA-256 digest of raw token
recovery_token_expires: datetime
```

## Notes

- Keep bot and dependencies updated.
- Use long, random admin passwords.
- Restrict host access where the bot runs.
- Rotate logs and monitor suspicious auth events.
