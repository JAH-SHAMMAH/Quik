/* Quik web client. Talks to the FastAPI backend; falls back to a built-in demo when no API is reachable. */
(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const h = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (v, cur = "NGN") => (cur === "NGN" ? "₦" : cur + " ") + Math.round(v).toLocaleString("en-NG");
  const hm = (iso) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
  const day = (iso) => new Date(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
  const dur = (m) => `${Math.floor(m / 60)}h${m % 60 ? " " + String(m % 60).padStart(2, "0") + "m" : ""}`;
  const isoDate = (d) => d.toISOString().slice(0, 10);
  const addDays = (iso, n) => { const d = new Date(iso + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return isoDate(d); };
  const TAIL = { P4: "#0B3D91", QI: "#0F7B6C", W3: "#C8102E", VK: "#6A2C91", OF: "#1C6DD0", ET: "#2E7D32", EK: "#C8102E", QR: "#5C0632", TK: "#D81E05", KL: "#00A1DE", AF: "#002157", BA: "#2E5C99", KQ: "#B71C1C", WB: "#1B5FAA", DL: "#9B1631", UA: "#1B3C87", AW: "#E65100" };

  const S = { demo: false, airports: [], search: null, results: null, sort: "best", offer: null, hotels: [], hotelId: null,
    quotes: [], rideProvider: "quik_driver", here: null, booking: null, token: null, voice: {}, wantHotel: false, wantRide: false };
  const stage = $("#stage");

  /* ------------------------------------------------------------------ API */
  async function api(path, { method = "GET", body, params } = {}) {
    if (S.demo) return Demo.handle(path, method, body, params);
    const url = new URL(path, location.origin);
    Object.entries(params || {}).forEach(([k, v]) => v != null && url.searchParams.set(k, v));
    const r = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    const data = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
    if (!r.ok) { const e = new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || "Something went wrong"); e.status = r.status; e.detail = data.detail; throw e; }
    return data;
  }

  async function detect() {
    try {
      const ctl = new AbortController(); setTimeout(() => ctl.abort(), 2500);
      const r = await fetch("/api/health", { signal: ctl.signal });
      if (!r.ok) throw 0;
      await r.json();
    } catch { S.demo = true; $("#demoBanner").hidden = false; }
    S.airports = await api("/api/airports", { params: { limit: 100 } });
  }

  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove("on"), 3200); }
  const ap = (code) => S.airports.find((a) => a.iata === code);

  /* ------------------------------------------------------------ planner */
  function bindAirportInput(id) {
    const input = $("#" + id), list = $("#" + id + "List"), label = $("#" + id + "Name");
    const show = () => {
      const q = input.value.trim().toLowerCase();
      const a = ap(input.value.trim().toUpperCase());
      label.textContent = a ? `${a.city}, ${a.country}` : "";
      if (!q || (a && q.length === 3)) { list.hidden = true; return; }
      const hits = S.airports.filter((x) => [x.iata, x.city, x.name, x.country, x.state].some((f) => f.toLowerCase().includes(q))).slice(0, 6);
      list.innerHTML = hits.map((x) => `<li><button type="button" data-iata="${x.iata}"><b>${x.iata}</b><span>${h(x.city)}, ${h(x.country)}</span></button></li>`).join("");
      list.hidden = !hits.length;
    };
    input.addEventListener("input", show);
    input.addEventListener("blur", () => setTimeout(() => (list.hidden = true), 150));
    list.addEventListener("click", (e) => {
      const b = e.target.closest("[data-iata]"); if (!b) return;
      input.value = b.dataset.iata; list.hidden = true; show(); input.blur();
    });
    input._refresh = show;
  }
  bindAirportInput("from"); bindAirportInput("to");

  $("#swap").onclick = () => { const f = $("#from"), t = $("#to"); [f.value, t.value] = [t.value, f.value]; f._refresh(); t._refresh(); };
  $("#nearMe").onclick = () => {
    if (!navigator.geolocation) return toast("Location isn't available on this device");
    $("#nearMe").textContent = "Finding airports near you…";
    navigator.geolocation.getCurrentPosition(async (p) => {
      S.here = { lat: p.coords.latitude, lng: p.coords.longitude };
      const near = await api("/api/airports", { params: { lat: S.here.lat, lng: S.here.lng, limit: 3 } });
      $("#from").value = near[0].iata; $("#from")._refresh();
      $("#nearMe").textContent = `Nearest: ${near.map((a) => `${a.iata} (${Math.round(a.distance_km)} km)`).join(", ")}`;
    }, () => { $("#nearMe").textContent = "Location blocked — type your city instead"; }, { timeout: 8000 });
  };

  const today = new Date(); $("#dep").min = isoDate(today); $("#dep").value = addDays(isoDate(today), 14); $("#ret").min = $("#dep").value;
  $("#dep").addEventListener("change", () => ($("#ret").min = $("#dep").value));

  $("#planForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const o = $("#from").value.trim().toUpperCase(), d = $("#to").value.trim().toUpperCase();
    if (!ap(o) || !ap(d)) return toast("Pick airports from the list");
    if (o === d) return toast("From and To need to be different");
    S.wantHotel = $("#wantHotel").checked; S.wantRide = $("#wantRide").checked;
    runSearch({ origin: o, destination: d, departure_date: $("#dep").value, return_date: $("#ret").value || null,
      adults: +$("#pax").value, cabin_class: $("#cabin").value });
  });

  async function runSearch(search) {
    S.search = search; S.sort = "best";
    stage.innerHTML = `<div class="head"><h2>Checking airlines…</h2></div>` + '<div class="skeleton"></div>'.repeat(3);
    $("#searchBtn").disabled = true;
    try { S.results = await api("/api/flights/search", { method: "POST", body: search }); renderResults(); }
    catch (err) { stage.innerHTML = `<div class="empty"><h2>No results</h2><p>${h(err.message)}</p></div>`; }
    finally { $("#searchBtn").disabled = false; }
    if (innerWidth < 960) stage.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /* ------------------------------------------------------------ results */
  function legHTML(sl) {
    const a = sl.segments[0], b = sl.segments[sl.segments.length - 1];
    const via = sl.stops ? `${sl.stops} stop · ${sl.segments.slice(0, -1).map((s) => s.destination).join(", ")}` : "Nonstop";
    return `<div class="leg">
      <div><div class="t">${hm(a.departing_at)}</div><div class="c">${a.origin} · ${day(a.departing_at)}</div></div>
      <div class="path"><span>${dur(sl.duration_minutes)} · ${via}</span></div>
      <div class="end"><div class="t">${hm(b.arriving_at)}</div><div class="c">${b.destination} · ${day(b.arriving_at)}</div></div>
    </div>`;
  }

  function passHTML(o, pick) {
    const tagNames = { cheapest: "Cheapest", fastest: "Fastest" };
    const tags = o.tags.filter((t) => tagNames[t]).map((t) => `<span class="tag">${tagNames[t]}</span>`).join("");
    const facts = [o.checked_bags ? `${o.checked_bags} checked bag${o.checked_bags > 1 ? "s" : ""}` : "Cabin bag only",
      o.changeable ? "Changes allowed" : "No changes", o.refundable ? "Refundable" : "Non-refundable",
      o.slices[0].segments[0].aircraft].filter(Boolean).map((f) => `<span>${h(f)}</span>`).join("");
    const pax = S.search.adults > 1 ? `for ${S.search.adults} travellers` : "per traveller";
    return `<article class="pass ${pick ? "pick" : ""}" aria-label="${h(o.owner.name)} ${money(o.total_amount, o.currency)}">
      <div class="main">
        <div class="airline"><span class="tail" style="background:${TAIL[o.owner.code] || "#334"}">${h(o.owner.code)}</span>${h(o.owner.name)}<span class="tags" style="margin-left:auto">${tags}</span></div>
        <div class="legs">${o.slices.map(legHTML).join("")}</div>
        <div class="facts">${facts}</div>
        ${pick ? `<div class="why"><div class="pickline">Why it's our pick</div><ul class="reasons">${pick.reasons.map((r) => `<li>${h(r)}</li>`).join("")}</ul></div>` : ""}
      </div>
      <div class="stub">
        ${pick ? `<div class="pickline">Quik Pick</div>` : ""}
        <div class="price">${money(o.total_amount, o.currency)}<small>${pax}, taxes included</small></div>
        <button class="${pick ? "primary" : "secondary"}" style="margin-top:0" data-choose="${o.id}">${pick ? "Book my pick" : "Choose"}</button>
      </div>
    </article>`;
  }

  function renderResults() {
    const r = S.results, s = S.search;
    if (!r.offers.length) { stage.innerHTML = `<div class="empty"><h2>No seats on that day</h2><p>Try a nearby date or another airport in the same city.</p></div>`; return; }
    const pick = r.pick, pickOffer = r.offers.find((o) => o.id === pick.offer_id);
    const rest = r.offers.filter((o) => o.id !== pick.offer_id);
    const key = { best: (o) => o.score, cheapest: (o) => o.total_amount, fastest: (o) => o.slices.reduce((a, b) => a + b.duration_minutes, 0) }[S.sort];
    rest.sort((a, b) => key(a) - key(b));
    const oa = ap(s.origin), da = ap(s.destination);
    stage.innerHTML = `
      <div class="head">
        <div><h2>${h(oa?.city || s.origin)} to ${h(da?.city || s.destination)}</h2><p>${day(s.departure_date + "T12:00:00Z")}${s.return_date ? " – " + day(s.return_date + "T12:00:00Z") : ", one way"} · ${r.offers.length} options</p></div>
        <div class="sort" role="group" aria-label="Sort other flights">
          ${["best", "cheapest", "fastest"].map((k) => `<button type="button" data-sort="${k}" aria-pressed="${S.sort === k}">${k[0].toUpperCase() + k.slice(1)}</button>`).join("")}
        </div>
      </div>
      ${passHTML(pickOffer, pick)}
      <form class="watch" id="watchForm"><label for="watchEmail">Prices on this route move. Get an email if it drops:</label><input id="watchEmail" type="email" required placeholder="you@email.com"><button class="secondary" id="watchBtn">Track this fare</button></form>
      ${rest.map((o) => passHTML(o)).join("")}`;
  }

  stage.addEventListener("click", (e) => {
    const sort = e.target.closest("[data-sort]");
    if (sort) { S.sort = sort.dataset.sort; renderResults(); return; }
    const ch = e.target.closest("[data-choose]");
    if (ch) { chooseOffer(ch.dataset.choose); return; }
  });
  stage.addEventListener("submit", (e) => { if (e.target.id === "watchForm") { e.preventDefault(); trackFare($("#watchBtn")); } });

  async function trackFare(btn) {
    const email = $("#watchEmail").value.trim();
    try {
      const w = await api("/api/price-watches", { method: "POST", body: { email, search: S.search } });
      btn.textContent = "Tracking"; btn.disabled = true;
      toast(`Tracking from ${money(w.starting_price)}. We'll email you if it drops.`);
    } catch (err) { toast(err.message); }
  }

  /* ------------------------------------------------------------ extras */
  function chooseOffer(id) {
    S.offer = S.results.offers.find((o) => o.id === id);
    if (S.wantHotel || S.wantRide) renderExtras(); else renderPassengers();
  }

  async function renderExtras() {
    const o = S.offer, dest = ap(S.search.destination), orig = ap(S.search.origin);
    stage.innerHTML = `<button class="back" data-go="results">← Back to flights</button><div id="extras"></div>`;
    const box = $("#extras");
    let html = "";
    if (S.wantHotel) {
      const out = o.slices[0], arrive = out.segments[out.segments.length - 1].arriving_at.slice(0, 10);
      const leave = S.search.return_date || addDays(arrive, 3);
      S.hotels = await api("/api/hotels/search", { method: "POST", body: { city_iata: S.search.destination, check_in: arrive, check_out: leave > arrive ? leave : addDays(arrive, 1), guests: S.search.adults } });
      S.hotelId = S.hotelId || S.hotels[0]?.id;
      html += `<section class="panel"><h3>Hotel in ${h(dest.city)}</h3><p>${day(arrive + "T12:00:00Z")} to ${day((leave > arrive ? leave : addDays(arrive, 1)) + "T12:00:00Z")}, sorted by price.</p><div class="choices">
        ${S.hotels.map((x) => `<label class="choice"><input type="radio" name="hotel" value="${x.id}" ${x.id === S.hotelId ? "checked" : ""}>
          <span class="grow"><b>${h(x.name)}</b> <span aria-label="${x.stars} stars">${"★".repeat(x.stars)}</span><div class="sub">${h(x.area)} · ${x.guest_rating}/10 · ${x.distance_to_airport_km} km from the airport${x.free_cancellation ? " · Free cancellation" : ""}</div></span>
          <span class="amt">${money(x.total_amount)}<div class="sub">${money(x.price_per_night)}/night</div></span></label>`).join("")}
        <label class="choice"><input type="radio" name="hotel" value="" ${S.hotelId ? "" : "checked"}><span class="grow">No hotel this time</span></label></div></section>`;
    }
    if (S.wantRide) {
      const from = S.here || { lat: orig.lat + 0.07, lng: orig.lng + 0.2 };
      S.pickup = { ...from, address: S.here ? "Your current location" : `${orig.city} city centre` };
      S.quotes = await api("/api/rides/quotes", { method: "POST", body: { pickup: S.pickup, dropoff: { lat: orig.lat, lng: orig.lng, address: orig.name } } });
      html += `<section class="panel"><h3>Driver to ${h(orig.iata)}</h3><p>Pickup from ${h(S.pickup.address)}, timed to your ${hm(o.slices[0].segments[0].departing_at)} departure.</p><div class="choices">
        ${S.quotes.map((q) => `<label class="choice"><input type="radio" name="ride" value="${q.provider}" ${q.provider === S.rideProvider ? "checked" : ""}>
          <span class="grow"><b>${h(q.product)}</b><div class="sub">${h(q.note)}</div></span>
          <span class="amt">${money(q.estimate_low)}–${money(q.estimate_high).replace("₦", "")}<div class="sub">${q.in_app_booking ? "Pay with your trip" : "Pay in app"}</div></span></label>`).join("")}
        <label class="choice"><input type="radio" name="ride" value="" ${S.rideProvider ? "" : "checked"}><span class="grow">I'll get there myself</span></label></div></section>`;
    }
    box.innerHTML = html + `<button class="primary" data-go="passengers">Continue to traveller details</button>`;
    box.addEventListener("change", (e) => {
      if (e.target.name === "hotel") S.hotelId = e.target.value || null;
      if (e.target.name === "ride") S.rideProvider = e.target.value || null;
    });
  }

  /* ------------------------------------------------------------ passengers */
  function intl() { const a = ap(S.search.origin), b = ap(S.search.destination); return a && b && a.country_code !== b.country_code; }

  function renderPassengers() {
    const n = S.search.adults, needPassport = intl();
    const one = (i) => `<fieldset class="panel" style="margin:0 0 12px"><legend class="sr">Traveller ${i + 1}</legend>
      <h3>Traveller ${i + 1}</h3><p>As written on ${needPassport ? "the passport" : "a valid ID"}.</p>
      <div class="grid2">
        <div class="field"><label for="t${i}">Title</label><select id="t${i}" name="title"><option value="mr">Mr</option><option value="ms">Ms</option><option value="mrs">Mrs</option><option value="miss">Miss</option><option value="dr">Dr</option></select></div>
        <div class="field"><label for="g${i}">Gender</label><select id="g${i}" name="gender"><option value="m">Male</option><option value="f">Female</option></select></div>
        <div class="field"><label for="fn${i}">First name</label><input id="fn${i}" name="given_name" required autocomplete="given-name"></div>
        <div class="field"><label for="ln${i}">Last name</label><input id="ln${i}" name="family_name" required autocomplete="family-name"></div>
        <div class="field"><label for="dob${i}">Date of birth</label><input id="dob${i}" name="born_on" type="date" required max="${isoDate(today)}"></div>
        ${needPassport ? `<div class="field"><label for="pp${i}">Passport number</label><input id="pp${i}" name="passport_number" required></div>` : ""}
      </div></fieldset>`;
    stage.innerHTML = `<button class="back" data-go="${S.wantHotel || S.wantRide ? "extras" : "results"}">← Back</button>
      <form id="paxForm">${Array.from({ length: n }, (_, i) => one(i)).join("")}
        <section class="panel"><h3>Where should we send the ticket?</h3><p>Your ticket, trip document and any flight changes go here.</p>
          <div class="grid2"><div class="field"><label for="cEmail">Email</label><input id="cEmail" type="email" required autocomplete="email"></div>
          <div class="field"><label for="cPhone">Phone</label><input id="cPhone" type="tel" required placeholder="+234…" autocomplete="tel"></div></div>
          ${S.rideProvider && S.wantRide ? `<p class="note" style="margin-top:10px">Your driver will see this number, and you'll get theirs.</p>` : ""}
        </section>
        <button class="primary">Review and pay</button><p class="err" id="paxErr" hidden></p></form>`;
    $("#paxForm").addEventListener("submit", createBooking);
  }

  async function createBooking(e) {
    e.preventDefault();
    const passengers = [...e.target.querySelectorAll("fieldset")].map((fs) => {
      const p = { type: "adult" }; fs.querySelectorAll("[name]").forEach((el) => (p[el.name] = el.value.trim())); return p;
    });
    const orig = ap(S.search.origin);
    const body = { flight_offer_id: S.offer.id, hotel_offer_id: S.wantHotel ? S.hotelId : null, passengers,
      ride: S.wantRide && S.rideProvider ? { provider: S.rideProvider, pickup: S.pickup, dropoff: { lat: orig.lat, lng: orig.lng, address: orig.name } } : null,
      contact_email: $("#cEmail").value.trim(), contact_phone: $("#cPhone").value.trim() };
    const btn = e.submitter; btn.disabled = true;
    try {
      const res = await api("/api/bookings", { method: "POST", body });
      S.booking = res.booking; S.token = res.token; renderReview();
    } catch (err) {
      if (err.status === 409 && err.detail?.new) {
        $("#paxErr").textContent = `The airline changed this fare from ${money(err.detail.old)} to ${money(err.detail.new)}. Press again to accept the new price.`;
        S.offer = { ...S.offer, id: err.detail.offer_id, total_amount: err.detail.new };
      } else $("#paxErr").textContent = err.message;
      $("#paxErr").hidden = false;
    } finally { btn.disabled = false; }
  }

  function renderReview() {
    const b = S.booking;
    const row = (l, v) => (v ? `<div><span>${l}</span><span>${money(v, b.currency)}</span></div>` : "");
    stage.innerHTML = `<section class="panel"><h3>Review your trip</h3><p>${h(b.flight_offer.owner.name)} · ${b.flight_offer.slices.map((s) => `${s.origin}–${s.destination}`).join(", ")}</p>
      <div class="total">${row("Flight", b.fare_amount)}${row("Hotel", b.hotel_amount)}${row("Airport driver", b.ride_amount)}${row("Quik service fee", b.service_fee)}
      <div class="sum"><span>Total</span><span>${money(b.total_amount, b.currency)}</span></div></div>
      <button class="primary" id="payBtn">Pay ${money(b.total_amount, b.currency)}</button>
      <p class="note">Card, bank transfer or USSD. Your fare is held for a few minutes.</p></section>`;
    $("#payBtn").onclick = pay;
  }

  async function pay() {
    $("#payBtn").disabled = true;
    try {
      const p = await api(`/api/bookings/${S.booking.id}/pay`, { method: "POST", params: { token: S.token } });
      if (S.demo) return openTrip(S.booking.id, S.token);
      location.href = p.checkout_url;
    } catch (err) { toast(err.message); $("#payBtn").disabled = false; }
  }

  /* ------------------------------------------------------------ trip */
  async function openTrip(id, token) {
    let b;
    try { b = await api(`/api/bookings/${id}`, { params: { token } }); } catch { toast("We couldn't open that trip"); return; }
    S.booking = b; S.token = token;
    const st = { ticketed: ["Ticket confirmed", ""], pending_payment: ["Awaiting payment", "wait"], paid: ["Confirming with airline", "wait"], failed: ["Needs attention", "bad"] }[b.status] || [b.status, "wait"];
    const o = b.flight_offer, r = b.ride, ho = b.hotel_offer;
    const driver = r?.driver ? `<div class="driver"><span class="face">${h(r.driver.name[0])}</span><div><b>${h(r.driver.name)}</b> · ${r.driver.rating}★<div class="note">${h(r.driver.car)} · ${h(r.driver.plate)}<br>Pickup ${day(r.pickup_time)}, ${hm(r.pickup_time)}</div></div><a class="secondary" href="tel:${h(r.driver.phone)}">Call</a></div>`
      : r?.deeplink ? `<div class="driver"><div><b>Ride with ${h(r.provider)}</b><div class="note">Trip pre-filled. Book it in the app closer to pickup.</div></div><a class="secondary" href="${h(r.deeplink)}" target="_blank" rel="noopener">Open ${h(r.provider)}</a></div>` : "";
    stage.innerHTML = `
      <div class="ticket-head"><div><small>Quik reference</small><div class="ref">${h(b.reference)}</div><small>Airline PNR ${h(b.airline_booking_reference || "pending")}</small></div><span class="status ${st[1]}">${st[0]}</span></div>
      <div class="ticket-body">
        <div class="airline"><span class="tail" style="background:${TAIL[o.owner.code] || "#334"}">${h(o.owner.code)}</span>${h(o.owner.name)}</div>
        <div class="legs">${o.slices.map(legHTML).join("")}</div>
        ${ho ? `<p style="margin:14px 0 0"><b>${h(ho.name)}</b> · ${h(ho.area)} · ${ho.nights} night${ho.nights > 1 ? "s" : ""}</p>` : ""}
        ${driver}
        <div class="actions">
          ${b.status === "ticketed" && !S.demo ? `<a class="secondary" href="/api/bookings/${b.id}/document?token=${encodeURIComponent(token)}" target="_blank" rel="noopener">Download trip document</a>` : ""}
          <button class="secondary" type="button" data-agent>Talk to an agent</button>
        </div>
      </div>
      <section class="panel"><h3>What's happened</h3><p>Flight changes from the airline show up here and in your email.</p>
        <ol class="timeline">${[...b.events].reverse().map((ev) => `<li class="${h(ev.kind)}"><time>${new Date(ev.at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}</time>${h(ev.text)}</li>`).join("")}</ol></section>`;
    history.replaceState(null, "", `?trip=${encodeURIComponent(id)}&token=${encodeURIComponent(token)}`);
  }

  stage.addEventListener("click", (e) => {
    const go = e.target.closest("[data-go]")?.dataset.go;
    if (go === "results") renderResults(); else if (go === "extras") renderExtras(); else if (go === "passengers") renderPassengers();
    if (e.target.closest("[data-agent]")) openSheet("agentSheet");
  });

  /* ------------------------------------------------------------ sheets */
  function openSheet(id) { const s = $("#" + id); s.setAttribute("open", ""); s.querySelector("input")?.focus(); if (id === "agentSheet") Agent.connect(); }
  document.querySelectorAll(".sheet").forEach((s) => {
    s.addEventListener("click", (e) => { if (e.target === s || e.target.closest("[data-close]")) s.removeAttribute("open"); });
  });
  addEventListener("keydown", (e) => { if (e.key === "Escape") document.querySelectorAll(".sheet[open]").forEach((s) => s.removeAttribute("open")); });
  $("#openTrips").onclick = () => openSheet("tripSheet");
  $("#openAgent").onclick = () => openSheet("agentSheet");
  $("#tripForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/bookings/lookup", { method: "POST", body: { reference: $("#tripRef").value.trim(), email: $("#tripEmail").value.trim() } });
      $("#tripSheet").removeAttribute("open");
      if (r.kind && r.kind !== "flight") window.QuikMore.openReservation(r.reservation.id, r.token); else openTrip(r.booking.id, r.token);
    } catch (err) { $("#tripErr").textContent = "No trip matches that reference and email."; $("#tripErr").hidden = false; }
  });

  /* ------------------------------------------------------------ voice */
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const log = $("#voiceLog"), chips = $("#voiceChips");
  function say(text, who) {
    log.insertAdjacentHTML("beforeend", `<div class="msg ${who}">${h(text)}</div>`); log.scrollTop = log.scrollHeight;
    if (who === "them" && "speechSynthesis" in window && S.voiceOn) { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.lang = "en-GB"; speechSynthesis.speak(u); }
  }
  $("#openVoice").onclick = () => {
    openSheet("voiceSheet");
    if (!log.children.length) { say("Hi! Where are you going, or what are you hungry for? I can book flights, trains and restaurant tables.", "them"); setChips(["Fly to Canada next Friday", "Train to Kaduna tomorrow", "I'm hungry, I want jollof"]); }
  };
  function setChips(list) { chips.innerHTML = list.map((c) => `<button type="button">${h(c)}</button>`).join(""); }
  chips.addEventListener("click", (e) => { if (e.target.tagName === "BUTTON") send(e.target.textContent); });
  $("#voiceForm").addEventListener("submit", (e) => { e.preventDefault(); const t = $("#voiceText").value.trim(); if (t) send(t); $("#voiceText").value = ""; });

  async function send(text) {
    say(text, "me"); chips.innerHTML = "";
    if (/hotel/i.test(text)) { S.wantHotel = true; $("#wantHotel").checked = true; }
    if (/driver|ride|pick ?up|uber|bolt/i.test(text)) { S.wantRide = true; $("#wantRide").checked = true; }
    try {
      const r = await api("/api/assistant", { method: "POST", body: { text, session: S.voice, origin_hint: $("#from").value.trim().toUpperCase() || (S.demo ? "ABV" : null) } });
      S.voice = r.session; say(r.reply, "them"); setChips(r.suggestions || []);
      if (window.QuikMore?.onAssistant(r)) return;
      if (r.results) {
        S.search = r.search; S.results = r.results; S.sort = "best";
        $("#from").value = r.search.origin; $("#to").value = r.search.destination; $("#dep").value = r.search.departure_date;
        $("#from")._refresh(); $("#to")._refresh(); renderResults();
      }
      if (r.intent === "confirm_offer" && r.session.pick_offer_id) { $("#voiceSheet").removeAttribute("open"); chooseOffer(r.session.pick_offer_id); }
    } catch (err) { say(err.message, "them"); }
  }

  $("#micBtn").onclick = () => {
    if (!SR) { toast("Voice input isn't supported in this browser — type instead"); return; }
    S.voiceOn = true;
    const rec = new SR(); rec.lang = "en-NG"; rec.interimResults = false;
    $("#micBtn").classList.add("live");
    rec.onresult = (e) => send(e.results[0][0].transcript);
    rec.onend = () => $("#micBtn").classList.remove("live");
    rec.onerror = () => toast("I didn't catch that. Try again or type it.");
    rec.start();
  };

  /* ------------------------------------------------------------ live agent */
  const Agent = {
    ws: null, id: "c_" + Math.random().toString(36).slice(2, 10),
    connect() {
      if (this.ws || S.demo) { if (S.demo && !$("#agentLog").children.length) this.show("system", "You're connected. An agent will reply shortly."); return; }
      const proto = location.protocol === "https:" ? "wss" : "ws";
      this.ws = new WebSocket(`${proto}://${location.host}/api/ws/support?conversation=${this.id}&name=${encodeURIComponent(S.booking?.reference || "Traveller")}`);
      this.ws.onmessage = (e) => { const m = JSON.parse(e.data); this.show(m.from, m.text); };
      this.ws.onclose = () => (this.ws = null);
    },
    show(from, text) { const l = $("#agentLog"); l.insertAdjacentHTML("beforeend", `<div class="msg ${from === "me" ? "me" : "them"}">${h(text)}</div>`); l.scrollTop = l.scrollHeight; },
  };
  $("#agentForm").addEventListener("submit", (e) => {
    e.preventDefault(); const t = $("#agentText").value.trim(); if (!t) return;
    Agent.show("me", t); $("#agentText").value = "";
    if (S.demo) setTimeout(() => Agent.show("agent", "Thanks — I'm Chiamaka from Quik support. Let me pull up your trip."), 900);
    else Agent.ws?.send(t);
  });

  /* ------------------------------------------------------------ demo backend (no API reachable) */
  const Demo = (() => {
    const A = [["ABV", "Nnamdi Azikiwe International Airport", "Abuja", "FCT", "Nigeria", "NG", 9.0068, 7.2632], ["LOS", "Murtala Muhammed International Airport", "Lagos", "Lagos", "Nigeria", "NG", 6.5774, 3.3212], ["PHC", "Port Harcourt International Airport", "Port Harcourt", "Rivers", "Nigeria", "NG", 5.0155, 6.9496], ["KAN", "Mallam Aminu Kano International Airport", "Kano", "Kano", "Nigeria", "NG", 12.0476, 8.5246], ["ENU", "Akanu Ibiam International Airport", "Enugu", "Enugu", "Nigeria", "NG", 6.4743, 7.562], ["QUO", "Victor Attah International Airport", "Uyo", "Akwa Ibom", "Nigeria", "NG", 4.8725, 8.0934], ["ACC", "Kotoka International Airport", "Accra", "Greater Accra", "Ghana", "GH", 5.6052, -0.1668], ["NBO", "Jomo Kenyatta International Airport", "Nairobi", "Nairobi", "Kenya", "KE", -1.3192, 36.9278], ["ADD", "Addis Ababa Bole International Airport", "Addis Ababa", "Addis Ababa", "Ethiopia", "ET", 8.9779, 38.7993], ["LHR", "Heathrow Airport", "London", "England", "United Kingdom", "GB", 51.47, -0.4543], ["LGW", "Gatwick Airport", "London", "England", "United Kingdom", "GB", 51.1537, -0.1821], ["YYZ", "Toronto Pearson International Airport", "Toronto", "Ontario", "Canada", "CA", 43.6777, -79.6248], ["YUL", "Montréal–Trudeau International Airport", "Montreal", "Quebec", "Canada", "CA", 45.4706, -73.7408], ["JFK", "John F. Kennedy International Airport", "New York", "New York", "United States", "US", 40.6413, -73.7781], ["ATL", "Hartsfield–Jackson Atlanta International Airport", "Atlanta", "Georgia", "United States", "US", 33.6407, -84.4277], ["DXB", "Dubai International Airport", "Dubai", "Dubai", "United Arab Emirates", "AE", 25.2532, 55.3657], ["DOH", "Hamad International Airport", "Doha", "Doha", "Qatar", "QA", 25.2731, 51.6081], ["IST", "Istanbul Airport", "Istanbul", "Istanbul", "Turkey", "TR", 41.2753, 28.7519], ["AMS", "Amsterdam Airport Schiphol", "Amsterdam", "North Holland", "Netherlands", "NL", 52.3105, 4.7683], ["CDG", "Paris Charles de Gaulle Airport", "Paris", "Île-de-France", "France", "FR", 49.0097, 2.5479]]
      .map(([iata, name, city, state, country, country_code, lat, lng]) => ({ iata, name, city, state, country, country_code, lat, lng }));
    const km = (a, b) => { const R = 6371, r = Math.PI / 180, dl = (b.lat - a.lat) * r, dn = (b.lng - a.lng) * r; const x = Math.sin(dl / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dn / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(x)); };
    const mins = (a, b) => Math.round(km(ap(a), ap(b)) / 820 * 60 + 35);
    let seed = 1; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const pickR = (arr) => arr[Math.floor(rnd() * arr.length)];
    const DOM = [["P4", "Air Peace"], ["QI", "Ibom Air"], ["W3", "Arik Air"], ["VK", "ValueJet"], ["OF", "Overland Airways"]];
    const HUB = [["ET", "Ethiopian Airlines", "ADD"], ["EK", "Emirates", "DXB"], ["QR", "Qatar Airways", "DOH"], ["TK", "Turkish Airlines", "IST"], ["KL", "KLM", "AMS"], ["AF", "Air France", "CDG"], ["BA", "British Airways", "LHR"]];
    const REL = { ET: .86, EK: .9, QR: .9, TK: .84, KL: .85, AF: .82, BA: .8, P4: .72, QI: .82, W3: .68, VK: .74, OF: .7 };
    const bookings = {};

    function slice(legs, dateIso) {
      let t = Date.parse(dateIso + "T00:00:00Z") + pickR([6, 8, 9, 11, 13, 15, 17, 20, 22]) * 3600e3 + pickR([0, 15, 30, 45]) * 60e3;
      const segs = legs.map(([c, n, a, b], i) => {
        if (i) t += (75 + Math.floor(rnd() * 200)) * 60e3;
        const m = mins(a, b), s = { carrier: { code: c, name: n }, flight_number: c + (100 + Math.floor(rnd() * 880)), origin: a, destination: b, departing_at: new Date(t).toISOString(), arriving_at: new Date(t + m * 60e3).toISOString(), duration_minutes: m, aircraft: pickR(["Boeing 737-800", "Embraer E195", "Airbus A330", "Boeing 787-9", "Airbus A350"]) };
        t += m * 60e3; return s;
      });
      return { origin: legs[0][2], destination: legs.at(-1)[3], duration_minutes: Math.round((Date.parse(segs.at(-1).arriving_at) - Date.parse(segs[0].departing_at)) / 60e3), stops: segs.length - 1, segments: segs };
    }

    function search(s) {
      seed = [...(s.origin + s.destination + s.departure_date)].reduce((a, c) => a * 31 + c.charCodeAt(0), 7) % 2147483647 || 1;
      const domestic = ap(s.origin).country_code === ap(s.destination).country_code;
      const its = domestic ? DOM.slice(0, 4 + Math.floor(rnd() * 2)).map(([c, n]) => [[c, n, s.origin, s.destination]])
        : HUB.filter(([, , hub]) => hub !== s.origin).map(([c, n, hub]) => hub === s.destination ? [[c, n, s.origin, hub]] : [[c, n, s.origin, hub], [c, n, hub, s.destination]])
          .filter((legs) => legs.length === 1 || mins(legs[0][2], legs[0][3]) + mins(legs[1][2], legs[1][3]) < mins(s.origin, s.destination) * 1.7);
      const offers = its.map((legs, i) => {
        const slices = [slice(legs, s.departure_date)];
        if (s.return_date) slices.push(slice(legs.slice().reverse().map(([c, n, a, b]) => [c, n, b, a]), s.return_date));
        const k = legs.reduce((a, l) => a + mins(l[2], l[3]), 0) / 60 * 820;
        let p = (domestic ? 62000 + k * 115 : 180000 + k * 155) * (0.85 + rnd() * 0.35) * (s.return_date ? 1.75 : 1) * ({ economy: 1, premium_economy: 1.6, business: 3.2, first: 5 }[s.cabin_class]) * s.adults;
        p = Math.round(p / 100) * 100;
        return { id: `demo_${seed}_${i}`, provider: "demo", owner: { code: legs[0][0], name: legs[0][1] }, slices, currency: "NGN", base_amount: p * .8, tax_amount: p * .2, total_amount: p, checked_bags: domestic ? Math.round(rnd()) : 1 + Math.round(rnd()), refundable: rnd() < .25, changeable: rnd() < .6, tags: [], score: 0 };
      });
      const P = offers.map((o) => o.total_amount), T = offers.map((o) => o.slices.reduce((a, b) => a + b.duration_minutes, 0));
      const n = (v, a) => (Math.max(...a) === Math.min(...a) ? 0 : (v - Math.min(...a)) / (Math.max(...a) - Math.min(...a)));
      offers.forEach((o, i) => (o.score = .5 * n(P[i], P) + .22 * n(T[i], T) + .13 * o.slices[0].stops / 2 + .1 * (1 - (REL[o.owner.code] || .75)) + .05 * (o.changeable ? .5 : 1)));
      offers.sort((a, b) => a.score - b.score);
      const best = offers[0], cheap = offers.reduce((a, b) => (b.total_amount < a.total_amount ? b : a)), fast = offers.reduce((a, b, i) => (T[offers.indexOf(b)] < T[offers.indexOf(a)] ? b : a));
      cheap.tags.push("cheapest"); fast.tags.push("fastest"); best.tags.push("quik_pick");
      const reasons = [best === cheap ? "Lowest fare on this route" : `Only ${money(best.total_amount - cheap.total_amount)} more than the cheapest, with a better schedule`,
        best.slices[0].stops ? `1 stop via ${best.slices[0].segments[0].destination}` : "Nonstop"];
      if ((REL[best.owner.code] || 0) >= .84) reasons.push(`${best.owner.name} has a strong on-time record`);
      if (best.checked_bags) reasons.push(`${best.checked_bags} checked bag${best.checked_bags > 1 ? "s" : ""} included`);
      offers.forEach((o) => (Demo._offers[o.id] = o));
      return { search: s, offers, pick: { offer_id: best.id, headline: best.owner.name, reasons }, service_fee: 3500 + best.total_amount * .015, currency: "NGN" };
    }

    function assistant({ text, session }) {
      const t = text.toLowerCase(); const sess = { ...session };
      if (sess.pick_offer_id && /^(yes|yeah|ok|sure|book it|go ahead)/.test(t)) return { reply: "Great choice. I just need the passenger details and you'll pay in one tap.", intent: "confirm_offer", session: sess, suggestions: [] };
      const map = { canada: "YYZ", toronto: "YYZ", montreal: "YUL", london: "LHR", "uk": "LHR", lagos: "LOS", abuja: "ABV", dubai: "DXB", accra: "ACC", ghana: "ACC", nairobi: "NBO", "new york": "JFK", atlanta: "ATL", paris: "CDG", amsterdam: "AMS", istanbul: "IST", "port harcourt": "PHC", kano: "KAN", enugu: "ENU" };
      const to = t.match(/to ([a-z ]+?)(?= on| next| tomorrow| in| for| with|$)/); const fr = t.match(/from ([a-z ]+?)(?= to| on|$)/);
      const lookup = (s) => Object.entries(map).find(([k]) => s.includes(k))?.[1];
      if (to) sess.destination = lookup(to[1]) || sess.destination; else if (!sess.destination) sess.destination = lookup(t.replace(/^.*?(?=[a-z])/, ""));
      if (fr) sess.origin = lookup(fr[1]); sess.origin = sess.origin || "ABV";
      if (sess.origin === sess.destination) sess.origin = sess.destination === "ABV" ? "LOS" : "ABV";
      const now = new Date(); const d0 = isoDate(now);
      if (/tomorrow/.test(t)) sess.departure_date = addDays(d0, 1);
      else if (/next week/.test(t)) sess.departure_date = addDays(d0, 7);
      else if (/two weeks|2 weeks/.test(t)) sess.departure_date = addDays(d0, 14);
      else { const wd = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"].findIndex((w) => t.includes(w)); if (wd >= 0) sess.departure_date = addDays(d0, ((wd - now.getDay() + 7) % 7) || 7); }
      const forN = t.match(/for (\d+|five|three|seven) (day|night)s?/); if (forN && sess.departure_date) sess.return_date = addDays(sess.departure_date, +forN[1] || { three: 3, five: 5, seven: 7 }[forN[1]]);
      if (!sess.destination) return { reply: "Where would you like to fly to?", intent: "need_destination", session: sess, suggestions: ["Lagos", "London", "Toronto", "Dubai"] };
      if (!sess.departure_date) return { reply: `When do you want to fly to ${ap(sess.destination).city}?`, intent: "need_date", session: sess, suggestions: ["Tomorrow", "Next Friday", "In two weeks"] };
      const s = { origin: sess.origin, destination: sess.destination, departure_date: sess.departure_date, return_date: sess.return_date || null, adults: 1, cabin_class: "economy" };
      const r = search(s); const o = r.offers[0]; sess.pick_offer_id = o.id;
      return { reply: `I found ${r.offers.length} options from ${ap(s.origin).city} to ${ap(s.destination).city}. My pick is ${o.owner.name} at ${money(o.total_amount)}, ${dur(o.slices[0].duration_minutes)}${o.slices[0].stops ? " with one stop" : " nonstop"}, leaving at ${hm(o.slices[0].segments[0].departing_at)}. Shall I book it?`, intent: "offer_suggested", session: sess, search: s, results: r, suggestions: ["Yes, book it", "Add a hotel", "Add a driver to the airport"] };
    }

    return {
      _offers: {},
      async handle(path, method, body, params = {}) {
        await new Promise((r) => setTimeout(r, path.includes("search") || path.includes("assistant") ? 650 : 200));
        if (path === "/api/airports") {
          let a = A.map((x) => ({ ...x }));
          if (params.lat != null) { a.forEach((x) => (x.distance_km = km({ lat: +params.lat, lng: +params.lng }, x))); a.sort((p, q) => p.distance_km - q.distance_km); }
          return a.slice(0, params.limit || 10);
        }
        if (path === "/api/flights/search") return search(body);
        if (path === "/api/assistant") return window.QuikMore?.demoAssistant(body) || assistant(body);
        if (path === "/api/hotels/search") {
          const nights = Math.max(1, (Date.parse(body.check_out) - Date.parse(body.check_in)) / 864e5), city = ap(body.city_iata).city, ng = ap(body.city_iata).country_code === "NG";
          return ["Palm Court", "Skyline Suites", "The Residency", "Baobab Lodge"].map((n, i) => { const ppn = Math.round((ng ? 32000 : 98000) * (1 + i * .35) / 500) * 500; return { id: `demo_h${i}`, name: `${n} ${city}`, area: ng ? ["Maitama", "Wuse II", "Victoria Island", "GRA"][i] : ["City Centre", "Downtown", "Airport District", "Old Town"][i], stars: 3 + (i % 3), guest_rating: (8 + i * .4).toFixed(1), nights, price_per_night: ppn, total_amount: ppn * nights, currency: "NGN", distance_to_airport_km: 6 + i * 7, free_cancellation: i % 2 === 0 }; });
        }
        if (path === "/api/rides/quotes") {
          const k = km(body.pickup, body.dropoff) * 1.3;
          const q = (b, p) => [Math.round((b + p * k) * .85 / 100) * 100, Math.round((b + p * k) * 1.2 / 100) * 100];
          const [a, b] = q(2500, 480), [c, d] = q(1500, 420), [e, f] = q(1300, 400);
          return [{ provider: "quik_driver", product: "Quik Airport · Sedan", estimate_low: a, estimate_high: b, in_app_booking: true, note: "Fixed price, scheduled to your flight. Driver waits 45 min after landing." },
            { provider: "uber", product: "UberX", estimate_low: c, estimate_high: d, in_app_booking: false, deeplink: "https://m.uber.com/ul/", note: "Opens Uber with pickup and drop-off filled in. Paid in Uber." },
            { provider: "bolt", product: "Bolt", estimate_low: e, estimate_high: f, in_app_booking: false, deeplink: "https://bolt.eu/en/rides/", note: "Opens Bolt; confirm the destination there. Paid in Bolt." }];
        }
        if (path === "/api/bookings" && method === "POST") {
          const o = this._offers[body.flight_offer_id], hotel = body.hotel_offer_id ? { name: "Palm Court " + ap(o.slices[0].destination).city, area: "City Centre", nights: 3, stars: 4, total_amount: 0 } : null;
          const ride = body.ride ? (await this.handle("/api/rides/quotes", "POST", body.ride)).find((q) => q.provider === body.ride.provider) : null;
          const fee = 3500 + o.total_amount * .015, hotelAmt = body.hotel_offer_id ? 294000 : 0, rideAmt = ride?.in_app_booking ? ride.estimate_high : 0;
          const id = "demo_bkg_" + Date.now(), ref = "QK" + Math.random().toString(36).slice(2, 6).toUpperCase();
          bookings[id] = { id, reference: ref, status: "pending_payment", bundle: "flight", contact_email: body.contact_email, flight_offer: o, hotel_offer: hotel, passengers: body.passengers, currency: "NGN", fare_amount: o.total_amount, hotel_amount: hotelAmt, ride_amount: rideAmt, service_fee: fee, total_amount: o.total_amount + hotelAmt + rideAmt + fee, airline_booking_reference: null, ride: body.ride, events: [{ at: new Date().toISOString(), kind: "created", text: "Trip created — awaiting payment" }] };
          return { booking: bookings[id], token: "demo" };
        }
        const m = path.match(/^\/api\/bookings\/([^/]+)(\/pay)?$/);
        if (m && m[2]) {
          const b = bookings[m[1]], now = () => new Date().toISOString(), dep = b.flight_offer.slices[0].segments[0].departing_at;
          b.status = "ticketed"; b.airline_booking_reference = Math.random().toString(36).slice(2, 8).toUpperCase();
          b.events.push({ at: now(), kind: "paid", text: "Payment received" }, { at: now(), kind: "ticketed", text: `Ticket confirmed by ${b.flight_offer.owner.name} · PNR ${b.airline_booking_reference}` });
          if (b.ride) {
            const pt = new Date(Date.parse(dep) - 3.75 * 3600e3).toISOString();
            b.ride = b.ride.provider === "quik_driver" ? { ...b.ride, pickup_time: pt, driver: { name: "Emeka Okafor", phone: "+2348030000101", car: "Toyota Corolla 2019 · Silver", plate: "ABJ-342-KD", rating: 4.9 } } : { ...b.ride, pickup_time: pt, deeplink: b.ride.provider === "uber" ? "https://m.uber.com/ul/" : "https://bolt.eu/en/rides/" };
            if (b.ride.driver) b.events.push({ at: now(), kind: "ride_assigned", text: `Driver Emeka Okafor (+2348030000101) will pick you up at ${hm(pt)}, ${day(pt)}` });
          }
          b.events.push({ at: now(), kind: "email", text: `Ticket and trip document emailed to ${b.contact_email}` });
          return { checkout_url: "#" };
        }
        if (m) return bookings[m[1]] || Promise.reject(new Error("Not found"));
        if (path === "/api/price-watches") return { starting_price: Math.min(...Object.values(this._offers).map((o) => o.total_amount)) };
        if (path === "/api/bookings/lookup") { const b = Object.values(bookings).find((x) => x.reference === body.reference.toUpperCase()); if (!b) return window.QuikMore.demo(path, method, body, params); return { kind: "flight", booking: b, token: "demo" }; }
        if (window.QuikMore) return window.QuikMore.demo(path, method, body, params);
        throw new Error("Not available in demo");
      },
    };
  })();

  /* ------------------------------------------------------------ boot */
  window.Quik = { $, h, money, hm, day, dur, isoDate, addDays, api, S, stage, toast, openSheet, legHTML, Demo, today };
  detect().then(() => {
    const q = new URLSearchParams(location.search);
    if (q.get("trip") && q.get("token") && !S.demo) openTrip(q.get("trip"), q.get("token"));
    if (q.get("res") && q.get("token") && !S.demo) window.QuikMore?.openReservation(q.get("res"), q.get("token"));
    window.QuikMore?.ready();
  });
})();
