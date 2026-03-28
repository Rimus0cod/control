"""
Dota 2 handlers.

Commands:
  /dota          — текущий статус игрока (онлайн / в игре, последний матч)
  /dotahistory   — последние 10 матчей с KDA и героями
  /doталive       — реал-тайм данные текущего матча (OpenDota /live)
  /dotabuffs <match_id>  — перманентные баффы всех игроков в матче

Callbacks:
  dota_status   — аналог /dota
  dota_live     — аналог /dotaLive
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.filters import IsAuthorized
from bot.keyboards import get_dota_keyboard, get_main_keyboard
from database import DatabaseRepository
from services import DotaMonitor
from utils import get_logger

router = Router()
logger = get_logger(__name__)


def _auth_check_sync(user) -> bool:
    return user is not None and user.is_authorized


# ---------------------------------------------------------------------------
# /dota — player status
# ---------------------------------------------------------------------------

@router.message(Command("dota"))
async def cmd_dota(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not _auth_check_sync(user):
        await message.answer("Нет доступа.", reply_markup=get_main_keyboard(is_authorized=False))
        return

    wait = await message.answer("Загружаю данные Dota 2…")
    monitor = DotaMonitor()
    status = await monitor.get_player_status()

    online = "Онлайн" if status.get("online") else "Оффлайн"
    in_game = "В игре" if status.get("in_game") else "Не в игре"

    lines = [
        "<b>Dota 2 — статус игрока</b>\n",
        f"Игрок: <b>{status.get('player_name', '?')}</b>",
        f"Steam: {online}  |  {in_game}",
    ]

    if status.get("in_game"):
        lines.append(f"Игра: {status.get('game_extra', 'Dota 2')}")

    last = status.get("last_match")
    if last:
        won = "Победа" if last.get("won") else "Поражение"
        lines += [
            "",
            "<b>Последний матч</b>",
            f"Герой: {last.get('hero_name', '?')}",
            f"KDA: <code>{last.get('kills', 0)}/{last.get('deaths', 0)}/{last.get('assists', 0)}</code>",
            f"Длительность: {last.get('duration_min', '?')} мин",
            f"Результат: {won}",
            f"Дата: {last.get('started_at', '?')}",
        ]

    await wait.delete()
    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=get_dota_keyboard(),
    )
    assert user is not None
    await db.add_log_entry(action="dota_status_check", user_id=user.id)


# ---------------------------------------------------------------------------
# /dotahistory — last N matches
# ---------------------------------------------------------------------------

@router.message(Command("dotahistory"))
async def cmd_dota_history(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not _auth_check_sync(user):
        await message.answer("Нет доступа.", reply_markup=get_main_keyboard(is_authorized=False))
        return

    wait = await message.answer("Загружаю историю матчей…")
    monitor = DotaMonitor()
    matches = await monitor.get_match_history(limit=10)

    await wait.delete()

    if not matches:
        await message.answer("Нет данных об играх.")
        return

    lines = ["<b>Последние матчи</b>\n"]
    for i, m in enumerate(matches, 1):
        won = "✅" if m.get("won") else "❌"
        lines.append(
            f"{i}. {won} <b>{m.get('hero_name', '?')}</b> | "
            f"<code>{m.get('kills', 0)}/{m.get('deaths', 0)}/{m.get('assists', 0)}</code> | "
            f"{m.get('duration_min', '?')} мин | {m.get('game_mode', '?')}"
        )

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin),
    )
    await db.add_log_entry(action="dota_history_check", user_id=user.id)


# ---------------------------------------------------------------------------
# /dotalive — real-time match via OpenDota /live
# ---------------------------------------------------------------------------

@router.message(Command("dotalive"))
async def cmd_dota_live(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not _auth_check_sync(user):
        await message.answer("Нет доступа.", reply_markup=get_main_keyboard(is_authorized=False))
        return

    wait = await message.answer("Ищу активный матч в реал-тайм…")
    monitor = DotaMonitor()
    live = await monitor.get_live_match()

    await wait.delete()

    if not live:
        await message.answer(
            "Активный матч не найден.\n"
            "OpenDota /live может задерживаться на ~5 минут после начала игры."
        )
        return

    await message.answer(
        _format_live(live),
        parse_mode="HTML",
        reply_markup=get_dota_keyboard(),
    )
    await db.add_log_entry(action="dota_live_check", user_id=user.id)


def _format_live(live: dict) -> str:
    """Format a live match dict into HTML message."""
    rad_score = live.get("radiant_score", 0)
    dire_score = live.get("dire_score", 0)
    game_time = live.get("game_time", "?")
    mode = live.get("game_mode", "?")
    match_id = live.get("match_id", "?")

    lines = [
        f"<b>LIVE Матч #{match_id}</b>",
        f"Режим: {mode}  |  Время: {game_time}",
        f"Счёт: Radiant <b>{rad_score}</b> : <b>{dire_score}</b> Dire",
        "",
    ]

    current_team = None
    for p in live.get("players", []):
        team = p.get("team", "?")
        if team != current_team:
            current_team = team
            lines.append(f"<b>— {team} —</b>")

        hero = p.get("hero_name", "?")
        kda = f"{p.get('kills', 0)}/{p.get('deaths', 0)}/{p.get('assists', 0)}"
        nw = p.get("net_worth", 0)
        lvl = p.get("level", 0)
        buffs = p.get("buffs", [])

        line = f"  {hero} | KDA: <code>{kda}</code> | Lvl {lvl} | NW: {nw}"
        if buffs:
            buff_str = ", ".join(
                f"{b['name']}" + (f" ×{b['stack_count']}" if b["stack_count"] > 1 else "")
                for b in buffs
            )
            line += f"\n    Баффы: {buff_str}"
        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /dotabuffs <match_id> — permanent buffs for finished match
# ---------------------------------------------------------------------------

@router.message(Command("dotabuffs"))
async def cmd_dota_buffs(message: Message, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if not _auth_check_sync(user):
        await message.answer("Нет доступа.", reply_markup=get_main_keyboard(is_authorized=False))
        return

    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) < 2:
        # Try last played match
        monitor = DotaMonitor()
        recent = await monitor.get_match_history(limit=1)
        if not recent:
            await message.answer("Укажите ID матча: /dotabuffs <match_id>")
            return
        match_id = recent[0]["match_id"]
    else:
        try:
            match_id = int(parts[1])
        except ValueError:
            await message.answer("Некорректный match_id. Пример: /dotabuffs 7654321000")
            return

    wait = await message.answer(f"Загружаю баффы для матча #{match_id}…")
    monitor = DotaMonitor()
    result = await monitor.get_match_buffs(match_id)

    await wait.delete()

    if not result or not result.get("players"):
        await message.answer(f"Данные для матча #{match_id} недоступны.")
        return

    await message.answer(
        _format_buffs(result),
        parse_mode="HTML",
    )
    await db.add_log_entry(action="dota_buffs_check", user_id=user.id, details=str(match_id))


def _format_buffs(data: dict) -> str:
    mid = data.get("match_id", "?")
    dur = data.get("duration_min", "?")
    mode = data.get("game_mode", "?")
    winner = "Radiant" if data.get("radiant_win") else "Dire"

    lines = [
        f"<b>Баффы игроков — Матч #{mid}</b>",
        f"Режим: {mode}  |  Длительность: {dur} мин  |  Победа: {winner}",
        "",
    ]

    current_team = None
    for p in data.get("players", []):
        team = p.get("team", "?")
        if team != current_team:
            current_team = team
            lines.append(f"<b>— {team} —</b>")

        hero = p.get("hero_name", "?")
        kda = p.get("kda", "?")
        nw = p.get("net_worth", 0)
        lvl = p.get("level", 0)
        buffs = p.get("buffs", [])

        line = f"  {hero} | {kda} | Lvl {lvl} | {nw} золота"
        if buffs:
            buff_str = ", ".join(
                f"{b['name']}" + (f" ×{b['stack_count']}" if b["stack_count"] > 1 else "")
                for b in buffs
            )
            line += f"\n    Баффы: <i>{buff_str}</i>"
        else:
            line += "\n    Баффы: нет"
        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "dota_status", IsAuthorized())
async def callback_dota_status(callback: CallbackQuery, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    monitor = DotaMonitor()
    status = await monitor.get_player_status()

    online = "Онлайн" if status.get("online") else "Оффлайн"
    in_game = "В игре" if status.get("in_game") else "Не в игре"
    name = status.get("player_name", "?")

    text = f"<b>{name}</b> — {online} | {in_game}"
    last = status.get("last_match")
    if last:
        text += (
            f"\n\nПоследний: {last.get('hero_name', '?')} "
            f"<code>{last.get('kills', 0)}/{last.get('deaths', 0)}/{last.get('assists', 0)}</code>"
        )

    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_dota_keyboard())
    await callback.answer()


@router.callback_query(F.data == "dota_live", IsAuthorized())
async def callback_dota_live(callback: CallbackQuery, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await callback.message.answer("Ищу активный матч…")
    monitor = DotaMonitor()
    live = await monitor.get_live_match()

    if live:
        await callback.message.answer(_format_live(live), parse_mode="HTML")
    else:
        await callback.message.answer("Активный матч не найден.")
    await callback.answer()


@router.callback_query(F.data == "dota_history", IsAuthorized())
async def callback_dota_history(callback: CallbackQuery, bot: Bot) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    monitor = DotaMonitor()
    matches = await monitor.get_match_history(limit=10)

    if not matches:
        await callback.message.answer("Нет данных об играх.")
        await callback.answer()
        return

    lines = ["<b>Последние матчи</b>\n"]
    for i, m in enumerate(matches, 1):
        won = "✅" if m.get("won") else "❌"
        lines.append(
            f"{i}. {won} <b>{m.get('hero_name', '?')}</b> | "
            f"<code>{m.get('kills', 0)}/{m.get('deaths', 0)}/{m.get('assists', 0)}</code> | "
            f"{m.get('duration_min', '?')} мин"
        )

    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()