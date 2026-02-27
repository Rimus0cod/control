"""PC control handlers — Arch Linux."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.filters import IsAuthorized
from bot.keyboards import (
    get_confirm_keyboard,
    get_main_keyboard,
    get_pc_commands_keyboard,
)
from database import DatabaseRepository
from services import NotificationService, PCManager
from utils import get_logger

router = Router()
logger = get_logger(__name__)

# Non-admin safe command whitelist
SAFE_CMDS = ["ls", "pwd", "whoami", "hostname", "uname", "df", "free", "uptime", "ps", "ip"]


# ---------------------------------------------------------------------------
# /status  — system metrics
# ---------------------------------------------------------------------------

@router.message(Command("status"))
async def cmd_status(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer(
            "Нет доступа.",
            reply_markup=get_main_keyboard(is_authorized=False),
        )
        return

    pc = PCManager()
    info = await pc.get_system_info()

    if not info:
        await message.answer("Не удалось получить информацию о системе.")
        return

    text = (
        "<b>Статус ПК</b>\n\n"
        f"Хост: <code>{info.get('hostname', '?')}</code>\n"
        f"CPU: <b>{info.get('cpu_percent')}%</b>\n"
        f"RAM: <b>{info.get('memory_used_gb')} / {info.get('memory_total_gb')} ГБ</b> "
        f"({info.get('memory_percent')}%)\n"
        f"Диск: <b>{info.get('disk_used_gb')} / {info.get('disk_total_gb')} ГБ</b> "
        f"({info.get('disk_percent')}%)\n"
        f"Uptime: <b>{info.get('uptime')}</b>"
    )
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin),
    )
    await db.add_log_entry(action="status_check", user_id=user.id)


# ---------------------------------------------------------------------------
# /screenshot
# ---------------------------------------------------------------------------

@router.message(Command("screenshot"))
async def cmd_screenshot(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer("Нет доступа.", reply_markup=get_main_keyboard(is_authorized=False))
        return

    wait_msg = await message.answer("Делаю скриншот…")
    pc = PCManager()
    data = await pc.take_screenshot()

    await wait_msg.delete()

    if data:
        photo = BufferedInputFile(data, filename="screenshot.png")
        await message.answer_photo(
            photo,
            caption="Скриншот рабочего стола",
            reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin),
        )
        await db.add_log_entry(action="screenshot_taken", user_id=user.id)
    else:
        await message.answer(
            "Не удалось сделать скриншот.\n"
            "Установите: <code>pacman -S scrot</code> или <code>pacman -S imagemagick</code>",
            parse_mode="HTML",
        )


# ---------------------------------------------------------------------------
# /reboot / /shutdown
# ---------------------------------------------------------------------------

@router.message(Command("reboot"))
async def cmd_reboot(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer("Нет доступа.", reply_markup=get_main_keyboard(is_authorized=False))
        return

    await message.answer(
        "<b>Подтвердите перезагрузку</b>\n\nПК перезагрузится через 1 минуту.\nОтменить: /cancel",
        reply_markup=get_confirm_keyboard("reboot"),
        parse_mode="HTML",
    )


@router.message(Command("shutdown"))
async def cmd_shutdown(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer("Нет доступа.", reply_markup=get_main_keyboard(is_authorized=False))
        return

    await message.answer(
        "<b>Подтвердите выключение</b>\n\nПК выключится через 1 минуту.\nОтменить: /cancel",
        reply_markup=get_confirm_keyboard("shutdown"),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# /cancel — abort scheduled shutdown/reboot
# ---------------------------------------------------------------------------

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer("Нет доступа.", reply_markup=get_main_keyboard(is_authorized=False))
        return

    pc = PCManager()
    ok = await pc.cancel_shutdown()

    await message.answer(
        "Выключение/перезагрузка отменены." if ok else "Нечего отменять или ошибка.",
        reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin),
    )
    if ok:
        await db.add_log_entry(action="shutdown_cancelled", user_id=user.id)


# ---------------------------------------------------------------------------
# /cmd — execute shell command
# ---------------------------------------------------------------------------

@router.message(Command("cmd"))
async def cmd_command(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer("Нет доступа.", reply_markup=get_main_keyboard(is_authorized=False))
        return

    command = (message.text or "").replace("/cmd", "", 1).strip()
    if not command:
        await message.answer(
            "Использование: /cmd &lt;команда&gt;\n\n"
            f"Доступно без прав: {', '.join(SAFE_CMDS)}",
            parse_mode="HTML",
        )
        return

    # For non-admins restrict to safe list
    allowed = None if user.is_admin else SAFE_CMDS

    await message.answer(f"Выполняю: <code>{command}</code>", parse_mode="HTML")

    pc = PCManager()
    result = await pc.execute_command(command, allowed_commands=allowed)

    output = result.get("output") or result.get("error") or "Нет вывода"
    icon = "✅" if result.get("success") else "❌"

    await message.answer(
        f"{icon} <pre>{output[:4000]}</pre>",
        parse_mode="HTML",
    )
    await db.add_log_entry(
        action="command_executed",
        user_id=user.id,
        details=f"cmd: {command!r}",
    )


# ---------------------------------------------------------------------------
# /processes — top processes by RAM
# ---------------------------------------------------------------------------

@router.message(Command("processes"))
async def cmd_processes(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer("Нет доступа.", reply_markup=get_main_keyboard(is_authorized=False))
        return

    pc = PCManager()
    procs = await pc.get_running_processes(limit=15)

    if not procs:
        await message.answer("Список процессов недоступен.")
        return

    lines = ["<b>Топ процессов (по RAM)</b>\n"]
    for i, p in enumerate(procs, 1):
        name = p.get("name", "?")
        mem = p.get("memory_percent") or 0
        cpu = p.get("cpu_percent") or 0
        lines.append(f"{i}. <code>{name}</code> | RAM: {mem:.1f}% | CPU: {cpu:.1f}%")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Callbacks: pc_commands menu
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "pc_commands", IsAuthorized())
async def callback_pc_commands(callback: CallbackQuery, bot: Bot) -> None:
    await callback.message.answer(
        "Управление ПК:",
        reply_markup=get_pc_commands_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "pc_status", IsAuthorized())
async def callback_pc_status(callback: CallbackQuery, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    pc = PCManager()
    info = await pc.get_system_info()

    if info:
        text = (
            "<b>Статус ПК</b>\n\n"
            f"CPU: {info.get('cpu_percent')}%\n"
            f"RAM: {info.get('memory_used_gb')}/{info.get('memory_total_gb')} ГБ "
            f"({info.get('memory_percent')}%)\n"
            f"Диск: {info.get('disk_used_gb')}/{info.get('disk_total_gb')} ГБ\n"
            f"Uptime: {info.get('uptime')}"
        )
    else:
        text = "Не удалось получить данные."

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "pc_screenshot", IsAuthorized())
async def callback_pc_screenshot(callback: CallbackQuery, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await callback.message.answer("Делаю скриншот…")
    pc = PCManager()
    data = await pc.take_screenshot()

    if data:
        photo = BufferedInputFile(data, filename="screenshot.png")
        await callback.message.answer_photo(photo, caption="Скриншот рабочего стола")
        await db.add_log_entry(action="screenshot_taken", user_id=user.id)
    else:
        await callback.message.answer("Не удалось сделать скриншот. Установите scrot.")
    await callback.answer()


@router.callback_query(F.data == "pc_reboot", IsAuthorized())
async def callback_pc_reboot(callback: CallbackQuery, bot: Bot) -> None:
    await callback.message.answer(
        "<b>Подтвердите перезагрузку</b>",
        reply_markup=get_confirm_keyboard("reboot"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "pc_shutdown", IsAuthorized())
async def callback_pc_shutdown(callback: CallbackQuery, bot: Bot) -> None:
    await callback.message.answer(
        "<b>Подтвердите выключение</b>",
        reply_markup=get_confirm_keyboard("shutdown"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "pc_cancel", IsAuthorized())
async def callback_pc_cancel(callback: CallbackQuery, bot: Bot) -> None:
    pc = PCManager()
    ok = await pc.cancel_shutdown()
    await callback.message.answer(
        "Отменено." if ok else "Нечего отменять."
    )
    await callback.answer()


@router.callback_query(F.data == "pc_processes", IsAuthorized())
async def callback_pc_processes(callback: CallbackQuery, bot: Bot) -> None:
    pc = PCManager()
    procs = await pc.get_running_processes(limit=10)

    if procs:
        lines = ["<b>Топ процессов</b>\n"]
        for p in procs:
            lines.append(
                f"• {p.get('name', '?')} | "
                f"RAM: {(p.get('memory_percent') or 0):.1f}% | "
                f"CPU: {(p.get('cpu_percent') or 0):.1f}%"
            )
        await callback.message.answer("\n".join(lines), parse_mode="HTML")
    else:
        await callback.message.answer("Список процессов недоступен.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Confirm / cancel actions
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("confirm_"), IsAuthorized())
async def callback_confirm(callback: CallbackQuery, bot: Bot) -> None:
    action = (callback.data or "").replace("confirm_", "")
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    pc = PCManager()
    notif = NotificationService()

    if action == "reboot":
        ok = await pc.reboot(delay_minutes=1)
        label = "перезагрузку"
    elif action == "shutdown":
        ok = await pc.shutdown(delay_minutes=1)
        label = "выключение"
    else:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return

    if ok:
        await callback.message.answer(
            f"ПК запланирован на {label} через 1 минуту.",
            reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin),
        )
        await db.add_log_entry(action=f"{action}_initiated", user_id=user.id)
        await notif.notify_all_users(
            f"ПК запланирован на {label} пользователем "
            f"@{callback.from_user.username or str(user.id)}."
        )
    else:
        await callback.message.answer(
            f"Не удалось выполнить {label}. Убедитесь, что бот запущен с правами sudo.",
            reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin),
        )
    await callback.answer()




@router.callback_query(F.data == "cancel_action")
async def callback_cancel_action(callback: CallbackQuery, bot: Bot) -> None:
    await callback.message.answer(
        "Действие отменено.",
        reply_markup=get_main_keyboard(is_authorized=True),
    )
    await callback.answer()
