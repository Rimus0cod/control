"""Dota 2 player monitoring service."""
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, List

import aiohttp
from loguru import logger

from config import get_settings
from database import DatabaseRepository


class DotaMonitor:
    """Dota 2 player monitoring service."""
    
    # Dota 2 Hero IDs (partial list)
    HERO_NAMES = {
        1: "Anti-Mage", 2: "Axe", 3: "Bane", 4: "Bloodseeker", 5: "Crystal Maiden",
        6: "Drow Ranger", 7: "Earthshaker", 8: "Juggernaut", 9: "Mirana",
        10: "Morphling", 11: "Shadow Fiend", 12: "Phantom Lancer", 13: "Puck",
        14: "Pugna", 15: "Rattletrap", 16: "Riki", 17: "Sniper", 18: "Spectre",
        19: "Tidehunter", 20: "Witch Doctor", 21: "Lich", 22: "Lion", 23: "Shadow Shaman",
        24: "Slardar", 25: "Viper", 26: "Warlock", 27: "Zeus", 28: "Kunkka",
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
        self.db = DatabaseRepository()
        
    def _convert_account_id(self, steam_id: str) -> int:
        """
        Convert Steam ID to Dota 2 account ID.
        
        Args:
            steam_id: Steam ID (64-bit)
            
        Returns:
            Dota 2 account ID
        """
        try:
            return int(steam_id) - 76561197960265728
        except ValueError:
            return 0
    
    async def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Make API request to Steam.
        
        Args:
            endpoint: API endpoint
            params: Query parameters
            
        Returns:
            JSON response
        """
        if not self.steam_api_key:
            logger.warning("Steam API key not configured")
            return None
        
        params = params or {}
        params["key"] = self.steam_api_key
        
        url = f"{self.base_url}/{endpoint}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"API request failed: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"API request error: {e}")
            return None
    
    async def get_player_summary(self) -> Optional[Dict[str, Any]]:
        """
        Get player summary from Steam.
        
        Returns:
            Player summary data
        """
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
    
    async def get_match_history(
        self,
        matches_requested: int = 10
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get player match history.
        
        Args:
            matches_requested: Number of matches to retrieve
            
        Returns:
            List of matches
        """
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
    
    async def get_match_details(self, match_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed match information.
        
        Args:
            match_id: Match ID
            
        Returns:
            Match details
        """
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
