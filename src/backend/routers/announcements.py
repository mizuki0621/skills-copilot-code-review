"""
Announcement endpoints for the High School Management System API
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementBase(BaseModel):
    """Shared announcement fields for create/update operations."""

    message: str = Field(min_length=1, max_length=280)
    expires_at: str
    starts_at: Optional[str] = None


class AnnouncementCreate(AnnouncementBase):
    """Payload for creating a new announcement."""


class AnnouncementUpdate(AnnouncementBase):
    """Payload for updating an existing announcement."""


def parse_iso_datetime(value: str) -> datetime:
    """Parse ISO 8601 datetime values including UTC Z suffix."""
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def require_signed_in_user(username: Optional[str]) -> Dict[str, Any]:
    """Validate and return the signed-in user."""
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    teacher = teachers_collection.find_one({"_id": username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher


def serialize_announcement(announcement: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DB announcement docs into frontend-friendly objects."""
    return {
        "id": str(announcement.get("_id")),
        "message": announcement.get("message", ""),
        "starts_at": announcement.get("starts_at"),
        "expires_at": announcement.get("expires_at"),
        "created_by": announcement.get("created_by"),
        "updated_by": announcement.get("updated_by")
    }


@router.get("", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Return all currently active (non-expired and started) announcements."""
    now = datetime.now(timezone.utc)
    active_announcements: List[Dict[str, Any]] = []

    for announcement in announcements_collection.find({}):
        starts_at_value = announcement.get("starts_at")
        expires_at_value = announcement.get("expires_at")

        try:
            starts_at = parse_iso_datetime(starts_at_value) if starts_at_value else None
            expires_at = parse_iso_datetime(expires_at_value)
        except Exception as exc:
            print(f"Invalid announcement date format for {announcement.get('_id')}: {exc}")
            continue

        if starts_at and starts_at > now:
            continue
        if expires_at < now:
            continue

        active_announcements.append(serialize_announcement(announcement))

    active_announcements.sort(key=lambda item: item.get("expires_at", ""))
    return active_announcements


@router.get("/manage", response_model=List[Dict[str, Any]])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Return all announcements for management UI (requires signed-in user)."""
    require_signed_in_user(teacher_username)

    announcements = [serialize_announcement(doc) for doc in announcements_collection.find({})]
    announcements.sort(key=lambda item: item.get("expires_at", ""))
    return announcements


@router.post("", response_model=Dict[str, Any])
def create_announcement(
    payload: AnnouncementCreate,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Create an announcement (requires signed-in user)."""
    teacher = require_signed_in_user(teacher_username)

    try:
        starts_at = parse_iso_datetime(payload.starts_at) if payload.starts_at else None
        expires_at = parse_iso_datetime(payload.expires_at)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO 8601")

    if starts_at and starts_at >= expires_at:
        raise HTTPException(status_code=400, detail="Start date must be before expiration date")

    clean_message = payload.message.strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    created_doc = {
        "_id": f"announcement-{uuid4().hex[:12]}",
        "message": clean_message,
        "starts_at": starts_at.isoformat().replace("+00:00", "Z") if starts_at else None,
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "created_by": teacher.get("username"),
        "updated_by": teacher.get("username")
    }

    announcements_collection.insert_one(created_doc)
    saved_doc = announcements_collection.find_one({"_id": created_doc["_id"]})
    if not saved_doc:
        raise HTTPException(status_code=500, detail="Failed to create announcement")

    return serialize_announcement(saved_doc)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    payload: AnnouncementUpdate,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an announcement (requires signed-in user)."""
    teacher = require_signed_in_user(teacher_username)

    existing = announcements_collection.find_one({"_id": announcement_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Announcement not found")

    try:
        starts_at = parse_iso_datetime(payload.starts_at) if payload.starts_at else None
        expires_at = parse_iso_datetime(payload.expires_at)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO 8601")

    if starts_at and starts_at >= expires_at:
        raise HTTPException(status_code=400, detail="Start date must be before expiration date")

    clean_message = payload.message.strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    update_result = announcements_collection.update_one(
        {"_id": announcement_id},
        {
            "$set": {
                "message": clean_message,
                "starts_at": starts_at.isoformat().replace("+00:00", "Z") if starts_at else None,
                "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
                "updated_by": teacher.get("username")
            }
        }
    )

    if update_result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    updated = announcements_collection.find_one({"_id": announcement_id})
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to load updated announcement")

    return serialize_announcement(updated)


@router.delete("/{announcement_id}", response_model=Dict[str, str])
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Delete an announcement (requires signed-in user)."""
    require_signed_in_user(teacher_username)

    result = announcements_collection.delete_one({"_id": announcement_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}
