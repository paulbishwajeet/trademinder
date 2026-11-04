import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

TEST_DATABASE_URL = "postgresql+asyncpg://trademinder:password@localhost:5432/trademinder_test"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_test_tables():
    from app.database import Base
    import app.models  # noqa: F401 — ensures all models are registered
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(autouse=True)
async def clean_tables():
    yield
    from app.database import Base
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


async def make_user_with_account(email: str, nickname: str = "E*TRADE"):
    """Insert a user plus a default brokerage account directly (no API), committed."""
    from app.models.user import User
    from app.models.brokerage_account import BrokerageAccount
    async with TestSessionLocal() as s:
        user = User(email=email, display_name=email.split("@")[0], role="user", status="active")
        s.add(user)
        await s.flush()
        account = BrokerageAccount(user_id=user.id, broker="E*TRADE", nickname=nickname, is_default=True)
        s.add(account)
        await s.commit()
        return user, account


@pytest_asyncio.fixture(autouse=True)
async def owner_and_account():
    """Every test runs as a seeded owner with one default account, mirroring migrations 015/016."""
    return await make_user_with_account("owner@test.local")


@pytest_asyncio.fixture
async def owner(owner_and_account):
    return owner_and_account[0]


@pytest_asyncio.fixture
async def default_account(owner_and_account):
    return owner_and_account[1]


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    from app.main import app
    from app.database import get_db
    from app.deps import get_current_user

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _acting_user["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


_acting_user: dict = {}


@pytest_asyncio.fixture(autouse=True)
async def act_as(owner):
    """Requests run as the owner; call act_as(other_user) to switch the current user mid-test."""
    def _switch(user):
        _acting_user["user"] = user
    _switch(owner)
    yield _switch
    _acting_user.clear()
