/* 文渊 官网：导航配色 + 首屏演示 */
(function () {
  var nav = document.getElementById("nav");
  var hero = document.getElementById("top");
  if ("IntersectionObserver" in window && hero) {
    new IntersectionObserver(function (es) {
      nav.classList.toggle("light", !es[0].isIntersecting);
    }, { rootMargin: "-68px 0px 0px 0px" }).observe(hero);
  } else {
    nav.classList.add("light");
  }

  var demo = document.getElementById("demo");
  if (!demo) return;
  var replay = document.getElementById("replay");
  var q = function (s) { return demo.querySelector(s); };
  var plan = [
    [q(".d-in"), 0], [q(".s1"), 600], [q(".s2"), 950], [q(".s3"), 1300], [q(".s4"), 1650], [q(".s5"), 2000],
    [q(".d-out"), 2600], [q(".t0"), 4000], [q(".t1"), 4150], [q(".t2"), 4300], [q(".t3"), 4450], [q(".land"), 4850]
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
      timers.push(setTimeout(function () { p[0].classList.add("on"); }, p[1] + 500));
    });
    timers.push(setTimeout(function () { q(".d-in").classList.add("done"); }, 3200));
    timers.push(setTimeout(function () { q(".t3").classList.add("lit"); }, 5000));
    timers.push(setTimeout(function () { replay.hidden = false; }, 5800));
  }

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || !("IntersectionObserver" in window)) { finish(); }
  else {
    var io = new IntersectionObserver(function (es) {
      if (es[0].isIntersecting) { io.disconnect(); play(); }
    }, { threshold: 0.25 });
    io.observe(demo);
  }
  replay.addEventListener("click", function () { reduce ? finish() : play(); });
})();
