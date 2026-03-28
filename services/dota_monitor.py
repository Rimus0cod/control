"""
Dota 2 monitor service.

Uses two APIs:
  * Steam Web API   — player online/in-game status, match history
  * OpenDota API    — real-time live match, per-player buffs (permanent buffs),
                      full hero list, detailed match data

OpenDota free tier: ~2 000 req/day (no key needed for most endpoints).
Steam API key is read from DOTA2_STEAM_API_KEY env-var.
Player account ID (32-bit) is read from DOTA2_ACCOUNT_ID.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger

from config import get_settings
from database import DatabaseRepository

settings = get_settings()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STEAM_API_BASE = "https://api.steampowered.com"
OPENDOTA_BASE = "https://api.opendota.com/api"
STEAM_ID_OFFSET = 76561197960265728

# Game mode names (most common)
GAME_MODES: Dict[int, str] = {
    0: "Unknown",
    1: "All Pick",
    2: "Captain's Mode",
    3: "Random Draft",
    4: "Single Draft",
    5: "All Random",
    6: "Intro",
    7: "Diretide",
    8: "Reverse CM",
    9: "The Greeviling",
    10: "Tutorial",
    11: "Mid Only",
    12: "Least Played",
    13: "New Player Pool",
    14: "Compendium",
    15: "Custom",
    16: "Captain's Draft",
    17: "Balanced Draft",
    18: "Ability Draft",
    19: "Event",
    20: "ARDM",
    21: "All Draft (AP)",
    22: "Ranked",
    23: "Turbo",
    24: "Mutation",
}

# Lobby types
LOBBY_TYPES: Dict[int, str] = {
    -1: "Invalid",
    0: "Public Matchmaking",
    1: "Practice",
    2: "Tournament",
    3: "Tutorial",
    4: "Co-op vs Bots",
    5: "Team Match",
    6: "Solo Queue",
    7: "Ranked",
    8: "1v1 Solo Mid",
}

# Permanent buff names (item/ability IDs from OpenDota)
BUFF_NAMES: Dict[int, str] = {
    # Aghanim's upgrades tracked as permanent buffs
    108:  "Aghanim's Scepter",
    609:  "Aghanim's Shard",
    # Common permanent items on unit
    235:  "Moon Shard (consumed)",
    # Roshan drops
    102:  "Aegis of the Immortal",
    603:  "Cheese",
    604:  "Refresher Shard",
    # Ability permanent buffs (ability_id references)
    5004: "Rupture (Bloodseeker)",
    5317: "Glyph of Fortification",
}


class DotaMonitor:
    """Dota 2 player and match monitoring service (Steam + OpenDota)."""

    def __init__(
        self,
        steam_api_key: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> None:
        self.steam_api_key = steam_api_key or settings.dota2_steam_api_key
        # account_id can be either 64-bit Steam ID or 32-bit Dota ID
        raw_id = account_id or settings.dota2_account_id or "0"
        self.account_id_64 = int(raw_id)
        self.account_id_32 = self._to_32bit(self.account_id_64)
        self.db = DatabaseRepository()
        self._hero_cache: Dict[int, str] = {}  # hero_id → hero name

    # ------------------------------------------------------------------
    # ID helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_32bit(steam_id: int) -> int:
        """Convert 64-bit Steam ID → 32-bit Dota account ID."""
        result = steam_id - STEAM_ID_OFFSET
        if result < 0:
            # Already a 32-bit ID
            return steam_id
        return result

    @staticmethod
    def _to_64bit(account_id: int) -> int:
        """Convert 32-bit Dota account ID → 64-bit Steam ID."""
        if account_id > STEAM_ID_OFFSET:
            return account_id
        return account_id + STEAM_ID_OFFSET

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _steam_get(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """GET request to Steam Web API."""
        if not self.steam_api_key:
            logger.warning("Steam API key not configured.")
            return None
        p = dict(params or {})
        p["key"] = self.steam_api_key
        url = f"{STEAM_API_BASE}/{endpoint}"
        return await _http_get(url, p)

    async def _opendota_get(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """GET request to OpenDota API (no key required for public data)."""
        url = f"{OPENDOTA_BASE}/{endpoint}"
        return await _http_get(url, params)

    # ------------------------------------------------------------------
    # Hero name resolution (cached from OpenDota)
    # ------------------------------------------------------------------

    async def _ensure_hero_cache(self) -> None:
        """Populate hero name cache from OpenDota /heroes if empty."""
        if self._hero_cache:
            return
        data = await self._opendota_get("heroes")
        if isinstance(data, list):
            for hero in data:
                self._hero_cache[hero["id"]] = hero.get("localized_name", f"Hero {hero['id']}")
            logger.info(f"Hero cache loaded: {len(self._hero_cache)} heroes.")

    def get_hero_name(self, hero_id: int) -> str:
        """Resolve hero name by ID (uses cache)."""
        return self._hero_cache.get(hero_id, f"Hero #{hero_id}")

    def get_game_mode(self, mode_id: int) -> str:
        """Resolve game mode name by ID."""
        return GAME_MODES.get(mode_id, f"Mode #{mode_id}")

    # ------------------------------------------------------------------
    # Steam: player online / in-game status
    # ------------------------------------------------------------------

    async def get_player_summary(self) -> Optional[Dict[str, Any]]:
        """Return Steam player summary for the configured account."""
        steam_id_64 = self._to_64bit(self.account_id_32)
        data = await self._steam_get(
            "ISteamUser/GetPlayerSummaries/v0002/",
            {"steamids": str(steam_id_64)},
        )
        players = (data or {}).get("response", {}).get("players", [])
        return players[0] if players else None

    async def get_player_status(self) -> Dict[str, Any]:
        """
        High-level player status: online, in Dota 2, last match summary.
        """
        await self._ensure_hero_cache()

        status: Dict[str, Any] = {
            "online": False,
            "in_game": False,
            "match_id": None,
            "hero": None,
            "player_name": None,
            "last_match": None,
        }

        summary = await self.get_player_summary()
        if summary:
            status["player_name"] = summary.get("personaname")
            persona_state = summary.get("personastate", 0)
            status["online"] = persona_state > 0

            if summary.get("gameid") == "570":
                status["in_game"] = True
                status["game_extra"] = summary.get("gameextrainfo", "Dota 2")

        # Last played match from OpenDota
        recent = await self._opendota_get(
            f"players/{self.account_id_32}/recentMatches"
        )
        if isinstance(recent, list) and recent:
            m = recent[0]
            hero_id = m.get("hero_id", 0)
            status["last_match"] = {
                "match_id": m.get("match_id"),
                "hero_id": hero_id,
                "hero_name": self.get_hero_name(hero_id),
                "kills": m.get("kills", 0),
                "deaths": m.get("deaths", 0),
                "assists": m.get("assists", 0),
                "duration_min": round(m.get("duration", 0) / 60, 1),
                "won": m.get("radiant_win") == (m.get("player_slot", 0) < 128),
                "started_at": datetime.utcfromtimestamp(
                    m["start_time"]
                ).strftime("%Y-%m-%d %H:%M UTC")
                if m.get("start_time")
                else None,
            }

        return status

    # ------------------------------------------------------------------
    # OpenDota: match history
    # ------------------------------------------------------------------

    async def get_match_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent match summaries from OpenDota."""
        await self._ensure_hero_cache()
        data = await self._opendota_get(
            f"players/{self.account_id_32}/matches",
            {"limit": limit},
        )
        if not isinstance(data, list):
            return []

        result = []
        for m in data:
            hero_id = int(m.get("hero_id") or 0)
            result.append({
                "match_id": m.get("match_id"),
                "hero_id": hero_id,
                "hero_name": self.get_hero_name(hero_id),
                "kills": m.get("kills", 0),
                "deaths": m.get("deaths", 0),
                "assists": m.get("assists", 0),
                "duration_min": round(m.get("duration", 0) / 60, 1),
                "game_mode": self.get_game_mode(m.get("game_mode", 0)),
                "won": m.get("radiant_win") == (m.get("player_slot", 0) < 128),
                "started_at": datetime.utcfromtimestamp(
                    m["start_time"]
                ).strftime("%Y-%m-%d %H:%M UTC")
                if m.get("start_time")
                else None,
            })
        return result

    # ------------------------------------------------------------------
    # OpenDota: full match details with per-player buffs
    # ------------------------------------------------------------------

    async def get_match_details(self, match_id: int) -> Optional[Dict[str, Any]]:
        """Return full match details from OpenDota."""
        return await self._opendota_get(f"matches/{match_id}")

    async def get_match_buffs(self, match_id: int) -> Dict[str, Any]:
        """
        Return permanent buffs for every player in the match.

        Structure:
        {
            "match_id": int,
            "players": [
                {
                    "account_id": int,
                    "hero_name": str,
                    "team": "Radiant" | "Dire",
                    "buffs": [{"name": str, "stack_count": int}, ...],
                    "kda": "k/d/a",
                    "net_worth": int,
                    "level": int,
                }
            ]
        }
        """
        await self._ensure_hero_cache()
        details = await self.get_match_details(match_id)
        if not details or "players" not in details:
            return {"match_id": match_id, "players": []}

        players_out = []
        for p in details["players"]:
            slot = p.get("player_slot", 0)
            team = "Radiant" if slot < 128 else "Dire"
            hero_id = p.get("hero_id", 0)

            # permanent_buffs is a list of {permanent_buff, stack_count}
            raw_buffs = p.get("permanent_buffs") or []
            buffs = []
            for b in raw_buffs:
                buff_id = b.get("permanent_buff", 0)
                count = b.get("stack_count", 1)
                name = BUFF_NAMES.get(buff_id, f"Buff #{buff_id}")
                buffs.append({"name": name, "stack_count": count})

            players_out.append({
                "account_id": p.get("account_id"),
                "hero_name": self.get_hero_name(hero_id),
                "team": team,
                "buffs": buffs,
                "kda": f"{p.get('kills', 0)}/{p.get('deaths', 0)}/{p.get('assists', 0)}",
                "net_worth": p.get("total_gold", 0),
                "level": p.get("level", 0),
                "damage_dealt": p.get("hero_damage", 0),
            })

        # Sort: Radiant first, then Dire
        players_out.sort(key=lambda x: (0 if x["team"] == "Radiant" else 1))

        return {
            "match_id": match_id,
            "duration_min": round(details.get("duration", 0) / 60, 1),
            "game_mode": self.get_game_mode(details.get("game_mode", 0)),
            "radiant_win": details.get("radiant_win"),
            "players": players_out,
        }

    # ------------------------------------------------------------------
    # OpenDota: live match (real-time)
    # ------------------------------------------------------------------

    async def get_live_match(self) -> Optional[Dict[str, Any]]:
        """
        Fetch the player's currently running live match via OpenDota /live.

        OpenDota /live returns matches that are in progress.
        We scan for a match where the configured player is a participant.

        Returns None if the player is not in a live match.
        """
        await self._ensure_hero_cache()
        live_data = await self._opendota_get("live")
        if not isinstance(live_data, list):
            return None

        for match in live_data:
            players = match.get("players") or []
            for p in players:
                # OpenDota /live uses account_id (32-bit)
                if int(p.get("account_id", -1)) == self.account_id_32:
                    return await self._format_live_match(match)

        return None

    async def _format_live_match(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Format a raw OpenDota /live match entry."""
        players_out = []
        for p in raw.get("players", []):
            hero_id = p.get("hero_id", 0)
            slot = p.get("team", 0)  # 0=Radiant, 1=Dire in /live
            team = "Radiant" if slot == 0 else "Dire"

            # Permanent buffs are available in live data too
            raw_buffs = p.get("permanent_buffs") or []
            buffs = []
            for b in raw_buffs:
                buff_id = b.get("permanent_buff", 0)
                count = b.get("stack_count", 1)
                name = BUFF_NAMES.get(buff_id, f"Buff #{buff_id}")
                buffs.append({"name": name, "stack_count": count})

            players_out.append({
                "account_id": p.get("account_id"),
                "hero_name": self.get_hero_name(hero_id),
                "team": team,
                "buffs": buffs,
                "net_worth": p.get("net_worth", 0),
                "level": p.get("level", 0),
                "kills": p.get("kills", 0),
                "deaths": p.get("deaths", 0),
                "assists": p.get("assists", 0),
            })

        players_out.sort(key=lambda x: (0 if x["team"] == "Radiant" else 1))

        elapsed_sec = raw.get("game_time", 0)
        elapsed_min = elapsed_sec // 60
        elapsed_s = elapsed_sec % 60

        return {
            "match_id": raw.get("match_id"),
            "game_time": f"{elapsed_min}:{elapsed_s:02d}",
            "game_mode": self.get_game_mode(raw.get("game_mode", 0)),
            "radiant_score": raw.get("radiant_score", 0),
            "dire_score": raw.get("dire_score", 0),
            "players": players_out,
        }

    # ------------------------------------------------------------------
    # DB helpers (new match detection for notifications)
    # ------------------------------------------------------------------

    async def check_new_matches(self) -> List[Dict[str, Any]]:
        """Return matches played since the last DB record."""
        last = await self.db.get_last_dota_match()
        matches = await self.get_match_history(5)
        new: List[Dict[str, Any]] = []
        for m in matches:
            if last and last.match_id == m["match_id"]:
                break
            new.append(m)
            await self.db.add_dota_match(m)
        return new


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

async def _http_get(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Perform an async GET request, return parsed JSON or None."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                logger.warning(f"HTTP {resp.status} for {url}")
                return None
    except asyncio.TimeoutError:
        logger.error(f"Timeout fetching {url}")
        return None
    except Exception as exc:
        logger.error(f"HTTP error for {url}: {exc}")
        return None