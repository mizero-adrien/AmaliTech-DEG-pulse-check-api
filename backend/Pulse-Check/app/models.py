from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, func
from app.database import Base


class Monitor(Base):
    __tablename__ = "monitors"

    id = Column(String, primary_key=True, index=True)
    timeout = Column(Integer, nullable=False)
    status = Column(String, default="active", nullable=False)
    alert_email = Column(String, nullable=False)
    last_ping = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    health_score = Column(Float, default=100.0)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(
        String,
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message = Column(String, nullable=False)
    ai_analysis = Column(String)
    confidence = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False, index=True)
    device_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
