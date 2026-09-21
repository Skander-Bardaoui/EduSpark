/* ------------------------------------------------------------------
   Hero video: seamless loop with a smooth crossfade to black.
   The video has no `loop` attribute on purpose — we restart it
   manually so we can fade out before it ends and fade back in.
   ------------------------------------------------------------------ */
(function heroVideoFade() {
  var video = document.getElementById('hero-video');
  if (!video) return;

  var FADE_MS = 500;
  var FADE_TAIL = 0.55; // start fading out when this many seconds remain
  var frameId = null;
  var hasStarted = false;
  var isFadingOut = false;

  function currentOpacity() {
    var value = parseFloat(window.getComputedStyle(video).opacity);
    return isNaN(value) ? 0 : value;
  }

  function setOpacity(value) {
    video.style.opacity = String(value);
  }

  function animateOpacity(from, to, duration, onDone) {
    if (frameId !== null) {
      window.cancelAnimationFrame(frameId);
      frameId = null;
    }

    var start = null;

    function step(timestamp) {
      if (start === null) start = timestamp;
      var progress = Math.min((timestamp - start) / duration, 1);
      setOpacity(from + (to - from) * progress);

      if (progress < 1) {
        frameId = window.requestAnimationFrame(step);
      } else {
        frameId = null;
        if (typeof onDone === 'function') onDone();
      }
    }

    frameId = window.requestAnimationFrame(step);
  }

  function fadeIn() {
    isFadingOut = false;
    animateOpacity(0, 1, FADE_MS);
  }

  function fadeOut(onDone) {
    isFadingOut = true;
    animateOpacity(currentOpacity(), 0, FADE_MS, onDone);
  }

  video.addEventListener('canplay', function () {
    if (hasStarted) return;
    hasStarted = true;
    video.play().then(fadeIn).catch(function () {
      // Autoplay blocked: leave the poster-less video hidden.
      fadeIn();
    });
  });

  video.addEventListener('timeupdate', function () {
    if (!video.duration || isFadingOut) return;
    var remaining = video.duration - video.currentTime;
    if (remaining <= FADE_TAIL) {
      fadeOut();
    }
  });

  video.addEventListener('ended', function () {
    setOpacity(0);
    window.setTimeout(function () {
      video.currentTime = 0;
      video.play().then(fadeIn).catch(fadeIn);
    }, 100);
  });
})();

/* ------------------------------------------------------------------
   Scroll reveal — replaces framer-motion's useInView(ref,
   { once: true, margin: "-100px" }) + whileInView variants.
   ------------------------------------------------------------------ */
(function scrollReveal() {
  var elements = document.querySelectorAll('.reveal');
  if (!elements.length) return;

  if (!('IntersectionObserver' in window)) {
    elements.forEach(function (el) {
      el.classList.add('is-visible');
    });
    return;
  }

  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    },
    { rootMargin: '-100px', threshold: 0 }
  );

  elements.forEach(function (el) {
    observer.observe(el);
  });
})();

/* ------------------------------------------------------------------
   Background video playback.
   Browsers throttling many concurrent <video> elements can leave the
   section videos paused even though they carry `autoplay`. Force them
   muted + playing, and retry once on the first user gesture for the
   cases where autoplay is blocked outright.
   ------------------------------------------------------------------ */
(function primeVideos() {
  var videos = Array.prototype.slice.call(document.querySelectorAll('video'));
  if (!videos.length) return;

  function play(video) {
    if (!video.paused) return;
    video.muted = true;
    var attempt = video.play();
    if (attempt && typeof attempt.catch === 'function') {
      attempt.catch(function () {});
    }
  }

  function playAll() {
    videos.forEach(play);
  }

  playAll();
  window.addEventListener('load', playAll);

  // Retry whenever a video enters the viewport.
  if ('IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) play(entry.target);
      });
    }, { threshold: 0.1 });
    videos.forEach(function (video) {
      observer.observe(video);
    });
  }

  // And once more on the first interaction, for blocked autoplay.
  ['pointerdown', 'touchstart', 'keydown', 'scroll'].forEach(function (evt) {
    window.addEventListener(evt, playAll, { once: true, passive: true });
  });
})();

/* Email capture — no backend wired up, keep the page from reloading. */
(function newsletterForm() {
  var forms = document.querySelectorAll('[data-newsletter]');
  forms.forEach(function (form) {
    form.addEventListener('submit', function (event) {
      event.preventDefault();
    });
  });
})();
