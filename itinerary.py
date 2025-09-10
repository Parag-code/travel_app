import re
import pandas as pd
import json
from openai import OpenAI
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta

# Load data
attractions = pd.read_csv("uae_attractions.csv")
hotels = pd.read_csv("uae_hotels.csv")
restaurants = pd.read_csv("uae_restaurants.csv")

attractions.columns = attractions.columns.str.strip()
hotels.columns = hotels.columns.str.strip()
restaurants.columns = restaurants.columns.str.strip()

# Rating conversion
rating_map = {
    "OneStar": 1,
    "TwoStar": 2,
    "ThreeStar": 3,
    "FourStar": 4,
    "FiveStar": 5
}
hotels["HotelRating"] = hotels["HotelRating"].map(rating_map)
restaurants["Average Cost for two"] = pd.to_numeric(
    restaurants["Average Cost for two"], errors="coerce"
)

# Helpers
def clean_value(val, default="Not Available"):
    if pd.isna(val) or str(val).strip().lower() in ["nan", "none", ""]:
        return default
    return str(val)

def format_rating(rating):
    if pd.isna(rating):
        return "Not Rated"
    return f"{int(rating)}-Star"

# Preference mapping
preference_map = {
    "beach": ["Beach", "Water Park", "Island", "Waterway"],  
    "culture": ["Heritage", "Cultural", "Museum", "Religious", "Memorial"],
    "adventure": ["Adventure", "Theme Park", "Desert", "Safari"],  
    "luxury": ["Landmark", "Leisure"],  
    "nature": ["Nature", "Park", "Garden", "Zoo"],  
    "shopping": ["Shopping", "Mall", "Souq", "Market"],   
    "history": ["Heritage", "Museum", "Religious", "Memorial"],  
    "wildlife": ["Zoo", "Nature"],  
}

# Categories best suited for Evening slot
time_based_map = {
    "Morning": ["Museum", "Heritage", "Cultural", "Religious", "Theme Park", "Nature", "Zoo"],
    "Afternoon": ["Shopping", "Mall", "Souq", "Market", "Aquarium", "Art", "Exhibition"],
    "Evening": ["Desert", "Safari", "Adventure", "Nightlife", "Show", "Observation", "Fountain", "Water Park"]
}

# Load keys
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY").strip()
OPENAI_ORG_ID = os.getenv("OPENAI_ORG_ID")
OPENAI_PROJECT_ID = os.getenv("OPENAI_PROJECT_ID")

client = OpenAI(
    api_key=OPENAI_API_KEY,
    organization=OPENAI_ORG_ID if OPENAI_ORG_ID else None,
    project=OPENAI_PROJECT_ID if OPENAI_PROJECT_ID else None
)

import re
from datetime import datetime

def extract_start_date(query):
    """
    Use OpenAI LLM to extract a normalized start date (YYYY-MM-DD)
    from any date-related text in the query.
    Handles formats like:
    - Absolute dates: '12 Sep', '20 Dec 2024', '15/09/2025'
    - Relative: 'next Friday', 'tomorrow', 'day after tomorrow'
    - Named holidays: 'Christmas', 'New Year'
    Returns None if no date is present.
    """
    prompt = f"""
    You are a date parser. 
    Extract exactly ONE start date from the query and normalize it to ISO format (YYYY-MM-DD).
    If the query mentions relative days (like "next Friday", "next Monday", "tomorrow",next week), 
    calculate the exact date based on today's date.

    Rules:
    - "Next <weekday>" means the very next occurrence of that weekday *after today*.
    - If today IS that weekday, then "next <weekday>" means one week later.
    - Handle formats like "12 Sep", "12 September 2025", "12/09/25", "12-09-2025".
    - Handle relative phrases like "tomorrow", "day after tomorrow".
    - Handle common holidays like "Christmas" (25 Dec), "New Year" (1 Jan).
    - Always return one ISO date: YYYY-MM-DD
    - If no valid date is found, return: null

    Today's date: {datetime.today().strftime('%Y-%m-%d')}
    Query: "{query}"

    Output format: YYYY-MM-DD or null
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    content = response.choices[0].message.content.strip()

    # Handle null case
    if content.lower() == "null":
        return None

    # Extract clean ISO-like date
    match = re.search(r"\d{4}-\d{2}-\d{2}", content)
    if match:
        return match.group(0)

    # Extra handling: check for DD/MM/YYYY or DD-MM-YYYY or DD Mon YYYY
    alt_match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", content)
    if alt_match:
        d, m, y = alt_match.groups()
        if len(y) == 2:  # normalize 2-digit year
            y = "20" + y
        try:
            return datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
        except:
            pass

    # Check for DD Mon YYYY (e.g., 12 Sep 2025)
    alt_match2 = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", content)
    if alt_match2:
        d, mon, y = alt_match2.groups()
        try:
            return datetime.strptime(f"{d} {mon} {y}", "%d %B %Y").strftime("%Y-%m-%d")
        except:
            try:
                return datetime.strptime(f"{d} {mon} {y}", "%d %b %Y").strftime("%Y-%m-%d")
            except:
                pass

    return None



def filter_by_preferences(city_attractions, preferences):
    if not preferences:
        return city_attractions
    matched = pd.DataFrame()
    for pref in preferences:
        for cat in preference_map.get(pref.lower(), []):
            matches = city_attractions[city_attractions["Category"].str.contains(cat, case=False, na=False)]
            matched = pd.concat([matched, matches])
    if not matched.empty:
        non_pref = city_attractions[~city_attractions.index.isin(matched.index)]
        return pd.concat([matched, non_pref]).drop_duplicates().reset_index(drop=True)
    return city_attractions

def pick_time_based_attraction(city_attractions, used, slot):
    categories = time_based_map.get(slot, [])
    candidates = city_attractions[
        city_attractions["Category"].str.contains("|".join(categories), case=False, na=False)
    ]
    candidates = candidates[~candidates["Name"].isin(used)]
    if not candidates.empty:
        return candidates.iloc[0]
    unused = city_attractions[~city_attractions["Name"].isin(used)]
    if not unused.empty:
        return unused.iloc[0]
    return None

def split_days_among_cities(cities, total_days):
    city_day_counts = {}
    n = len(cities)
    min_days = 2 if total_days >= n * 2 else 1
    for c in cities:
        city_day_counts[c] = min_days
    remaining_days = total_days - (min_days * n)
    idx = 0
    while remaining_days > 0:
        city_day_counts[cities[idx % n]] += 1
        remaining_days -= 1
        idx += 1
    return city_day_counts

def build_itinerary(query):
    days, budget, currency, preferences = None, None, "AED", []

    # Days
    days_match = re.search(r'(\d+)\s*[- ]?\s*(day|days|night|nights)', query, re.IGNORECASE)
    if days_match:
        days = int(days_match.group(1))
        if "night" in days_match.group(2).lower():
            days += 1

    # Budget
    budget_match = re.search(r'(?:under|budget|cost|price)\s*(\d+)\s*(AED|Dhs|\$|USD)?', query, re.IGNORECASE)
    if budget_match:
        budget = int(budget_match.group(1))
        if budget_match.group(2):
            currency = budget_match.group(2).upper().replace("DHS", "AED").replace("$", "USD")

    # Cities
    known_cities = ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Fujairah", "Ras Al Khaimah", "Umm Al Quwain"]
    cities = [c for c in known_cities if c.lower() in query.lower()]
    if not cities:
        cities = ["Dubai"]

    # Preferences
    for kw in preference_map.keys():
        if kw in query.lower():
            preferences.append(kw)
    valid_categories = [c for c in attractions["Category"].dropna().unique().tolist() if c.lower() != "hotel"]
    for cat in valid_categories:
        if cat.lower() in query.lower() and cat not in preferences:
            preferences.append(cat)
    preferences = list(set([p.capitalize() for p in preferences]))

    # Start date via LLM
    start_date = extract_start_date(query)

    # Split days
    city_day_counts = split_days_among_cities(cities, days)
    itinerary = {}
    day_counter = 1

    for idx, city in enumerate(cities):
        city_attractions = attractions[attractions["City"].str.lower() == city.lower()].sample(frac=1).reset_index(drop=True)
        city_attractions = filter_by_preferences(city_attractions, preferences)

        city_hotels = hotels[hotels["cityName"].str.lower() == city.lower()].sample(frac=1).reset_index(drop=True)
        city_restaurants = restaurants[restaurants["City"].str.lower() == city.lower()].sample(frac=1).reset_index(drop=True)

        current_hotel = None
        used_attractions = set()

        for i in range(city_day_counts[city]):
            morning = pick_time_based_attraction(city_attractions, used_attractions, "Morning")
            if morning is not None:
                used_attractions.add(morning["Name"])
            afternoon = pick_time_based_attraction(city_attractions, used_attractions, "Afternoon")
            if afternoon is not None:
                used_attractions.add(afternoon["Name"])
            evening_pick = pick_time_based_attraction(city_attractions, used_attractions, "Evening")
            if evening_pick is not None:
                used_attractions.add(evening_pick["Name"])

            restaurant = city_restaurants.iloc[i % len(city_restaurants)] if not city_restaurants.empty else None
            hotel = city_hotels.iloc[i % len(city_hotels)] if not city_hotels.empty else None

            if i == 0 and idx > 0:
                morning_text = f"🚗 Travel to **{city}**, check into hotel."
                current_hotel = hotel
                hotel_text = "No hotels available" if hotel is None else f"{clean_value(hotel['HotelName'])} ⭐ {format_rating(hotel['HotelRating'])}"
            elif i == 0 and idx == 0:
                morning_text = f"Check into hotel then visit {morning['Name']} ({morning['Category']}) – {morning['Description']}"
                current_hotel = hotel
                hotel_text = "No hotels available" if hotel is None else f"{clean_value(hotel['HotelName'])} ⭐ {format_rating(hotel['HotelRating'])}"
            else:
                morning_text = f"{morning['Name']} ({morning['Category']}) – {morning['Description']}"
                hotel_text = "Same hotel as previous day" if current_hotel is not None else "No hotels available"

            afternoon_text = "No afternoon activity" if afternoon is None else f"{afternoon['Name']} ({afternoon['Category']}) – {afternoon['Description']}"

            dinner_text = "No restaurants available" if restaurant is None else f"{clean_value(restaurant['Restaurant Name'])} 🍴 {clean_value(restaurant['Cuisines'])} | ⭐ {clean_value(restaurant['Aggregate rating'], 'Not Rated')} ({clean_value(restaurant['Votes'], '0')} reviews) | 💰 {clean_value(restaurant['Average Cost for two'], 'N/A')} AED for 2 people"

            if evening_pick is not None:
                evening_activity = f"{evening_pick['Name']} ({evening_pick['Category']}) – {evening_pick['Description']}"
                evening_text = f"{evening_activity}\nDinner: {dinner_text}"
            else:
                evening_text = f"Dinner: {dinner_text}"

            # Add actual calendar date
            day_date = None
            if start_date:
                try:
                    day_date = (datetime.fromisoformat(start_date) + timedelta(days=(day_counter-1))).strftime("%d %b %Y")
                except:
                    day_date = None

            itinerary[f"Day {day_counter}"] = {
                "Date": day_date if day_date else f"Day {day_counter}",
                "Morning": morning_text,
                "Afternoon": afternoon_text,
                "Evening": evening_text,
                "Hotel": hotel_text
            }
            day_counter += 1

    parsed = {
        "city": cities[0] if cities else None,
        "cities": cities,
        "days": days,
        "budget": budget,
        "currency": currency,
        "preferences": preferences,
        "day_split": city_day_counts,
        "start_date": start_date
    }

    return parsed, itinerary

def make_human_like(parsed, itinerary):
    import json
    from datetime import datetime

    days = parsed.get("days", len(itinerary))
    cities = parsed.get("cities", [])

    if not cities:
        city_title = parsed.get("city", "your destination")
    else:
        city_title = " & ".join(cities) if len(cities) > 1 else cities[0]

    # ✅ Title without any date
    title = f"{city_title} – {days} Day Itinerary"

    prompt = f"""
    You are a professional travel curator.
    Create a {days}-day travel itinerary titled "**{title}**" in the **Mindtrip.ai style**.

    Formatting rules:
    - Title does NOT include any dates.
    - Add a short tagline (one catchy sentence).
    - Use headings: "**Day X – …**" with an emoji.
    - Subsections: "**☀️ Morning:**", "**🌤️ Afternoon:**", "**🌙 Evening:**"
    - Each subsection should be a short paragraph (2–3 sentences), not bullet points.
    - **Day 1 Morning must include hotel check-in**.
    - From Day 2 onwards, only say "Breakfast at hotel" (same hotel throughout).
    - If itinerary includes multiple cities, add clear notes when transferring (e.g., "🚗 Travel to Abu Dhabi").
    - **Traveler preferences to highlight:** {parsed.get("preferences", [])}.
    - **Bold all hotels, restaurants, landmarks, and key experiences.**
    - Keep tone lively, polished, and smooth storytelling — like a premium travel app.
    - ONLY use the following JSON itinerary data. Do not add places not in JSON.

    JSON itinerary data:
    {json.dumps(itinerary, indent=2, ensure_ascii=False)}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content
