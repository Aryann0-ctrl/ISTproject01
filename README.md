# Events API

Flask backend for the event and registration API contract. It uses the existing Supabase tables:

- `users(id, email, role)`
- `events(id, organizer_id, title, capacity, status)`
- `registrations(id, user_id, event_id, created_at)`

## Run

Copy `.env.example` to `.env` and set the Supabase values. The existing `.evn` file is also supported for compatibility. Set `SUPABASE_SECRET_KEY` for the server; otherwise the publishable key is used and Supabase must grant the `anon` role the required table privileges.

```powershell
.\venv\Scripts\Activate.ps1
python app.py
```

## Deploy to Render

This repository includes `render.yaml` and a `Procfile`. Create a Render Blueprint from the repository, then set `SUPABASE_URL` and `SUPABASE_SECRET_KEY` in the service environment. Render supplies `PORT` automatically, and the production command must be `gunicorn app:app`.

If the Render service was created manually and still shows `gunicorn your_application.wsgi`, replace its Start Command with `gunicorn app:app` in Settings, save, and redeploy.

Authentication is intentionally not enabled yet. The registration and private attendee endpoints identify the caller with an `X-User-Id` UUID header. This is a temporary development mechanism, not an authentication boundary.

The secret key is used only by this Flask process and must never be sent to a frontend. If you intentionally use the publishable key during development, grant only the required `anon` privileges and enable RLS before exposing the API publicly.

## Endpoints

- `GET /api/events?status=open&q=python&limit=20&offset=0`
- `GET /api/events/<id>`
- `POST /api/registrations` with `{ "event_id": "<uuid>" }`
- `GET /api/me/registrations`
- `GET /api/events/<id>/registrations`

The last three routes that depend on the caller require `X-User-Id`. The organizer list additionally checks that the header matches `events.organizer_id`.
