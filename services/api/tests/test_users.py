import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import get_db
from src.middleware.auth import get_current_admin
from src.models.audit_log import User
from src.routers.users import get_user_service
from src.services.user_service import UserActionForbiddenError, UserConflictError


def make_fake_admin() -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = 'admin'
    user.email = 'admin@meetrec.local'
    user.is_active = True
    user.is_admin = True
    user.must_change_password = False
    user.created_at = datetime.now(timezone.utc)
    user.last_login = None
    user.full_name = 'Administrator'
    return user


def make_user_item(user_id: uuid.UUID | None = None) -> MagicMock:
    item = MagicMock(spec=User)
    item.id = user_id or uuid.uuid4()
    item.username = 'newuser'
    item.email = 'newuser@meetrec.local'
    item.full_name = 'New User'
    item.is_active = True
    item.is_admin = False
    item.must_change_password = True
    item.created_at = datetime.now(timezone.utc)
    item.last_login = None
    return item


def make_mock_service() -> AsyncMock:
    svc = AsyncMock()
    svc.list_users = AsyncMock(return_value={
        'items': [], 'total': 0, 'page': 1, 'page_size': 20, 'pages': 0,
    })
    svc.get_by_id = AsyncMock(return_value=None)
    svc.create_user = AsyncMock(return_value=make_user_item())
    svc.update_user = AsyncMock(return_value=make_user_item())
    svc.delete_user = AsyncMock(return_value=None)
    return svc


@asynccontextmanager
async def override_service(mock_svc, admin_user: User | None = None):
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    fake_admin = admin_user or make_fake_admin()

    async def _mock_db():
        yield mock_db

    app.dependency_overrides[get_user_service] = lambda: mock_svc
    app.dependency_overrides[get_db] = _mock_db
    app.dependency_overrides[get_current_admin] = lambda: fake_admin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url='http://test',
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


class TestUsersRouter:

    @pytest.mark.asyncio
    async def test_list_users_returns_200_for_admin(self):
        svc = make_mock_service()
        svc.list_users.return_value = {
            'items': [],
            'total': 0,
            'page': 1,
            'page_size': 20,
            'pages': 0,
        }

        async with override_service(svc) as client:
            response = await client.get('/api/v1/users')

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_create_user_returns_201(self):
        svc = make_mock_service()
        svc.create_user.return_value = make_user_item()

        async with override_service(svc) as client:
            response = await client.post('/api/v1/users', json={
                'username': 'newuser',
                'email': 'newuser@meetrec.local',
                'full_name': 'New User',
                'password': 'TempPass123',
                'is_admin': False,
            })

        assert response.status_code == 201
        assert response.json()['must_change_password'] is True

    @pytest.mark.asyncio
    async def test_create_user_returns_409_on_conflict(self):
        svc = make_mock_service()
        svc.create_user.side_effect = UserConflictError('Username sau email deja existent.')

        async with override_service(svc) as client:
            response = await client.post('/api/v1/users', json={
                'username': 'admin',
                'email': 'admin@meetrec.local',
                'password': 'TempPass123',
                'is_admin': True,
            })

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_update_user_returns_403_on_self_protection_rule(self):
        svc = make_mock_service()
        admin_user = make_fake_admin()
        svc.get_by_id.return_value = admin_user
        svc.update_user.side_effect = UserActionForbiddenError(
            'Nu îți poți revoca singur drepturile de administrator.'
        )

        async with override_service(svc, admin_user=admin_user) as client:
            response = await client.patch(f'/api/v1/users/{admin_user.id}', json={'is_admin': False})

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_user_returns_204(self):
        svc = make_mock_service()
        svc.get_by_id.return_value = make_user_item()

        async with override_service(svc) as client:
            response = await client.delete(f'/api/v1/users/{uuid.uuid4()}')

        assert response.status_code == 204
