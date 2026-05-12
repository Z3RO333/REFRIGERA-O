import ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


def _make_engine():
    kwargs: dict = {"echo": False, "pool_pre_ping": True}
    url = settings.database_url
    if settings.database_ssl:
        ctx = ssl.create_default_context()
        kwargs["connect_args"] = {"ssl": ctx}
        # Strip any stale ?ssl=... from the URL to avoid asyncpg confusion
        from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
        parsed = urlparse(url)
        qs = {k: v for k, v in parse_qs(parsed.query).items() if k != "ssl"}
        url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
    return create_async_engine(url, **kwargs)


engine = _make_engine()
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
