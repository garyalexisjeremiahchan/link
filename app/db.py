import os
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import event, select
from app.config import settings
from app.models import Base, Domain, User, UserDomain

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

# Create engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False}
)

# Enable WAL mode and foreign keys for SQLite
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with AsyncSessionLocal() as session:
        # 1. Seed Domains
        for domain_name in settings.domain_list:
            res = await session.execute(select(Domain).where(Domain.name == domain_name))
            existing = res.scalar_one_or_none()
            if not existing:
                root_redirect = ""
                if domain_name == "fcc.li":
                    root_redirect = "https://freecomchurch.org/"
                elif domain_name == "amp.ad":
                    root_redirect = "https://amplifyasiapacific.org/"
                
                domain = Domain(name=domain_name, is_active=True, root_redirect_url=root_redirect)
                session.add(domain)
        await session.commit()
        
        # 2. Seed Default Super Admin
        res = await session.execute(select(User).where(User.email == settings.DEFAULT_SUPERADMIN))
        superadmin = res.scalar_one_or_none()
        if not superadmin:
            superadmin = User(
                email=settings.DEFAULT_SUPERADMIN,
                name="Free Community Church",
                role="superadmin",
                status="approved",
            )
            session.add(superadmin)
            await session.commit()
            await session.refresh(superadmin)
            
        # Give superadmin access to all domains
        domains_res = await session.execute(select(Domain))
        all_domains = domains_res.scalars().all()
        for dom in all_domains:
            assoc_res = await session.execute(
                select(UserDomain).where(UserDomain.user_id == superadmin.id, UserDomain.domain_id == dom.id)
            )
            if not assoc_res.scalar_one_or_none():
                session.add(UserDomain(user_id=superadmin.id, domain_id=dom.id))
        await session.commit()
