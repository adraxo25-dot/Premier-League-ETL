import os
import requests
import pandas as pd

# Data sources for the 2026/27 Premier League season
CSV_URL = "https://www.football-data.co.uk/mmz4281/2627/E0.csv"
FPL_BASE_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"


def run_etl():
    print("1. Fetching team match data from football-data.co.uk...")
    raw_df = pd.read_csv(CSV_URL)
    raw_df = raw_df.dropna(subset=["HomeTeam", "AwayTeam"]).copy()

    raw_df["match_id"] = raw_df.index + 1
    raw_df["gameweek"] = (raw_df.index // 10) + 1

    # Home team perspective
    home_df = pd.DataFrame({
        "match_id": raw_df["match_id"],
        "gameweek": raw_df["gameweek"],
        "date": raw_df["Date"],
        "team": raw_df["HomeTeam"],
        "opponent": raw_df["AwayTeam"],
        "venue": "Home",
        "goals_for": raw_df["FTHG"],
        "goals_against": raw_df["FTAG"],
        "total_shots": raw_df["HS"],
        "shots_on_target": raw_df["HST"],
        "result": raw_df["FTR"].map({"H": "W", "D": "D", "A": "L"})
    })

    # Away team perspective
    away_df = pd.DataFrame({
        "match_id": raw_df["match_id"],
        "gameweek": raw_df["gameweek"],
        "date": raw_df["Date"],
        "team": raw_df["AwayTeam"],
        "opponent": raw_df["HomeTeam"],
        "venue": "Away",
        "goals_for": raw_df["FTAG"],
        "goals_against": raw_df["FTHG"],
        "total_shots": raw_df["AS"],
        "shots_on_target": raw_df["AST"],
        "result": raw_df["FTR"].map({"A": "W", "D": "D", "H": "L"})
    })

    team_stats = (
        pd.concat([home_df, away_df], ignore_index=True)
        .sort_values(by=["match_id", "venue"])
        .reset_index(drop=True)
    )

    print("2. Fetching player data from Fantasy Premier League API...")
    general_data = requests.get(FPL_BASE_URL).json()

    position_names = {
        1: "Goalkeeper",
        2: "Defender",
        3: "Midfielder",
        4: "Forward"
    }

    players_lookup = {
        p["id"]: f"{p['first_name']} {p['second_name']}"
        for p in general_data["elements"]
    }
    player_position_lookup = {
        p["id"]: position_names.get(p["element_type"], "Unknown")
        for p in general_data["elements"]
    }
    fpl_teams_lookup = {
        t["id"]: t["name"]
        for t in general_data["teams"]
    }
    player_team_lookup = {
        p["id"]: fpl_teams_lookup[p["team"]]
        for p in general_data["elements"]
    }

    finished_gameweeks = [
        event["id"] for event in general_data["events"] if event["finished"]
    ]

    player_rows = []
    for gw in finished_gameweeks:
        gw_url = f"https://fantasy.premierleague.com/api/event/{gw}/live/"
        gw_data = requests.get(gw_url).json()

        for p in gw_data["elements"]:
            stats = p["stats"]
            if stats["minutes"] > 0:
                p_id = p["id"]
                player_rows.append({
                    "gameweek": gw,
                    "player_id": p_id,
                    "player_name": players_lookup.get(p_id, "Unknown"),
                    "position": player_position_lookup.get(p_id, "Unknown"),
                    "fpl_team": player_team_lookup.get(p_id, "Unknown"),
                    "minutes": stats["minutes"],
                    "goals": stats["goals_scored"],
                    "assists": stats["assists"],
                    "clean_sheets": stats["clean_sheets"],
                    "fpl_points": stats["total_points"],
                    "bps": stats["bps"]
                })

    player_stats = pd.DataFrame(player_rows)

    # 3. Standardize team names and attach matching match_id
    team_name_map = {
        "Man Utd": "Man United",
        "Spurs": "Tottenham",
        "Ipswich Town": "Ipswich",
        "Coventry City": "Coventry",
        "Hull City": "Hull",
        "Nott'm Forest": "Nott'm Forest"
    }
    player_stats["team"] = player_stats["fpl_team"].replace(team_name_map)

    match_lookup = team_stats[["match_id", "gameweek", "team"]].drop_duplicates()
    player_stats = pd.merge(
        player_stats,
        match_lookup,
        on=["gameweek", "team"],
        how="left"
    )

    cols = [
        "match_id", "gameweek", "team", "player_id", "player_name",
        "position", "minutes", "goals", "assists", "clean_sheets",
        "fpl_points", "bps"
    ]
    player_stats = player_stats[cols]

    # 4. Save both clean tables to the data/ folder
    os.makedirs("data", exist_ok=True)
    team_stats.to_csv("data/fact_team_stats.csv", index=False)
    player_stats.to_csv("data/fact_player_stats.csv", index=False)
    
    # Save lookup tables so Power BI Web can connect everything cleanly
    team_stats[["team"]].drop_duplicates().sort_values("team").to_csv("data/dim_teams.csv", index=False)
    team_stats[["gameweek"]].drop_duplicates().sort_values("gameweek").to_csv("data/dim_gameweeks.csv", index=False)

    print(f"Done! Saved {len(team_stats)} team rows and {len(player_stats)} player rows.")
    print(f"Unmatched player rows: {player_stats['match_id'].isna().sum()}")


if __name__ == "__main__":
    run_etl()
