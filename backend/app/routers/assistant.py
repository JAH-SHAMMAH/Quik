"""Voice/chat assistant + live agent chat."""
import json
from datetime import date, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import airports
from ..schemas import AssistantMessage, AssistantReply, FlightSearch
from ..services import assistant as nlu
from ..services.recommend import _hours, _money
from .catalog import run_flight_search

router = APIRouter(prefix="/api", tags=["assistant"])


@router.post("/assistant", response_model=AssistantReply)
async def talk(msg: AssistantMessage):
    """One conversational turn. The client keeps `session` and sends it back each time."""
    today = date.today()
    sess = dict(msg.session)

    # Confirming a suggestion ("yes, book it")
    if sess.get("pick_offer_id") and nlu.is_yes(msg.text):
        return AssistantReply(
            reply="Great choice. I just need the passenger details and you'll pay in one tap.",
            intent="confirm_offer", session=sess, suggestions=["Add a hotel", "Add an airport driver"],
        )

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
