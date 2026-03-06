"""PC control handlers — Cross-platform (Windows/Linux)."""

from __future__ import annotations

import platform
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
SAFE_CMDS_LINUX = ["ls", "pwd", "whoami", "hostname", "uname", "df", "free", "uptime", "ps", "ip"]
SAFE_CMDS_WINDOWS = ["dir", "cd", "type", "ipconfig", "hostname", "systeminfo", "ver", "whoami", "netstat", "tasklist"]


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
        import platform
        os_type = platform.system().lower()
        if os_type == "windows":
            safe = SAFE_CMDS_WINDOWS
        else:
            safe = SAFE_CMDS_LINUX
        await message.answer(
            f"Использование: /cmd &lt;команда&gt;\n\n"
            f"Доступно без прав: {', '.join(safe)}",
            parse_mode="HTML",
        )
        return

    # For non-admins restrict to safe list based on OS
    import platform
    os_type = platform.system().lower()
    if os_type == "windows":
        allowed = None if user.is_admin else SAFE_CMDS_WINDOWS
    else:
        allowed = None if user.is_admin else SAFE_CMDS_LINUX

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


@router.callback_query(F.data == "pc_sleep", IsAuthorized())
async def callback_pc_sleep(callback: CallbackQuery, bot: Bot) -> None:
    await callback.message.answer(
        "<b>Подтвердите спящий режим</b>",
        reply_markup=get_confirm_keyboard("sleep"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "pc_hibernate", IsAuthorized())
async def callback_pc_hibernate(callback: CallbackQuery, bot: Bot) -> None:
    await callback.message.answer(
        "<b>Подтвердите гибернацию</b>",
        reply_markup=get_confirm_keyboard("hibernate"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "pc_network", IsAuthorized())
async def callback_pc_network(callback: CallbackQuery, bot: Bot) -> None:
    pc = PCManager()
    connections = await pc.get_network_connections()

    if not connections:
        await callback.message.answer("Нет активных сетевых соединений.")
    else:
        lines = ["<b>Активные соединения</b>\n"]
        for c in connections[:15]:
            laddr = c.get("laddr", "")
            raddr = c.get("raddr", "")
            pid = c.get("pid", "?")
            lines.append(f"• {laddr} → {raddr} (PID:{pid})")
        await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "pc_collect_data", IsAuthorized())
async def callback_pc_collect_data(callback: CallbackQuery, bot: Bot) -> None:
    await callback.message.answer("Сбор данных…")
    pc = PCManager()
    data = await pc.collect_data()

    if not data or "error" in data:
        await callback.message.answer("Ошибка сбора данных.")
        await callback.answer()
        return

    sys_info = data.get("system", {})
    text = f"<b>📊 Данные ПК</b>\n\n"
    text += f"<b>ОС:</b> {sys_info.get('os', '?')} {sys_info.get('os_version', '')}\n"
    text += f"<b>Хост:</b> <code>{sys_info.get('hostname', '?')}</code>\n"
    text += f"<b>CPU:</b> <b>{sys_info.get('cpu_percent')}%</b>\n"
    text += f"<b>RAM:</b> <b>{sys_info.get('memory_used_gb')} / {sys_info.get('memory_total_gb')} ГБ</b> ({sys_info.get('memory_percent')}%)\n"
    text += f"<b>Диск:</b> <b>{sys_info.get('disk_used_gb')} / {sys_info.get('disk_total_gb')} ГБ</b> ({sys_info.get('disk_percent')}%)\n"
    text += f"<b>Uptime:</b> {sys_info.get('uptime', '?')}\n"
    
    if "battery_percent" in sys_info:
        battery_charging = "⚡" if sys_info.get("battery_charging") else "🔋"
        text += f"<b>Батарея:</b> {battery_charging} {sys_info.get('battery_percent')}%\n"

    partitions = data.get("disk_partitions", [])
    if partitions:
        text += "\n<b>Диски:</b>\n"
        for p in partitions[:5]:
            text += f"• {p.get('mountpoint', '?')}: {p.get('used_gb', 0)}/{p.get('total_gb', 0)} ГБ ({p.get('percent', 0)}%)\n"

    net_conn = data.get("network_connections", [])
    text += f"\n<b>Соединений:</b> {len(net_conn)}"

    await callback.message.answer(text, parse_mode="HTML")
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


# ---------------------------------------------------------------------------
# /collect_data — collect all PC stats
# ----------------------------------------------------------------------------

@router.message(Command("collect_data"))
async def cmd_collect_data(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer(
            "Нет доступа.",
            reply_markup=get_main_keyboard(is_authorized=False),
        )
        return

    await message.answer("Сбор данных о ПК…")
    pc = PCManager()
    data = await pc.collect_data()

    if not data or "error" in data:
        await message.answer("Ошибка сбора данных.")
        return

    # Format system info
    sys_info = data.get("system", {})
    text = f"<b>📊 Данные ПК</b>\n\n"
    text += f"<b>ОС:</b> {sys_info.get('os', '?')} {sys_info.get('os_version', '')}\n"
    text += f"<b>Хост:</b> <code>{sys_info.get('hostname', '?')}</code>\n"
    text += f"<b>CPU:</b> <b>{sys_info.get('cpu_percent')}%</b>\n"
    text += f"<b>RAM:</b> <b>{sys_info.get('memory_used_gb')} / {sys_info.get('memory_total_gb')} ГБ</b> ({sys_info.get('memory_percent')}%)\n"
    text += f"<b>Диск:</b> <b>{sys_info.get('disk_used_gb')} / {sys_info.get('disk_total_gb')} ГБ</b> ({sys_info.get('disk_percent')}%)\n"
    text += f"<b>Uptime:</b> {sys_info.get('uptime', '?')}\n"
    
    if "battery_percent" in sys_info:
        battery_charging = "🔌" if sys_info.get("battery_charging") else "🔋"
        text += f"<b>Батарея:</b> {battery_charging} {sys_info.get('battery_percent')}%\n"

    # Add disk partitions info
    partitions = data.get("disk_partitions", [])
    if partitions:
        text += "\n<b>Диски:</b>\n"
        for p in partitions[:5]:
            text += f"• {p.get('mountpoint', '?')}: {p.get('used_gb', 0)}/{p.get('total_gb', 0)} ГБ ({p.get('percent', 0)}%)\n"

    # Network connections count
    net_conn = data.get("network_connections", [])
    text += f"\n<b>Активных соединений:</b> {len(net_conn)}"

    await message.answer(text, parse_mode="HTML")
    await db.add_log_entry(action="collect_data", user_id=user.id)


# ---------------------------------------------------------------------------
# /list_processes — list all running processes
# ----------------------------------------------------------------------------

@router.message(Command("list_processes"))
async def cmd_list_processes(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer(
            "Нет доступа.",
            reply_markup=get_main_keyboard(is_authorized=False),
        )
        return

    pc = PCManager()
    procs = await pc.get_running_processes(limit=30)

    if not procs:
        await message.answer("Список процессов недоступен.")
        return

    lines = ["<b>Запущенные процессы (топ по RAM)</b>\n"]
    for i, p in enumerate(procs, 1):
        name = p.get("name", "?")[:30]
        pid = p.get("pid", "?")
        mem = p.get("memory_percent") or 0
        cpu = p.get("cpu_percent") or 0
        lines.append(f"{i}. <code>{name}</code> (PID:{pid}) | RAM:{mem:.1f}% CPU:{cpu:.1f}%")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ---------------------------------------------------------------------------
# /kill_process — kill a process by PID or name
# ----------------------------------------------------------------------------

@router.message(Command("kill_process"))
async def cmd_kill_process(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer(
            "Нет доступа.",
            reply_markup=get_main_keyboard(is_authorized=False),
        )
        return

    # Parse command arguments
    args = (message.text or "").replace("/kill_process", "", 1).strip()
    if not args:
        await message.answer(
            "Использование: /kill_process <PID или имя>\n\n"
            "Примеры:\n"
            "• /kill_process 1234\n"
            "• /kill_process chrome",
            parse_mode="HTML",
        )
        return

    pc = PCManager()

    # Try to parse as PID first
    try:
        pid = int(args)
        proc_info = await pc.get_process_by_pid(pid)
        if proc_info:
            await message.answer(
                f"<b>Подтвердите завершение процесса:</b>\n\n"
                f"Имя: <code>{proc_info.get('name', '?')}</code>\n"
                f"PID: {pid}\n"
                f"Статус: {proc_info.get('status', '?')}",
                reply_markup=get_confirm_keyboard(f"kill_pid_{pid}"),
                parse_mode="HTML",
            )
        else:
            await message.answer(f"Процесс с PID {pid} не найден.")
        return
    except ValueError:
        # Not a number, try to find by name
        pass

    # Try to kill by name
    killed = await pc.kill_process_by_name(args)
    if killed > 0:
        await message.answer(
            f"✅ Завершено процессов: {killed}\n\n"
            f"(Все процессы с именем содержащим '{args}')",
        )
        await db.add_log_entry(
            action="process_killed_by_name",
            user_id=user.id,
            details=f"name: {args}, count: {killed}",
        )
    else:
        await message.answer(f"Процессы с именем '{args}' не найдены.")


# ---------------------------------------------------------------------------
# /sleep — put PC to sleep
# ----------------------------------------------------------------------------

@router.message(Command("sleep"))
async def cmd_sleep(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer(
            "Нет доступа.",
            reply_markup=get_main_keyboard(is_authorized=False),
        )
        return

    await message.answer(
        "<b>Подтвердите спящий режим</b>\n\nПК перейдёт в спящий режим.\nОтменить: /cancel",
        reply_markup=get_confirm_keyboard("sleep"),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# /hibernate — put PC to hibernate
# ----------------------------------------------------------------------------

@router.message(Command("hibernate"))
async def cmd_hibernate(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer(
            "Нет доступа.",
            reply_markup=get_main_keyboard(is_authorized=False),
        )
        return

    await message.answer(
        "<b>Подтвердите гибернацию</b>\n\nПК перейдёт в режим гибернации.\nОтменить: /cancel",
        reply_markup=get_confirm_keyboard("hibernate"),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# /network — show network connections
# ----------------------------------------------------------------------------

@router.message(Command("network"))
async def cmd_network(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not user or not user.is_authorized:
        await message.answer(
            "Нет доступа.",
            reply_markup=get_main_keyboard(is_authorized=False),
        )
        return

    pc = PCManager()
    connections = await pc.get_network_connections()

    if not connections:
        await message.answer("Нет активных сетевых соединений.")
        return

    lines = ["<b>Активные сетевые соединения</b>\n"]
    for c in connections[:15]:
        laddr = c.get("laddr", "")
        raddr = c.get("raddr", "")
        pid = c.get("pid", "?")
        lines.append(f"• {laddr} → {raddr} (PID:{pid})")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Callback handlers for new confirmations
# ----------------------------------------------------------------------------

@router.callback_query(F.data.startswith("confirm_sleep"), IsAuthorized())
async def callback_confirm_sleep(callback: CallbackQuery, bot: Bot) -> None:
    pc = PCManager()
    ok = await pc.sleep()
    
    await callback.message.answer(
        "ПК переходит в спящий режим." if ok else "Не удалось перевести ПК в спячий режим.",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_hibernate"), IsAuthorized())
async def callback_confirm_hibernate(callback: CallbackQuery, bot: Bot) -> None:
    pc = PCManager()
    ok = await pc.hibernate()
    
    await callback.message.answer(
        "ПК переходит в режим гибернации." if ok else "Не удалось перевести ПК в режим гибернации.",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_kill_pid_"), IsAuthorized())
async def callback_confirm_kill(callback: CallbackQuery, bot: Bot) -> None:
    try:
        pid = int(callback.data.replace("confirm_kill_pid_", ""))
    except ValueError:
        await callback.answer("Неверный PID.", show_alert=True)
        return

    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    
    pc = PCManager()
    ok = await pc.kill_process(pid)
    
    if ok:
        await callback.message.answer(f"✅ Процесс PID {pid} завершён.")
        await db.add_log_entry(
            action="process_killed",
            user_id=user.id if user else None,
            details=f"pid: {pid}",
        )
    else:
        await callback.message.answer(
            f"❌ Не удалось завершить процесс PID {pid}.\n"
            f"Возможно, требуются права администратора.",
        )
    await callback.answer()
