from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _join_button(text: str = "Вступить в клуб") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data="menu:join", style="success")


def main_menu_keyboard(*, show_renew_button: bool = False, hide_entry_actions: bool = False, mini_app_url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not hide_entry_actions:
        primary_entry_text = "Продлить участие в клубе" if show_renew_button else "Вступить в клуб"
        rows.append([_join_button(primary_entry_text)])
    if mini_app_url:
        rows.append([InlineKeyboardButton(text="Открыть Mini App", url=mini_app_url)])
    rows.extend(
        [
            [InlineKeyboardButton(text="Мой статус", callback_data="menu:status")],
            [InlineKeyboardButton(text="О клубе", callback_data="menu:about")],
            [InlineKeyboardButton(text="Что внутри", callback_data="menu:inside")],
            [InlineKeyboardButton(text="Об авторе", callback_data="menu:author")],
            [InlineKeyboardButton(text="Как оплатить", callback_data="menu:payment")],
            [InlineKeyboardButton(text="Задать вопрос", callback_data="menu:question")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def about_keyboard(*, hide_entry_actions: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Что внутри", callback_data="menu:inside")]]
    if not hide_entry_actions:
        rows.extend(
            [
                [_join_button()],
            ]
        )
    rows.append([InlineKeyboardButton(text="Назад в меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inside_keyboard(*, hide_entry_actions: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Как оплатить", callback_data="menu:payment")]]
    if not hide_entry_actions:
        rows.extend(
            [
                [_join_button()],
            ]
        )
    rows.append([InlineKeyboardButton(text="Назад в меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def author_keyboard(owner_contact_url: str, *, hide_entry_actions: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Задать вопрос", url=owner_contact_url)]]
    if not hide_entry_actions:
        rows.extend(
            [
                [_join_button()],
            ]
        )
    rows.append([InlineKeyboardButton(text="Назад в меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def question_keyboard(owner_contact_url: str, *, hide_entry_actions: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if not hide_entry_actions:
        rows.extend(
            [
                [_join_button()],
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="Написать Вячеславу", url=owner_contact_url)],
            [InlineKeyboardButton(text="Назад в меню", callback_data="menu:main")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_keyboard(*, hide_entry_actions: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Я оплатил", callback_data="payment:send_receipt")]]
    rows.extend(
        [
            [InlineKeyboardButton(text="Задать вопрос", callback_data="menu:question")],
            [InlineKeyboardButton(text="Назад в меню", callback_data="menu:main")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def promo_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Я оплатил", callback_data="payment:send_receipt")],
            [InlineKeyboardButton(text="Задать вопрос", callback_data="menu:question")],
            [InlineKeyboardButton(text="Назад в меню", callback_data="menu:main")],
        ]
    )


def trial_info_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Начать тестовый период", callback_data="trial:start", style="success")],
            [InlineKeyboardButton(text="Назад в меню", callback_data="menu:main")],
        ]
    )


def trial_started_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад в меню", callback_data="menu:main")],
        ]
    )


def trial_finished_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_join_button()],
            [InlineKeyboardButton(text="Как оплатить", callback_data="menu:payment")],
            [InlineKeyboardButton(text="Задать вопрос", callback_data="menu:question")],
        ]
    )


def receipt_received_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Задать вопрос", callback_data="menu:question")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:main")],
        ]
    )


def approved_keyboard(club_invite_link: str, owner_contact_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Перейти в клуб", url=club_invite_link)],
            [InlineKeyboardButton(text="Написать Вячеславу", url=owner_contact_url)],
        ]
    )


def rejected_keyboard(owner_contact_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отправить чек заново", callback_data="payment:send_receipt")],
            [InlineKeyboardButton(text="Задать вопрос", url=owner_contact_url)],
        ]
    )


def reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_join_button("Продлить участие в клубе")],
            [InlineKeyboardButton(text="Как оплатить", callback_data="menu:payment")],
            [InlineKeyboardButton(text="Задать вопрос", callback_data="menu:question")],
        ]
    )


def expired_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_join_button("Продлить участие в клубе")],
            [InlineKeyboardButton(text="Как оплатить", callback_data="menu:payment")],
            [InlineKeyboardButton(text="Задать вопрос", callback_data="menu:question")],
        ]
    )


def admin_payment_keyboard(payment_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить оплату", callback_data=f"admin:approve:{payment_id}")],
            [InlineKeyboardButton(text="Отклонить", callback_data=f"admin:reject:{payment_id}")],
            [InlineKeyboardButton(text="Написать пользователю", url=f"tg://user?id={user_id}")],
        ]
    )


def admin_user_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Продлить на 30 дней", callback_data=f"admin:extend:{user_id}")],
            [InlineKeyboardButton(text="Отключить доступ", callback_data=f"admin:disable:{user_id}")],
            [InlineKeyboardButton(text="История оплат", callback_data=f"admin:payments:{user_id}")],
            [InlineKeyboardButton(text="Выдать вечный бесплатный доступ", callback_data=f"admin:lifetime_on:{user_id}")],
            [InlineKeyboardButton(text="Снять вечный бесплатный доступ", callback_data=f"admin:lifetime_off:{user_id}")],
            [InlineKeyboardButton(text="Назад к фильтрам", callback_data="admin:users_panel")],
        ]
    )


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="Пользователи", callback_data="admin:users_panel")],
            [InlineKeyboardButton(text="Кто в клубе", callback_data="admin:list:members")],
            [InlineKeyboardButton(text="Активировали бот", callback_data="admin:list:activated")],
            [InlineKeyboardButton(text="Особые участники", callback_data="admin:list:special")],
            [InlineKeyboardButton(text="Рассылка", callback_data="admin:broadcast")],
        ]
    )


def admin_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Обновить статистику", callback_data="admin:stats")],
            [InlineKeyboardButton(text="Открыть админ-панель", callback_data="admin:panel")],
        ]
    )


def admin_users_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Кто в клубе", callback_data="admin:list:members")],
            [InlineKeyboardButton(text="Активировали бот", callback_data="admin:list:activated")],
            [InlineKeyboardButton(text="Особые участники", callback_data="admin:list:special")],
            [InlineKeyboardButton(text="Активные", callback_data="admin:list:active")],
            [InlineKeyboardButton(text="Скоро истекают", callback_data="admin:list:expiring")],
            [InlineKeyboardButton(text="Ждут подтверждения", callback_data="admin:list:waiting_confirmation")],
            [InlineKeyboardButton(text="Доступ истёк", callback_data="admin:list:expired")],
            [InlineKeyboardButton(text="Назад в админ-панель", callback_data="admin:panel")],
        ]
    )


def user_status_keyboard(
    *,
    show_renew_button: bool = False,
    club_invite_link: str | None = None,
    trial_invite_link: str | None = None,
    is_trial_active: bool = False,
    hide_entry_actions: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_trial_active and trial_invite_link:
        rows.append([InlineKeyboardButton(text="Открыть пробный клуб", url=trial_invite_link)])
    elif club_invite_link:
        rows.append([InlineKeyboardButton(text="Получить ссылку в клуб", url=club_invite_link)])
    if not hide_entry_actions:
        rows.append([_join_button("Продлить участие в клубе" if show_renew_button else "Вступить в клуб")])
    rows.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_broadcast_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin:broadcast_cancel")],
        ]
    )


def promo_entry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад в меню", callback_data="menu:main")],
        ]
    )


def maintenance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Клуб на каникулах до 01.08.2026", callback_data="maintenance:info")],
        ]
    )


def promo_success_keyboard(club_invite_link: str, owner_contact_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Перейти в клуб", url=club_invite_link)],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:main")],
            [InlineKeyboardButton(text="Написать Вячеславу", url=owner_contact_url)],
        ]
    )


def admin_promo_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать постоянный", callback_data="admin:promo_create:permanent")],
            [InlineKeyboardButton(text="Создать временный", callback_data="admin:promo_create:temporary")],
            [InlineKeyboardButton(text="Список промокодов", callback_data="admin:promo_list")],
            [InlineKeyboardButton(text="Назад в админ-панель", callback_data="admin:panel")],
        ]
    )


def admin_promo_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin:promo_cancel")],
        ]
    )


def admin_promo_list_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Обновить список", callback_data="admin:promo_list")],
            [InlineKeyboardButton(text="Назад к промокодам", callback_data="admin:promo_panel")],
        ]
    )
