"""Voice/chat assistant + live agent chat."""
import json
import re
from datetime import date, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import airports
from ..providers import restaurants as rest
from ..providers import trains
from ..schemas import AssistantMessage, AssistantReply, FlightSearch, RestaurantSearch, TrainSearch
from ..services import assistant as nlu
from ..services.recommend import _hours, _money
from .catalog import run_flight_search
from .reservations import run_restaurant_search, run_train_search

router = APIRouter(prefix="/api", tags=["assistant"])
CUR = "NGN"


@router.post("/assistant", response_model=AssistantReply)
async def talk(msg: AssistantMessage):
    """One conversational turn across flights, trains and restaurants.
    The client keeps `session` and sends it back each time."""
    today = date.today()
    sess = dict(msg.session)
    mode = sess.get("mode") or "flight"

    # "yes, book it" confirms whatever was suggested last
    if nlu.is_yes(msg.text):
        if mode == "flight" and sess.get("pick_offer_id"):
            return AssistantReply(reply="Great choice. I just need the passenger details and you'll pay in one tap.",
                                  intent="confirm_offer", mode="flight", session=sess,
                                  suggestions=["Add a hotel", "Add an airport driver"])
        if mode == "train" and sess.get("pick_train_id"):
            return AssistantReply(reply="Done. Pick your seats and I'll hold them while you pay.",
                                  intent="confirm_train", mode="train", session=sess)
        if mode == "food" and sess.get("pick_restaurant_id"):
            return AssistantReply(reply="Lovely. Choose anything you'd like ready when you arrive, then confirm the table.",
                                  intent="confirm_table", mode="food", session=sess)

    new_mode = nlu.detect_mode(msg.text, mode)
    if new_mode != mode:  # switching topic: keep the other topics' state, drop this one's stale pick
        sess.pop({"flight": "pick_offer_id", "train": "pick_train_id", "food": "pick_restaurant_id"}[new_mode], None)
    sess["mode"] = mode = new_mode

    if mode == "train":
        return _train_turn(msg, sess, today)
    if mode == "food":
        return _food_turn(msg, sess, today)
    return await _flight_turn(msg, sess, today)


async def _flight_turn(msg: AssistantMessage, sess: dict, today: date) -> AssistantReply:
    parsed = await nlu.llm_parse(msg.text, today) or nlu.rule_parse(msg.text, today)
    for k, v in parsed.items():
        sess[k] = v.isoformat() if isinstance(v, date) else v

    origin, _ = nlu.to_iata(sess.get("origin_place"))
    origin = origin or sess.get("origin") or msg.origin_hint
    dest, alts = nlu.to_iata(sess.get("destination_place"))
    dest = dest or sess.get("destination")
    sess.update({"origin": origin, "destination": dest})

    if not dest:
        return AssistantReply(reply="Where would you like to fly to?", intent="need_destination", session=nlu.dumps(sess),
                              suggestions=["Lagos", "London", "Toronto", "Dubai"])
    if not origin:
        return AssistantReply(reply="Which city are you flying from? You can also turn on location and I'll find the nearest airport.",
                              intent="need_origin", session=nlu.dumps(sess), suggestions=["Abuja", "Lagos", "Port Harcourt"])
    if not sess.get("departure_date"):
        d = airports.get(dest)
        return AssistantReply(reply=f"When do you want to fly to {d.city if d else dest}?", intent="need_date",
                              session=nlu.dumps(sess), suggestions=["Tomorrow", "Next Friday", "In two weeks"])

    dep = date.fromisoformat(sess["departure_date"])
    if dep < today:
        dep = today + timedelta(days=1)
    search = FlightSearch(
        origin=origin, destination=dest, departure_date=dep,
        return_date=date.fromisoformat(sess["return_date"]) if sess.get("return_date") else None,
        adults=int(sess.get("adults") or 1), children=int(sess.get("children") or 0),
        cabin_class=sess.get("cabin_class") or "economy",
    )
    results = await run_flight_search(search)
    if not results.offers:
        return AssistantReply(reply="I couldn't find seats for that day. Want me to try the day after?",
                              intent="no_results", session=nlu.dumps(sess), search=search, suggestions=["Try the next day"])

    by_id = {o.id: o for o in results.offers}
    if sess.get("priority") == "cheapest":
        chosen = min(results.offers, key=lambda o: o.total_amount)
    elif sess.get("priority") == "fastest":
        chosen = next(o for o in results.offers if "fastest" in o.tags)
    else:
        chosen = by_id[results.pick.offer_id]
    sess["pick_offer_id"] = chosen.id

    o_ap, d_ap = airports.get(origin), airports.get(dest)
    sl = chosen.slices[0]
    stop_txt = "nonstop" if sl.stops == 0 else f"with {sl.stops} stop via {sl.segments[0].destination}"
    alt_txt = f" I searched {d_ap.city if d_ap else dest}; I can also check {', '.join(alts)}." if alts else ""
    reply = (f"I found {len(results.offers)} options from {o_ap.city if o_ap else origin} to {d_ap.city if d_ap else dest} "
             f"on {dep:%A %d %B}. My pick is {chosen.owner.name} at {_money(chosen.total_amount, chosen.currency)}, "
             f"{_hours(sl.duration_minutes)} {stop_txt}, leaving at {sl.segments[0].departing_at:%H:%M}.{alt_txt} Shall I book it?")
    sugg = ["Yes, book it", "Show me the cheapest"]
    if not sess.get("want_hotel"):
        sugg.append("Add a hotel")
    if not sess.get("want_ride"):
        sugg.append("Add a driver to the airport")
    return AssistantReply(reply=reply, intent="offer_suggested", session=nlu.dumps(sess), search=search,
                          results=results, suggestions=sugg)


def _train_turn(msg: AssistantMessage, sess: dict, today: date) -> AssistantReply:
    p = nlu.parse_train(msg.text, today)
    for src, dst in (("origin", "t_origin"), ("destination", "t_destination"), ("passengers", "t_passengers"),
                     ("travel_class", "t_class")):
        if src in p:
            sess[dst] = p[src]
    if "date" in p:
        sess["t_date"] = p["date"].isoformat()
    lines = "Abuja–Kaduna, Lagos–Ibadan, Warri–Itakpe and Port Harcourt–Aba"
    if not sess.get("t_destination"):
        return AssistantReply(reply=f"Where are you going by train? I can book {lines}.", intent="need_destination",
                              mode="train", session=nlu.dumps(sess), suggestions=["Abuja to Kaduna", "Lagos to Ibadan"])
    if not sess.get("t_origin"):
        dest = trains.station(sess["t_destination"])
        same_line = [s for s in trains.all_stations() if s.line == dest.line and s.code != dest.code]
        guess = next((s for s in same_line if s.city in ("Abuja", "Lagos", "Warri", "Port Harcourt")), same_line[0])
        sess["t_origin"] = guess.code
    o, d = trains.station(sess["t_origin"]), trains.station(sess["t_destination"])
    if o.line != d.line:
        return AssistantReply(reply=f"There's no direct train from {o.city} to {d.city}; they're on different lines. "
                                    f"Want me to look at flights instead?", intent="no_route", mode="train",
                              session=nlu.dumps(sess), suggestions=[f"Fly from {o.city} to {d.city}"])
    if not sess.get("t_date"):
        return AssistantReply(reply=f"Which day do you want to travel from {o.city} to {d.city}?", intent="need_date",
                              mode="train", session=nlu.dumps(sess), suggestions=["Today", "Tomorrow", "Saturday"])
    search = TrainSearch(origin=o.code, destination=d.code, date=date.fromisoformat(sess["t_date"]),
                         passengers=int(sess.get("t_passengers") or 1))
    res = run_train_search(search)
    if not res.offers:
        return AssistantReply(reply=f"No more trains with seats from {o.city} on {search.date:%A %d %B}. Try the next day?",
                              intent="no_results", mode="train", session=nlu.dumps(sess), train_results=res,
                              suggestions=["Tomorrow"])
    pick = next(x for x in res.offers if x.id == res.pick.offer_id)
    if re.search(r"\blater\b", msg.text, re.I) and sess.get("pick_train_id"):
        ids = [x.id for x in res.offers]
        if sess["pick_train_id"] in ids and ids.index(sess["pick_train_id"]) + 1 < len(ids):
            pick = res.offers[ids.index(sess["pick_train_id"]) + 1]
    cls = sess.get("t_class") or "standard"
    fare = next(f for f in pick.fares if f.travel_class == cls)
    sess["pick_train_id"] = pick.id
    sess["t_class"] = cls
    pax = search.passengers
    reply = (f"Train {pick.train_number} leaves {o.name.split(',')[0]} at {pick.departing_at:%H:%M} on {search.date:%A %d %B} "
             f"and reaches {d.city} at {pick.arriving_at:%H:%M}. {cls.title()} is {_money(fare.amount, 'NGN')} per person"
             f"{f' ({_money(fare.amount * pax, CUR)} for {pax})' if pax > 1 else ''}, "
             f"{fare.seats_left} seats left. Shall I book it?")
    return AssistantReply(reply=reply, intent="train_suggested", mode="train", session=nlu.dumps(sess),
                          train_results=res, suggestions=["Yes, book it", "Business class instead", "A later train"])


def _food_turn(msg: AssistantMessage, sess: dict, today: date) -> AssistantReply:
    p = nlu.parse_food(msg.text, today)
    if terms := rest.craving_terms(p["craving"]):
        sess["f_craving"] = " ".join(terms)
    for src, dst in (("city", "f_city"), ("party_size", "f_party"), ("time", "f_time"), ("budget", "f_budget")):
        if src in p:
            sess[dst] = p[src]
    if "date" in p:
        sess["f_date"] = p["date"].isoformat()
    if not sess.get("f_city") and msg.origin_hint and (ap := airports.get(msg.origin_hint)):
        sess["f_city"] = ap.city
    if not sess.get("f_craving") and not sess.get("asked_craving"):
        sess["asked_craving"] = True
        return AssistantReply(reply="What are you in the mood for?", intent="need_craving", mode="food",
                              session=nlu.dumps(sess), suggestions=["Jollof", "Suya", "Pepper soup", "Sushi", "Pizza", "Surprise me"])
    search = RestaurantSearch(craving=sess.get("f_craving"), city=sess.get("f_city") or "Abuja",
                              date=date.fromisoformat(sess["f_date"]) if sess.get("f_date") else today,
                              time=sess.get("f_time") or "19:30", party_size=int(sess.get("f_party") or 2),
                              budget=sess.get("f_budget"))
    res = run_restaurant_search(search)
    if not res.restaurants:
        return AssistantReply(reply=f"I couldn't find that in {search.city}. Want to try something close to it?",
                              intent="no_results", mode="food", session=nlu.dumps(sess), restaurant_results=res,
                              suggestions=["Nigerian food", "Grills", "Surprise me"])
    best = res.restaurants[0]
    sess["pick_restaurant_id"] = best.id
    dish = next((it.name for it in best.menu if it.id in best.matches), None)
    when = search.time if search.time in best.slots else (best.slots[0] if best.slots else None)
    if when:
        sess["f_time"] = when
    if not when:
        table = "has no free tables near that time"
    elif when == search.time:
        table = f"has a table for {search.party_size} at {when}"
    else:
        table = f"{search.time} is taken, but there's a table for {search.party_size} at {when}"
    reply = (f"Try {best.name} in {best.area}" + (f" for the {dish.lower()}" if dish else "") +
             f". It's rated {best.rating}/5 and {table}"
             + (f"; they take a {_money(best.deposit_per_guest, 'NGN')} deposit per guest, taken off your bill" if best.deposit_per_guest else "")
             + ". Want me to book it? I can have your food ready when you arrive.")
    return AssistantReply(reply=reply, intent="table_suggested", mode="food", session=nlu.dumps(sess),
                          restaurant_results=res, suggestions=["Yes, book it", "Somewhere cheaper", "Show me other places"])


# ---------------------------------------------------------------- live agents
class SupportHub:
    """Minimal in-memory relay between travellers and on-duty agents.
    Production: back this with Redis pub/sub or plug in Intercom/Freshchat."""

    def __init__(self):
        self.agents: set[WebSocket] = set()
        self.travellers: dict[str, WebSocket] = {}

    async def broadcast_agents(self, payload: dict):
        for ws in list(self.agents):
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                self.agents.discard(ws)


hub = SupportHub()


@router.websocket("/ws/support")
async def support(ws: WebSocket, role: str = "traveller", conversation: str = "", name: str = "Traveller"):
    await ws.accept()
    if role == "agent":
        hub.agents.add(ws)
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                target = hub.travellers.get(msg.get("conversation", ""))
                if target:
                    await target.send_text(json.dumps({"from": "agent", "name": msg.get("name", "Quik agent"), "text": msg["text"]}))
        except WebSocketDisconnect:
            hub.agents.discard(ws)
        return

    hub.travellers[conversation] = ws
    await ws.send_text(json.dumps({"from": "system", "text": "You're connected. An agent will reply shortly."
                                   if hub.agents else "No agents are online right now — leave a message and we'll email you."}))
    try:
        while True:
            text = await ws.receive_text()
            await hub.broadcast_agents({"conversation": conversation, "name": name, "text": text})
    except WebSocketDisconnect:
        hub.travellers.pop(conversation, None)
