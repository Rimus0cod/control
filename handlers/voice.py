"""
Voice command handler.

Listens for Telegram voice messages from authorised users,
transcribes them with Whisper and executes the matching bot action.

Supported commands (Russian & English):
  reboot     — перезагрузка
  shutdown   — выключение
  cancel     — отмена выключения
  screenshot — скриншот
  status     — статус
  processes  — процессы
  dota       — статус доты
  wake       — включи компьютер
"""

from __future__ import annotations

import io

from aiogram import Bot, F, Router
from aiogram.types import BufferedInputFile, Message

from bot.filters import IsAuthorized
from bot.keyboards import get_main_keyboard
from database import DatabaseRepository
from services import PCManager, WakeOnLanService
from services.voice_handler import VoiceCommandService
from utils import get_logger

router = Router()
logger = get_logger(__name__)

_voice_service = VoiceCommandService()


@router.message(F.voice | F.audio, IsAuthorized())
async def handle_voice_message(message: Message, bot: Bot) -> None:
    """Process a voice/audio message and execute the recognised command."""

    # ------------------------------------------------------------------ #
    # 0. Check Whisper availability
    # ------------------------------------------------------------------ #
    if not _voice_service.available:
        await message.answer(
            "Голосовые команды недоступны.\n"
            "Установите Whisper: <code>pip install openai-whisper</code> "
            "и ffmpeg: <code>pacman -S ffmpeg</code>",
            parse_mode="HTML",
        )
        return

    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user or not user.is_authorized:
        await message.answer("Нет доступа.")
        return

    # ------------------------------------------------------------------ #
    # 1. Download the voice file
    # ------------------------------------------------------------------ #
    file_obj = message.voice or message.audio
    processing_msg = await message.answer("Распознаю голосовую команду…")

    try:
        file_info = await bot.get_file(file_obj.file_id)
        buf = io.BytesIO()
        await bot.download_file(file_info.file_path, destination=buf)
        ogg_bytes = buf.getvalue()
    except Exception as exc:
        logger.error(f"Failed to download voice file: {exc}")
        await processing_msg.edit_text("Не удалось скачать аудио-файл.")
        return

    # ------------------------------------------------------------------ #
    # 2. Transcribe + parse
    # ------------------------------------------------------------------ #
    text, command = await _voice_service.process_voice(ogg_bytes)

    if text is None:
        await processing_msg.edit_text("Ошибка при распознавании речи.")
        return

    if command is None:
        await processing_msg.edit_text(
            f'Сказано: <i>"{text}"</i>\n\n'
            "Команда не распознана. Доступные команды:\n"
            "• <b>скриншот</b> / screenshot\n"
            "• <b>статус</b> / status\n"
            "• <b>процессы</b> / processes\n"
            "• <b>перезагрузи</b> / reboot\n"
            "• <b>выключи</b> / shutdown\n"
            "• <b>отмени выключение</b> / cancel shutdown\n"
            "• <b>включи компьютер</b> / wake\n"
            "• <b>дота</b> / dota",
            parse_mode="HTML",
        )
        return

    await processing_msg.edit_text(
        f'Распознано: <i>"{text}"</i>\nВыполняю команду: <b>{command}</b>…',
        parse_mode="HTML",
    )

    # ------------------------------------------------------------------ #
    # 3. Execute command
    # ------------------------------------------------------------------ #
    await db.add_log_entry(
        action=f"voice_command_{command}",
        user_id=user.id,
        details=f"transcribed: {text!r}",
    )

    pc_manager = PCManager()

    match command:
        case "screenshot":
            data = await pc_manager.take_screenshot()
            if data:
                photo = BufferedInputFile(data, filename="screenshot.png")
                await message.answer_photo(
                    photo,
                    caption="Скриншот рабочего стола",
                )
            else:
                await message.answer(
                    "Не удалось сделать скриншот.\n"
                    "Убедитесь, что установлен <code>scrot</code> или ImageMagick.",
                    parse_mode="HTML",
                )

        case "status":
            info = await pc_manager.get_system_info()
            if info:
                text_reply = (
                    "<b>Статус ПК</b>\n\n"
                    f"CPU: {info.get('cpu_percent')}%\n"
                    f"RAM: {info.get('memory_used_gb')} / {info.get('memory_total_gb')} ГБ "
                    f"({info.get('memory_percent')}%)\n"
                    f"Диск: {info.get('disk_used_gb')} / {info.get('disk_total_gb')} ГБ "
                    f"({info.get('disk_percent')}%)\n"
                    f"Uptime: {info.get('uptime')}\n"
                    f"Хост: {info.get('hostname')}"
                )
                await message.answer(text_reply, parse_mode="HTML")
            else:
                await message.answer("Не удалось получить информацию о системе.")

        case "processes":
            procs = await pc_manager.get_running_processes(limit=10)
            if procs:
                lines = ["<b>Топ процессов</b>\n"]
                for p in procs:
                    lines.append(
                        f"• {p.get('name','?')} | "
                        f"MEM: {p.get('memory_percent', 0):.1f}% | "
                        f"CPU: {p.get('cpu_percent', 0):.1f}%"
                    )
                await message.answer("\n".join(lines), parse_mode="HTML")
            else:
                await message.answer("Список процессов недоступен.")

        case "reboot":
            ok = await pc_manager.reboot(delay_minutes=1)
            await message.answer(
                "Перезагрузка через 1 минуту! Отмените командой /cancel." if ok
                else "Не удалось инициировать перезагрузку."
            )

        case "shutdown":
            ok = await pc_manager.shutdown(delay_minutes=1)
            await message.answer(
                "Выключение через 1 минуту! Отмените командой /cancel." if ok
                else "Не удалось инициировать выключение."
            )

        case "cancel":
            ok = await pc_manager.cancel_shutdown()
            await message.answer(
                "Отложенное выключение/перезагрузка отменены." if ok
                else "Ничего не было запланировано."
            )

        case "wake":
            wol = WakeOnLanService()
            ok = await wol.wake(retries=3)
            await message.answer(
                "Магический пакет отправлен — ПК должен включиться." if ok
                else "Не удалось отправить WoL-пакет."
            )

        case "dota":
            # Import here to avoid circular deps
            from services import DotaMonitor  # noqa: PLC0415

            monitor = DotaMonitor()
            status = await monitor.get_player_status()
            online = "Онлайн" if status.get("online") else "Оффлайн"
            in_game = "В игре" if status.get("in_game") else "Не в игре"
            text_reply = (
                f"<b>Dota 2</b>\n"
                f"Игрок: {status.get('player_name', '?')}\n"
                f"Статус: {online} | {in_game}"
            )
            last = status.get("last_match")
            if last:
                text_reply += (
                    f"\n\nПоследний матч: {last.get('hero_name', '?')} | "
                    f"{last.get('kills', 0)}/{last.get('deaths', 0)}/{last.get('assists', 0)}"
                )
            await message.answer(text_reply, parse_mode="HTML")

        case _:
            await message.answer(f"Команда <b>{command}</b> ещё не реализована.", parse_mode="HTML")

    # Show main keyboard after any command
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin),
    )