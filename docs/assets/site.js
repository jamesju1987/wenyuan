/* 文渊 官网：首屏演示 + 导航分隔线 */
(function () {
  var nav = document.getElementById("nav");
  var onScroll = function () { nav.classList.toggle("scrolled", window.scrollY > 8); };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  var demo = document.getElementById("demo");
  if (!demo) return;
  var replay = document.getElementById("replay");
  var q = function (s) { return demo.querySelector(s); };
  // [元素, 出现时间(ms)]
  var plan = [
    [q(".d-in"), 0], [q(".s1"), 550], [q(".s2"), 900], [q(".s3"), 1250], [q(".s4"), 1600], [q(".s5"), 1950],
    [q(".d-out"), 2500], [q(".t0"), 3900], [q(".t1"), 4050], [q(".t2"), 4200], [q(".t3"), 4350], [q(".land"), 4750]
  ];
  var timers = [];
  plan.forEach(function (p) { p[0].classList.add("anim"); });

  function finish() {
    plan.forEach(function (p) { p[0].classList.add("on"); });
    q(".d-in").classList.add("done");
    q(".t3").classList.add("lit");
    replay.hidden = false;
  }
  function play() {
    timers.forEach(clearTimeout);
    timers = [];
    replay.hidden = true;
    q(".d-in").classList.remove("done");
    q(".t3").classList.remove("lit");
    plan.forEach(function (p) { p[0].classList.remove("on"); });
    plan.forEach(function (p) {
      timers.push(setTimeout(function () { p[0].classList.add("on"); }, p[1] + 120));
    });
    timers.push(setTimeout(function () { q(".d-in").classList.add("done"); }, 2600));
    timers.push(setTimeout(function () { q(".t3").classList.add("lit"); }, 4500));
    timers.push(setTimeout(function () { replay.hidden = false; }, 5200));
  }

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || !("IntersectionObserver" in window)) { finish(); }
  else {
    var io = new IntersectionObserver(function (es) {
      if (es[0].isIntersecting) { io.disconnect(); play(); }
    }, { threshold: 0.35 });
    io.observe(demo);
  }
  replay.addEventListener("click", function () { reduce ? finish() : play(); });
})();
