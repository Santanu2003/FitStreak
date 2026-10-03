// ===================== FitStreak frontend =====================
const api = async (path, options = {}) => {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// Every value that came from a user (theirs or someone else's — a registered name,
// a free-typed food name, etc.) must go through this before landing in innerHTML.
// Values chosen from a fixed <select> (activity type, mood, meal) are also escaped
// here for defense in depth, even though the backend now validates them too.
function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value === null || value === undefined ? "" : String(value);
  return div.innerHTML;
}

let libraryState = { page: 1, per_page: 8 };
let nutritionState = { logDate: null, historyDays: 7 };
let CURRENT_USER = null; // canonical profile snapshot used by every view
let APP_CONFIG = null;
let LAST_USER_SUMMARY = null;

async function loadAppConfig() {
  if (APP_CONFIG) return APP_CONFIG;
  APP_CONFIG = await api("/config");
  const d = APP_CONFIG.datasets || {};
  const setText = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
  setText("exercise-library-count", `${fmtNum(d.exercise_count || 0)} exercises`);
  setText("activity-comparison-count", fmtNum(d.activity_comparison_sample_size || 0));
  setText("student-insights-count", fmtNum(d.student_sample_size || 0));
  setText("health-benchmark-count", fmtNum(d.health_sample_size || 0));
  setText("nutrition-food-count", `${fmtNum(d.food_count || 0)} foods`);
  return APP_CONFIG;
}

async function syncCanonicalUser() {
  const { user } = await api("/me");
  CURRENT_USER = user;
  $("#sidebar-user-name").textContent = user.name;
  $("#sidebar-user-meta").textContent = `BMI ${user.bmi} · ${user.bmi_category} · ${user.weight_kg} kg`;
  return user;
}

async function syncCrossSectionState() {
  try {
    await syncCanonicalUser();
    LAST_USER_SUMMARY = await api("/user/summary");
    return LAST_USER_SUMMARY;
  } catch (err) {
    console.warn("Cross-section sync failed", err);
    return null;
  }
}

// ------------------------------------------------------------ date helpers --
// Dates are always the browser's LOCAL calendar day (toISOString() would give the UTC day,
// which is "yesterday" for the first hours of the morning east of Greenwich, e.g. in India).
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const pad2 = (n) => String(n).padStart(2, "0");
function localIso(d = new Date()) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}
function todayIso() { return localIso(); }
function parseIso(iso) { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); }
function addDays(iso, n) { const d = parseIso(iso); d.setDate(d.getDate() + n); return localIso(d); }
function shortDate(iso) { const d = parseIso(iso); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; }
function longDate(iso) {
  const d = parseIso(iso);
  return `${WEEKDAYS[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}
function daysAgo(iso) {
  return Math.round((parseIso(todayIso()) - parseIso(iso)) / 86400000);
}
function relativeDay(iso) {
  const n = daysAgo(iso);
  return n === 0 ? "Today" : n === 1 ? "Yesterday" : n > 1 ? `${n} days ago` : n === -1 ? "Tomorrow" : `In ${-n} days`;
}
const fmtNum = (n) => Number(n).toLocaleString("en-US");
const signed = (n) => (n > 0 ? "+" : n < 0 ? "\u2212" : "") + fmtNum(Math.abs(Math.round(n)));

// Animated count-up for headline numbers (instant when the OS asks for reduced motion).
function countUp(el, to, opts = {}) {
  const { decimals = 0, duration = 900, prefix = "", suffix = "" } = opts;
  const show = (v) => { el.textContent = `${prefix}${decimals ? v.toFixed(decimals) : fmtNum(Math.round(v))}${suffix}`; };
  if (!isFinite(to)) { el.textContent = `${prefix}${to}${suffix}`; return; }
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) { show(to); return; }
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min(1, (now - start) / duration);
    show(to * (1 - Math.pow(1 - t, 3)));
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

const TYPE_COLORS = {
  Cardio: "#3E7CA6", HIIT: "#E4573F", Strength: "#3F5A34", Yoga: "#9AAE20", Running: "#F08A00",
  Walking: "#6FA35A", Swimming: "#2B93A6", Cycling: "#6B5CA5", Dancing: "#D1477A", Other: "#6E7266",
  Rest: "#DAD9C8",
};
const typeColor = (t) => TYPE_COLORS[t] || "#6E7266";

function showToast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 2600);
}

// -------------------------------------------------------------------- charts --
// Every chart goes through renderChart(). js/minicharts.js draws it as an interactive SVG
// (hover highlights, tooltips, click-to-hide legend, animations) with no library and no
// internet needed. Re-rendering a canvas first tears down the previous chart on it.
const chartRegistry = {};

function clearChartArtifacts(canvas) {
  canvas.classList.remove("hidden");
  canvas.parentElement.querySelectorAll(".chart-fallback, .mini-chart").forEach((el) => el.remove());
}

function resetChart(canvasId) {
  if (chartRegistry[canvasId]) { try { chartRegistry[canvasId].destroy(); } catch (e) { /* already gone */ } }
  delete chartRegistry[canvasId];
  const canvas = $(`#${canvasId}`);
  if (canvas) clearChartArtifacts(canvas);
  return canvas;
}

function renderChart(canvasId, config) {
  const canvas = resetChart(canvasId);
  if (!canvas) return null;
  if (window.MiniChart) {
    try {
      const chart = MiniChart.render(canvas, config);
      chartRegistry[canvasId] = chart;
      return chart;
    } catch (err) { console.error(err); }
  }
  showChartFallback(canvas, "This chart couldn't be drawn.");
  return null;
}

function showChartFallback(canvas, msg) {
  canvas.classList.add("hidden");
  let fallback = canvas.parentElement.querySelector(".chart-fallback");
  if (!fallback) {
    fallback = document.createElement("div");
    fallback.className = "chart-fallback";
    canvas.insertAdjacentElement("afterend", fallback);
  }
  fallback.textContent = msg;
}

// ------------------------------------------------------------ auth screen --
function initAuthTabs() {
  $$(".auth-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".auth-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const which = tab.dataset.tab;
      $("#login-form").classList.toggle("hidden", which !== "login");
      $("#register-form").classList.toggle("hidden", which !== "register");
    });
  });
}

async function handleLogin(e) {
  e.preventDefault();
  const form = e.target;
  const errBox = $("#login-error");
  errBox.textContent = "";
  try {
    const payload = {
      email: form.email.value,
      password: form.password.value,
    };
    const { user } = await api("/login", { method: "POST", body: JSON.stringify(payload) });
    onAuthenticated(user);
  } catch (err) {
    errBox.textContent = err.message;
  }
}

async function handleRegister(e) {
  e.preventDefault();
  const form = e.target;
  const errBox = $("#register-error");
  errBox.textContent = "";
  try {
    const payload = {
      name: form.name.value,
      email: form.email.value,
      password: form.password.value,
      age: form.age.value,
      gender: form.gender.value,
      height_cm: form.height_cm.value,
      weight_kg: form.weight_kg.value,
      experience_level: form.experience_level.value,
    };
    const { user } = await api("/register", { method: "POST", body: JSON.stringify(payload) });
    onAuthenticated(user);
  } catch (err) {
    errBox.textContent = err.message;
  }
}

// Safety net: no dropdown may ever list the same option twice (matched on value + text,
// ignoring case/extra spaces). Runs after the dropdowns are filled and whenever one is opened.
function dedupeSelect(sel) {
  if (!sel || sel.tagName !== "SELECT") return;
  const seen = new Set();
  [...sel.options].forEach((opt) => {
    const key = `${opt.value.trim().toLowerCase()}|${opt.textContent.trim().toLowerCase()}`;
    if (seen.has(key)) opt.remove(); else seen.add(key);
  });
}
function dedupeAllSelects() {
  document.querySelectorAll("select").forEach(dedupeSelect);
}
["mousedown", "focusin", "keydown"].forEach((evt) =>
  document.addEventListener(evt, (e) => { if (e.target && e.target.tagName === "SELECT") dedupeSelect(e.target); }, true)
);

async function onAuthenticated(user) {
  CURRENT_USER = user;
  $("#auth-screen").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");
  await loadAppConfig();
  await syncCrossSectionState();
  await populateWorkoutTypeSelects();
  await populateDynamicFormControls();
  dedupeAllSelects();
  await loadDashboard();
}

async function handleLogout() {
  await api("/logout", { method: "POST" });
  $("#app-shell").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
  $("#login-form").reset();
}

// -------------------------------------------------------------- nav/views --
function initNav() {
  $$(".nav-link").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".nav-link").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      $$(".view").forEach((v) => v.classList.remove("active"));
      $(`#view-${btn.dataset.view}`).classList.add("active");

      if (btn.dataset.view === "library") loadLibrary();
      if (btn.dataset.view === "insights") loadInsights();
      if (btn.dataset.view === "leaderboard") loadLeaderboard();
      if (btn.dataset.view === "dashboard") loadDashboard();
      if (btn.dataset.view === "predict") { loadActivityComparison(); loadPredictProfile(); }
      if (btn.dataset.view === "benchmark") { loadBenchmarkChart(); prefillBenchmarkFromUser(); }
      if (btn.dataset.view === "nutrition") loadNutrition();
      if (btn.dataset.view === "weight") loadWeight();
    });
  });
}

// -------------------------------------------------------------- dashboard --
function renderNudge(summary) {
  const box = $("#today-nudge");
  let text, kind;
  if (summary.logged_today) {
    text = `Logged today — nice work. Current streak: ${summary.current_streak} day(s).`;
    kind = "ok";
  } else if (summary.current_streak > 0) {
    text = `Your ${summary.current_streak}-day streak ends tonight — log any activity to keep it alive.`;
    kind = "warn";
  } else {
    text = "Nothing logged today yet — even a 10-minute walk starts a streak.";
    kind = "info";
  }
  box.textContent = text;
  box.className = `nudge nudge-${kind}`;
}

function renderNetCalories(net) {
  const num = $("#stat-net");
  const detail = $("#stat-net-detail");
  if (!net) { num.textContent = "0"; detail.textContent = ""; return; }
  const sign = net.net > 0 ? "+" : "";
  num.textContent = `${sign}${Math.round(net.net)}`;
  num.classList.toggle("net-surplus", net.net > 0);
  num.classList.toggle("net-deficit", net.net < 0);
  detail.textContent = `${Math.round(net.consumed)} eaten − ${Math.round(net.burned)} burned`;
}

async function loadDashboard() {
  try {
    const summary = await api("/dashboard/summary");
    $("#stat-streak").textContent = summary.current_streak;
    $("#stat-calories").textContent = Math.round(summary.total_calories);
    $("#stat-sessions").textContent = summary.total_sessions;
    $("#stat-steps").textContent = summary.total_steps;
    $("#stat-badge").textContent = summary.badge === "None" ? "No badge yet" : `${summary.badge} badge`;
    renderNetCalories(summary.net_calories_today);
    renderNudge(summary);

    const { logs } = await api("/activity/history");
    renderHistoryTable(logs);
    renderHistoryChart(logs);
  } catch (err) {
    showToast(err.message);
  }
}

function renderHistoryTable(logs) {
  const tbody = $("#history-table tbody");
  tbody.innerHTML = "";
  const recent = [...logs].reverse().slice(0, 8);
  $("#history-empty").classList.toggle("hidden", recent.length > 0);
  for (const log of recent) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(log.log_date)}</td>
      <td>${escapeHtml(log.activity_type)}</td>
      <td>${log.duration_min} min</td>
      <td>${Math.round(log.calories_burned)}</td>
      <td>${log.steps || 0}</td>
      <td>${escapeHtml(log.mood)}</td>
      <td><button class="row-delete" data-id="${log.id}">Delete</button></td>
    `;
    tbody.appendChild(tr);
  }
  $$(".row-delete", tbody).forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api(`/activity/${btn.dataset.id}`, { method: "DELETE" });
        showToast("Entry deleted.");
        loadDashboard();
      } catch (err) {
        showToast(err.message);
      }
    });
  });
}

function renderHistoryChart(logs) {
  const shortLabels = logs.map((l) => shortDate(l.log_date));
  const labels = logs.map((l) => `${shortDate(l.log_date)} \u00b7 ${l.activity_type}`);
  const data = logs.map((l) => l.calories_burned);
  renderChart("history-chart", {
    type: "line",
    data: {
      labels, shortLabels,
      datasets: [{
        label: "Calories burned", data, unit: " kcal", decimals: 0,
        borderColor: "#3F5A34", backgroundColor: "rgba(201,222,59,0.25)",
        fill: true, tension: 0.35,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, title: { display: true, text: "kcal" } } },
      tooltipExtra: (i) => [`${logs[i].duration_min} min \u00b7 mood ${logs[i].mood}`],
    },
  });
}

async function handleActivitySubmit(e) {
  e.preventDefault();
  const form = e.target;
  const errBox = $("#activity-error");
  errBox.textContent = "";
  try {
    const payload = {
      date: form.date.value,
      activity_type: form.activity_type.value,
      duration_min: form.duration_min.value,
      steps: form.steps.value || 0,
      mood: form.mood.value,
    };
    const { log, updated } = await api("/activity", { method: "POST", body: JSON.stringify(payload) });
    showToast(updated
      ? `Entry updated · ${Math.round(log.calories_burned)} kcal`
      : `Entry saved · ${Math.round(log.calories_burned)} kcal`);
    loadDashboard();
  } catch (err) {
    errBox.textContent = err.message;
  }
}

let estimateDebounce;
async function refreshCalorieEstimate() {
  const form = $("#activity-form");
  const box = $("#calorie-estimate");
  const activityType = form.activity_type.value;
  const duration = parseFloat(form.duration_min.value);
  if (!activityType || !duration || duration <= 0) {
    box.textContent = "Fill in activity, duration and mood to see an estimated calorie burn.";
    return;
  }
  clearTimeout(estimateDebounce);
  estimateDebounce = setTimeout(async () => {
    try {
      const params = new URLSearchParams({
        activity_type: activityType,
        duration_min: duration,
        mood: form.mood.value,
      });
      const { estimated_calories } = await api(`/activity/estimate-calories?${params.toString()}`);
      box.innerHTML = `Estimated calories burned: <b>${Math.round(estimated_calories)} kcal</b>`;
    } catch (err) {
      box.textContent = "Couldn't estimate calories right now.";
    }
  }, 250);
}

// ---------------------------------------------------------------- predict --
async function handlePredictSubmit(e) {
  e.preventDefault();
  const form = e.target;
  const errBox = $("#predict-error");
  errBox.textContent = "";
  try {
    const payload = Object.fromEntries(new FormData(form).entries());
    if (CURRENT_USER) {
      payload.age = CURRENT_USER.age; payload.gender = CURRENT_USER.gender;
      payload.weight_kg = CURRENT_USER.weight_kg; payload.height_cm = CURRENT_USER.height_cm;
      payload.experience_level = CURRENT_USER.experience_level;
      if (!payload.frequency) payload.frequency = Math.max(1, Math.min(7, Math.round((LAST_USER_SUMMARY?.last_7_days?.active_days || 3))));
    }
    const result = await api("/predict/calories", { method: "POST", body: JSON.stringify(payload) });
    // Everything the person typed goes into the plan too, so the week reflects their real
    // frequency, session length and body - and every training day gets a model estimate.
    const params = new URLSearchParams({
      bmi: result.bmi, experience_level: payload.experience_level, workout_type: payload.workout_type,
      frequency: payload.frequency, duration_min: payload.duration_min, age: payload.age,
      gender: payload.gender, weight_kg: payload.weight_kg, height_cm: payload.height_cm,
      avg_bpm: payload.avg_bpm, max_bpm: payload.max_bpm, resting_bpm: payload.resting_bpm,
    });
    const rec = await api(`/recommend/workout?${params.toString()}`);
    renderPredictResult(result, rec, payload.workout_type);
  } catch (err) {
    errBox.textContent = err.message;
  }
}

let fatEstimateDebounce;
async function refreshFatEstimate() {
  const form = $("#predict-form");
  const box = $("#fat-estimate");
  const age = form.age.value, gender = form.gender.value;
  const heightCm = form.height_cm.value, weightKg = form.weight_kg.value;
  if (!age || !heightCm || !weightKg) return;
  clearTimeout(fatEstimateDebounce);
  fatEstimateDebounce = setTimeout(async () => {
    try {
      const params = new URLSearchParams({ age, gender, height_cm: heightCm, weight_kg: weightKg });
      const { estimated_fat_percentage, bmi } = await api(`/predict/estimate-fat?${params.toString()}`);
      box.innerHTML = `Estimated body fat: <b>${estimated_fat_percentage}%</b> (BMI ${bmi}, from the Deurenberg formula — no manual entry needed).`;
    } catch {
      // silent — this is a passive preview, not a required step
    }
  }, 250);
}

function renderPredictResult(result, rec, selectedWorkoutType) {
  const box = $("#predict-result");
  const cohort = rec.cohort_insight;
  const cohortHtml = cohort ? `
    <div class="cohort-box">
      Users with a similar BMI &amp; experience level (n=${cohort.sample_size} in the dataset) most often do
      <b>${escapeHtml(cohort.common_workout)}</b> for about <b>${Math.round(cohort.avg_duration_hr * 60)} min</b>,
      ${cohort.avg_frequency}\u00d7 a week, burning roughly <b>${Math.round(cohort.avg_calories)} kcal</b> per session.
    </div>` : "";

  const rate = result.type_intensity;
  const typeNoteHtml = `
    <p class="form-hint" style="margin-top:0;">
      Scored as <b>${escapeHtml(result.model_workout_type)}</b> itself \u2014 the model is trained on all
      ${result.trained_types.length} workout types. ${escapeHtml(result.model_workout_type)} burns about
      <b>${rate}\u00d7</b> the average activity's calories per minute at the same effort.
    </p>`;

  const plan = rec.weekly_plan;
  const planHtml = plan.map((d) => {
    const rest = d.type === "Rest";
    const exercises = d.exercises.map((e) => `${escapeHtml(e.Title)} (${escapeHtml(e.BodyPart)})`).join(", ");
    return `
    <div class="plan-day ${rest ? "rest" : ""}" style="--type:${typeColor(d.type)}">
      <span class="plan-day-label">${escapeHtml(d.day)}</span>
      <span class="plan-day-type">${escapeHtml(d.type)}</span>
      <span class="plan-day-duration">${rest ? "\u2014" : `${d.duration_min} min`}</span>
      <span class="plan-day-kcal">${rest || d.est_kcal == null ? "" : `\u2248${fmtNum(d.est_kcal)} kcal`}</span>
      <span class="plan-day-exercises">${exercises || (rest ? "Recovery \u2014 light stretching or a walk" : "")}</span>
    </div>`;
  }).join("");

  const types = rec.types_in_plan || [];
  const weekKcal = rec.week_total_kcal ? ` \u00b7 about ${fmtNum(rec.week_total_kcal)} kcal for the week` : "";
  box.innerHTML = `
    <div class="result-hero">${Math.round(result.predicted_calories)} kcal</div>
    <div class="result-sub">Estimated for this session \u00b7 BMI ${result.bmi} (${escapeHtml(result.bmi_category)}) \u00b7 body fat \u2248 ${result.estimated_fat_percentage}%</div>
    ${typeNoteHtml}
    ${cohortHtml}
    <h3 style="font-size:14px;margin-bottom:2px;">Your 1-week plan</h3>
    <p class="form-hint" style="margin-top:0;margin-bottom:8px;">${rec.training_days} training day(s)${weekKcal}. The week rotates through
      ${types.map((t) => `<span class="type-dot" style="--type:${typeColor(t)}">${escapeHtml(t)}</span>`).join(" ")}
      with rest days between.</p>
    <canvas id="plan-chart" height="170"></canvas>
    <div class="weekly-plan">${planHtml}</div>
  `;

  renderChart("plan-chart", {
    type: "bar",
    data: {
      labels: plan.map((d) => `${d.day} \u00b7 ${d.type}`),
      shortLabels: plan.map((d) => d.day),
      datasets: [{
        label: "Estimated calories", data: plan.map((d) => d.est_kcal || 0), unit: " kcal",
        backgroundColor: plan.map((d) => typeColor(d.type)),
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: { y: { title: { display: true, text: "kcal per session" } } },
      tooltipExtra: (i) => plan[i].type === "Rest"
        ? ["Rest day \u2014 recovery"]
        : [`${plan[i].duration_min} min`, ...plan[i].exercises.slice(0, 3).map((e) => e.Title)],
    },
  });
}

async function populateDynamicFormControls() {
  const c = await loadAppConfig();
  const setOptions = (selector, values, keepFirst = false) => {
    const el = $(selector);
    if (!el) return;
    const first = keepFirst ? el.options[0]?.outerHTML || "" : "";
    el.innerHTML = first + values.map(v => {
      const value = typeof v === "object" ? v.value : v;
      const label = typeof v === "object" ? v.label : v;
      return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`;
    }).join("");
  };
  setOptions("#food-form select[name=meal]", c.meal_types);
  setOptions("#activity-form select[name=mood]", c.moods);
  const exp = c.experience_levels || [];
  setOptions("#predict-form select[name=experience_level]", exp);
}

async function populateWorkoutTypeSelects() {
  const { activity_types, body_parts, equipment, levels } = await api("/exercises/options");
  const fill = (sel, values) => {
    values = [...new Set(values)];
    sel.innerHTML = values.map((v) => `<option value="${v}">${v}</option>`).join("");
  };
  fill($("#predict-workout-type"), activity_types);
  fill($("#activity-type-select"), activity_types);

  // Rebuild (not append) so repeated logins never duplicate the options.
  const fillFilter = (sel, label, values) => {
    const unique = [...new Set(values)];
    sel.innerHTML = `<option value="">${label}</option>` +
      unique.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join("");
  };
  fillFilter($("#lib-bodypart"), "All body parts", body_parts);
  fillFilter($("#lib-equipment"), "All equipment", equipment);
  fillFilter($("#lib-level"), "All levels", levels);
}

let activityComparisonChart = null;
let activityComparisonLoaded = false;

async function loadPredictProfile() {
  try {
    const { profile, recent_28_days, model } = await api("/predict/profile");
    CURRENT_USER = { ...CURRENT_USER, ...profile };
    const form = $("#predict-form");
    if (!form) return;
    ["age", "gender", "weight_kg", "height_cm", "experience_level"].forEach(name => {
      if (form.elements[name]) form.elements[name].value = profile[name];
    });
    if (form.elements.frequency && !form.elements.frequency.value) form.elements.frequency.value = Math.max(1, Math.min(7, recent_28_days.active_days ? Math.round(recent_28_days.active_days / 4) : 3));
    const m = $("#model-info-box");
    if (m) m.innerHTML = `<b>${escapeHtml(model.algorithm)}</b> · ${fmtNum(model.training_rows || 0)} training sessions · ${model.feature_count} features · MAE ${model.metrics?.mae ?? "—"} kcal · ${model.trained_types.length} workout types`;
  } catch (err) { console.warn("Prediction profile load failed", err); }
}

async function loadActivityComparison() {
  if (activityComparisonLoaded) return;
  try {
    const data = await api("/insights/activity-comparison");
    const labels = data.by_activity_type.map((r) => r.activity_type);
    const values = data.by_activity_type.map((r) => r.cal_per_min);
    activityComparisonChart = renderChart("activity-comparison-chart", {
      type: "bar",
      data: {
        labels,
        datasets: [{ label: "kcal / min", data: values, unit: " kcal/min", decimals: 2,
                    backgroundColor: labels.map((l) => (TYPE_COLORS[l] ? TYPE_COLORS[l] : "#3F5A34")) }],
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: { x: { title: { display: true, text: "kcal per minute" } } },
      },
    });
    activityComparisonLoaded = true;
  } catch (err) {
    showToast(err.message);
  }
}

// ------------------------------------------------------------- benchmark --
function renderBenchmarkResult(result) {
  const box = $("#benchmark-result");
  if (!box) return;

  const pct = result.your_percentiles || {};
  const avg = result.bracket_averages || {};
  const top = result.top_quartile_in_bracket || {};
  const bracket = escapeHtml(result.age_bracket || "your age bracket");
  const sample = fmtNum(result.sample_size_in_bracket || 0);

  const metrics = [
    ["Daily steps", pct.daily_steps, "steps", top.daily_steps],
    ["Sleep", pct.sleep_hours, "hours/night", top.sleep_hours],
    ["Exercise", pct.exercise_hours_per_week, "hours/week", top.exercise_hours_per_week],
  ];
  if (pct.bmi !== undefined && pct.bmi !== null) {
    metrics.push(["BMI", pct.bmi, "BMI", null]);
  }

  const rows = metrics.map(([label, value, unit, topValue]) => {
    const safePct = Math.max(0, Math.min(100, Number(value) || 0));
    const pctText = value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}th percentile`;
    let note = `Reference average: ${label === "Daily steps" ? fmtNum(avg.avg_steps) + " steps" : label === "Sleep" ? avg.avg_sleep + " hours/night" : label === "Exercise" ? avg.avg_exercise_hrs + " hours/week" : avg.avg_bmi + " BMI"}.`;
    if (topValue !== null && topValue !== undefined) {
      note += ` 75th percentile: ${Number(topValue).toLocaleString("en-US", { maximumFractionDigits: 1 })} ${unit}.`;
    }
    return `
      <div class="pct-meter-row">
        <div class="pct-meter-head"><span>${escapeHtml(label)}</span><b>${escapeHtml(pctText)}</b></div>
        <div class="pct-meter" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${safePct}">
          <span class="pct-meter-fill" style="width:${safePct}%"></span>
          <span class="pct-meter-avg" title="Reference average"></span>
        </div>
        <p class="pct-meter-note">${escapeHtml(note)}</p>
      </div>`;
  }).join("");

  box.innerHTML = `
    <div class="benchmark-headline">
      You are in the <b>${bracket}</b> age bracket, compared with <b>${sample}</b> reference records.
    </div>
    ${rows}
    <p class="form-hint" style="margin-top:18px">Percentiles are descriptive comparisons within your age bracket; they are not medical advice or a health diagnosis.</p>
  `;
}

async function handleBenchmarkSubmit(e) {
  e.preventDefault();
  const form = e.target;
  const errBox = $("#benchmark-error");
  errBox.textContent = "";
  try {
    const payload = Object.fromEntries(new FormData(form).entries());
    if (form.dataset.bmi) payload.bmi = form.dataset.bmi;
    const result = await api("/health-benchmark", { method: "POST", body: JSON.stringify(payload) });
    renderBenchmarkResult(result);
    renderBenchmarkChart(result.all_bracket_averages, result.age_bracket_index);
  } catch (err) { errBox.textContent = err.message; }
}

async function prefillBenchmarkFromUser() {
  try {
    const p = await api("/health-benchmark/personal");
    const form = $("#benchmark-form");
    form.age.value = p.age; form.daily_steps.value = p.daily_steps;
    form.exercise_hours_per_week.value = p.exercise_hours_per_week;
    if (p.bmi) form.dataset.bmi = p.bmi;
    const note = $("#benchmark-source-note");
    if (note) note.innerHTML = `Steps and exercise are prefilled from your last ${p.window_days} days (${escapeHtml(p.source)}). Sleep is intentionally entered by you because FitStreak does not fabricate sleep data.`;
  } catch (err) { console.warn(err); }
}


let benchmarkChart = null;
let benchmarkBracketsCache = null;

function renderBenchmarkChart(benchmarks, highlightIndex) {
  const hasHighlight = highlightIndex !== null && highlightIndex !== undefined;
  const stepsColor = benchmarks.map((_, i) => (hasHighlight && i === highlightIndex ? "#9AAE20" : "#C9DE3B"));
  const exColor = benchmarks.map((_, i) => (hasHighlight && i === highlightIndex ? "#E4573F" : "#14201A"));
  $("#benchmark-chart-note").textContent = hasHighlight
    ? `You're in the ${benchmarks[highlightIndex].Age_Bracket} bracket — highlighted below.`
    : "Compare across every age group — your bracket lights up once you submit the form.";
  benchmarkChart = renderChart("benchmark-chart", {
    type: "bar",
    data: {
      labels: benchmarks.map((r) => r.Age_Bracket),
      datasets: [
        { label: "Avg daily steps", data: benchmarks.map((r) => r.avg_steps), unit: " steps", decimals: 0, backgroundColor: stepsColor, yAxisID: "y" },
        { label: "Avg exercise hrs/week", data: benchmarks.map((r) => r.avg_exercise_hrs), unit: " hrs", decimals: 1, backgroundColor: exColor, yAxisID: "y1" },
      ],
    },
    options: {
      highlightIndex: hasHighlight ? highlightIndex : undefined,
      scales: {
        y: { type: "linear", position: "left", title: { display: true, text: "Steps" } },
        y1: { type: "linear", position: "right", title: { display: true, text: "Hours/week" }, grid: { drawOnChartArea: false } },
      },
      tooltipExtra: (i) => [`Avg sleep: ${benchmarks[i].avg_sleep} hrs`, `Avg BMI: ${benchmarks[i].avg_bmi}`],
    },
  });
}

async function loadBenchmarkChart() {
  if (benchmarkBracketsCache) return;
  try {
    const { benchmarks } = await api("/health-benchmark/summary");
    benchmarkBracketsCache = benchmarks;
    renderBenchmarkChart(benchmarks, null);
  } catch (err) {
    showToast(err.message);
  }
}

// ------------------------------------------------------------- nutrition --
let selectedFood = null; // { Food_Item, Calories, Protein_g, Carbs_g, Fat_g } — set when a
                          // suggestion is clicked; used to rescale macros if servings changes.

function applyFoodMacros() {
  if (!selectedFood) return;
  const servings = parseFloat($("#food-servings-input").value) || 1;
  $("#food-calories-input").value = Math.round(selectedFood.Calories * servings);
  $("#food-protein-input").value = +(selectedFood.Protein_g * servings).toFixed(1);
  $("#food-carbs-input").value = +(selectedFood.Carbs_g * servings).toFixed(1);
  $("#food-fat-input").value = +(selectedFood.Fat_g * servings).toFixed(1);
}

function updateFoodFormHints() {
  // Not-found hint + "save to My foods" only make sense while a typed name isn't a picked suggestion.
  const typed = $("#food-search-input").value.trim().length >= 2;
  const custom = typed && !selectedFood;
  $("#save-custom-row").classList.toggle("hidden", !custom);
  if (!custom) $("#food-not-found").classList.add("hidden");
}

function initFoodCombobox() {
  const input = $("#food-search-input");
  const box = $("#food-suggestions");
  let debounceTimer;
  let searchSeq = 0; // ignore out-of-order responses while typing fast

  function pickFood(f) {
    selectedFood = f;
    input.value = f.Food_Item;
    box.classList.add("hidden");
    applyFoodMacros();
    updateFoodFormHints();
  }

  input.addEventListener("input", () => {
    selectedFood = null; // typing again means the previous pick no longer applies
    updateFoodFormHints();
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (q.length < 2) { box.classList.add("hidden"); box.innerHTML = ""; return; }
    debounceTimer = setTimeout(async () => {
      const seq = ++searchSeq;
      try {
        const { results } = await api(`/foods?search=${encodeURIComponent(q)}&limit=10`);
        if (seq !== searchSeq || selectedFood) return;
        $("#food-not-found").classList.toggle("hidden", results.length > 0);
        if (results.length === 0) { box.classList.add("hidden"); box.innerHTML = ""; return; }
        box.innerHTML = results.map((f) => `
          <div class="food-suggestion-item">
            <b>${escapeHtml(f.Food_Item)}</b>${f.Custom ? `<span class="badge-mine">Custom</span>` : ""}
            <span>${escapeHtml(f.Category)} · ${escapeHtml(String(f.Calories))} kcal, ${escapeHtml(String(f.Protein_g))}g protein, ${escapeHtml(String(f.Carbs_g))}g carbs, ${escapeHtml(String(f.Fat_g))}g fat per serving</span>
          </div>
        `).join("");
        box.classList.remove("hidden");
        $$(".food-suggestion-item", box).forEach((item, i) => {
          item.addEventListener("click", () => pickFood(results[i]));
        });
      } catch {
        // silent — search-as-you-type shouldn't toast on every keystroke
      }
    }, 250);
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".food-combobox")) box.classList.add("hidden");
  });

  $("#food-servings-input").addEventListener("input", applyFoodMacros);
}

let myFoodsCache = [];

function openMyFoodForm(food = null) {
  const form = $("#my-food-form");
  $("#my-food-error").textContent = "";
  $("#my-food-id").value = food ? food.custom_id : "";
  $("#my-food-name").value = food ? food.Food_Item : "";
  $("#my-food-calories").value = food ? food.Calories : "";
  $("#my-food-protein").value = food ? food.Protein_g : "";
  $("#my-food-carbs").value = food ? food.Carbs_g : "";
  $("#my-food-fat").value = food ? food.Fat_g : "";
  $("#my-food-form-title").textContent = food ? "Edit custom food" : "Add a custom food";
  $("#my-food-save").textContent = food ? "Update food" : "Save food";
  form.classList.remove("hidden");
  $("#my-food-name").focus();
}

function closeMyFoodForm() {
  $("#my-food-form").classList.add("hidden");
  $("#my-food-form").reset();
  $("#my-food-id").value = "";
  $("#my-food-error").textContent = "";
}

function renderMyFoods() {
  const query = $("#my-food-search").value.trim().toLowerCase();
  const foods = myFoodsCache.filter((f) => !query || f.Food_Item.toLowerCase().includes(query));
  const tbody = $("#my-foods-table tbody");
  const total = myFoodsCache.length;
  $("#my-foods-count").textContent = `· ${total} saved`;

  const empty = $("#my-foods-empty");
  const table = $("#my-foods-table");
  if (total === 0) {
    table.classList.add("hidden");
    empty.classList.remove("hidden");
    $("#my-foods-empty-title").textContent = "No custom foods yet";
    $("#my-foods-empty-copy").textContent = "Save a food you eat regularly and it will appear first when you search for it in the meal logger.";
    $("#my-foods-empty-btn").textContent = "Create your first food";
    return;
  }

  if (foods.length === 0) {
    table.classList.add("hidden");
    empty.classList.remove("hidden");
    $("#my-foods-empty-title").textContent = "No matching foods";
    $("#my-foods-empty-copy").textContent = `Nothing in your ${total} saved food${total === 1 ? "" : "s"} matches “${$("#my-food-search").value.trim()}”.`;
    $("#my-foods-empty-btn").textContent = "Clear search";
    return;
  }

  empty.classList.add("hidden");
  table.classList.remove("hidden");
  tbody.innerHTML = foods.map((f) => `
    <tr>
      <td><b>${escapeHtml(f.Food_Item)}</b><span class="my-food-badge">CUSTOM</span></td>
      <td>${fmtNum(Math.round(f.Calories))} kcal</td>
      <td>${escapeHtml(Number(f.Protein_g).toFixed(1))}g</td>
      <td>${escapeHtml(Number(f.Carbs_g).toFixed(1))}g</td>
      <td>${escapeHtml(Number(f.Fat_g).toFixed(1))}g</td>
      <td class="my-food-actions">
        <button class="row-action row-use" data-id="${Number(f.custom_id)}">Use</button>
        ${f.CanEdit ? `<button class="row-action row-edit" data-id="${Number(f.custom_id)}">Edit</button>
        <button class="row-action row-delete" data-id="${Number(f.custom_id)}">Delete</button>` : `<span class="my-food-owner-note">Shared food</span>`}
      </td>
    </tr>
  `).join("");
}

async function loadMyFoods() {
  try {
    const { foods } = await api("/custom-foods");
    myFoodsCache = Array.isArray(foods) ? foods : [];
    renderMyFoods();
  } catch (err) {
    showToast(err.message);
  }
}

function initMyFoodsControls() {
  $("#my-food-add-btn").addEventListener("click", () => openMyFoodForm());
  $("#my-foods-empty-btn").addEventListener("click", () => {
    if ($( "#my-foods-empty-title").textContent === "No matching foods") {
      $("#my-food-search").value = "";
      renderMyFoods();
      return;
    }
    openMyFoodForm();
  });
  $("#my-food-cancel").addEventListener("click", closeMyFoodForm);
  $("#my-food-search").addEventListener("input", renderMyFoods);

  $("#my-food-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const error = $("#my-food-error");
    error.textContent = "";
    const id = $("#my-food-id").value;
    const payload = {
      food_name: $("#my-food-name").value,
      calories: $("#my-food-calories").value,
      protein_g: $("#my-food-protein").value,
      carbs_g: $("#my-food-carbs").value,
      fat_g: $("#my-food-fat").value,
    };
    try {
      const result = await api(id ? `/custom-foods/${id}` : "/custom-foods", {
        method: id ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      showToast(result.created ? "Food added to My foods." : "My food updated.");
      closeMyFoodForm();
      await loadMyFoods();
    } catch (err) {
      error.textContent = err.message;
    }
  });

  $("#my-foods-table tbody").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-id]");
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const food = myFoodsCache.find((f) => Number(f.custom_id) === id);
    if (!food) return;

    if (btn.classList.contains("row-edit")) {
      if (!food.CanEdit) {
        showToast("Only the creator can edit this custom food.");
        return;
      }
      openMyFoodForm(food);
      return;
    }

    if (btn.classList.contains("row-use")) {
      selectedFood = food;
      $("#food-search-input").value = food.Food_Item;
      applyFoodMacros();
      updateFoodFormHints();
      $("#food-search-input").scrollIntoView({ behavior: "smooth", block: "center" });
      showToast(`${food.Food_Item} selected in the meal logger.`);
      return;
    }

    if (btn.classList.contains("row-delete")) {
      if (!food.CanEdit) {
        showToast("Only the creator can delete this custom food.");
        return;
      }
      if (!window.confirm(`Delete “${food.Food_Item}” from the shared custom-food library? Existing food logs will not be deleted.`)) return;
      try {
        await api(`/custom-foods/${id}`, { method: "DELETE" });
        showToast("Removed from My foods.");
        await loadMyFoods();
      } catch (err) {
        showToast(err.message);
      }
    }
  });
}

async function loadNutrition() {
  const input = $("#food-log-date");
  if (!input.value) input.value = todayIso();
  nutritionState.logDate = input.value;
  const formDate = $("#food-form [name=date]");
  if (!formDate.value) formDate.value = nutritionState.logDate;
  await refreshNutrition();
}

function refreshNutrition() {
  updateDayNavLabel();
  return Promise.all([loadGoal(), loadDay(), loadNutritionHistory(), loadMyFoods()]);
}

// Switch the whole page (goal meter, summary, macros, food log, history highlight) to one day.
function selectDate(iso) {
  if (!iso) return;
  nutritionState.logDate = iso;
  $("#food-log-date").value = iso;
  $("#food-form [name=date]").value = iso;      // new meals go to the day you're looking at
  refreshNutrition();
}

function updateDayNavLabel() {
  const iso = nutritionState.logDate;
  $("#day-nav-label").textContent = `${longDate(iso)} \u00b7 ${relativeDay(iso)}`;
  const short = shortDate(iso);
  ["#macro-date-label", "#food-log-date-label", "#day-summary-date"].forEach((sel) => {
    $(sel).textContent = `\u00b7 ${short}`;
  });
  $("#day-next").disabled = iso >= todayIso();
}

function initDayNav() {
  $("#food-log-date").addEventListener("change", (e) => selectDate(e.target.value));
  $("#day-prev").addEventListener("click", () => selectDate(addDays(nutritionState.logDate || todayIso(), -1)));
  $("#day-next").addEventListener("click", () => selectDate(addDays(nutritionState.logDate || todayIso(), 1)));
  $("#day-today").addEventListener("click", () => selectDate(todayIso()));
  $("#day-chips").addEventListener("click", (e) => {
    const chip = e.target.closest(".day-chip");
    if (chip) selectDate(chip.dataset.date);
  });
  $$("#history-range .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      nutritionState.historyDays = Number(btn.dataset.days);
      $$("#history-range .seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
      loadNutritionHistory();
    });
  });
  $("#history-days-table tbody").addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-date]");
    if (row) selectDate(row.dataset.date);
  });
}

async function handleFoodSubmit(e) {
  e.preventDefault();
  const form = e.target;
  const errBox = $("#food-error");
  errBox.textContent = "";
  try {
    const payload = {
      date: form.date.value,
      meal: form.meal.value,
      food_name: form.food_name.value,
      servings: form.servings.value,
      calories: form.calories.value,
      protein_g: form.protein_g.value,
      carbs_g: form.carbs_g.value,
      fat_g: form.fat_g.value,
      save_custom: !selectedFood && $("#save-custom-input").checked,
    };
    const { updated, saved_custom_food } = await api("/food", { method: "POST", body: JSON.stringify(payload) });
    showToast(updated ? "Existing entry updated (same food + meal + date)."
      : saved_custom_food ? "Meal logged and saved to My foods." : "Meal logged.");
    const keepDate = form.date.value;
    const keepMeal = form.meal.value;
    form.reset();
    form.date.value = keepDate;
    form.meal.value = keepMeal;
    form.servings.value = 1;
    selectedFood = null;
    updateFoodFormHints();
    await syncCrossSectionState();
    // Show the day the meal was logged on (the goal meter, summary and history all follow it).
    if (payload.date !== nutritionState.logDate) selectDate(payload.date);
    else refreshNutrition();
  } catch (err) {
    errBox.textContent = err.message;
  }
}

// ---- goal meter -------------------------------------------------------------
let goalOptionsFilled = false;
let goalSeq = 0;

async function loadGoal() {
  const seq = ++goalSeq;
  const iso = nutritionState.logDate || todayIso();
  try {
    const g = await api(`/goal?date=${iso}`);
    if (seq !== goalSeq) return;
    const sel = $("#goal-select");
    if (!goalOptionsFilled) {
      sel.innerHTML = "";
      for (const [value, label] of Object.entries(g.options)) {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = label;
        sel.appendChild(opt);
      }
      goalOptionsFilled = true;
    }
    sel.value = g.selected;
    const over = g.remaining < 0;
    const isToday = iso === todayIso();
    const when = isToday ? "today" : `on ${shortDate(iso)}`;
    $("#goal-bar-fill").style.width = `${Math.min(100, g.percent)}%`;
    $("#goal-bar-fill").classList.toggle("over", over);
    $("#goal-text").textContent =
      `${g.consumed} of ${g.target} kcal eaten ${when} \u2014 ` +
      (over ? `${Math.abs(g.remaining)} over target` : `${g.remaining} left`) +
      ` (resting needs \u2248 ${g.bmr} kcal, exercise ${when} +${g.burned})`;
  } catch (err) {
    $("#goal-text").textContent = "Couldn't load your goal.";
  }
}

async function handleGoalChange(e) {
  $("#goal-error").textContent = "";
  try {
    await api("/goal", { method: "POST", body: JSON.stringify({ goal: e.target.value }) });
    showToast("Goal updated.");
    await syncCrossSectionState();
  } catch (err) {
    $("#goal-error").textContent = err.message;
  }
  refreshNutrition();
}

// ---- one day: summary tiles, verdict, meals, workouts, macros, food log --------
let daySeq = 0;
const GOAL_NAMES = { lose: "weight-loss", maintain: "maintain-weight", gain: "muscle-building" };

async function loadDay() {
  const seq = ++daySeq;
  const iso = nutritionState.logDate || todayIso();
  try {
    const day = await api(`/nutrition/day?date=${iso}`);
    if (seq !== daySeq) return;
    renderDay(day);
  } catch (err) {
    showToast(err.message);
  }
}

function dayVerdict(d) {
  const isToday = d.date === todayIso();
  const when = isToday ? "So far today" : "This day";
  const goalLine = d.consumed > 0
    ? ` Against your ${GOAL_NAMES[d.goal] || "daily"} target of <b>${fmtNum(d.target)} kcal</b>: ` +
      (d.remaining >= 0 ? `<b>${fmtNum(d.remaining)}</b> left.` : `<b>${fmtNum(Math.abs(d.remaining))}</b> over.`)
    : "";
  switch (d.verdict) {
    case "no_data":
      return { kind: "no_data", html: isToday
        ? "Nothing logged yet today \u2014 add a meal or a workout and this summary fills in."
        : `No meals or workouts were logged for ${escapeHtml(longDate(d.date))}.` };
    case "activity_only":
      return { kind: "activity_only", html: `${when} you logged <b>${fmtNum(d.burned)} kcal</b> of exercise but no meals, so there's no energy balance to show yet.` };
    case "surplus":
      return { kind: "surplus", html: `${when}: you ate <b>${fmtNum(d.consumed)} kcal</b> and burned <b>${fmtNum(d.burned)} kcal</b> in workouts. Your body needed about <b>${fmtNum(d.maintenance)} kcal</b>, so you ${isToday ? "are" : "ended"} roughly <b>${fmtNum(d.balance)} kcal</b> in surplus (gained).${goalLine}` };
    case "deficit":
      return { kind: "deficit", html: `${when}: you ate <b>${fmtNum(d.consumed)} kcal</b> and burned <b>${fmtNum(d.burned)} kcal</b> in workouts. Your body needed about <b>${fmtNum(d.maintenance)} kcal</b>, so you ${isToday ? "are" : "ended"} roughly <b>${fmtNum(Math.abs(d.balance))} kcal</b> in deficit (burned beyond what you ate).${goalLine}` };
    default:
      return { kind: "balanced", html: `${when}: you ate <b>${fmtNum(d.consumed)} kcal</b> and burned <b>${fmtNum(d.burned)} kcal</b> in workouts \u2014 within 150 kcal of the <b>${fmtNum(d.maintenance)} kcal</b> your body needed. That's a balanced day.${goalLine}` };
  }
}

function renderDay(d) {
  // --- summary tiles ---
  const hasFood = d.consumed > 0;
  const balanceCls = d.verdict === "surplus" ? "surplus" : d.verdict === "deficit" ? "deficit" : "";
  $("#balance-grid").innerHTML = `
    <div class="balance-tile"><span class="bt-label">Eaten</span><b class="bt-num" id="bt-eaten">0</b><span class="bt-sub">kcal gained from food</span></div>
    <div class="balance-tile burn"><span class="bt-label">Burned</span><b class="bt-num" id="bt-burned">0</b><span class="bt-sub">kcal from ${d.sessions ? `${d.minutes} min of exercise` : "exercise"}</span></div>
    <div class="balance-tile"><span class="bt-label">Net</span><b class="bt-num">${d.logged ? signed(d.net) : "\u2014"}</b><span class="bt-sub">eaten \u2212 burned</span></div>
    <div class="balance-tile ${balanceCls}"><span class="bt-label">Energy balance</span><b class="bt-num">${hasFood ? signed(d.balance) : "\u2014"}</b><span class="bt-sub">${hasFood ? `vs \u2248${fmtNum(d.maintenance)} kcal needed` : "log a meal to see it"}</span></div>
  `;
  countUp($("#bt-eaten"), d.consumed);
  countUp($("#bt-burned"), d.burned);

  const v = dayVerdict(d);
  const verdictEl = $("#day-verdict");
  verdictEl.className = `day-verdict verdict-${v.kind}`;
  verdictEl.innerHTML = v.html;

  // --- meals + workouts ---
  $("#day-meals").innerHTML = d.by_meal.length
    ? d.by_meal.map((m) => `<div class="mini-row"><span>${escapeHtml(m.meal)}</span><b>${fmtNum(m.calories)} kcal</b></div>`).join("")
    : `<p class="empty-note">No meals logged.</p>`;
  $("#day-workouts").innerHTML = d.activities.length
    ? d.activities.map((a) => `<div class="mini-row"><span>${escapeHtml(a.activity_type)} \u00b7 ${a.duration_min} min</span><b>${fmtNum(a.calories_burned)} kcal</b></div>`).join("")
    : `<p class="empty-note">No workouts logged.</p>`;

  // --- macros ---
  $("#macro-calories").textContent = fmtNum(d.consumed);
  $("#macro-protein").textContent = `${d.protein_g}g`;
  $("#macro-carbs").textContent = `${d.carbs_g}g`;
  $("#macro-fat").textContent = `${d.fat_g}g`;
  renderMacroChart(d);

  // --- food log table ---
  const tbody = $("#food-table tbody");
  tbody.innerHTML = "";
  $("#food-empty").classList.toggle("hidden", d.entries.length > 0);
  for (const entry of d.entries) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(entry.meal)}</td>
      <td>${escapeHtml(entry.food_name)}</td>
      <td>${entry.servings}</td>
      <td>${Math.round(entry.calories)}</td>
      <td>${Math.round(entry.protein_g)}g</td>
      <td>${Math.round(entry.carbs_g)}g</td>
      <td>${Math.round(entry.fat_g)}g</td>
      <td><button class="row-delete" data-id="${entry.id}">Delete</button></td>
    `;
    tbody.appendChild(tr);
  }
  $$(".row-delete", tbody).forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api(`/food/${btn.dataset.id}`, { method: "DELETE" });
        showToast("Entry deleted.");
        refreshNutrition();
      } catch (err) {
        showToast(err.message);
      }
    });
  });
}

function renderMacroChart(d) {
  const values = [d.protein_g, d.carbs_g, d.fat_g];
  if (values.every((v) => !v)) {
    showChartFallback(resetChart("macro-chart"), "Log a meal to see this day's macro split.");
    return;
  }
  renderChart("macro-chart", {
    type: "doughnut",
    data: {
      labels: ["Protein", "Carbs", "Fat"],
      datasets: [{ data: values, unit: " g", backgroundColor: ["#3F5A34", "#C9DE3B", "#E4573F"] }],
    },
    options: { centerLabel: "grams of macros" },
  });
}

// ---- history (last 7 / 14 / 30 days) ---------------------------------------
let historySeq = 0;
const VERDICT_LABEL = { no_data: "Not logged", activity_only: "Workout only", balanced: "Balanced", surplus: "Surplus", deficit: "Deficit" };

async function loadNutritionHistory() {
  const seq = ++historySeq;
  try {
    const data = await api(`/nutrition/history?days=${nutritionState.historyDays}&end=${todayIso()}`);
    if (seq !== historySeq) return;
    renderDayChips(data.days.slice(-7));
    renderHistoryStats(data);
    renderNutritionHistoryChart(data.days);
    renderNutritionHistoryTable(data.days);
  } catch (err) {
    showToast(err.message);
  }
}

function renderDayChips(rows) {
  const selected = nutritionState.logDate;
  $("#day-chips").innerHTML = rows.map((r) => {
    const net = r.consumed > 0 ? signed(r.balance) : r.burned > 0 ? "workout" : "\u2014";
    const cls = ["day-chip", r.date === selected ? "active" : "", r.logged ? "logged" : "", r.verdict].join(" ");
    return `<button type="button" class="${cls}" data-date="${escapeHtml(r.date)}" title="${escapeHtml(longDate(r.date))}">
      <span class="dc-wd">${escapeHtml(r.weekday)}</span>
      <span class="dc-day">${parseIso(r.date).getDate()}</span>
      <span class="dc-net">${net}</span>
    </button>`;
  }).join("");
}

function renderHistoryStats(data) {
  const s = data.summary, n = data.days.length;
  const balanced = data.days.filter((d) => d.verdict === "balanced").length;
  $("#history-stats").innerHTML = `
    <div class="hs"><b>${s.logged_days}<small>/${n}</small></b><span>days logged</span></div>
    <div class="hs"><b>${fmtNum(s.avg_consumed)}</b><span>avg kcal eaten (days with meals)</span></div>
    <div class="hs"><b>${fmtNum(s.avg_burned)}</b><span>avg kcal burned (workout days)</span></div>
    <div class="hs"><b>${balanced}</b><span>balanced days</span></div>
  `;
}

function renderNutritionHistoryChart(days) {
  const compact = days.length > 7;
  const selectedIdx = days.findIndex((d) => d.date === nutritionState.logDate);
  renderChart("nutrition-history-chart", {
    type: "bar",
    data: {
      labels: days.map((d) => `${d.weekday} ${shortDate(d.date)}`),
      shortLabels: days.map((d) => (compact ? String(parseIso(d.date).getDate()) : `${d.weekday} ${parseIso(d.date).getDate()}`)),
      datasets: [
        { label: "Eaten", data: days.map((d) => d.consumed), unit: " kcal", backgroundColor: "#3F5A34" },
        { label: "Burned (exercise)", data: days.map((d) => d.burned), unit: " kcal", backgroundColor: "#E4573F" },
        { type: "line", label: "Target", data: days.map((d) => d.target), unit: " kcal", borderColor: "#14201A", borderDash: [5, 4], borderWidth: 2, pointRadius: 0 },
      ],
    },
    options: {
      scales: { y: { beginAtZero: true, title: { display: true, text: "kcal" } } },
      highlightIndex: selectedIdx,
      onClick: (i) => selectDate(days[i].date),
      tooltipExtra: (i) => {
        const d = days[i];
        if (!d.logged) return ["Nothing logged \u2014 click to open"];
        return [`Net ${signed(d.net)} kcal (eaten \u2212 burned)`,
                d.consumed > 0 ? `${VERDICT_LABEL[d.verdict]} ${signed(d.balance)} kcal vs needs` : VERDICT_LABEL[d.verdict],
                "Click to open this day"];
      },
    },
  });
}

function renderNutritionHistoryTable(days) {
  const tbody = $("#history-days-table tbody");
  tbody.innerHTML = [...days].reverse().map((d) => {
    const extra = d.verdict === "surplus" || d.verdict === "deficit" ? ` ${signed(d.balance)}` : "";
    return `<tr class="clickable-row ${d.date === nutritionState.logDate ? "selected" : ""}" data-date="${escapeHtml(d.date)}">
      <td>${escapeHtml(d.weekday)} ${escapeHtml(shortDate(d.date))}</td>
      <td>${d.consumed ? fmtNum(d.consumed) : "\u2014"}</td>
      <td>${d.burned ? fmtNum(d.burned) : "\u2014"}</td>
      <td>${d.logged ? signed(d.net) : "\u2014"}</td>
      <td>${fmtNum(d.target)}</td>
      <td><span class="pill pill-${d.verdict}">${VERDICT_LABEL[d.verdict]}${extra}</span></td>
    </tr>`;
  }).join("");
}

// ---------------------------------------------------------------- library --
async function loadLibrary() {
  try {
    const params = new URLSearchParams({
      page: libraryState.page,
      per_page: libraryState.per_page,
    });
    const search = $("#lib-search").value.trim();
    const bodypart = $("#lib-bodypart").value;
    const equipment = $("#lib-equipment").value;
    const level = $("#lib-level").value;
    if (search) params.set("search", search);
    if (bodypart) params.set("body_part", bodypart);
    if (equipment) params.set("equipment", equipment);
    if (level) params.set("level", level);

    const { results, total, page, per_page } = await api(`/exercises?${params.toString()}`);
    renderExerciseGrid(results);
    const totalPages = Math.max(1, Math.ceil(total / per_page));
    $("#lib-page-info").textContent = `Page ${page} of ${totalPages} · ${total} exercises`;
    $("#lib-prev").disabled = page <= 1;
    $("#lib-next").disabled = page >= totalPages;
  } catch (err) {
    showToast(err.message);
  }
}

function renderExerciseGrid(results) {
  const grid = $("#exercise-grid");
  if (results.length === 0) {
    grid.innerHTML = `<p class="empty-note">No exercises match those filters.</p>`;
    return;
  }
  grid.innerHTML = results.map((e) => `
    <div class="exercise-card">
      <h4>${escapeHtml(e.Title)}</h4>
      <div class="exercise-tags">
        <span class="tag tag-level">${escapeHtml(e.Level)}</span>
        <span class="tag">${escapeHtml(e.BodyPart)}</span>
        <span class="tag">${escapeHtml(e.Equipment)}</span>
        <span class="tag">${escapeHtml(e.Type)}</span>
      </div>
      <p>${escapeHtml(e.Desc)}</p>
    </div>
  `).join("");
}

function initLibraryControls() {
  let debounceTimer;
  $("#lib-search").addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => { libraryState.page = 1; loadLibrary(); }, 350);
  });
  [$("#lib-bodypart"), $("#lib-equipment"), $("#lib-level")].forEach((sel) => {
    sel.addEventListener("change", () => { libraryState.page = 1; loadLibrary(); });
  });
  $("#lib-prev").addEventListener("click", () => {
    if (libraryState.page > 1) { libraryState.page -= 1; loadLibrary(); }
  });
  $("#lib-next").addEventListener("click", () => {
    libraryState.page += 1; loadLibrary();
  });
}

// --------------------------------------------------------------- insights --
let insightsData = null;

async function loadInsights() {
  try {
    insightsData = await api("/insights/student");
  } catch (err) {
    showToast(err.message);
    return;
  }
  const data = insightsData;
  // Rendered independently: one piece failing must never block the others.
  try { renderInsightsHero(data); } catch (err) { console.error(err); }
  try { renderInsightsKpis(data); } catch (err) { console.error(err); }
  try { renderInsightsChart(data); } catch (err) { console.error(err); }
  try { renderExplorer(data, data.your_stats ? data.your_stats.avg_daily_activity_hours : data.overall_avg_activity_hours); } catch (err) { console.error(err); }
  try { renderDailyChart(data); } catch (err) { console.error(err); }
  try { renderMixChart(data); } catch (err) { console.error(err); }
  try { renderStressChart(data); } catch (err) { console.error(err); }
  try { renderWeekdayChart(data); } catch (err) { console.error(err); }
  try { renderInsightsStrip(data); } catch (err) { console.error(err); }
  try { renderInsightsText(data); } catch (err) { console.error(err); }
  try { renderPersonalInsight(data); } catch (err) { console.error(err); }
}

function renderInsightsHero(data) {
  const you = data.your_stats;
  const box = $("#insights-hero");
  if (!you) {
    box.innerHTML = `<div class="hero-empty">Log a few activities on the Dashboard and this page comes alive with your own numbers, set against ${fmtNum(data.sample_size)} surveyed users.</div>`;
    return;
  }
  box.innerHTML = `
    <div class="hero-num"><span id="hero-hours">0</span><small>hrs/day, your average</small></div>
    <div class="hero-copy">
      You're in the <b>"${escapeHtml(you.activity_bucket)}"</b> bucket, favoring <b>${escapeHtml(you.favorite_activity)}</b>,
      on a <b>${you.current_streak}-day</b> active streak. Best day so far:
      <b>${escapeHtml(you.best_day.weekday)} ${escapeHtml(shortDate(you.best_day.date))}</b> (${fmtNum(you.best_day.minutes)} min, ${fmtNum(you.best_day.kcal)} kcal).
    </div>
  `;
  countUp($("#hero-hours"), you.avg_daily_activity_hours, { decimals: 1 });
}

function renderInsightsKpis(data) {
  const you = data.your_stats;
  const box = $("#insights-kpis");
  const cards = [
    { label: "Users surveyed", value: fmtNum(data.sample_size), sub: "self-reported lifestyle survey" },
    { label: "Survey avg activity", value: `${data.overall_avg_activity_hours} hrs/day`, sub: `${data.overall_avg_gpa} avg GPA` },
    { label: "Activity \u2194 GPA", value: data.correlation_activity_gpa, sub: "correlation (\u22121 to 1)" },
    { label: "Activity \u2194 sleep", value: data.correlation_activity_sleep, sub: "correlation (\u22121 to 1)" },
  ];
  if (you) {
    cards.push({ label: "Your last 7 days", value: `${you.active_days_last7}/7 active`, sub: `${fmtNum(you.minutes_last7)} min logged` });
  }
  box.innerHTML = cards.map((c) => `
    <div class="kpi-card"><span class="kpi-label">${escapeHtml(c.label)}</span><b class="kpi-num">${c.value}</b><span class="kpi-sub">${escapeHtml(c.sub)}</span></div>
  `).join("");
}

function renderInsightsChart(data) {
  const labels = data.activity_vs_outcomes.map((r) => r.Activity_Bucket);
  const gpa = data.activity_vs_outcomes.map((r) => r.avg_gpa);
  const sleep = data.activity_vs_outcomes.map((r) => r.avg_sleep);
  const counts = data.activity_vs_outcomes.map((r) => r.count);
  const highlightIdx = data.your_stats ? labels.indexOf(data.your_stats.activity_bucket) : -1;
  renderChart("insights-chart", {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Avg GPA", data: gpa, decimals: 2, yAxisID: "y",
          backgroundColor: labels.map((_, i) => (i === highlightIdx ? "#E4573F" : "#C9DE3B")) },
        { label: "Avg sleep (hrs)", data: sleep, unit: " hrs", decimals: 1, yAxisID: "y1",
          backgroundColor: labels.map((_, i) => (i === highlightIdx ? "#E4573F" : "#14201A")) },
      ],
    },
    options: {
      scales: {
        y: { type: "linear", position: "left", title: { display: true, text: "GPA" } },
        y1: { type: "linear", position: "right", title: { display: true, text: "Sleep hrs" }, grid: { drawOnChartArea: false } },
      },
      onClick: (i) => renderExplorer(data, i * 1 + 0.5, true),
      tooltipExtra: (i) => [`${fmtNum(counts[i])} users in this bucket${i === highlightIdx ? " \u2014 your bucket" : ""}`, "Click to explore this range"],
    },
  });
}

// ---- what-if explorer: hours -> the closest 1-hour bucket in activity_curve ----
function curveRowFor(data, hours) {
  const curve = data.activity_curve;
  const capped = Math.max(0, Math.min(curve[curve.length - 1].from_hr, Math.floor(hours)));
  return curve.find((r) => r.from_hr === capped) || curve[curve.length - 1];
}

function renderExplorer(data, hours, fromChartClick = false) {
  const range = $("#explorer-range");
  if (fromChartClick) range.value = Math.min(10, Math.round(hours * 2) / 2);
  const h = Number(range.value);
  $("#explorer-hours").textContent = h.toFixed(1);
  const row = curveRowFor(data, h);
  const you = data.your_stats;
  const compareToYou = you ? h - you.avg_daily_activity_hours : null;
  $("#explorer-result").innerHTML = `
    <div class="explorer-stats">
      <div class="ex-stat"><b>${row.avg_gpa}</b><span>avg GPA</span></div>
      <div class="ex-stat"><b>${row.avg_sleep} hrs</b><span>avg sleep</span></div>
      <div class="ex-stat"><b>${row.avg_study} hrs</b><span>avg study</span></div>
      <div class="ex-stat"><b>${row.pct_high_stress}%</b><span>report high stress</span></div>
    </div>
    <p class="form-hint" style="margin-top:10px;">Based on ${fmtNum(row.count)} surveyed users who log about ${row.label} hrs/day.
      ${compareToYou !== null ? `That's ${Math.abs(compareToYou).toFixed(1)} hrs ${compareToYou >= 0 ? "more" : "less"} than your own average.` : ""}</p>
  `;
}

function initInsightsControls() {
  const range = $("#explorer-range");
  range.addEventListener("input", () => { if (insightsData) renderExplorer(insightsData, Number(range.value)); });
  $("#explorer-me").addEventListener("click", () => {
    if (!insightsData || !insightsData.your_stats) { showToast("Log a few activities first."); return; }
    range.value = Math.min(10, Math.round(insightsData.your_stats.avg_daily_activity_hours * 2) / 2);
    renderExplorer(insightsData, Number(range.value));
  });
  $("#explorer-avg").addEventListener("click", () => {
    if (!insightsData) return;
    range.value = Math.min(10, Math.round(insightsData.overall_avg_activity_hours * 2) / 2);
    renderExplorer(insightsData, Number(range.value));
  });
}

function renderDailyChart(data) {
  const you = data.your_stats;
  const panel = $("#insights-daily-chart").closest(".panel");
  if (!you) { showChartFallback(resetChart("insights-daily-chart"), "Log a few activities and your last 14 days show up here."); return; }
  const days = you.daily;
  renderChart("insights-daily-chart", {
    type: "bar",
    data: {
      labels: days.map((d) => `${d.weekday} ${shortDate(d.date)}`),
      shortLabels: days.map((d) => d.weekday[0]),
      datasets: [
        { label: "Minutes", data: days.map((d) => d.minutes), unit: " min", backgroundColor: "#C9DE3B" },
        { type: "line", label: "Calories burned", data: days.map((d) => d.kcal), unit: " kcal", yAxisID: "y1", borderColor: "#E4573F", pointRadius: 3 },
      ],
    },
    options: {
      scales: {
        y: { beginAtZero: true, title: { display: true, text: "Minutes" } },
        y1: { position: "right", title: { display: true, text: "kcal" }, grid: { drawOnChartArea: false } },
      },
      tooltipExtra: (i) => [days[i].sessions ? `${days[i].sessions} session(s)` : "No activity logged"],
    },
  });
}

function renderMixChart(data) {
  const you = data.your_stats;
  if (!you || !you.activity_mix.length) { showChartFallback(resetChart("insights-mix-chart"), "Log a few activities to see your mix."); return; }
  const mix = you.activity_mix;
  renderChart("insights-mix-chart", {
    type: "doughnut",
    data: {
      labels: mix.map((m) => m.activity),
      datasets: [{ data: mix.map((m) => m.minutes), unit: " min", backgroundColor: mix.map((m) => typeColor(m.activity)) }],
    },
    options: { centerLabel: "minutes logged" },
  });
}

function renderStressChart(data) {
  const labels = data.stress_by_bucket.map((r) => r.Activity_Bucket);
  const highlightIdx = data.your_stats ? labels.indexOf(data.your_stats.activity_bucket) : -1;
  renderChart("insights-stress-chart", {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Low stress", data: data.stress_by_bucket.map((r) => r.low), unit: "%", decimals: 1, backgroundColor: "#9AAE20" },
        { label: "Moderate", data: data.stress_by_bucket.map((r) => r.moderate), unit: "%", decimals: 1, backgroundColor: "#F0B429" },
        { label: "High stress", data: data.stress_by_bucket.map((r) => r.high), unit: "%", decimals: 1, backgroundColor: "#E4573F" },
      ],
    },
    options: {
      scales: { y: { beginAtZero: true, title: { display: true, text: "% of users" } } },
      highlightIndex: highlightIdx,
    },
  });
}

function renderWeekdayChart(data) {
  const you = data.your_stats;
  if (!you) { showChartFallback(resetChart("insights-weekday-chart"), "Log a few activities to see your weekday pattern."); return; }
  const rows = you.weekday_pattern;
  renderChart("insights-weekday-chart", {
    type: "bar",
    data: {
      labels: rows.map((r) => r.day),
      datasets: [{ label: "Minutes logged", data: rows.map((r) => r.minutes), unit: " min", backgroundColor: "#3F5A34" }],
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, title: { display: true, text: "Minutes" } } } },
  });
}

function renderInsightsStrip(data) {
  $("#insights-strip").innerHTML = `
    <div class="stat-line"><span>Users surveyed</span><b>${fmtNum(data.sample_size)}</b></div>
    <div class="stat-line"><span>Avg physical activity / day</span><b>${data.overall_avg_activity_hours} hrs</b></div>
    <div class="stat-line"><span>Correlation: activity \u2194 GPA</span><b>${data.correlation_activity_gpa}</b></div>
    <div class="stat-line"><span>Correlation: activity \u2194 sleep</span><b>${data.correlation_activity_sleep}</b></div>
  `;
}

function renderInsightsText(data) {
  $("#insights-text").innerHTML = `
    <p>
      In this self-reported dataset, users logging 3+ hours of daily physical activity show
      slightly lower average GPA and sleep than those logging under an hour \u2014 most likely a
      time-budget trade-off (more activity hours leaves less time for sleep and study on a fixed
      24-hour day), not evidence that exercise itself hurts grades.
    </p>
    <p>
      Stress tells a different story: users reporting <b>low</b> stress average the most
      physical activity per day, and those reporting <b>high</b> stress average the least \u2014
      consistent with moderate, sustainable activity supporting lower stress, rather than
      maximizing hours at the expense of everything else.
    </p>
  `;
}

function renderPersonalInsight(data) {
  const box = $("#insights-personal");
  const you = data.your_stats;
  if (!you) {
    box.innerHTML = `<p class="empty-note">Log a few activities on the Dashboard and this section will show how your own habits compare to the ${fmtNum(data.sample_size)}-user survey.</p>`;
    return;
  }
  const bucketRow = data.activity_vs_outcomes.find((r) => r.Activity_Bucket === you.activity_bucket);
  const stressRow = data.activity_by_stress.find((r) => r.stress_level === you.mapped_stress_level);
  box.innerHTML = `
    <div class="personal-insight-box">
      Across <b>${you.logged_days}</b> logged day(s) (${you.total_sessions} session(s)), you're averaging
      <b>${you.avg_daily_activity_hours} hrs/day</b> of activity \u2014 that puts you in the highlighted
      <b>"${escapeHtml(you.activity_bucket)}"</b> bucket on the chart, where surveyed users average a
      <b>${bucketRow ? bucketRow.avg_gpa : "\u2014"} GPA</b> and <b>${bucketRow ? bucketRow.avg_sleep : "\u2014"} hrs</b> of sleep.
      <br><br>
      Your most logged mood is <b>${escapeHtml(you.dominant_mood)}</b> \u2014 a rough stand-in (not a real measurement) for
      <b>${escapeHtml(you.mapped_stress_level)}</b> reported stress, where surveyed users average
      <b>${stressRow ? stressRow.avg_activity_hours : "\u2014"} hrs/day</b> of activity.
    </div>
  `;
}

// ------------------------------------------------------------- weight / BMI --

async function loadWeight() {
  const dateInput = $("#weight-form [name=date]");
  if (!dateInput.value) dateInput.value = todayIso();
  try {
    const { logs, bmi_history } = await api("/weight/history");
    renderWeightStats(bmi_history);
    renderWeightTable(logs, bmi_history);
    renderBmiChart(bmi_history);
  } catch (err) {
    showToast(err.message);
  }
}

function ordinal(n) {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  const suffix = ["th", "st", "nd", "rd"][n % 10] || "th";
  return `${n}${suffix}`;
}

function bmiCategory(bmi) {
  if (bmi < 18.5) return "Underweight";
  if (bmi < 25) return "Normal";
  if (bmi < 30) return "Overweight";
  return "Obese";
}

function daysBetween(a, b) {
  return Math.round((new Date(b) - new Date(a)) / 86400000);
}

// signed() rounds to whole numbers (fine for kcal); weight deltas need one decimal
// place or a -0.4 kg/week trend reads as a misleading "0".
function signedKg(n) {
  const r = Math.round(n * 10) / 10;
  return (r > 0 ? "+" : r < 0 ? "\u2212" : "") + Math.abs(r).toFixed(1);
}

// Hero stat cards above the log form: current weight/BMI, the healthy-BMI weight
// range for the user's height, and the trend since the first logged entry.
function renderWeightStats(bmiHistory) {
  const row = $("#weight-stat-cards");
  if (!bmiHistory.length) {
    row.innerHTML = `
      <div class="stat-card" style="grid-column:1/-1;">
        <span class="sc-label">No entries yet</span>
        <span class="sc-sub">Log your first weight below to unlock your BMI trend, healthy-range comparison and streak of updates.</span>
      </div>`;
    return;
  }
  const first = bmiHistory[0];
  const last = bmiHistory[bmiHistory.length - 1];
  const cat = bmiCategory(last.bmi);
  const chipClass = `bmi-chip bmi-${cat.toLowerCase()}`;

  const weightDelta = last.weight_kg - first.weight_kg;
  const span = daysBetween(first.date, last.date);
  const weeklyRate = span >= 7 ? weightDelta / (span / 7) : null;
  const deltaClass = weightDelta < -0.05 ? "sc-delta-down" : weightDelta > 0.05 ? "sc-delta-up" : "";
  const trendSub = bmiHistory.length < 2
    ? "Log a second entry to start tracking your trend."
    : `<span class="${deltaClass}">${signedKg(weightDelta)} kg</span> since ${shortDate(first.date)}${weeklyRate !== null ? ` · ~${signedKg(weeklyRate)} kg/week` : ""}`;

  let rangeHtml = `<span class="sc-sub">Log your height on the Predict &amp; Recommend page to see your healthy-weight range.</span>`;
  let rangeValue = "—";
  const heightCm = CURRENT_USER && CURRENT_USER.height_cm;
  if (heightCm) {
    const hM = heightCm / 100;
    const minKg = Math.round(18.5 * hM * hM * 10) / 10;
    const maxKg = Math.round(24.9 * hM * hM * 10) / 10;
    rangeValue = `${minKg}–${maxKg}<small>kg</small>`;
    if (last.weight_kg < minKg) rangeHtml = `<span class="sc-sub">${(minKg - last.weight_kg).toFixed(1)} kg below this range, for your height.</span>`;
    else if (last.weight_kg > maxKg) rangeHtml = `<span class="sc-sub">${(last.weight_kg - maxKg).toFixed(1)} kg above this range, for your height.</span>`;
    else rangeHtml = `<span class="sc-sub">You're within this range for your height.</span>`;
  }

  row.innerHTML = `
    <div class="stat-card">
      <span class="sc-label">Current weight</span>
      <span class="sc-value">${last.weight_kg}<small>kg</small></span>
      <span class="sc-sub">Logged ${shortDate(last.date)}</span>
    </div>
    <div class="stat-card">
      <span class="sc-label">Current BMI</span>
      <span class="sc-value">${last.bmi}</span>
      <span class="${chipClass}">${cat}</span>
    </div>
    <div class="stat-card">
      <span class="sc-label">Healthy range (your height)</span>
      <span class="sc-value">${rangeValue}</span>
      ${rangeHtml}
    </div>
    <div class="stat-card">
      <span class="sc-label">Trend</span>
      <span class="sc-value" style="font-size:22px;">${trendSub}</span>
      <span class="sc-sub">${bmiHistory.length} entr${bmiHistory.length === 1 ? "y" : "ies"} logged</span>
    </div>
  `;
}

function renderWeightTable(logs, bmiHistory) {
  const tbody = $("#weight-table tbody");
  tbody.innerHTML = "";
  $("#weight-empty").classList.toggle("hidden", logs.length > 0);
  const bmiByDate = Object.fromEntries(bmiHistory.map((b) => [b.date, b.bmi]));
  const ascending = [...logs].sort((a, b) => (a.log_date < b.log_date ? -1 : 1));
  const prevByDate = {};
  ascending.forEach((log, i) => { prevByDate[log.log_date] = i > 0 ? ascending[i - 1].weight_kg : null; });
  for (const log of [...logs].reverse()) {
    const prev = prevByDate[log.log_date];
    const delta = prev === null || prev === undefined ? null : Math.round((log.weight_kg - prev) * 10) / 10;
    const deltaHtml = delta === null ? "—"
      : `<span class="${delta < -0.05 ? "sc-delta-down" : delta > 0.05 ? "sc-delta-up" : ""}">${signedKg(delta)} kg</span>`;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(log.log_date)}</td>
      <td>${log.weight_kg} kg</td>
      <td>${deltaHtml}</td>
      <td>${bmiByDate[log.log_date] ?? "—"}</td>
      <td><button class="row-delete" data-id="${log.id}">Delete</button></td>
    `;
    tbody.appendChild(tr);
  }
  $$(".row-delete", tbody).forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api(`/weight/${btn.dataset.id}`, { method: "DELETE" });
        showToast("Weight entry deleted.");
        loadWeight();
      } catch (err) {
        showToast(err.message);
      }
    });
  });
}

function renderBmiChart(bmiHistory) {
  renderChart("bmi-chart", {
    type: "line",
    data: {
      labels: bmiHistory.map((b) => b.date),
      shortLabels: bmiHistory.map((b) => shortDate(b.date)),
      datasets: [
        { label: "BMI", data: bmiHistory.map((b) => b.bmi), decimals: 1, borderColor: "#3F5A34", backgroundColor: "rgba(201,222,59,0.25)", fill: true, tension: 0.35, yAxisID: "y" },
        { label: "Weight (kg)", data: bmiHistory.map((b) => b.weight_kg), unit: " kg", decimals: 1, borderColor: "#14201A", borderDash: [5, 4], tension: 0.35, yAxisID: "y1" },
      ],
    },
    options: {
      scales: {
        y: { type: "linear", position: "left", title: { display: true, text: "BMI" } },
        y1: { type: "linear", position: "right", title: { display: true, text: "kg" }, grid: { drawOnChartArea: false } },
      },
    },
  });
}

async function handleWeightSubmit(e) {
  e.preventDefault();
  const form = e.target;
  const errBox = $("#weight-error");
  errBox.textContent = "";
  try {
    const payload = { date: form.date.value, weight_kg: form.weight_kg.value };
    const { updated } = await api("/weight", { method: "POST", body: JSON.stringify(payload) });
    showToast(updated ? "Weight for that date updated." : "Weight saved.");
    form.weight_kg.value = "";
    loadWeight();
    // keep the sidebar BMI line (and cached profile) in sync with the newest weight
    await syncCrossSectionState();
  } catch (err) {
    errBox.textContent = err.message;
  }
}

// ------------------------------------------------------------- leaderboard --
let leaderboardPeriod = "week";
let leaderboardData = null;
let leaderboardSearch = "";

const PERIOD_LABEL = { week: "7-day", month: "30-day", all: "all-time" };
const MEDAL_LABEL = { 1: "1st", 2: "2nd", 3: "3rd" };

function initLeaderboardToggle() {
  $$("#lb-period .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      leaderboardPeriod = btn.dataset.period;
      $$("#lb-period .seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
      loadLeaderboard();
    });
  });
  $("#lb-search").addEventListener("input", (e) => {
    leaderboardSearch = e.target.value.trim().toLowerCase();
    if (leaderboardData) renderLeaderboardTable(leaderboardData);
  });
}

async function loadLeaderboard() {
  try {
    leaderboardData = await api(`/leaderboard?period=${leaderboardPeriod}`);
  } catch (err) {
    showToast(err.message);
    return;
  }
  const data = leaderboardData;
  try { renderLeaderboardCommunity(data); } catch (err) { console.error(err); }
  try { renderLeaderboardPodium(data); } catch (err) { console.error(err); }
  try { renderLeaderboardChart(data); } catch (err) { console.error(err); }
  try { renderLeaderboardTable(data); } catch (err) { console.error(err); }
}

function renderLeaderboardCommunity(data) {
  const c = data.community;
  const label = PERIOD_LABEL[data.period];
  const cards = [
    { label: "Users on board", value: fmtNum(c.participants), sub: `${c.active_participants} active ${label}` },
    { label: "Community kcal burned", value: fmtNum(c.total_calories), sub: `${label}, all users combined` },
    { label: "Sessions logged", value: fmtNum(c.total_sessions), sub: label },
    { label: "Avg active streak", value: `${c.avg_streak} day${c.avg_streak === 1 ? "" : "s"}`, sub: "among active users" },
  ];
  if (c.top_activity) cards.push({ label: "Most popular activity", value: c.top_activity, sub: "by calories, this board" });
  $("#lb-community").innerHTML = cards.map((card, i) => `
    <div class="lb-stat" style="--i:${i}"><span class="lb-stat-label">${escapeHtml(card.label)}</span><b class="lb-stat-num" data-val="${escapeHtml(String(card.value))}">0</b><span class="lb-stat-sub">${escapeHtml(card.sub)}</span></div>
  `).join("");
  $$("#lb-community .lb-stat-num").forEach((el) => {
    const raw = el.dataset.val;
    const num = Number(raw.replace(/,/g, ""));
    if (isFinite(num) && String(num) !== "" && /^[\d,]+$/.test(raw)) countUp(el, num);
    else el.textContent = raw;
  });
}

function initials(name) {
  const parts = name.trim().split(/\s+/);
  return ((parts[0] || "?")[0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}

function renderLeaderboardPodium(data) {
  const box = $("#lb-podium");
  const top3 = data.leaderboard.slice(0, 3).filter((r) => r.sessions > 0 || data.period === "all");
  if (!top3.length) { box.innerHTML = ""; box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const order = [1, 0, 2].filter((i) => top3[i]);   // 2nd, 1st, 3rd, for the classic podium layout
  box.innerHTML = order.map((i) => {
    const r = top3[i];
    const you = data.your_row && r.user_id === data.your_row.user_id;
    const trend = r.trend_pct === null || r.trend_pct === undefined ? "" :
      `<span class="lb-trend ${r.trend_pct >= 0 ? "up" : "down"}">${r.trend_pct >= 0 ? "\u25b2" : "\u25bc"} ${Math.abs(r.trend_pct)}%</span>`;
    return `
    <div class="podium-card rank-${r.rank} ${you ? "is-you" : ""}">
      <span class="podium-medal">${MEDAL_LABEL[r.rank]}</span>
      <span class="podium-avatar">${escapeHtml(initials(r.name))}</span>
      <span class="podium-name">${escapeHtml(r.name)}${you ? ' <span class="you-badge">YOU</span>' : ""}</span>
      <span class="podium-kcal" data-val="${r.total_calories}">0</span>
      <span class="podium-kcal-unit">kcal ${trend}</span>
      <span class="podium-sub">${escapeHtml(r.favorite_activity || "\u2014")} \u00b7 ${r.sessions} session${r.sessions === 1 ? "" : "s"} \u00b7 ${r.streak}-day streak</span>
    </div>`;
  }).join("");
  $$("#lb-podium .podium-kcal").forEach((el) => countUp(el, Number(el.dataset.val)));
}

function renderLeaderboardChart(data) {
  const rows = data.leaderboard.slice(0, 10);
  const sub = $("#lb-chart-sub"), hint = $("#lb-chart-hint");
  sub.textContent = data.period === "all" ? "All-time totals" : `Totals for the last ${data.period === "week" ? "7" : "30"} days`;
  if (!rows.length) { showChartFallback(resetChart("leaderboard-chart"), "No one has logged activity in this period yet \u2014 be the first!"); hint.textContent = ""; return; }

  const yourIdx = data.your_row ? rows.findIndex((r) => r.user_id === data.your_row.user_id) : -1;
  const b = data.benchmark;
  const datasets = [{
    label: "kcal burned", data: rows.map((r) => r.total_calories), unit: " kcal",
    backgroundColor: rows.map((r, i) => (i === yourIdx ? "#E4573F" : i < 3 ? "#9AAE20" : "#3F5A34")),
    legendColor: "#3F5A34",
  }];
  if (b) {
    datasets.push({
      type: "line", label: `Typical active person (${b.age_bracket})`, data: rows.map(() => b.weekly_kcal),
      unit: " kcal", borderColor: "#14201A", borderDash: [5, 4], borderWidth: 2, pointRadius: 0,
    });
    hint.textContent = `Dashed line: roughly what someone in the ${b.age_bracket} age bracket burns through exercise in a typical ${data.period === "week" ? "week" : "30 days"} (${b.avg_exercise_hrs_per_week} hrs/week \u00d7 ~${b.kcal_per_min} kcal/min), from real survey + gym-session data \u2014 a reference point, not a target.`;
  } else {
    hint.textContent = "Click a bar to jump to that user in the table below.";
  }

  renderChart("leaderboard-chart", {
    type: "bar",
    data: {
      labels: rows.map((r) => r.name), shortLabels: rows.map((r) => (r.name.length > 10 ? r.name.slice(0, 9) + "\u2026" : r.name)),
      datasets,
    },
    options: {
      indexAxis: "y",
      plugins: { legend: { display: !!b } },
      scales: { x: { beginAtZero: true, title: { display: true, text: "kcal" } } },
      onClick: (i) => highlightLeaderboardRow(rows[i].user_id),
      tooltipExtra: (i) => [
        `${rows[i].sessions} session(s) \u00b7 ${rows[i].favorite_activity || "no activity yet"}`,
        rows[i].user_id === (data.your_row && data.your_row.user_id) ? "That's you \u2014 click to jump to your row" : "Click to jump to this row",
      ],
    },
  });
}

function highlightLeaderboardRow(userId) {
  const row = $(`#leaderboard-table tr[data-user-id="${userId}"]`);
  if (!row) return;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  row.classList.add("lb-flash");
  setTimeout(() => row.classList.remove("lb-flash"), 1200);
}

function renderLeaderboardTable(data) {
  const tbody = $("#leaderboard-table tbody");
  const rankNote = $("#your-rank-note");
  const label = PERIOD_LABEL[data.period];
  rankNote.textContent = data.your_rank
    ? `Your current rank in this ${label} board: #${data.your_rank}${data.your_row && data.your_row.trend_pct !== null && data.your_row.trend_pct !== undefined ? ` (${data.your_row.trend_pct >= 0 ? "up" : "down"} ${Math.abs(data.your_row.trend_pct)}% vs. the period before)` : ""}`
    : "You are not ranked in this period yet \u2014 log an activity to join the board.";

  const rows = data.leaderboard.filter((r) => !leaderboardSearch || r.name.toLowerCase().includes(leaderboardSearch));
  if (data.leaderboard.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-note">No logged activity in this period yet \u2014 be the first!</td></tr>`;
    return;
  }
  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-note">No user matches "${escapeHtml(leaderboardSearch)}".</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((r) => {
    const you = data.your_row && r.user_id === data.your_row.user_id;
    const trend = r.trend_pct === null || r.trend_pct === undefined ? "" :
      `<span class="lb-trend ${r.trend_pct >= 0 ? "up" : "down"}">${r.trend_pct >= 0 ? "\u25b2" : "\u25bc"}${Math.abs(r.trend_pct)}%</span>`;
    return `
    <tr data-user-id="${r.user_id}" class="${you ? "is-you" : ""}">
      <td>${r.rank <= 3 ? `<span class="rank-badge rank-${r.rank}">${r.rank}</span>` : r.rank}</td>
      <td>
        <span class="lb-athlete"><span class="lb-avatar">${escapeHtml(initials(r.name))}</span>
          <span><span class="lb-name">${escapeHtml(r.name)}${you ? ' <span class="you-badge">YOU</span>' : ""}</span>
          <span class="lb-sub">${escapeHtml(r.favorite_activity || "No activity logged")}</span></span></span>
      </td>
      <td><b>${fmtNum(Math.round(r.total_calories))}</b> ${trend}</td>
      <td>${r.sessions ? fmtNum(r.avg_kcal_per_session) : "\u2014"}</td>
      <td>${r.sessions}</td>
      <td>${r.streak}</td>
    </tr>
  `;
  }).join("");
}

// -------------------------------------------------------------------- init --
async function checkExistingSession() {
  try {
    const { user } = await api("/me");
    onAuthenticated(user);
  } catch {
    // not logged in — show auth screen (default state)
  }
}

function setDefaultDate() {
  const input = $("#activity-form [name=date]");
  input.value = todayIso();
}

document.addEventListener("DOMContentLoaded", () => {
  fetch("/api/health").catch(() => {}); // wakes a sleeping free-tier backend while the user reads the login screen
  initAuthTabs();
  initNav();
  initLibraryControls();
  initFoodCombobox();
  initMyFoodsControls();
  loadAppConfig().catch(() => {});
  setDefaultDate();

  $("#login-form").addEventListener("submit", handleLogin);
  $("#register-form").addEventListener("submit", handleRegister);
  $("#logout-btn").addEventListener("click", handleLogout);
  $("#activity-form").addEventListener("submit", handleActivitySubmit);
  $("#predict-form").addEventListener("submit", handlePredictSubmit);
  $("#benchmark-form").addEventListener("submit", handleBenchmarkSubmit);
  $("#food-form").addEventListener("submit", handleFoodSubmit);
  $("#weight-form").addEventListener("submit", handleWeightSubmit);
  $("#goal-select").addEventListener("change", handleGoalChange);
  initLeaderboardToggle();
  initDayNav();
  initInsightsControls();
  ["activity_type", "duration_min", "mood"].forEach((name) => {
    $(`#activity-form [name=${name}]`).addEventListener("input", refreshCalorieEstimate);
    $(`#activity-form [name=${name}]`).addEventListener("change", refreshCalorieEstimate);
  });
  ["age", "gender", "height_cm", "weight_kg"].forEach((name) => {
    $(`#predict-form [name=${name}]`).addEventListener("input", refreshFatEstimate);
    $(`#predict-form [name=${name}]`).addEventListener("change", refreshFatEstimate);
  });

  checkExistingSession();
});
