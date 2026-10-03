// Login screen: embers drifting up from the flame logo. Purely decorative.
// Pauses while the login screen is hidden (logged in) and honours reduced-motion.
(function () {
  const screen = document.getElementById("auth-screen");
  const canvas = document.getElementById("embers");
  const flame = document.getElementById("hero-flame");
  if (!screen || !canvas || !flame) return;

  const ctx = canvas.getContext("2d");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  const COLORS = ["255,210,63", "255,138,0", "255,61,104"];
  const MAX_PARTICLES = 48;
  let w = 0, h = 0, raf = 0, running = false;
  const parts = [];

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const r = canvas.getBoundingClientRect();
    w = r.width; h = r.height;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function origin() {
    const c = canvas.getBoundingClientRect();
    const f = flame.getBoundingClientRect();
    return { x: f.left - c.left + f.width * 0.5, y: f.top - c.top + f.height * 0.42, spread: f.width * 0.16 };
  }

  function spawn() {
    const o = origin();
    parts.push({
      x: o.x + (Math.random() - 0.5) * o.spread * 2,
      y: o.y + Math.random() * 10,
      vx: (Math.random() - 0.5) * 0.3,
      vy: -(0.35 + Math.random() * 0.9),
      r: 1.2 + Math.random() * 2.4,
      life: 1,
      decay: 0.004 + Math.random() * 0.006,
      c: COLORS[(Math.random() * COLORS.length) | 0],
      ph: Math.random() * 6.283,
    });
  }

  function frame() {
    if (screen.classList.contains("hidden")) { running = false; return; }
    ctx.clearRect(0, 0, w, h);
    if (parts.length < MAX_PARTICLES && Math.random() < 0.35) spawn();
    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i];
      p.ph += 0.04;
      p.x += p.vx + Math.sin(p.ph) * 0.25;
      p.y += p.vy;
      p.life -= p.decay;
      if (p.life <= 0 || p.y < -10) { parts.splice(i, 1); continue; }
      ctx.fillStyle = "rgba(" + p.c + "," + (p.life * 0.95).toFixed(3) + ")";
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r * (0.5 + p.life * 0.5), 0, 6.283);
      ctx.fill();
    }
    raf = requestAnimationFrame(frame);
  }

  function start() {
    if (running || reduce.matches || screen.classList.contains("hidden")) return;
    running = true;
    resize();
    raf = requestAnimationFrame(frame);
  }

  function stop() {
    cancelAnimationFrame(raf);
    running = false;
    ctx.clearRect(0, 0, w, h);
  }

  // resume when the login screen comes back (after logging out)
  new MutationObserver(start).observe(screen, { attributes: true, attributeFilter: ["class"] });
  window.addEventListener("resize", () => { if (running) resize(); });
  reduce.addEventListener("change", () => (reduce.matches ? stop() : start()));
  start();
})();
