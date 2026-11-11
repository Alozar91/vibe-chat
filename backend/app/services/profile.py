"""Профиль пользователя: обновление персональных данных (Docs/concept.md §5, §12).

Персональные данные (имя, фамилия, почта, display_name, аватар, часовой пояс)
живут только в системе — Keycloak отвечает только за идентификацию/аутентификацию.
"""

from zoneinfo import available_timezones

from app.models.user import User
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession


async def update_profile(
    db: AsyncSession,
    *,
    user_id: str,
    updates: dict[str, object],
) -> User:
    """PATCH /users/me: частичное обновление профиля.

    Пользователь перечитывается в переданной сессии по `user_id` (ORM-инстанс
    привязан к сессии, создавшей его). `updates` — уже отфильтрованный dict
    (exclude_unset): ключ присутствует → поле меняем (None = очистить).
    timezone валидируется по IANA; невалидный — 422 (у пользователя есть явная
    настройка, в отличие от сообщений, где невалидный пояс молча становится
    NULL — §6).
    """
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account deactivated")

    if "timezone" in updates and updates["timezone"] is not None:
        tz_name = str(updates["timezone"])
        if tz_name not in available_timezones():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid IANA timezone")

    allowed = {"display_name", "first_name", "last_name", "email", "avatar_file_id", "time_display", "timezone"}
    for key, value in updates.items():
        if key in allowed:
            setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user
