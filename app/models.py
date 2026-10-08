from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint, Table
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

# Association table for ShortLink <-> LinkTag
link_tag_table = Table(
    "link_tag_association",
    Base.metadata,
    Column("short_link_id", Integer, ForeignKey("short_links.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("link_tags.id", ondelete="CASCADE"), primary_key=True),
)

class UserDomain(Base):
    __tablename__ = "user_domains"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "domain_id", name="uq_user_domain"),
    )

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    avatar_url = Column(String(1024), nullable=True)
    role = Column(String(50), default="user", nullable=False)  # "superadmin", "admin", "user"
    status = Column(String(50), default="pending", nullable=False)  # "approved", "pending", "revoked"
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    domains = relationship("Domain", secondary="user_domains", back_populates="users", lazy="selectin")
    links = relationship("ShortLink", back_populates="created_by", cascade="all, delete-orphan")

    @property
    def is_superadmin(self) -> bool:
        return self.role == "superadmin"

    @property
    def is_admin(self) -> bool:
        return self.role in ("superadmin", "admin")

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

class Domain(Base):
    __tablename__ = "domains"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)  # "fcc.li", "amp.ad", "link.gajc.site"
    is_active = Column(Boolean, default=True, nullable=False)
    root_redirect_url = Column(String(1024), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    users = relationship("User", secondary="user_domains", back_populates="domains", lazy="selectin")
    links = relationship("ShortLink", back_populates="domain", cascade="all, delete-orphan")

class ShortLink(Base):
    __tablename__ = "short_links"
    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True)
    slug = Column(String(255), nullable=False, index=True)
    destination_url = Column(Text, nullable=False)
    title = Column(String(512), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    total_clicks = Column(Integer, default=0, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    # Relationships
    domain = relationship("Domain", back_populates="links", lazy="selectin")
    created_by = relationship("User", back_populates="links", lazy="selectin")
    tags = relationship("LinkTag", secondary=link_tag_table, back_populates="short_links", lazy="selectin")
    clicks = relationship("ClickEvent", back_populates="short_link", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("domain_id", "slug", name="uq_domain_slug"),
    )

class LinkTag(Base):
    __tablename__ = "link_tags"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    color = Column(String(50), default="teal", nullable=False)  # "coral", "saffron", "blue", "forest", "teal"

    short_links = relationship("ShortLink", secondary=link_tag_table, back_populates="tags", lazy="selectin")

class ClickEvent(Base):
    __tablename__ = "click_events"
    id = Column(Integer, primary_key=True, index=True)
    short_link_id = Column(Integer, ForeignKey("short_links.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    ip_hash = Column(String(64), nullable=True)
    referrer = Column(String(1024), nullable=True)
    user_agent = Column(String(1024), nullable=True)
    device_type = Column(String(50), default="desktop", nullable=False)  # "desktop", "mobile", "tablet"
    is_qr = Column(Boolean, default=False, nullable=False)

    short_link = relationship("ShortLink", back_populates="clicks")
