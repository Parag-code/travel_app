from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid, time

from itinerary import build_itinerary, make_human_like
from flight_utils import ask_and_show_flights
from smart_flight_utils import run_smart_flight_search

app = Flask(__name__)
CORS(app)

sessions = {}
SESSION_TTL = 600


def get_session(session_id=None):
    """Fetch existing session or create a new one."""
    now = time.time()

    # Purane expired sessions hata do
    expired = [sid for sid, s in sessions.items() if now - s["timestamp"] > SESSION_TTL]
    for sid in expired:
        del sessions[sid]

    # ✅ Agar client ne session_id bheja hai
    if session_id:
        if session_id in sessions:
            # Existing session update
            sessions[session_id]["timestamp"] = now
        else:
            # 👇 Quick fix: Naya session create karo but same ID use karo
            sessions[session_id] = {
                "flight_already_searched": False,
                "started_with_flight": False,
                "last_depdate": None,
                "last_parsed": None,
                "timestamp": now
            }
        return session_id, sessions[session_id]

    # Agar client ne session_id nahi bheja to naya generate karo
    new_id = str(uuid.uuid4())
    sessions[new_id] = {
        "flight_already_searched": False,
        "started_with_flight": False,
        "last_depdate": None,
        "last_parsed": None,
        "timestamp": now
    }
    return new_id, sessions[new_id]



@app.route("/")
def home():
    return jsonify({"message": "🌍 Travel Planner API is running"})


@app.route("/query", methods=["POST"])
def query_handler():
    data = request.get_json()
    query = data.get("query", "").strip()
    session_id = data.get("session_id")

    # Get session
    session_id, state = get_session(session_id)

    if not query:
        return jsonify({"error": "⚠️ Please enter a query", "session_id": session_id}), 400

    # ---------------- detect flight query ----------------
    flight_keywords = ["flight", "book", "ticket"]
    is_flight = any(k in query.lower() for k in flight_keywords)
    if " from " in query.lower() and " to " in query.lower():
        is_flight = True

    # ---------------- case 1: flight after itinerary ----------------
    if state["last_parsed"] and not is_flight:
        parts = query.split(" ", 1)
        dep_from = parts[0].strip().upper()
        raw_date = parts[1] if len(parts) > 1 else None

        flights = ask_and_show_flights(state["last_parsed"], dep_from=dep_from, raw_date=raw_date)
        return jsonify({
            "session_id": session_id,
            "flight_search": "✅ Flights fetched after itinerary",
            "flights": flights
        })

    # ---------------- case 2: direct flight query ----------------
    if is_flight:
        flight_data = run_smart_flight_search(query)

        # ✅ Force update flags hamesha
        state["flight_already_searched"] = True
        state["started_with_flight"] = True
        if isinstance(flight_data, dict):
            state["last_depdate"] = flight_data.get("depdate")

        return jsonify({
            "session_id": session_id,
            "flight_search": "✅ Flights fetched from SkyExperts API",
            **flight_data,
            "next_question": "🗺️ Want me to plan a trip for your dates? Just tell me for how many days."
        })

    # ---------------- case 3: itinerary query ----------------
    parsed, itinerary = build_itinerary(query)
    if state["last_depdate"]:
        parsed["start_date"] = state["last_depdate"]

    state["last_parsed"] = parsed
    narrative = make_human_like(parsed, itinerary)

    response = {
        "session_id": session_id,
        "itinerary": itinerary,
        "narrative": narrative
    }

    # ✅ Flight question tabhi poochna jab ab tak flights search hi nahi hue
    if state.get("flight_already_searched") is False:
        response["next_question"] = "✈️ Do you want to book flights? Just tell me your departure city and date."

    return jsonify(response)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
