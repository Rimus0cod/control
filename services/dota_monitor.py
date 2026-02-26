"""Dota 2 player monitoring service."""
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, List

import aiohttp
from loguru import logger

from config import get_settings
from database import DatabaseRepository


class SteamAPIError(Exception):
    """Base exception for Steam API errors."""
    pass


class SteamAPIAuthError(SteamAPIError):
    """Authentication error with Steam API."""
    pass


class SteamAPIRateLimitError(SteamAPIError):
    """Rate limit error from Steam API."""
    pass


class DotaMonitor:
    """Dota 2 player monitoring service."""
    
    # Dota 2 Hero IDs (comprehensive list)
    HERO_NAMES = {
        1: "Anti-Mage", 2: "Axe", 3: "Bane", 4: "Bloodseeker", 5: "Crystal Maiden",
        6: "Drow Ranger", 7: "Earthshaker", 8: "Juggernaut", 9: "Mirana",
        10: "Morphling", 11: "Shadow Fiend", 12: "Phantom Lancer", 13: "Puck",
        14: "Pugna", 15: "Rattletrap", 16: "Riki", 17: "Sniper", 18: "Spectre",
        19: "Tidehunter", 20: "Witch Doctor", 21: "Lich", 22: "Lion", 23: "Shadow Shaman",
        24: "Slardar", 25: "Viper", 26: "Warlock", 27: "Zeus", 28: "Kunkka",
        29: "Storm Spirit", 30: "Sven", 31: "Tiny", 32: "Vengeful Spirit",
        33: "Windrunner", 34: "Zuus", 35: "Queen of Pain", 36: "Razor",
        37: "Necrophos", 38: "Warlock", 39: "Skeleton King", 40: "Death Prophet",
        41: "Phantom Assassin", 42: "Pugna", 43: "Templar Assassin", 44: "Viper",
        45: "Luna", 46: "Dragon Knight", 47: "Dazzle", 48: "Clockwerk",
        49: "Nature's Prophet", 50: "Shadow Shaman", 51: "Slithe", 52: "Medusa",
        53: "Sniper", 54: "Troll Warlord", 55: "Centaur Warrunner", 56: "Magnus",
        57: "Timbersaw", 58: "Batrider", 59: "Chaos Knight", 60: "Huskar",
        61: "Naga Siren", 62: "Doom", 63: "Ancient Apparition", 64: "Lycan",
        65: "Brewmaster", 66: "Shadow Demon", 67: "Skeleton King", 68: "Lich",
        69: "Riki", 70: "Enigma", 71: "Terrorblade", 72: "Nyx Assassin",
        73: "Silencer", 74: "Oracle", 75: "Winter Wyvern", 76: "Arc Warden",
        77: "Monkey King", 78: "Pangolier", 79: "Grimstroke", 80: "Hoodwink",
        81: "Void Spirit", 82: "Snapfire", 83: "Mars", 84: "Ringmaster",
        85: "Dawnbreaker", 86: "Marci", 87: "Primal Beast", 88: "Templar Assassin",
        89: "Abaddon", 90: "Alchemist", 91: "Legion Commander", 92: "Techies",
        93: "Bane", 94: "Templar Assassin", 95: "Underlord", 96: "Rubick",
        97: "Disruptor", 98: "Nyx Assassin", 99: "Nature's Prophet", 100: "Invoker",
    }
    
    # Game modes
    GAME_MODES = {
        1: "All Pick", 2: "Captain's Mode", 3: "Random Draft", 4: "Single Draft",
        5: "All Random", 12: "Captains Draft", 18: "Direct Strike", 22: "Ranked",
    }
    
    def __init__(
        self,
        steam_api_key: Optional[str] = None,
        account_id: Optional[str] = None,
    ):
        """Initialize Dota 2 monitor."""
        settings = get_settings()
        
        self.steam_api_key = steam_api_key or settings.dota2_steam_api_key
        self.account_id = account_id or settings.dota2_account_id
        
        self.base_url = "https://api.steampowered.com"
        self.opendota_url = "https://api.opendota.com/api"
        self.db = DatabaseRepository()
        
    def _convert_account_id(self, steam_id: str) -> int:
        """
        Convert Steam ID to Dota 2 account ID.
        
        Args:
            steam_id: Steam ID (64-bit)
            
        Returns:
            Dota 2 account ID (32-bit)
        """
        try:
            steam_id_int = int(steam_id)
            # If the ID is already a 32-bit number (< 2^31), return as is
            if steam_id_int < 2**31:
                return steam_id_int
            # Convert 64-bit Steam ID to 32-bit account ID
            return steam_id_int - 76561197960265728
        except ValueError:
            return 0
    
    def _get_account_id_for_api(self) -> int:
        """
        Get the appropriate account ID for the current API.
        
        Returns:
            Account ID in the correct format for the API being used
        """
        if not self.account_id:
            return 0
        account_id_int = int(self.account_id)
        # If it's a 64-bit Steam ID, convert to 32-bit
        if account_id_int >= 2**31:
            return account_id_int - 76561197960265728
        return account_id_int
    
    async def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
        backoff_factor: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """
        Make API request to Steam with retry logic and enhanced error handling.

        Args:
            endpoint: API endpoint
            params: Query parameters
            max_retries: Maximum number of retry attempts
            backoff_factor: Backoff multiplier for exponential backoff

        Returns:
            JSON response

        Raises:
            SteamAPIAuthError: If authentication fails
            SteamAPIRateLimitError: If rate limited
            SteamAPIError: For other API errors
        """
        if not self.steam_api_key:
            logger.warning("Steam API key not configured")
            return None

        params = params or {}
        params["key"] = self.steam_api_key

        url = f"{self.base_url}/{endpoint}"

        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 403:
                            logger.error(f"API request failed: 403 Forbidden (attempt {attempt + 1}/{max_retries})")
                            raise SteamAPIAuthError(f"403 Forbidden: Invalid or expired API key")
                        elif response.status == 429:
                            logger.warning(f"API rate limited: {response.status} (attempt {attempt + 1}/{max_retries})")
                            raise SteamAPIRateLimitError(f"429 Too Many Requests")
                        elif response.status == 500:
                            logger.error(f"API server error: {response.status} (attempt {attempt + 1}/{max_retries})")
                            raise SteamAPIError(f"500 Server Error")
                        else:
                            logger.error(f"API request failed: {response.status} (attempt {attempt + 1}/{max_retries})")
                            raise SteamAPIError(f"HTTP {response.status}")

            except aiohttp.ClientError as e:
                logger.error(f"Network error: {e} (attempt {attempt + 1}/{max_retries})")
                if attempt == max_retries - 1:
                    raise SteamAPIError(f"Network error: {e}")
            except SteamAPIError as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(backoff_factor * (2 ** attempt))
            except Exception as e:
                logger.error(f"Unexpected error: {e} (attempt {attempt + 1}/{max_retries})")
                if attempt == max_retries - 1:
                    raise SteamAPIError(f"Unexpected error: {e}")

            await asyncio.sleep(backoff_factor * (2 ** attempt))

        return None
    
    async def get_player_summary_opendota(self) -> Optional[Dict[str, Any]]:
        """Get player summary from OpenDota.
        
        Returns:
            Player summary data
        """
        if not self.account_id:
            return None
        
        # Get the 32-bit account ID for OpenDota
        opendota_account_id = self._get_account_id_for_api()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.opendota_url}/players/{opendota_account_id}") as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "personaname": data.get("profile", {}).get("personaname", "Unknown"),
                            "avatarfull": data.get("profile", {}).get("avatarfull", ""),
                            "profileurl": data.get("profile", {}).get("profileurl", ""),
                            "rank_tier": data.get("rank_tier"),
                            "mmr_estimate": data.get("mmr_estimate", {}),
                        }
                    else:
                        logger.warning(f"OpenDota API request failed: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"OpenDota API error: {e}")
            return None
    
    async def get_player_summary(self) -> Optional[Dict[str, Any]]:
        """Get player summary from Steam (with OpenDota fallback).
        
        Returns:
            Player summary data
        """
        # Try OpenDota first as it's more reliable
        try:
            opendota_result = await self.get_player_summary_opendota()
            if opendota_result:
                return opendota_result
        except Exception as e:
            logger.warning(f"OpenDota player summary failed: {e}")
        
        # Fall back to Steam API if we have a key
        if self.steam_api_key:
            try:
                return await self._get_player_summary_steam()
            except SteamAPIAuthError as e:
                logger.warning(f"Steam API auth error: {e}")
            except Exception as e:
                logger.error(f"Steam API error: {e}")
        
        return None
    
    async def _get_player_summary_steam(self) -> Optional[Dict[str, Any]]:
        """Get player summary from Steam API."""
        if not self.account_id:
            return None
        
        params = {"steamids": f"{(int(self.account_id) + 76561197960265728)}"}
        data = await self._make_request(
            "ISteamUser/GetPlayerSummaries/v0002/",
            params
        )
        
        if data and data.get("response", {}).get("players"):
            return data["response"]["players"][0]
        
        return None
    
    async def get_match_history_opendota(
        self,
        matches_requested: int = 10
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get player match history from OpenDota.
        
        Args:
            matches_requested: Number of matches to retrieve
            
        Returns:
            List of matches
        """
        if not self.account_id:
            return None
        
        # Get the 32-bit account ID for OpenDota
        opendota_account_id = self._get_account_id_for_api()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.opendota_url}/players/{opendota_account_id}/matches",
                    params={"limit": matches_requested}
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.warning(f"OpenDota match history failed: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"OpenDota match history error: {e}")
            return None
    
    async def get_match_history(
        self,
        matches_requested: int = 10
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get player match history (with OpenDota fallback).
        
        Args:
            matches_requested: Number of matches to retrieve
            
        Returns:
            List of matches
        """
        # Try OpenDota first as it's more reliable
        try:
            opendota_result = await self.get_match_history_opendota(matches_requested)
            if opendota_result:
                return opendota_result
        except Exception as e:
            logger.warning(f"OpenDota match history failed: {e}")
        
        # Fall back to Steam API if we have a key
        if self.steam_api_key:
            try:
                return await self._get_match_history_steam(matches_requested)
            except SteamAPIAuthError as e:
                logger.warning(f"Steam API auth error: {e}")
            except Exception as e:
                logger.error(f"Steam API error: {e}")
        
        return None
    
    async def _get_match_history_steam(
        self,
        matches_requested: int = 10
    ) -> Optional[List[Dict[str, Any]]]:
        """Get player match history from Steam API."""
        if not self.account_id:
            return None
        
        params = {
            "account_id": self.account_id,
            "matches_requested": matches_requested,
        }
        
        data = await self._make_request(
            "IDOTA2Match_570/GetMatchHistory/v1/",
            params
        )
        
        if data and data.get("result", {}).get("matches"):
            return data["result"]["matches"]
        
        return None
    
    async def get_match_details_opendota(self, match_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed match information from OpenDota.
        
        Args:
            match_id: Match ID
            
        Returns:
            Match details
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.opendota_url}/matches/{match_id}") as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.warning(f"OpenDota match details failed: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"OpenDota match details error: {e}")
            return None
    
    async def get_match_details(self, match_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed match information (with OpenDota fallback).
        
        Args:
            match_id: Match ID
            
        Returns:
            Match details
        """
        # Try OpenDota first as it's more reliable
        try:
            opendota_result = await self.get_match_details_opendota(match_id)
            if opendota_result:
                return opendota_result
        except Exception as e:
            logger.warning(f"OpenDota match details failed: {e}")
        
        # Fall back to Steam API if we have a key
        if self.steam_api_key:
            try:
                return await self._get_match_details_steam(match_id)
            except SteamAPIAuthError as e:
                logger.warning(f"Steam API auth error: {e}")
            except Exception as e:
                logger.error(f"Steam API error: {e}")
        
        return None
    
    async def _get_match_details_steam(self, match_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed match information from Steam API."""
        params = {"match_id": match_id}
        
        data = await self._make_request(
            "IDOTA2Match_570/GetMatchDetails/v1/",
            params
        )
        
        if data and data.get("result"):
            return data["result"]
        
        return None
    
    async def get_player_status(self) -> Dict[str, Any]:
        """
        Get current player status.
        
        Returns:
            Status dictionary
        """
        status = {
            "online": False,
            "in_game": False,
            "match_id": None,
            "hero": None,
            "player_name": None,
        }
        
        # Get player summary
        summary = await self.get_player_summary()
        if summary:
            status["player_name"] = summary.get("personaname")
            
            # Check if playing Dota 2 (gameid 570)
            game_id = summary.get("gameid")
            if game_id == "570":
                status["in_game"] = True
                status["online"] = True
                
                # Get current game info
                status["game_extra"] = summary.get("gameextrainfo", "")
        
        # Get recent matches
        matches = await self.get_match_history(1)
        if matches:
            latest_match = matches[0]
            status["last_match"] = {
                "match_id": latest_match.get("match_id"),
                "hero_id": latest_match.get("hero_id"),
                "hero_name": self.HERO_NAMES.get(latest_match.get("hero_id")),
                "started_at": datetime.fromtimestamp(
                    latest_match.get("start_time", 0)
                ).isoformat() if latest_match.get("start_time") else None,
            }
        
        return status
    
    async def check_new_matches(self) -> List[Dict[str, Any]]:
        """
        Check for new matches since last check.
        
        Returns:
            List of new matches
        """
        last_match = await self.db.get_last_dota_match()
        
        matches = await self.get_match_history(5)
        if not matches:
            return []
        
        new_matches = []
        
        for match in matches:
            match_id = match.get("match_id")
            
            # Skip if same as last recorded
            if last_match and last_match.match_id == match_id:
                break
            
            # Get detailed match info
            details = await self.get_match_details(match_id)
            
            if details:
                # Find player's data in the match
                players = details.get("players", [])
                player_data = None
                
                for player in players:
                    account_id = player.get("account_id")
                    if account_id and int(account_id) == int(self.account_id):
                        player_data = player
                        break
                
                match_info = {
                    "match_id": match_id,
                    "player_name": self.HERO_NAMES.get(
                        player_data.get("hero_id") if player_data else 0
                    ),
                    "hero_id": player_data.get("hero_id") if player_data else None,
                    "kills": player_data.get("kills") if player_data else None,
                    "deaths": player_data.get("deaths") if player_data else None,
                    "assists": player_data.get("assists") if player_data else None,
                    "duration": details.get("duration"),
                    "game_mode": self.GAME_MODES.get(details.get("game_mode")),
                    "started_at": datetime.fromtimestamp(
                        details.get("start_time", 0)
                    ) if details.get("start_time") else None,
                }
                
                new_matches.append(match_info)
                
                # Save to database
                await self.db.add_dota_match(match_info)
        
        return new_matches
    
    async def get_players_in_game(self) -> List[Dict[str, Any]]:
        """
        Get list of players in current game.
        
        Returns:
            List of player info
        """
        # This would require Steam Web API or OpenDota API
        # For now, return status info
        status = await self.get_player_status()
        
        if status.get("in_game"):
            return [{
                "name": status.get("player_name"),
                "hero": status.get("game_extra"),
                "status": "In Game",
            }]
        
        return []
    
    def get_hero_name(self, hero_id: int) -> str:
        """Get hero name by ID."""
        return self.HERO_NAMES.get(hero_id, f"Unknown ({hero_id})")
    
    def get_game_mode(self, mode_id: int) -> str:
        """Get game mode by ID."""
        return self.GAME_MODES.get(mode_id, f"Unknown ({mode_id})")

    async def test_api_connection(self) -> Dict[str, Any]:
        """
        Test the Steam API connection and key validity.

        Returns:
            Dictionary with test results including status, error details, and endpoint info
        """
        test_results = {
            "status": "pending",
            "error": None,
            "api_key_valid": False,
            "endpoints_tested": [],
            "steam_id": self.account_id,
            "steam_api_key": self.steam_api_key[:8] + "****" if self.steam_api_key else None,
        }

        if not self.steam_api_key:
            test_results["error"] = "Steam API key not configured"
            test_results["status"] = "failed"
            return test_results

        # Test basic Steam API endpoint
        try:
            test_params = {"key": self.steam_api_key}
            test_url = f"{self.base_url}/ISteamWebAPIUtil/GetSupportedAPIList/v0001/"

            async with aiohttp.ClientSession() as session:
                async with session.get(test_url, params=test_params) as response:
                    if response.status == 200:
                        test_results["api_key_valid"] = True
                        test_results["endpoints_tested"].append({
                            "endpoint": "ISteamWebAPIUtil/GetSupportedAPIList/v0001",
                            "status": "success",
                            "response_code": response.status
                        })
                    else:
                        test_results["endpoints_tested"].append({
                            "endpoint": "ISteamWebAPIUtil/GetSupportedAPIList/v0001",
                            "status": "failed",
                            "response_code": response.status
                        })
                        test_results["error"] = f"API key validation failed: HTTP {response.status}"
                        test_results["status"] = "failed"

        except Exception as e:
            test_results["error"] = f"API connection error: {str(e)}"
            test_results["status"] = "failed"

        return test_results
