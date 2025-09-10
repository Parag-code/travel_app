import json
import re
import parsedatetime
from datetime import datetime, timedelta
import dateutil.parser
from openai import OpenAI

from flight_utils import search_flights_skyexperts, summarize_skyexperts, trip_output


from dotenv import load_dotenv
import os

# Load environment variables from .env (for local dev)
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY").strip()
OPENAI_ORG_ID = os.getenv("OPENAI_ORG_ID")
OPENAI_PROJECT_ID = os.getenv("OPENAI_PROJECT_ID")

if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY not found. Please set it in environment variables or .env file.")

# Initialize OpenAI client
# This supports both normal keys (sk-...) and project keys (sk-proj-...)
client = OpenAI(
    api_key=OPENAI_API_KEY,
    organization=OPENAI_ORG_ID if OPENAI_ORG_ID else None,
    project=OPENAI_PROJECT_ID if OPENAI_PROJECT_ID else None
)

def build_prompt(query):
    return f"""
You are a multilingual flight booking assistant.

The current date is {datetime.now().strftime('%Y-%m-%d')}.
The user query may be in Hindi, English, or a mix of both.

You must:
- Understand Hindi and English date/time phrases (e.g., "कल", "परसों", "5 दिन बाद", 
  "अगला सोमवार", "अगले महीने", "next Friday", "next Tuesday", "next Wednesday", 
  "next Saturday", "next Thursday", "next Sunday").
- Always normalize all date expressions into strict ISO format: YYYY-MM-DD.
- "Next <weekday>" = the very next occurrence of that weekday after today.  
  If today is that weekday, then "next <weekday>" means 7 days later.  
- If `retdate` is relative (e.g., "10 दिन बाद", "after 10 days"), calculate it relative to the `depdate`, not today's date.
- Handle absolute dates: "12 Sep", "12 September 2025", "12/09/25", "12-09-2025".
- Handle relative phrases: "tomorrow", "day after tomorrow".
- Handle common holidays: "Christmas" = 25 Dec, "New Year" = 1 Jan (if already passed this year, take next year).
- Return all dates in YYYY-MM-DD format in the JSON output.
- Handle both Hindi and English city/airport names and convert them to their **IATA 3-letter codes**.
- If a location has multiple airports, choose the primary international passenger airport.
- If the user mentions an airline by name (e.g., "Indigo", "Air India", "SpiceJet"), convert it to the correct IATA airline code ("6E" for Indigo, "AI" for Air India, "SG" for SpiceJet) and put that code in `airline_include`. Always return the IATA code, never the name.

Extract and return only JSON with the following keys:
- from: departure airport IATA code (3 letters, e.g., DEL for Delhi)
- to: arrival airport IATA code (3 letters, e.g., DXB for Dubai)
- depdate: departure date in YYYY-MM-DD format
- retdate: return date in YYYY-MM-DD format (optional)
- adults: number of adults (default: 1)
- children: number of children (default: 0)
- infants: number of infants (default: 0)
- cabin: cabin class like economy, business (default: economy)
- airline_include: preferred airline IATA code if mentioned (e.g., "6E", "AI")

Rules:
- Only assign a value if it is clearly mentioned in the query.
- If a field is missing, set its value to null or "Not Provided", except:
  * Set "adults" to 1 by default
  * Set "children" and "infants" to 0 by default
  * Set "cabin" to "economy" by default

Return valid JSON only. Do not explain anything.

Query: "{query}"
"""

from dateutil.relativedelta import relativedelta  # put at top of file

def parse_date_string(natural_date, base_date=None):
    if not natural_date:
        return None

    natural_date_lower = natural_date.lower().strip()
    today = base_date or datetime.now()

    # Special cases first
    if "day after tomorrow" in natural_date_lower:
        return (today + timedelta(days=2)).strftime('%Y-%m-%d')
    if "tomorrow" in natural_date_lower:
        return (today + timedelta(days=1)).strftime('%Y-%m-%d')

    # Handle "next month"
    if natural_date_lower == "next month":
        return (today + relativedelta(months=1)).strftime('%Y-%m-%d')

    match = re.search(r'after (\d+) days?', natural_date_lower)
    if match:
            days = int(match.group(1))
            return (today + timedelta(days=days)).strftime('%Y-%m-%d')

    # parsedatetime fallback
    cal = parsedatetime.Calendar()
    time_struct, parse_status = cal.parse(natural_date, sourceTime=today.timetuple())
    if parse_status != 0:
        return datetime(*time_struct[:6]).strftime('%Y-%m-%d')

    # dateutil fallback
    try:
        return dateutil.parser.parse(natural_date, fuzzy=True, default=today).strftime('%Y-%m-%d')
    except Exception:
        return None


def is_missing(value):
    if value is None:
        return True
    value = str(value).strip().lower()
    return value in ["", "none", "not provided", "departure city (not provided)", "arrival city (not provided)"]
    
import random
import string

def generate_sc(length=20):
    """Generates a random alphanumeric string of given length."""
    letters = string.ascii_letters + string.digits
    return ''.join(random.choice(letters) for i in range(length))

def run_smart_flight_search(user_query):
    try:
        if not user_query:
            return {"error": "⚠️ Missing query"}

        # Build the prompt
        prompt = build_prompt(user_query)

        # Call GPT-4o
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        content = response.choices[0].message.content.strip()
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if not json_match:
            return {"error": "Invalid model output"}

        parsed = json.loads(json_match.group())

        depdate_raw = parsed.get("depdate")
        retdate_raw = parsed.get("retdate")
        depfrom = parsed.get("from")
        arrto = parsed.get("to")

        depdate = parse_date_string(depdate_raw) if depdate_raw else None
        retdate = (
            parse_date_string(retdate_raw, base_date=datetime.strptime(depdate, "%Y-%m-%d"))
            if retdate_raw and depdate else None
        )

        adults = int(parsed.get("adults", 1))
        children = int(parsed.get("children", 0))
        infants = int(parsed.get("infants", 0))
        cabin = parsed.get("cabin", "economy").lower()
        airline = parsed.get("airline_include", "")

        # ✅ Missing field checks
        missing_fields = []
        follow_up_questions = []

        if is_missing(depfrom):
            missing_fields.append("from")
            follow_up_questions.append("✈️ Where are you flying *from*?")
        if is_missing(arrto):
            missing_fields.append("to")
            follow_up_questions.append("🛬 Where are you flying *to*?")
        if not depdate_raw or not depdate:
            missing_fields.append("depdate")
            follow_up_questions.append("📅 When do you want to *depart*?")

        if missing_fields:
            return {
                "status": "incomplete",
                "message": f"Missing fields: {', '.join(missing_fields)}",
                "missing_fields": missing_fields,
                "follow_up": follow_up_questions,
                "parsed": {
                    "from": depfrom,
                    "to": arrto,
                    "depdate": depdate_raw or None
                }
            }

        # ✅ Prepare payload for SkyExperts API
        payload = {
            "adults": adults,
            "children": children,
            "infants": infants,
            "cabin": cabin,
            "stops": False,
            "airline_include": airline,
            "ages": [],
            "sc": generate_sc(),
            "segments": [{"depfrom": depfrom, "arrto": arrto, "depdate": depdate}]
        }
        if retdate:
            payload["segments"].append({
                "depfrom": arrto,
                "arrto": depfrom,
                "depdate": retdate
            })

        # ✅ Call SkyExperts API
        # ✅ Call SkyExperts API
        api_data = search_flights_skyexperts(payload)

# Summarize flights
        summary_dict = summarize_skyexperts(api_data)
        mindtrip=trip_output(summary_dict, has_return=bool(retdate))

        return {
            "from": depfrom,
            "to": arrto,
            "depdate": depdate,
            "retdate": retdate,
            "adults": adults,
            "children": children,
            "infants": infants,
            "cabin": cabin,
            "airline_include": airline or None,
            "flight_search": "✅ Flights fetched from SkyExperts API",
            "flights": mindtrip,   # ✅ direct flights summary only
            "api_sc": payload["sc"]
}



    except Exception as e:
        return {"error": str(e)}


    
    
if __name__ == '__main__':
    run_smart_flight_search()