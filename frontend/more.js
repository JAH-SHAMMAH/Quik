/* Quik: trains and restaurants. Plugs into app.js through window.Quik. */
(() => {
  "use strict";
  const Q = window.Quik;
  const { $, h, money, isoDate, addDays, api, S, stage, toast } = Q;
  const TZ = "Africa/Lagos";
  const tm = (iso) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: TZ });
  const dt = (iso) => new Date(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: TZ });
  const longDay = (isoD) => new Date(isoD + "T12:00:00Z").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
  const dur = (m) => `${Math.floor(m / 60)}h${m % 60 ? " " + String(m % 60).padStart(2, "0") + "m" : ""}`;
  const todayIso = isoDate(new Date());

  const T = { stations: [], search: null, results: null, offer: null, cls: "standard", map: null, coach: null, seats: [] };
  const E = { search: null, results: null, venue: null, slot: null, cart: {}, payNow: false };
  const stName = (code) => T.stations.find((s) => s.code === code);
  /* "Kubwa Station" -> "Kubwa"; "Babatunde Raji Fashola Station, Agege" -> "Agege" */
  const place = (code) => { const s = stName(code); if (!s) return code; return s.name.includes(",") ? s.name.split(",").pop().trim() : s.name.replace(/ Station$/, ""); };

  /* ------------------------------------------------------------ mode tabs */
  const MODES = {
    fly: { form: "#planForm", title: "Where to?", lede: "Local and international flights, with a hotel and a driver to the airport if you want them.",
      hint: "“Fly me to Toronto next Friday with a driver”",
      empty: ["Your options will land here", "Quik checks every airline we're connected to, then suggests one pick and tells you why. You always decide."] },
    train: { form: "#trainForm", title: "Which train?", lede: "Book seats on Abuja–Kaduna, Lagos–Ibadan, Warri–Itakpe and Port Harcourt–Aba.",
      hint: "“Train from Abuja to Kaduna on Saturday, two seats”",
      empty: ["Pick your train, then your seat", "Choose a class, tap the seats you want on the coach map, and your tickets arrive by email with a QR for the gate."] },
    eat: { form: "#eatForm", title: "What are you craving?", lede: "Tell Quik what you want to eat. It finds the best place that serves it, books the table and can have your food ready.",
      hint: "“I'm hungry, I want pepper soup in Wuse for 4 at 8pm”",
      empty: ["Hungry? Start with the food", "Say a dish or a mood. Quik matches it against real menus, checks for free tables, and suggests one place with reasons."] },
  };
  let mode = "fly";
  function setMode(m, { keepStage = false } = {}) {
    mode = m;
    document.querySelectorAll(".modes [role=tab]").forEach((b) => {
      const on = b.dataset.mode === m; b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1;
    });
    Object.entries(MODES).forEach(([k, v]) => ($(v.form).hidden = k !== m));
    $("#planTitle").textContent = MODES[m].title; $("#planLede").textContent = MODES[m].lede; $("#voiceHint").textContent = MODES[m].hint;
    if (!keepStage) stage.innerHTML = `<div class="empty"><h2>${MODES[m].empty[0]}</h2><p>${MODES[m].empty[1]}</p></div>`;
  }
  const tabs = $(".modes");
  tabs.addEventListener("click", (e) => { const b = e.target.closest("[data-mode]"); if (b && b.dataset.mode !== mode) setMode(b.dataset.mode); });
  tabs.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const order = ["fly", "train", "eat"]; const i = (order.indexOf(mode) + (e.key === "ArrowRight" ? 1 : 2)) % 3;
    setMode(order[i]); tabs.querySelector(`[data-mode=${order[i]}]`).focus();
  });

  /* ------------------------------------------------------------ trains: form */
  function fillTo() {
    const from = stName($("#tFrom").value); if (!from) return;
    const keep = $("#tTo").value;
    const opts = T.stations.filter((s) => s.line === from.line && s.code !== from.code);
    $("#tTo").innerHTML = opts.map((s) => `<option value="${s.code}">${h(s.city)} · ${h(s.name.split(",")[0])}</option>`).join("");
    if (opts.some((s) => s.code === keep)) $("#tTo").value = keep; else $("#tTo").value = opts[opts.length - 1].code;
    $("#tLine").textContent = `${from.line} line`;
  }
  async function initTrains() {
    T.stations = await api("/api/stations");
    const lines = [...new Set(T.stations.map((s) => s.line))];
    $("#tFrom").innerHTML = lines.map((l) => `<optgroup label="${h(l)}">${T.stations.filter((s) => s.line === l)
      .map((s) => `<option value="${s.code}">${h(s.city)} · ${h(s.name.split(",")[0])}</option>`).join("")}</optgroup>`).join("");
    $("#tFrom").value = "IDU"; fillTo(); $("#tTo").value = "RGS";
    $("#tDate").min = todayIso; $("#tDate").value = addDays(todayIso, 1);
  }
  $("#tFrom").addEventListener("change", fillTo);
  $("#tNear").onclick = () => {
    if (!navigator.geolocation) return toast("Location isn't available on this device");
    navigator.geolocation.getCurrentPosition(async (p) => {
      const near = await api("/api/stations", { params: { lat: p.coords.latitude, lng: p.coords.longitude } });
      $("#tFrom").value = near[0].code; fillTo();
      $("#tNear").textContent = `Nearest: ${near[0].name.split(",")[0]} (${Math.round(near[0].distance_km)} km)`;
    }, () => ($("#tNear").textContent = "Location blocked — pick your station instead"), { timeout: 8000 });
  };
  $("#trainForm").addEventListener("submit", (e) => {
    e.preventDefault();
    runTrainSearch({ origin: $("#tFrom").value, destination: $("#tTo").value, date: $("#tDate").value, passengers: +$("#tPax").value });
  });

  async function runTrainSearch(search) {
    T.search = search;
    stage.innerHTML = `<div class="head"><h2>Checking trains…</h2></div>` + '<div class="skeleton"></div>'.repeat(2);
    try { T.results = await api("/api/trains/search", { method: "POST", body: search }); renderTrains(); show(); }
    catch (err) { stage.innerHTML = `<div class="empty"><h2>No trains</h2><p>${h(err.message)}</p></div>`; }
  }

  /* ------------------------------------------------------------ trains: results */
  const CLS = { standard: "Standard", business: "Business", first: "First" };
  function trainCard(o, pick) {
    const from = stName(o.origin), to = stName(o.destination);
    const calls = o.calls_at.map(place);
    return `<article class="pass ${pick ? "pick" : ""}">
      <div class="main">
        <div class="airline"><span class="tail rail" aria-hidden="true">NRC</span>${h(o.train_number)} · ${h(o.line)}
          ${o.tags.includes("fastest") ? '<span class="tags" style="margin-left:auto"><span class="tag">Fastest</span></span>' : ""}</div>
        <div class="legs"><div class="leg">
          <div><div class="t">${tm(o.departing_at)}</div><div class="c">${h(place(o.origin))} · ${dt(o.departing_at)}</div></div>
          <div class="path"><span>${dur(o.duration_minutes)} · ${calls.length ? `${calls.length} stop${calls.length > 1 ? "s" : ""}` : "Direct"}</span></div>
          <div class="end"><div class="t">${tm(o.arriving_at)}</div><div class="c">${h(place(o.destination))}</div></div>
        </div></div>
        ${calls.length ? `<div class="facts"><span>Calls at ${h(calls.join(", "))}</span></div>` : ""}
        ${pick ? `<div class="why"><div class="pickline">Why it's our pick</div><ul class="reasons">${pick.reasons.map((r) => `<li>${h(r)}</li>`).join("")}</ul></div>` : ""}
      </div>
      <div class="stub">
        ${pick ? '<div class="pickline">Quik Pick</div>' : ""}
        <div class="fares" role="group" aria-label="Choose a class for ${h(o.train_number)}">
          ${o.fares.map((f) => `<button type="button" class="fare" data-train="${o.id}" data-cls="${f.travel_class}" ${f.seats_left < T.search.passengers ? "disabled" : ""}>
            <span>${CLS[f.travel_class]}</span><b>${money(f.amount)}</b><small>${f.seats_left < T.search.passengers ? "Full" : `${f.seats_left} left`}</small></button>`).join("")}
        </div>
      </div>
    </article>`;
  }

  function renderTrains() {
    const r = T.results, s = T.search, from = stName(s.origin), to = stName(s.destination);
    if (!r.offers.length) {
      stage.innerHTML = `<div class="empty"><h2>No more trains that day</h2><p>Sales close 30 minutes before departure. Try the next day.</p></div>`; return;
    }
    const pick = r.offers.find((o) => o.id === r.pick.offer_id);
    stage.innerHTML = `<div class="head"><div><h2>${h(from.city)} to ${h(to.city)}</h2>
      <p>${longDay(s.date)} · ${s.passengers} passenger${s.passengers > 1 ? "s" : ""} · prices per person</p></div></div>
      ${trainCard(pick, r.pick)}${r.offers.filter((o) => o !== pick).map((o) => trainCard(o)).join("")}`;
  }

  /* ------------------------------------------------------------ trains: seats */
  async function openSeats(offerId, cls) {
    T.offer = T.results.offers.find((o) => o.id === offerId); T.cls = cls; T.seats = [];
    T.map = await api(`/api/trains/${offerId}/seats`);
    T.coach = T.map.coaches.find((c) => c.travel_class === cls).coach;
    renderSeats(); show();
  }
  function seatIds(c) { const L = window.QUIK_DEMO.letters[c.layout]; const out = []; for (let r = 1; r <= c.rows; r++) for (const l of L) out.push(`${c.coach}-${String(r).padStart(2, "0")}${l}`); return out; }

  function renderSeats() {
    const o = T.offer, need = T.search.passengers, coaches = T.map.coaches.filter((c) => c.travel_class === T.cls);
    const c = coaches.find((x) => x.coach === T.coach) || coaches[0];
    const L = window.QUIK_DEMO.letters[c.layout], left = +c.layout.split("+")[0];
    const taken = new Set(c.taken);
    let grid = "";
    for (let r = 1; r <= c.rows; r++) {
      grid += `<div class="srow"><span class="rnum">${r}</span>`;
      L.split("").forEach((l, i) => {
        if (i === left) grid += '<span class="aisle" aria-hidden="true"></span>';
        const id = `${c.coach}-${String(r).padStart(2, "0")}${l}`, isT = taken.has(id), on = T.seats.includes(id);
        grid += `<button type="button" class="seat${on ? " on" : ""}" data-seat="${id}" ${isT ? "disabled" : ""} aria-pressed="${on}"
          aria-label="Row ${r} seat ${l}${isT ? ", taken" : on ? ", selected" : ""}${i === 0 || i === L.length - 1 ? ", window" : ""}">${l}</button>`;
      });
      grid += "</div>";
    }
    const freeHere = seatIds(c).filter((s) => !taken.has(s)).length;
    stage.innerHTML = `<button class="back" data-tgo="trains">← Back to trains</button>
      <section class="panel"><h3>Choose ${need > 1 ? `${need} seats` : "your seat"}</h3>
        <p>${h(o.train_number)} · ${tm(o.departing_at)} · ${CLS[T.cls]} · ${money(o.fares.find((f) => f.travel_class === T.cls).amount)} per seat</p>
        ${coaches.length > 1 ? `<div class="sort" role="group" aria-label="Coach">${coaches.map((x) => `<button type="button" data-coach="${x.coach}" aria-pressed="${x.coach === c.coach}">Coach ${x.coach}</button>`).join("")}</div>` : ""}
        <div class="legend"><span><i class="seat demo"></i>Free</span><span><i class="seat demo on"></i>Yours</span><span><i class="seat demo gone"></i>Taken</span><span>${freeHere} free in coach ${c.coach}</span></div>
        <div class="coach-wrap"><div class="coach-map" aria-label="Coach ${c.coach} seat map">
          <div class="cab">Front of train</div>${grid}</div></div>
        <p class="note">${T.seats.length ? `Selected: ${T.seats.join(", ")}` : "Window seats are on the outer edges."}</p>
        <button class="primary" data-tgo="pax" ${T.seats.length === need ? "" : "disabled"}>${T.seats.length === need ? "Continue" : `Pick ${need - T.seats.length} more`}</button>
      </section>`;
  }

  function renderTrainPax() {
    const n = T.search.passengers;
    stage.innerHTML = `<button class="back" data-tgo="seats">← Back to seats</button>
      <form id="tPaxForm" class="panel"><h3>Who's travelling?</h3><p>Names as on a valid ID. You'll need the ID at the gate.</p>
        <div class="grid2">${T.seats.map((s, i) => `<div class="field"><label for="tp${i}">Passenger ${i + 1} · seat ${s}</label><input id="tp${i}" required autocomplete="${i ? "off" : "name"}"></div>`).join("")}</div>
        <h3 style="margin-top:18px">Where should we send the tickets?</h3>
        <div class="grid2"><div class="field"><label for="tEmail">Email</label><input id="tEmail" type="email" required autocomplete="email"></div>
          <div class="field"><label for="tPhone">Phone</label><input id="tPhone" type="tel" required placeholder="+234…" autocomplete="tel"></div></div>
        <button class="primary">Review and pay</button><p class="err" id="tErr" hidden></p></form>`;
    $("#tPaxForm").addEventListener("submit", async (e) => {
      e.preventDefault(); e.submitter.disabled = true;
      try {
        const res = await api("/api/trains/bookings", { method: "POST", body: {
          offer_id: T.offer.id, travel_class: T.cls, seats: T.seats,
          passengers: T.seats.map((_, i) => ({ full_name: $("#tp" + i).value.trim() })),
          contact_email: $("#tEmail").value.trim(), contact_phone: $("#tPhone").value.trim() } });
        review(res.reservation, res.token);
      } catch (err) {
        $("#tErr").textContent = err.status === 409 ? `${err.message} Go back to pick another seat.` : err.message; $("#tErr").hidden = false; e.submitter.disabled = false;
      }
    });
  }

  /* ------------------------------------------------------------ shared review / pay */
  function review(r, token) {
    const d = r.details;
    const rows = r.kind === "train"
      ? `<div><span>${d.passengers.length} × ${CLS[d.travel_class]} seat</span><span>${money(r.amount)}</span></div><div><span>Booking fee</span><span>${money(r.service_fee)}</span></div>`
      : `${d.deposit ? `<div><span>Deposit (taken off your bill)</span><span>${money(d.deposit)}</span></div>` : ""}
         ${d.preorder.length ? `<div><span>Food ${d.preorder_paid ? "paid now" : "(pay at the restaurant)"}</span><span>${money(d.preorder_total)}</span></div>` : ""}`;
    stage.innerHTML = `<section class="panel"><h3>${r.kind === "train" ? "Review your tickets" : "Review your table"}</h3>
      <p>${r.kind === "train" ? `${h(d.offer.train_number)} · ${tm(d.offer.departing_at)}, ${dt(d.offer.departing_at)} · seats ${h(d.seats.join(", "))}` : `${h(d.restaurant.name)} · ${longDay(d.date)} at ${d.time} · ${d.party_size} guests`}</p>
      <div class="total">${rows}<div class="sum"><span>Pay now</span><span>${money(r.total_amount)}</span></div></div>
      <button class="primary" id="rPay">Pay ${money(r.total_amount)}</button>
      <p class="note">${r.kind === "train" ? "Seats are held for 15 minutes while you pay." : "Card, bank transfer or USSD."}</p></section>`;
    $("#rPay").onclick = async () => {
      $("#rPay").disabled = true;
      try {
        const p = await api(`/api/reservations/${r.id}/pay`, { method: "POST", params: { token } });
        if (S.demo) return openReservation(r.id, token);
        location.href = p.checkout_url;
      } catch (err) { toast(err.message); $("#rPay").disabled = false; }
    };
  }

  /* ------------------------------------------------------------ eat: form */
  function initEat() {
    const opts = []; for (let m = 7 * 60; m <= 22 * 60 + 30; m += 30) opts.push(`${String(m / 60 | 0).padStart(2, "0")}:${m % 60 ? "30" : "00"}`);
    $("#eTime").innerHTML = opts.map((o) => `<option>${o}</option>`).join("");
    const now = new Date(); const next = (now.getHours() + 1) * 60 + (now.getMinutes() >= 30 ? 30 : 0);
    const nextStr = `${String(next / 60 | 0).padStart(2, "0")}:${next % 60 ? "30" : "00"}`;
    $("#eTime").value = opts.includes(nextStr) ? nextStr : "19:30";
    $("#eDate").min = todayIso; $("#eDate").value = opts.includes(nextStr) ? todayIso : addDays(todayIso, 1);
    const from = $("#from").value.trim().toUpperCase();
    if (from === "LOS") $("#eCity").value = "Lagos"; else if (from === "PHC") $("#eCity").value = "Port Harcourt";
  }
  $("#eChips").addEventListener("click", (e) => { if (e.target.tagName === "BUTTON") { $("#eCraving").value = e.target.textContent; $("#eatForm").requestSubmit(); } });
  $("#eatForm").addEventListener("submit", (e) => {
    e.preventDefault();
    runEatSearch({ craving: $("#eCraving").value.trim() || null, city: $("#eCity").value, date: $("#eDate").value,
      time: $("#eTime").value, party_size: +$("#eParty").value });
  });

  async function runEatSearch(search) {
    E.search = search;
    stage.innerHTML = `<div class="head"><h2>Finding tables…</h2></div>` + '<div class="skeleton"></div>'.repeat(2);
    try { E.results = await api("/api/restaurants/search", { method: "POST", body: search }); renderVenues(); show(); }
    catch (err) { stage.innerHTML = `<div class="empty"><h2>No tables</h2><p>${h(err.message)}</p></div>`; }
  }

  /* ------------------------------------------------------------ eat: results */
  const naira = (n) => "₦".repeat(n) + `<span class="dim">${"₦".repeat(3 - n)}</span>`;
  function venueCard(v, pick) {
    const matched = v.menu.filter((m) => v.matches.includes(m.id));
    return `<article class="pass venue ${pick ? "pick" : ""}">
      <div class="main">
        <div class="airline"><span class="tail food" aria-hidden="true">${h(v.name[0])}</span><span>${h(v.name)}</span>
          <span class="tags" style="margin-left:auto"><span class="tag">${v.rating}★</span></span></div>
        <div class="facts" style="margin-top:6px"><span>${h(v.area)}</span><span>${h(v.cuisines.join(", "))}</span><span aria-label="Price level ${v.price_level} of 3">${naira(v.price_level)}</span>
          ${v.distance_km != null ? `<span>${v.distance_km} km</span>` : ""}<span>Open ${v.opens}–${v.closes}</span></div>
        ${matched.length ? `<div class="dishes">${matched.slice(0, 3).map((m) => `<div><b>${h(m.name)}</b><span>${money(m.price)}</span></div>`).join("")}</div>` : ""}
        ${pick ? `<div class="why"><div class="pickline">Why it's our pick</div><ul class="reasons">${pick.reasons.map((r) => `<li>${h(r)}</li>`).join("")}</ul></div>` : ""}
      </div>
      <div class="stub">
        ${pick ? '<div class="pickline">Quik Pick</div>' : ""}
        <div><div class="slotlbl">${v.slots.length ? "Free tables" : "Fully booked near that time"}</div>
          <div class="slots">${v.slots.slice(0, 6).map((s) => `<button type="button" data-venue="${v.id}" data-slot="${s}" class="${s === E.search.time ? "on" : ""}">${s}</button>`).join("")}</div></div>
        <small class="note">${v.deposit_per_guest ? `${money(v.deposit_per_guest)} deposit per guest, off your bill` : "No deposit"}</small>
        ${v.slots.length ? `<button class="${pick ? "primary" : "secondary"}" style="margin-top:0" data-venue="${v.id}" data-slot="${v.slots.includes(E.search.time) ? E.search.time : v.slots[0]}">Book a table</button>` : ""}
      </div>
    </article>`;
  }
  function renderVenues() {
    const r = E.results, s = E.search;
    if (!r.restaurants.length) {
      stage.innerHTML = `<div class="empty"><h2>Nothing matched “${h(s.craving)}” in ${h(s.city)}</h2><p>Try a broader word like “Nigerian”, “grills” or “spicy”, or clear the craving to see everything with a free table.</p></div>`; return;
    }
    const [best, ...rest] = r.restaurants;
    stage.innerHTML = `<div class="head"><div><h2>${s.craving ? h(cap(s.craving)) + " in " + h(s.city) : "Tables in " + h(s.city)}</h2>
      <p>${longDay(s.date)} around ${s.time} · ${s.party_size} guest${s.party_size > 1 ? "s" : ""} · ${r.restaurants.length} place${r.restaurants.length > 1 ? "s" : ""}</p></div></div>
      ${venueCard(best, r.pick)}${rest.map((v) => venueCard(v)).join("")}`;
  }
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  const show = () => { if (innerWidth < 960) stage.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }); };

  /* ------------------------------------------------------------ eat: book */
  async function openVenue(id, slot) {
    E.venue = E.results?.restaurants.find((v) => v.id === id)
      || await api(`/api/restaurants/${id}`, { params: { date: E.search.date, time: E.search.time, party_size: E.search.party_size } });
    E.slot = slot || E.venue.slots[0]; E.cart = {}; E.payNow = false;
    renderVenue(); show();
  }
  function renderVenue() {
    const v = E.venue, s = E.search;
    const order = [...v.menu].sort((a, b) => (v.matches.includes(b.id) - v.matches.includes(a.id)));
    const food = Object.entries(E.cart).reduce((t, [id, q]) => t + q * v.menu.find((m) => m.id === id).price, 0);
    const deposit = v.deposit_per_guest * s.party_size, due = deposit + (E.payNow ? food : 0);
    stage.innerHTML = `<button class="back" data-ego="venues">← Back to restaurants</button>
      <form id="tableForm">
      <section class="panel"><h3>${h(v.name)}</h3><p>${h(v.area)}, ${h(v.city)} · ${longDay(s.date)} · ${s.party_size} guest${s.party_size > 1 ? "s" : ""}</p>
        <div class="slotlbl">Time</div>
        <div class="slots" role="radiogroup" aria-label="Table time">${v.slots.map((t) => `<button type="button" role="radio" aria-checked="${t === E.slot}" class="${t === E.slot ? "on" : ""}" data-pickslot="${t}">${t}</button>`).join("")}</div>
      </section>
      <section class="panel"><h3>Want it ready when you arrive?</h3><p>Optional. Pre-order and the kitchen starts as you sit down.</p>
        <ul class="menu">${order.map((m) => `<li class="${v.matches.includes(m.id) ? "hit" : ""}">
          <div class="grow"><b>${h(m.name)}</b>${v.matches.includes(m.id) ? ' <span class="tag">Matches your craving</span>' : ""}<div class="sub">${h(m.description)}</div></div>
          <span class="amt">${money(m.price)}</span>
          <span class="qty"><button type="button" data-dec="${m.id}" aria-label="Remove one ${h(m.name)}" ${E.cart[m.id] ? "" : "disabled"}>−</button>
            <output aria-live="polite">${E.cart[m.id] || 0}</output>
            <button type="button" data-inc="${m.id}" aria-label="Add one ${h(m.name)}">+</button></span></li>`).join("")}</ul>
        ${food ? `<label class="choice" style="margin-top:10px"><input type="checkbox" id="payNow" ${E.payNow ? "checked" : ""}><span class="grow">Pay for the food now<div class="sub">Otherwise you pay ${money(food)} at the restaurant.</div></span></label>` : ""}
      </section>
      <section class="panel"><h3>Booking name</h3>
        <div class="grid2"><div class="field"><label for="rName">Name</label><input id="rName" required autocomplete="name"></div>
          <div class="field"><label for="rPhone">Phone</label><input id="rPhone" type="tel" required placeholder="+234…" autocomplete="tel"></div>
          <div class="field"><label for="rEmail">Email</label><input id="rEmail" type="email" required autocomplete="email"></div>
          <div class="field"><label for="rNotes">Notes for the restaurant</label><input id="rNotes" placeholder="Birthday, allergies, outdoor seat…"></div></div>
        <div class="total" style="margin-top:14px">${deposit ? `<div><span>Deposit (off your bill)</span><span>${money(deposit)}</span></div>` : ""}
          ${food ? `<div><span>Food${E.payNow ? "" : " (at the restaurant)"}</span><span>${money(food)}</span></div>` : ""}
          <div class="sum"><span>Pay now</span><span>${money(due)}</span></div></div>
        <button class="primary">${due ? `Book and pay ${money(due)}` : `Book table for ${E.slot}`}</button><p class="err" id="rErr" hidden></p>
      </section></form>`;
    stage._draft = stage._draft || {};
    ["rName", "rPhone", "rEmail", "rNotes"].forEach((id) => { const el = $("#" + id); el.value = stage._draft[id] || ""; el.addEventListener("input", () => (stage._draft[id] = el.value)); });
    $("#tableForm").addEventListener("submit", bookTable);
  }
  async function bookTable(e) {
    e.preventDefault(); const btn = e.submitter; btn.disabled = true;
    try {
      const res = await api("/api/restaurants/bookings", { method: "POST", body: {
        restaurant_id: E.venue.id, date: E.search.date, time: E.slot, party_size: E.search.party_size,
        preorder: Object.entries(E.cart).map(([item_id, qty]) => ({ item_id, qty })), pay_preorder_now: E.payNow,
        contact_name: $("#rName").value.trim(), contact_email: $("#rEmail").value.trim(), contact_phone: $("#rPhone").value.trim(),
        notes: $("#rNotes").value.trim() || null } });
      if (res.reservation.status === "ticketed") return openReservation(res.reservation.id, res.token);
      review(res.reservation, res.token);
    } catch (err) {
      if (err.status === 409 && err.detail?.free) { E.venue.slots = err.detail.free; E.slot = err.detail.free[0]; renderVenue(); toast(err.detail.message + ". Pick another time."); return; }
      $("#rErr").textContent = err.message; $("#rErr").hidden = false; btn.disabled = false;
    }
  }

  /* ------------------------------------------------------------ reservation view */
  async function openReservation(id, token) {
    let r;
    try { r = await api(`/api/reservations/${id}`, { params: { token } }); } catch { toast("We couldn't open that booking"); return; }
    const d = r.details;
    setMode(r.kind === "train" ? "train" : "eat", { keepStage: true });
    const st = { ticketed: [r.kind === "train" ? "Tickets issued" : "Table confirmed", ""], pending_payment: ["Awaiting payment", "wait"], cancelled: ["Expired", "bad"] }[r.status] || [r.status, "wait"];
    let body;
    if (r.kind === "train") {
      const o = d.offer;
      body = `<div class="airline"><span class="tail rail" aria-hidden="true">NRC</span>${h(o.train_number)} · ${h(o.line)} · ${CLS[d.travel_class]}</div>
        <div class="legs"><div class="leg"><div><div class="t">${tm(o.departing_at)}</div><div class="c">${h(place(o.origin))} · ${dt(o.departing_at)}</div></div>
          <div class="path"><span>${dur(o.duration_minutes)}</span></div>
          <div class="end"><div class="t">${tm(o.arriving_at)}</div><div class="c">${h(place(o.destination))}</div></div></div></div>
        <table class="tix"><thead><tr><th scope="col">Passenger</th><th scope="col">Seat</th><th scope="col">Ticket</th></tr></thead><tbody>
          ${d.passengers.map((p, i) => `<tr><td>${h(p.full_name)}</td><td>${h(d.seats[i])}</td><td>${h((d.ticket_numbers || [])[i] || "pending")}</td></tr>`).join("")}</tbody></table>
        <p class="note">Arrive 30 minutes early with a valid ID. Show the QR in your email at the gate.</p>`;
    } else {
      const v = d.restaurant;
      body = `<div class="airline"><span class="tail food" aria-hidden="true">${h(v.name[0])}</span>${h(v.name)}</div>
        <p style="margin:10px 0 0;font:600 28px/1.1 var(--display)">${longDay(d.date)}, ${h(d.time)}</p>
        <p class="note" style="margin:4px 0 0">${d.party_size} guest${d.party_size > 1 ? "s" : ""} · ${h(v.area)}, ${h(v.city)}${d.notes ? ` · “${h(d.notes)}”` : ""}</p>
        ${d.preorder.length ? `<ul class="menu" style="margin-top:12px">${d.preorder.map((l) => `<li><div class="grow"><b>${l.qty}× ${h(l.name)}</b></div><span class="amt">${money(l.subtotal)}</span></li>`).join("")}</ul>
          <p class="note">${d.preorder_paid ? "Food paid. The kitchen starts when you're seated." : "Pay for the food at the restaurant."}</p>` : ""}
        ${d.deposit ? `<p class="note">Deposit paid ${money(d.deposit)}, taken off your bill.</p>` : ""}
        <div class="actions"><a class="secondary" href="https://www.google.com/maps/search/?api=1&query=${v.lat},${v.lng}" target="_blank" rel="noopener">Directions</a></div>`;
    }
    stage.innerHTML = `<div class="ticket-head"><div><small>Quik reference</small><div class="ref">${h(r.reference)}</div>
        <small>${r.kind === "train" ? "Train ticket" : "Table reservation"} · ${h(r.contact_name)}</small></div><span class="status ${st[1]}">${st[0]}</span></div>
      <div class="ticket-body">${body}
        <div class="actions">${r.status === "ticketed" && !S.demo ? `<a class="secondary" href="/api/reservations/${r.id}/document?token=${encodeURIComponent(token)}" target="_blank" rel="noopener">Download ${r.kind === "train" ? "tickets" : "confirmation"}</a>` : ""}
          <button class="secondary" type="button" data-agent>Talk to an agent</button></div></div>
      <section class="panel"><h3>What's happened</h3>
        <ol class="timeline">${[...r.events].reverse().map((ev) => `<li class="${h(ev.kind)}"><time>${new Date(ev.at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}</time>${h(ev.text)}</li>`).join("")}</ol></section>`;
    show();
    if (!S.demo) history.replaceState(null, "", `?res=${encodeURIComponent(id)}&token=${encodeURIComponent(token)}`);
  }

  /* ------------------------------------------------------------ stage events */
  stage.addEventListener("click", (e) => {
    const fare = e.target.closest("[data-train]"); if (fare) return openSeats(fare.dataset.train, fare.dataset.cls);
    const seat = e.target.closest("[data-seat]");
    if (seat) {
      const id = seat.dataset.seat, i = T.seats.indexOf(id);
      if (i >= 0) T.seats.splice(i, 1); else if (T.seats.length < T.search.passengers) T.seats.push(id);
      else { T.seats.shift(); T.seats.push(id); }
      renderSeats(); stage.querySelector(`[data-seat="${id}"]`)?.focus(); return;
    }
    const coach = e.target.closest("[data-coach]"); if (coach) { T.coach = coach.dataset.coach; return renderSeats(); }
    const tgo = e.target.closest("[data-tgo]")?.dataset.tgo;
    if (tgo === "trains") return renderTrains(); if (tgo === "seats") return renderSeats(); if (tgo === "pax") return renderTrainPax();
    const v = e.target.closest("[data-venue]"); if (v) return openVenue(v.dataset.venue, v.dataset.slot);
    const ps = e.target.closest("[data-pickslot]"); if (ps) { E.slot = ps.dataset.pickslot; return renderVenue(); }
    const inc = e.target.closest("[data-inc]"), dec = e.target.closest("[data-dec]");
    if (inc || dec) { const id = (inc || dec).dataset.inc || (inc || dec).dataset.dec; E.cart[id] = Math.max(0, (E.cart[id] || 0) + (inc ? 1 : -1)); if (!E.cart[id]) delete E.cart[id]; renderVenue(); stage.querySelector(`[data-${inc ? "inc" : "dec"}="${id}"]`)?.focus(); return; }
    if (e.target.closest("[data-ego]")) return renderVenues();
  });
  stage.addEventListener("change", (e) => { if (e.target.id === "payNow") { E.payNow = e.target.checked; renderVenue(); } });

  /* ------------------------------------------------------------ assistant results */
  function onAssistant(r) {
    if (r.mode === "train") {
      if (mode !== "train") setMode("train", { keepStage: true });
      if (r.train_results) {
        T.results = r.train_results; T.search = r.train_results.search;
        $("#tFrom").value = T.search.origin; fillTo(); $("#tTo").value = T.search.destination; $("#tDate").value = T.search.date; $("#tPax").value = T.search.passengers;
        renderTrains();
      }
      if (r.intent === "confirm_train" && T.results) { $("#voiceSheet").removeAttribute("open"); openSeats(r.session.pick_train_id, r.session.t_class || "standard"); }
      return true;
    }
    if (r.mode === "food") {
      if (mode !== "eat") setMode("eat", { keepStage: true });
      if (r.restaurant_results) {
        E.results = r.restaurant_results; E.search = r.restaurant_results.search;
        $("#eCraving").value = E.search.craving || ""; $("#eCity").value = E.search.city; $("#eParty").value = String(E.search.party_size);
        renderVenues();
      }
      if (r.intent === "confirm_table" && E.results) { $("#voiceSheet").removeAttribute("open"); openVenue(r.session.pick_restaurant_id, r.session.f_time); }
      return true;
    }
    if (mode !== "fly" && r.results) setMode("fly", { keepStage: true });
    return false;
  }

  /* ------------------------------------------------------------ demo backend for trains & food */
  const D = window.QUIK_DEMO, store = {};
  const hash = (s) => [...s].reduce((a, c) => (Math.imul(a, 31) + c.charCodeAt(0)) | 0, 7) >>> 0;
  const rng = (seed) => () => { seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const allStations = () => Object.entries(D.lines).flatMap(([line, spec]) => spec.stations.map((s) => ({ ...s, line })));
  const km = (a, b) => { const R = 6371, r = Math.PI / 180, x = Math.sin((b.lat - a.lat) * r / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin((b.lng - a.lng) * r / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(x)); };
  const ref = () => "QK" + Math.random().toString(36).slice(2, 6).toUpperCase();
  const ev = (kind, text) => ({ at: new Date().toISOString(), kind, text });

  function demoTrains(s) {
    const st = allStations(), o = st.find((x) => x.code === s.origin), d = st.find((x) => x.code === s.destination);
    if (!o || !d || o.line !== d.line) return { search: s, offers: [], pick: null };
    const spec = D.lines[o.line], full = spec.stations.at(-1).mins, fwd = d.mins > o.mins, span = Math.abs(d.mins - o.mins);
    const calls = spec.stations.filter((x) => x.mins > Math.min(o.mins, d.mins) && x.mins < Math.max(o.mins, d.mins)).map((x) => x.code);
    if (!fwd) calls.reverse();
    const frac = Math.max(0.4, span / full);
    const offers = spec.departures.map((dep, i) => {
      const [hh, mm] = dep.split(":").map(Number);
      const start = Date.parse(`${s.date}T${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}:00+01:00`) + (fwd ? o.mins : full - o.mins) * 60e3;
      const end = start + (span + 3 * calls.length) * 60e3, R = rng(hash(o.line + s.date + dep + fwd));
      const fares = Object.entries(spec.fares).map(([cls, base]) => {
        const cap = D.consist.filter((c) => c.travel_class === cls).reduce((a, c) => a + D.letters[c.layout].length * c.rows, 0);
        return { travel_class: cls, amount: Math.round(base * frac / 100) * 100, seats_left: Math.max(0, Math.floor(cap * (0.05 + R() * 0.55))) };
      });
      return { id: `demo_trn_${spec.short}_${s.date}_${dep}_${s.origin}${s.destination}`, operator: "Nigerian Railway Corporation", line: o.line,
        train_number: `${spec.short}${String(2 * i + (fwd ? 1 : 2)).padStart(2, "0")}`, origin: s.origin, destination: s.destination,
        departing_at: new Date(start).toISOString(), arriving_at: new Date(end).toISOString(), duration_minutes: span + 3 * calls.length,
        calls_at: calls, fares, currency: "NGN", tags: [] };
    }).filter((x) => Date.parse(x.departing_at) > Date.now() + 30 * 60e3);
    if (!offers.length) return { search: s, offers, pick: null };
    const best = offers.find((x) => x.fares.some((f) => f.seats_left)) || offers[0];
    offers.reduce((a, b) => (b.duration_minutes < a.duration_minutes ? b : a)).tags.push("fastest");
    best.tags.push("quik_pick"); offers.forEach((x) => (store[x.id] = x));
    const std = best.fares[0];
    return { search: s, offers, pick: { offer_id: best.id, reasons: [`Next train with seats: leaves ${tm(best.departing_at)}, arrives ${tm(best.arriving_at)}`, `${std.seats_left} standard seats left`, ...(calls.length ? [`Calls at ${calls.length} stations on the way`] : [])] } };
  }
  function demoSeats(id) {
    const o = store[id], R = rng(hash(id)), sold = new Set(Object.values(store).filter((x) => x.kind === "train" && x.details.offer.id === id).flatMap((x) => x.details.seats));
    const left = Object.fromEntries(o.fares.map((f) => [f.travel_class, f.seats_left]));
    return { offer_id: id, coaches: D.consist.map((c) => {
      const ids = seatIds(c), per = Math.floor(left[c.travel_class] / D.consist.filter((x) => x.travel_class === c.travel_class).length);
      const free = new Set([...ids].sort(() => R() - 0.5).slice(0, per));
      return { ...c, taken: ids.filter((s) => !free.has(s) || sold.has(s)) };
    }) };
  }
  function demoTerms(text) {
    if (!text) return [];
    const stop = new Set("i want a an some me for the to and with near in at am im i'm craving like would please book table get find good best place restaurant really".split(" "));
    let t = []; for (const w of text.toLowerCase().match(/[a-z']+/g) || []) { if (stop.has(w)) continue; t.push(...(D.synonyms[w] || [w])); }
    const phrases = [...new Set(D.restaurants.flatMap((v) => v.menu.flatMap((m) => m.tags.filter((x) => x.includes(" ")))))];
    for (const p of phrases) if (text.toLowerCase().includes(p)) { t = t.filter((x) => !p.split(" ").includes(x)); t.push(p); }
    const V = new Set(D.vocab); return [...new Set(t.filter((x) => V.has(x) || V.has(x.replace(/s$/, ""))))];
  }
  const mins = (s) => { const [a, b] = s.split(":").map(Number); return a * 60 + b; };
  function demoSlots(v, date, around, party) {
    let o = mins(v.opens), c = mins(v.closes); if (c <= o) c += 1440; const want = mins(around), out = [];
    for (let t = o; t <= c - 60; t += 30) {
      if (Math.abs(t - want) > 120 && Math.abs(t - want - 1440) > 120) continue;
      const busy = 0.35 + (t % 1440 >= 1140 && t % 1440 <= 1260 ? 0.3 : 0) + (party > 4 ? 0.1 : 0);
      if (rng(hash(v.id + date + party + t))() > busy) out.push(`${String((t / 60 | 0) % 24).padStart(2, "0")}:${t % 60 ? "30" : "00"}`);
    }
    return out;
  }
  function demoVenues(s) {
    const terms = demoTerms(s.craving);
    let vs = D.restaurants.filter((v) => v.city.toLowerCase() === (s.city || "Abuja").toLowerCase()).map((v) => {
      const matches = terms.length ? v.menu.filter((m) => {
        const words = new Set([...(m.name.toLowerCase().match(/[a-z]+/g) || []), ...m.tags]);
        return terms.some((t) => words.has(t) || words.has(t.replace(/s$/, "")) || (t.includes(" ") && m.name.toLowerCase().includes(t)));
      }).map((m) => m.id) : [];
      return { ...v, matches, slots: demoSlots(v, s.date, s.time, s.party_size), tags: [] };
    });
    if (terms.length) vs = vs.filter((v) => v.matches.length);
    const score = (v) => v.rating / 12.5 + (v.matches.length ? 0.25 : 0) + (v.slots.includes(s.time) ? 0.15 : v.slots.length ? 0.08 : -0.5) + (v.deposit_per_guest ? 0 : 0.03);
    vs.sort((a, b) => score(b) - score(a));
    if (!vs.length) return { search: s, restaurants: [], pick: null };
    const b = vs[0], reasons = [];
    if (b.matches.length) reasons.push(`Serves ${b.menu.filter((m) => b.matches.includes(m.id)).slice(0, 2).map((m) => m.name).join(" and ")}`);
    reasons.push(`Rated ${b.rating}/5 by diners`);
    reasons.push(b.slots.includes(s.time) ? `Table free at ${s.time} for ${s.party_size}` : b.slots.length ? `Nearest free table: ${b.slots[0]}` : "Fully booked near that time");
    if (!b.deposit_per_guest) reasons.push("No deposit needed");
    return { search: s, restaurants: vs, pick: { offer_id: b.id, reasons: reasons.slice(0, 4) } };
  }
  function confirmDemo(r) {
    if (r.total_amount) r.events.push(ev("paid", "Payment received"));
    if (r.kind === "train") {
      r.details.ticket_numbers = r.details.seats.map((_, i) => `NRC${r.reference.slice(2)}${String(i + 1).padStart(2, "0")}`);
      r.events.push(ev("ticketed", `Tickets issued: ${r.details.ticket_numbers.join(", ")}. Show the QR at the gate.`));
    } else {
      r.events.push(ev("ticketed", `${r.details.restaurant.name} confirmed your table for ${r.details.party_size} at ${r.details.time}`));
      if (r.details.preorder.length) r.events.push(ev("preorder_sent", "Your pre-order was sent to the kitchen"));
    }
    r.events.push(ev("email", `Confirmation emailed to ${r.contact_email}`)); r.status = "ticketed";
  }

  async function demo(path, method, body, params = {}) {
    if (path === "/api/stations") {
      const st = allStations().map(({ mins: _, ...s }) => s);
      if (params.lat != null) { st.forEach((s) => (s.distance_km = km({ lat: +params.lat, lng: +params.lng }, s))); st.sort((a, b) => a.distance_km - b.distance_km); }
      return st;
    }
    if (path === "/api/trains/search") return demoTrains(body);
    let m = path.match(/^\/api\/trains\/(.+)\/seats$/); if (m) return demoSeats(m[1]);
    if (path === "/api/trains/bookings") {
      const o = store[body.offer_id], f = o.fares.find((x) => x.travel_class === body.travel_class), id = "demo_rsv_" + Date.now();
      store[id] = { id, reference: ref(), kind: "train", status: "pending_payment", contact_name: body.passengers[0].full_name, contact_email: body.contact_email,
        details: { offer: o, travel_class: body.travel_class, seats: body.seats, passengers: body.passengers }, currency: "NGN",
        amount: f.amount * body.seats.length, service_fee: 300, total_amount: f.amount * body.seats.length + 300,
        events: [ev("created", `Seats ${body.seats.join(", ")} held for 15 minutes — awaiting payment`)] };
      return { reservation: store[id], token: "demo" };
    }
    if (path === "/api/restaurants/search") return demoVenues(body);
    if (path === "/api/restaurants/bookings") {
      const v = D.restaurants.find((x) => x.id === body.restaurant_id), id = "demo_rsv_" + Date.now();
      const lines = body.preorder.map((l) => { const it = v.menu.find((x) => x.id === l.item_id); return { ...l, name: it.name, price: it.price, subtotal: it.price * l.qty }; });
      const food = lines.reduce((a, l) => a + l.subtotal, 0), deposit = v.deposit_per_guest * body.party_size, due = deposit + (body.pay_preorder_now ? food : 0);
      const r = store[id] = { id, reference: ref(), kind: "restaurant", status: "pending_payment", contact_name: body.contact_name, contact_email: body.contact_email,
        details: { restaurant: v, date: body.date, time: body.time, party_size: body.party_size, preorder: lines, preorder_total: food, preorder_paid: body.pay_preorder_now, deposit, notes: body.notes },
        currency: "NGN", amount: due, service_fee: 0, total_amount: due, events: [ev("created", `Table for ${body.party_size} at ${body.time} requested`)] };
      if (!due) confirmDemo(r);
      return { reservation: r, token: "demo" };
    }
    m = path.match(/^\/api\/restaurants\/([a-z-]+)$/);
    if (m) { const v = D.restaurants.find((x) => x.id === m[1]); if (!v) throw new Error("Not found"); return { ...v, matches: [], slots: demoSlots(v, params.date, params.time, +params.party_size) }; }
    m = path.match(/^\/api\/reservations\/([^/]+)(\/pay)?$/);
    if (m) { const r = store[m[1]]; if (!r) throw new Error("Not found"); if (m[2]) { confirmDemo(r); return { checkout_url: "#" }; } return r; }
    if (path === "/api/bookings/lookup") {
      const r = Object.values(store).find((x) => x.reference === body.reference.toUpperCase());
      if (!r) throw new Error("Not found"); return { kind: r.kind, reservation: r, token: "demo" };
    }
    throw new Error("Not available in demo");
  }

  function demoAssistant({ text, session = {} }) {
    const t = text.toLowerCase(), sess = { ...session }, yes = /^(yes|yeah|ok|sure|book it|go ahead)/.test(t);
    if (yes && sess.mode === "train" && sess.pick_train_id) return { reply: "Done. Pick your seats and I'll hold them while you pay.", intent: "confirm_train", mode: "train", session: sess };
    if (yes && sess.mode === "food" && sess.pick_restaurant_id) return { reply: "Lovely. Choose anything you'd like ready when you arrive, then confirm the table.", intent: "confirm_table", mode: "food", session: sess };
    const isTrain = /\b(train|rail|railway)\b/.test(t), isFlight = /\b(fly|flight|plane)\b/.test(t);
    const isFood = /\b(hungry|eat|food|restaurant|dinner|lunch|breakfast|table|craving|starving|jollof|suya|shawarma|pizza|sushi|pepper ?soup|amala|swallow|steak|grill)\b/.test(t);
    const m = isTrain ? "train" : isFlight ? "flight" : isFood ? "food" : sess.mode;
    if (m !== "train" && m !== "food") return null;
    sess.mode = m;
    const d0 = todayIso, wd = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"].findIndex((w) => t.includes(w));
    const date = /tomorrow/.test(t) ? addDays(d0, 1) : wd >= 0 ? addDays(d0, ((wd - new Date().getDay() + 7) % 7) || 7) : /today|tonight|now|hungry/.test(t) ? d0 : null;
    const num = (re) => { const x = t.match(re); if (!x) return null; return +x[1] || { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6 }[x[1]] || null; };
    if (m === "train") {
      const city = (frag) => { const s = allStations().find((x) => frag.includes(x.city.toLowerCase())); return s && allStations().find((x) => x.city === s.city)?.code; };
      const fr = t.match(/from ([a-z ]+?)(?= to| on| tomorrow| for|$)/), to = t.match(/to ([a-z ]+?)(?= from| on| tomorrow| for| next|$)/);
      if (to) sess.t_destination = city(to[1]) || sess.t_destination; if (fr) sess.t_origin = city(fr[1]) || sess.t_origin;
      if (date) sess.t_date = date; const p = num(/(\d+|\w+) (?:people|seats|tickets|passengers)/); if (p) sess.t_passengers = p;
      if (!sess.t_destination) return { reply: "Where are you going by train? I can book Abuja–Kaduna, Lagos–Ibadan, Warri–Itakpe and Port Harcourt–Aba.", intent: "need_destination", mode: m, session: sess, suggestions: ["Abuja to Kaduna", "Lagos to Ibadan"] };
      if (!sess.t_origin) { const dst = allStations().find((x) => x.code === sess.t_destination); sess.t_origin = allStations().find((x) => x.line === dst.line && x.code !== dst.code).code; }
      if (!sess.t_date) return { reply: "Which day do you want to travel?", intent: "need_date", mode: m, session: sess, suggestions: ["Tomorrow", "Saturday"] };
      const res = demoTrains({ origin: sess.t_origin, destination: sess.t_destination, date: sess.t_date, passengers: sess.t_passengers || 1 });
      if (!res.offers.length) return { reply: "No trains with seats on that route that day. Try another day?", intent: "no_results", mode: m, session: sess, train_results: res, suggestions: ["Tomorrow"] };
      const o = res.offers.find((x) => x.id === res.pick.offer_id); sess.pick_train_id = o.id; sess.t_class = "standard";
      return { reply: `Train ${o.train_number} leaves at ${tm(o.departing_at)} on ${longDay(sess.t_date)} and arrives at ${tm(o.arriving_at)}. Standard is ${money(o.fares[0].amount)} per person, ${o.fares[0].seats_left} seats left. Shall I book it?`, intent: "train_suggested", mode: m, session: sess, train_results: res, suggestions: ["Yes, book it"] };
    }
    if (demoTerms(text).length) sess.f_craving = demoTerms(text).join(" ");
    for (const [area, c] of [["wuse", "Abuja"], ["maitama", "Abuja"], ["jabi", "Abuja"], ["garki", "Abuja"], ["asokoro", "Abuja"], ["gwarinpa", "Abuja"], ["abuja", "Abuja"], ["lagos", "Lagos"], ["lekki", "Lagos"], ["ikoyi", "Lagos"], ["victoria island", "Lagos"], ["port harcourt", "Port Harcourt"]]) if (t.includes(area)) sess.f_city = c;
    const p = num(/(?:for|table for) (\d+|\w+)/); if (p) sess.f_party = p;
    const at = t.match(/(\d{1,2})(?::(\d{2}))?\s*(am|pm)/); if (at) sess.f_time = `${String((+at[1] % 12) + (at[3] === "pm" ? 12 : 0)).padStart(2, "0")}:${+at[2] >= 30 ? "30" : "00"}`;
    else if (/lunch/.test(t)) sess.f_time = "13:00"; else if (/dinner|tonight/.test(t)) sess.f_time = "19:30";
    if (date) sess.f_date = date;
    if (!sess.f_craving && !sess.asked) { sess.asked = true; return { reply: "What are you in the mood for?", intent: "need_craving", mode: m, session: sess, suggestions: ["Jollof", "Suya", "Pepper soup", "Sushi", "Surprise me"] }; }
    const s = { craving: sess.f_craving || null, city: sess.f_city || $("#eCity").value, date: sess.f_date || d0, time: sess.f_time || "19:30", party_size: sess.f_party || 2 };
    const res = demoVenues(s);
    if (!res.restaurants.length) return { reply: `I couldn't find that in ${s.city}. Want to try something close to it?`, intent: "no_results", mode: m, session: sess, restaurant_results: res, suggestions: ["Nigerian food", "Surprise me"] };
    const b = res.restaurants[0], dish = b.menu.find((x) => b.matches.includes(x.id)), when = b.slots.includes(s.time) ? s.time : b.slots[0];
    sess.pick_restaurant_id = b.id; if (when) sess.f_time = when;
    return { reply: `Try ${b.name} in ${b.area}${dish ? ` for the ${dish.name.toLowerCase()}` : ""}. It's rated ${b.rating}/5 and ${!when ? "has no free tables near that time" : when === s.time ? `has a table for ${s.party_size} at ${when}` : `${s.time} is taken, but there's a table for ${s.party_size} at ${when}`}${b.deposit_per_guest ? `; they take a ${money(b.deposit_per_guest)} deposit per guest, off your bill` : ""}. Want me to book it?`,
      intent: "table_suggested", mode: m, session: sess, restaurant_results: res, suggestions: ["Yes, book it", "Somewhere cheaper"] };
  }

  window.QuikMore = { ready: () => { initTrains(); initEat(); }, onAssistant, openReservation, demo, demoAssistant };
})();
