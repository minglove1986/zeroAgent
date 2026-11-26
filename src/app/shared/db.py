"""
异步数据库引擎与会话。

@author 赵振明
@date 2026-07-21 15:31:36
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """ORM 基类。禁止引入 tenant_id。"""


settings = get_settings()
# 设计思路（2026-11-19 09:59:21）：
# SQLAlchemy 2.0 + aiomysql 开启 pool_pre_ping 时，探活会调用
# AsyncAdapt_aiomysql_connection.ping() 却未传 reconnect，抛 TypeError，
# 表现为登录/me 等接口间歇性 HTTP 500。改用 pool_recycle 主动轮换连接。
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=False,
    pool_recycle=3600,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：请求级会话。"""
    async with SessionLocal() as session:
        yield session
