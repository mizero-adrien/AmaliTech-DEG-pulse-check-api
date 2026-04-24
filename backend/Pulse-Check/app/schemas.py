import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class MonitorCreate(BaseModel):
    id: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Unique device identifier (3-50 chars, alphanumeric and hyphens only)",
    )
    timeout: int = Field(
        ...,
        ge=10,
        le=86400,
        description="Timeout in seconds (min: 10, max: 86400 which is 24 hours)",
    )
    alert_email: EmailStr = Field(
        ...,
        description="Valid email address for alerts",
    )

    @field_validator("id")
    @classmethod
    def validate_device_id(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9-]+$', v):
            raise ValueError("Device ID must contain only letters, numbers, and hyphens")
        if v.startswith("-") or v.endswith("-"):
            raise ValueError("Device ID must not start or end with a hyphen")
        return v.lower()

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v < 10:
            raise ValueError("Timeout must be at least 10 seconds")
        if v > 86400:
            raise ValueError("Timeout cannot exceed 86400 seconds (24 hours)")
        return v


class AlertOut(BaseModel):
    id: int
    device_id: str
    message: str
    ai_analysis: Optional[str] = None
    confidence: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MonitorOut(BaseModel):
    id: str
    timeout: int
    status: str
    alert_email: str
    last_ping: Optional[datetime] = None
    created_at: datetime
    health_score: Optional[float] = None

    model_config = {"from_attributes": True}


class MonitorStatusOut(MonitorOut):
    alerts: List[AlertOut] = []


class DeviceHistoryOut(BaseModel):
    device_id: str
    uptime_percentage: float
    average_response_time_seconds: float | None
    total_alerts: int
    alerts: List[AlertOut]
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_previous: bool


class ApiKeyCreate(BaseModel):
    device_id: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Device ID this key belongs to",
    )
    name: str = Field(
        ...,
        min_length=3,
        max_length=100,
        description="Descriptive name for this key",
    )


class ApiKeyOut(BaseModel):
    id: int
    key: str
    device_id: str
    name: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    email: EmailStr = Field(
        ...,
        description="Valid email address",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=100,
        description="Password (min 8 characters)",
    )
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Full name (2-100 characters)",
    )

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z\s]+$', v):
            raise ValueError("Full name must contain only letters and spaces")
        return v.strip()


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str
    engineer_name: str
    email: str


class TokenData(BaseModel):
    email: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class DiagnosisBreakdown(BaseModel):
    power_failure: int = 0
    network_issue: int = 0
    hardware_failure: int = 0
    theft: int = 0
    unknown: int = 0


class DashboardOut(BaseModel):
    total_devices: int
    active_devices: int
    down_devices: int
    paused_devices: int
    total_alerts_today: int
    total_alerts_all_time: int
    ai_diagnosis_breakdown: DiagnosisBreakdown
    average_health_score: float
    most_recent_alert: str | None
    system_status: str
    generated_at: datetime


class PaginationMeta(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_previous: bool


class PaginatedMonitorsOut(BaseModel):
    data: List[MonitorOut]
    meta: PaginationMeta


class PaginatedAlertsOut(BaseModel):
    data: List[AlertOut]
    meta: PaginationMeta
