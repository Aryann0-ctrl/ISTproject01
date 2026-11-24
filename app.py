import os
from typing import Any
from uuid import UUID

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from postgrest import APIError
from supabase import Client, create_client


load_dotenv()
load_dotenv(".evn")

app = Flask(__name__)


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    app.logger.exception("Unhandled application error", exc_info=error)
    return jsonify({"error": "Internal server error"}), 500


def _required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


supabase_key = (
    os.getenv("SUPABASE_SECRET_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or _required_setting("SUPABASE_PUBLISHABLE_KEY")
)
supabase: Client = create_client(_required_setting("SUPABASE_URL"), supabase_key)


def _json_error(message: str, status: int):
    return jsonify({"error": message}), status


def _uuid(value: Any, field_name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise ValueError(f"{field_name} must be a valid UUID") from None


def _current_user_id() -> str:
    value = request.headers.get("X-User-Id")
    if not value:
        raise ValueError("X-User-Id header is required until authentication is added")
    return _uuid(value, "X-User-Id")


def _supabase_error(error: APIError):
    code = getattr(error, "code", None)
    message = getattr(error, "message", str(error))
    if code == "23505":
        return _json_error("You are already registered for this event", 409)
    if code in {"23503", "PGRST116"}:
        return _json_error("Referenced record was not found", 404)
    return jsonify({"error": "Database request failed", "code": code, "details": message}), 500


@app.get("/")
def index():
    return jsonify({"service": "events-api", "status": "ok"})


@app.get("/api/events")
def list_events():
    try:
        limit = min(max(int(request.args.get("limit", 20)), 1), 100)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return _json_error("limit and offset must be integers", 400)

    query = supabase.table("events").select("*")
    status = request.args.get("status")
    search = request.args.get("q")
    if status:
        query = query.eq("status", status)
    if search:
        query = query.ilike("title", f"%{search}%")

    try:
        response = query.order("id").range(offset, offset + limit - 1).execute()
        return jsonify({"data": response.data, "limit": limit, "offset": offset})
    except APIError as error:
        return _supabase_error(error)


@app.get("/api/events/<event_id>")
def get_event(event_id: str):
    try:
        event_id = _uuid(event_id, "id")
        event_response = (
            supabase.table("events").select("*").eq("id", event_id).limit(1).execute()
        )
        if not event_response.data:
            return _json_error("Event not found", 404)

        registration_response = (
            supabase.table("registrations")
            .select("id", count="exact")
            .eq("event_id", event_id)
            .execute()
        )
        event = dict(event_response.data[0])
        event["registration_count"] = registration_response.count or 0
        return jsonify({"data": event})
    except ValueError as error:
        return _json_error(str(error), 400)
    except APIError as error:
        return _supabase_error(error)


@app.post("/api/registrations")
def create_registration():
    payload = request.get_json(silent=True) or {}
    try:
        user_id = _current_user_id()
        event_id = _uuid(payload.get("event_id"), "event_id")
    except ValueError as error:
        return _json_error(str(error), 400)

    try:
        event_response = (
            supabase.table("events").select("id,capacity,status").eq("id", event_id).limit(1).execute()
        )
        if not event_response.data:
            return _json_error("Event not found", 404)
        event = event_response.data[0]
        if str(event.get("status", "")).lower() in {"closed", "cancelled", "canceled", "completed"}:
            return _json_error("Event is not open for registration", 409)

        registration_response = (
            supabase.table("registrations")
            .select("id", count="exact")
            .eq("event_id", event_id)
            .eq("user_id", user_id)
            .execute()
        )
        if registration_response.data:
            return _json_error("You are already registered for this event", 409)

        capacity = event.get("capacity")
        if capacity is not None:
            count_response = (
                supabase.table("registrations")
                .select("id", count="exact")
                .eq("event_id", event_id)
                .execute()
            )
            if (count_response.count or 0) >= capacity:
                return _json_error("Event capacity has been reached", 409)

        created = (
            supabase.table("registrations")
            .insert({"user_id": user_id, "event_id": event_id})
            .execute()
        )
        return jsonify({"data": created.data[0]}), 201
    except APIError as error:
        return _supabase_error(error)


@app.get("/api/me/registrations")
def current_user_registrations():
    try:
        user_id = _current_user_id()
    except ValueError as error:
        return _json_error(str(error), 400)

    try:
        response = (
            supabase.table("registrations")
            .select("*, events(*)")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return jsonify({"data": response.data})
    except APIError as error:
        return _supabase_error(error)


@app.get("/api/events/<event_id>/registrations")
def event_registrations(event_id: str):
    try:
        event_id = _uuid(event_id, "id")
        user_id = _current_user_id()
    except ValueError as error:
        return _json_error(str(error), 400)

    try:
        event_response = (
            supabase.table("events")
            .select("id,organizer_id")
            .eq("id", event_id)
            .limit(1)
            .execute()
        )
        if not event_response.data:
            return _json_error("Event not found", 404)
        if str(event_response.data[0]["organizer_id"]) != user_id:
            return _json_error("Only the event organizer can view attendees", 403)

        response = (
            supabase.table("registrations")
            .select("*, users(id,email,role)")
            .eq("event_id", event_id)
            .order("created_at")
            .execute()
        )
        return jsonify({"data": response.data})
    except APIError as error:
        return _supabase_error(error)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
