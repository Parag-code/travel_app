import requests
import random
import string
from itinerary import extract_start_date


FLIGHT_API_URL = "https://www.skyexperts.co.uk/api/FlightApi/searchflight"

# UAE city → airport code mapping
city_to_airport = {
    "Dubai": "DXB",
    "Abu Dhabi": "AUH",
    "Sharjah": "SHJ",
    "Ras Al Khaimah": "RKT",
    "Fujairah": "FJR",
    "Ajman": "DXB",          # nearest major airport
    "Umm Al Quwain": "DXB"   # nearest major airport
}

def generate_sc(length=20):
    """Generates a random alphanumeric session code for API calls."""
    letters = string.ascii_letters + string.digits
    return ''.join(random.choice(letters) for _ in range(length))

def get_price_val(flight):
    """Safe price extractor (handles both total_price and totalprice)."""
    try:
        return float(
            flight.get("price", {}).get("total_price")
            or flight.get("price", {}).get("totalprice")
            or float("inf")
        )
    except Exception:
        return float("inf")

def fmt_price(price, currency="GBP"):
    """Format price nicely with 2 decimals."""
    try:
        return f"{round(float(price), 2)} {currency}"
    except Exception:
        return f"{price} {currency}"

def search_flights(dep_from, destination, dep_date):
    payload = {
        "adults": 1,
        "children": 0,
        "infants": 0,
        "cabin": "economy",
        "stops": None,
        "airline_include": "",
        "ages": [],
        "sc": generate_sc(),
        "segments": [
            {"depfrom": dep_from, "arrto": destination, "depdate": dep_date}
        ]
    }

    try:
        response = requests.post(FLIGHT_API_URL, json=payload, timeout=20)
        if response.status_code != 200:
            return {"error": f"API call failed: {response.status_code}", "details": response.text}

        data = response.json()

        # ✅ Always check both
        flights = data.get("Data") or data.get("data", {}).get("Data", [])
        if not flights:
            return {"error": "No flights found", "raw": data}

        # Top 3 cheapest
        cheapest_list = sorted(flights, key=get_price_val)[:3]

        # Top 3 fastest
        fastest_list = sorted(
            flights,
            key=lambda x: float(x.get("totaltime") or float("inf"))
        )[:3]

        # Direct flights
        direct = []
        for f in flights:
            try:
                if len(f["OutboundInboundlist"][0]["flightlist"]) == 1:
                    direct.append(f)
            except:
                pass
        direct = direct[:3]

        # Currency
        currency = (
            cheapest_list[0].get("price", {}).get("currency") if cheapest_list else None
        ) or data.get("Currency") or "AED"

        return {
            "cheapest": cheapest_list,
            "fastest": fastest_list,
            "direct": direct,
            "currency": currency
        }

    except Exception as e:
        return {"error": str(e)}


from itinerary import extract_start_date
  # 👈 tumhara LLM date parser

def ask_and_show_flights(parsed, dep_from=None, raw_date=None):
    """
    API-friendly version: returns structured JSON.
    Uses LLM-based extract_start_date() for all date parsing.
    """

    destination_city = parsed.get("cities", [None])[0]
    start_date = parsed.get("start_date")  # ✅ fallback from itinerary

    # Priority: user date > itinerary date
    if raw_date:
        cleaned = raw_date.strip().lower()
        # 👇 common prefixes remove
        for prefix in ["on ", "for ", "starting ", "from "]:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
        parsed_date = extract_start_date(cleaned)  # 👈 Always LLM parser
        if parsed_date:
            start_date = parsed_date

    # -------- Validations --------
    if not dep_from:
        return {"error": "⚠️ Missing departure city/airport code."}
    if not destination_city:
        return {"error": "⚠️ Missing destination city from itinerary."}
    if not start_date:
        # Friendly error, not technical
        return {
            "error": f"⚠️ Sorry, I couldn’t understand the date '{raw_date}'. "
                     f"Please try again with a clear date (e.g., '15 Sep 2025')."
        }

    destination_code = city_to_airport.get(destination_city, destination_city[:3].upper())

    # -------- Search Flights --------
    results = search_flights(dep_from.upper(), destination_code, start_date)
    if "error" in results:
        return {"error": results["error"]}

    currency = results.get("currency", "AED")

    def format_list(flights):
        return [fmt(f, currency) for f in flights]

    return {
        "search": f"{dep_from.upper()} → {destination_code} on {start_date}",
        "cheapest": format_list(results.get("cheapest", [])),
        "fastest": format_list(results.get("fastest", [])),
        "direct": format_list(results.get("direct", [])),
        "currency": currency
    }





def fmt(flight, currency="AED"):
    if not isinstance(flight, dict) or not flight:
        return "⚠️ No flight data"

    try:
        # Airline
        airline_code = flight.get("Airlinelists", ["?"])[0] if flight.get("Airlinelists") else "?"
        airline_name = airline_code
        try:
            airline_name = flight["OutboundInboundlist"][0]["flightlist"][0].get("OperatingAirline", {}).get("name", airline_code)
        except Exception:
            pass

        # Departure and arrival times
        dep_time, arr_time = "??:??", "??:??"
        try:
            first_leg = flight["OutboundInboundlist"][0]["flightlist"][0]
            last_leg = flight["OutboundInboundlist"][0]["flightlist"][-1]
            dep_time = first_leg["Departure"].get("time", dep_time)
            arr_time = last_leg["Arrival"].get("time", arr_time)
        except Exception:
            pass

        # Stops
        stops = 0
        via_city = None
        try:
            legs = flight["OutboundInboundlist"][0]["flightlist"]
            stops = len(legs) - 1
            if stops == 1:
                via_city = legs[0]["Arrival"].get("city")
        except Exception:
            pass

        if stops == 0:
            stop_text = "Direct"
        elif stops == 1:
            stop_text = f"1 stop via {via_city}"
        else:
            stop_text = f"{stops} stops"

        # Duration
        duration = "?"
        try:
            duration_minutes = int(flight.get("totaltime", 0))
            h, m = divmod(duration_minutes, 60)
            duration = f"{h}h {m}m"
        except Exception:
            pass

        # Price
        price = (
            flight.get("price", {}).get("total_price")
            or flight.get("price", {}).get("totalprice")
            or "N/A"
        )
        price = fmt_price(price, currency)

        return f"{airline_name} ({airline_code}) | {dep_time} → {arr_time} | {stop_text} | Duration: {duration} | Price: {price}"

    except Exception as e:
        return f"⚠️ Could not parse flight: {e}"
    
    
import requests
from collections import OrderedDict

def search_flights_skyexperts(payload):
    url = "https://www.skyexperts.co.uk/api/FlightApi/searchflight"
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)
    return response.json()

def summarize_skyexperts(api_data):
    """
    Summarizes SkyExperts API results.
    - If return flights exist → build round-trip pairs (top 5 + cheapest, fastest, direct 3).
    - If return flights absent → summarize outbound only (top 5 + cheapest, fastest, direct 3).
    """
    data_root = api_data.get("data", {})
    flights_data = data_root.get("Data", [])
    currency_sign = data_root.get("Currency_sign", "£")

    if not flights_data:
        return {"all_flights": [], "cheapest": None, "fastest": None, "direct": [], "price_summary": {}}

    # --- Helper for parsing one segment ---
    def parse_segment(f, segment_index=0):
        try:
            airline_code = f.get("Airlinelists", ["Unknown"])[0]
            price = float(f.get("price", {}).get("total_price", 0))
            segments = (
                f.get("OutboundInboundlist", [])[segment_index].get("flightlist", [])
                if len(f.get("OutboundInboundlist", [])) > segment_index
                else []
            )
            if not segments:
                return None

            duration_minutes = int(
                f.get("OutboundInboundlist", [])[segment_index].get("totaltime", 0)
            )
            hours, mins = divmod(duration_minutes, 60)
            duration_str = f"{hours}h {mins}m"

            first_seg, last_seg = segments[0], segments[-1]

            dep_code = first_seg["Departure"].get("Iata", "")
            dep_city = first_seg["Departure"].get("city", "")
            dep_date = first_seg["Departure"].get("Date", "")
            dep_time = first_seg["Departure"].get("time", "")

            arr_code = last_seg["Arrival"].get("Iata", "")
            arr_city = last_seg["Arrival"].get("city", "")
            arr_date = last_seg["Arrival"].get("Date", "")
            arr_time = last_seg["Arrival"].get("time", "")

            if arr_code == "XNB":
                arr_city = f"{arr_city} (via Abu Dhabi Bus Transfer)"

            airline_name = first_seg.get("OperatingAirline", {}).get("name", airline_code)

            stops = max(len(segments) - 1, 0)
            stops_detail = []
            for seg in segments[:-1]:
                stop_code = seg["Arrival"].get("Iata", "")
                stop_city = seg["Arrival"].get("city", "")
                stop_date = seg["Arrival"].get("Date", "")
                stop_time = seg["Arrival"].get("time", "")
                if stop_code == "XNB":
                    stop_city = f"{stop_city} (Bus Transfer)"
                stops_detail.append(
                    {"code": stop_code, "city": stop_city, "date": stop_date, "time": stop_time}
                )

            return {
                "airline": airline_code,
                "airline_name": airline_name,
                "price": f"{currency_sign}{price:.2f}",
                "duration": duration_str,
                "stops": stops,
                "stops_detail": stops_detail,
                "dep_code": dep_code,
                "dep_city": dep_city,
                "dep_date": dep_date,
                "dep_time": dep_time,
                "arr_code": arr_code,
                "arr_city": arr_city,
                "arr_date": arr_date,
                "arr_time": arr_time,
            }
        except Exception as e:
            print("Error parsing segment:", e)
            return None

    # --- Try to build round-trip pairs ---
    pairs = []
    for f in flights_data:
        if not f.get("OutboundInboundlist"):
            continue
        outbound_seg = parse_segment(f, 0)
        return_seg = parse_segment(f, 1) if len(f.get("OutboundInboundlist", [])) > 1 else None
        if outbound_seg and return_seg:
            pairs.append({"outbound": outbound_seg, "return": return_seg})

    # --- If pairs exist → round-trip mode ---
    if pairs:
        def duration_to_minutes(dur):
            try:
                h, m = dur.replace("m", "").split("h")
                return int(h.strip())*60 + int(m.strip())
            except:
                return 99999

        cheapest = min(pairs, key=lambda x: float(x["outbound"]["price"].replace(currency_sign, "")))
        fastest = min(
            pairs,
            key=lambda x: duration_to_minutes(x["outbound"]["duration"]) +
                          duration_to_minutes(x["return"]["duration"])
        )
        direct = [p for p in pairs if p["outbound"]["stops"] == 0 and p["return"]["stops"] == 0][:3]
        top5 = sorted(pairs, key=lambda x: float(x["outbound"]["price"].replace(currency_sign, "")))[:5]

        prices = [float(p["outbound"]["price"].replace(currency_sign, "")) for p in pairs]
        return {
            "all_flights": top5,
            "cheapest": cheapest,
            "fastest": fastest,
            "direct": direct,
            "price_summary": {
                "min_price": min(prices),
                "max_price": max(prices),
                "currency": currency_sign
            }
        }

    # --- Else → outbound-only mode ---
    outbound_only = [parse_segment(f, 0) for f in flights_data if f.get("OutboundInboundlist")]
    outbound_only = [x for x in outbound_only if x]

    if not outbound_only:
        return {"all_flights": [], "cheapest": None, "fastest": None, "direct": [], "price_summary": {}}

    # Top 5 outbound
    top5 = sorted(outbound_only, key=lambda x: float(x["price"].replace(currency_sign, "")))[:5]

    def duration_to_minutes(dur):
        try:
            h, m = dur.replace("m", "").split("h")
            return int(h.strip())*60 + int(m.strip())
        except:
            return 99999

    cheapest = min(top5, key=lambda x: float(x["price"].replace(currency_sign, "")))
    fastest = min(top5, key=lambda x: duration_to_minutes(x["duration"]))
    direct = [f for f in top5 if f["stops"] == 0][:3]

    prices = [float(f["price"].replace(currency_sign, "")) for f in top5]

    return {
        "all_flights": top5,
        "cheapest": cheapest,
        "fastest": fastest,
        "direct": direct,
        "price_summary": {
            "min_price": min(prices),
            "max_price": max(prices),
            "currency": currency_sign
        }
    }

from collections import OrderedDict

def trip_output(summary_dict, html_format=False, has_return=False):
    """
    Returns structured data + recommendation text.
    - If has_return=True → round-trip summary
    - If has_return=False → one-way summary
    """
    br = "<br>" if html_format else " "
    result = OrderedDict()

    # --- Case 1: Round-trip recommendation ---
    if has_return and summary_dict.get("all_flights"):
        cheapest = summary_dict.get("cheapest")
        fastest = summary_dict.get("fastest")
        direct = summary_dict.get("direct")

        txt = f"We found {len(summary_dict['all_flights'])} round-trip options.{br}"
        if cheapest:
            ob, rt = cheapest["outbound"], cheapest["return"]
            txt += (
                f"The cheapest round trip is with {ob['airline_name']} ({ob['airline']}) at {ob['price']}, "
                f"departing {ob['dep_city']} ({ob['dep_code']}) on {ob['dep_date']} {ob['dep_time']} "
                f"and returning from {rt['dep_city']} ({rt['dep_code']}) on {rt['dep_date']} {rt['dep_time']}, "
                f"total duration {ob['duration']} + {rt['duration']}.{br}"
            )
        if fastest:
            ob, rt = fastest["outbound"], fastest["return"]
            txt += (
                f"The fastest round trip is with {ob['airline_name']} ({ob['airline']}) at {ob['price']}, "
                f"departing {ob['dep_city']} ({ob['dep_code']}) on {ob['dep_date']} {ob['dep_time']} "
                f"and returning from {rt['dep_city']} ({rt['dep_code']}) on {rt['dep_date']} {rt['dep_time']}, "
                f"taking {ob['duration']} + {rt['duration']}.{br}"
            )
        if direct:
            direct_list = ", ".join([
                f"{p['outbound']['airline_name']} ({p['outbound']['airline']}, {p['outbound']['price']})"
                for p in direct
            ])
            txt += f"There are {len(direct)} direct round trips: {direct_list}.{br}"
        if cheapest and fastest:
            txt += (
                f"For the best deal, choose {cheapest['outbound']['airline_name']} "
                f"({cheapest['outbound']['airline']}). "
                f"For the fastest trip, go with {fastest['outbound']['airline_name']} "
                f"({fastest['outbound']['airline']})."
            )

        result["combined_recommendation"] = txt.strip()
        result.update(summary_dict)

    # --- Case 2: One-way recommendation ---
    else:
        all_flights = summary_dict.get("all_flights", [])[:5]  # limit 5 flights
        cheapest = summary_dict.get("cheapest")
        fastest = summary_dict.get("fastest")
        directs = summary_dict.get("direct", [])

        if not all_flights:
            txt = "No flights found for your search."
        else:
            txt = f"We found {len(all_flights)} flights for your route.{br}"
            if cheapest:
                txt += (
                    f"The cheapest flight is with {cheapest['airline_name']} "
                    f"({cheapest['airline']}) at {cheapest['price']}, "
                    f"departing {cheapest['dep_city']} ({cheapest['dep_code']}) "
                    f"on {cheapest['dep_date']} {cheapest['dep_time']} "
                    f"and arriving {cheapest['arr_city']} ({cheapest['arr_code']}) "
                    f"on {cheapest['arr_date']} {cheapest['arr_time']}, "
                    f"taking {cheapest['duration']}.{br}"
                )
            if fastest:
                txt += (
                    f"The fastest flight is with {fastest['airline_name']} "
                    f"({fastest['airline']}) at {fastest['price']}, "
                    f"departing {fastest['dep_city']} ({fastest['dep_code']}) "
                    f"on {fastest['dep_date']} {fastest['dep_time']} "
                    f"and arriving {fastest['arr_city']} ({fastest['arr_code']}) "
                    f"on {fastest['arr_date']} {fastest['arr_time']}, "
                    f"taking {fastest['duration']}.{br}"
                )
            if directs:
                direct_list = ", ".join([
                    f"{f['airline_name']} ({f['airline']}, {f['price']})" for f in directs[:3]
                ])
                txt += f"There are {len(directs[:3])} direct flights: {direct_list}.{br}"
            if cheapest and fastest:
                txt += (
                    f"For the best deal, choose {cheapest['airline_name']} "
                    f"({cheapest['airline']}). "
                    f"For the fastest trip, go with {fastest['airline_name']} "
                    f"({fastest['airline']})."
                )

        result["combined_recommendation"] = txt.strip()
        result.update(summary_dict)

    return result
