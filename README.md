# Survey Infinity

Anonymous but completion-trackable employee survey built with FastAPI and PostgreSQL.

## Features
- Anonymous survey links per employee using hashed invite tokens
- Completion tracking via one-way hashed submission UUIDs (no answers tied to employee IDs)
- Admin login with bcrypt password hashing and session cookies
- Employee + department head management with bulk CSV import
- Invite/reminder emailing using saved SMTP settings (aiosmtplib)
- Aggregate dashboard (per department head and per-question averages)
- Modern minimal UI with Tailwind via CDN

## Tech stack
- FastAPI + Jinja2 templates
- SQLAlchemy 2.0 (async) + Alembic migrations
- PostgreSQL
- Docker + docker-compose

## Getting started
1. Copy environment file:
   ```bash
   cp .env.example .env
   ```
2. Adjust values as needed (admin credentials, secret key, database URLs, SMTP defaults).
3. Start the stack:
   ```bash
   docker-compose up --build
   ```
4. The app runs at http://localhost:8000. First admin user and SMTP row are seeded from env vars if none exist; sample department heads are also seeded.

## Database migrations
To run Alembic migrations (inside the app container):
```bash
alembic upgrade head
```

## SMTP
Configure SMTP under **Admin → SMTP**. Sending invites/reminders regenerates invite tokens and invalidates old links.

## Security/Anonymity model
- Invite links are tied to a random token; only its SHA-256 hash is stored with the employee record.
- Survey submissions generate a UUID; responses reference only that UUID. The employee linkage stores only a SHA-256 hash of the UUID, preventing direct joins between answers and employee records from the database alone.
- No employee identifiers are stored alongside responses.
