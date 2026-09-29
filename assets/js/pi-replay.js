// hugo-pi-replay: animated replay of a condensed Pi (coding-agent) session.
//
// Adapted from earendil-works/website _static/script.js (PiReplay player),
// https://github.com/earendil-works/website — Apache License 2.0.
// Changes for this module: shipped standalone, and it boots on
// DOMContentLoaded instead of relying on an htmx event. See NOTICE.


// Replay a condensed Pi session in a terminal-like panel, the way Pi's TUI
// draws it: the prompt is typed into the editor, the codemode script streams
// in, its nested tool calls tick through, and the answer follows. The figure
// carries a plain-text transcript that stays in place without JavaScript and
// in feeds; the replay data comes from the JSON file named by the attribute.
(function() {
  var SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
  var CALL_PREVIEW_COUNT = 8;
  var CANCELLED = {};
  var replayObserver = null;

  function node(tag, className, text) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = text;
    return element;
  }

  function formatDuration(ms) {
    return ms < 1000 ? Math.round(ms) + 'ms' : (ms / 1000).toFixed(1) + 's';
  }

  function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function PiReplay(figure, data) {
    this.figure = figure;
    this.data = data;
    this.run = 0;
    this.spinnerTimer = null;
    this.followOutput = true;
    this.scriptLength = data.script.reduce(function(sum, token) {
      return sum + token[1].length;
    }, 0);
    this.build();
  }

  PiReplay.prototype.build = function() {
    var self = this;
    var root = node('div', 'pi-replay__terminal');
    root.setAttribute('aria-hidden', 'true');

    this.chat = node('div', 'pi-replay__chat');
    this.status = node('div', 'pi-replay__status');
    this.statusSpinner = node('span', 'pi-replay__spinner');
    this.status.appendChild(this.statusSpinner);
    this.status.appendChild(node('span', 'pi-replay__muted', ' Working... (esc to abort)'));

    var editor = node('div', 'pi-replay__editor');
    this.editorText = node('span', 'pi-replay__editor-text');
    editor.appendChild(this.editorText);
    editor.appendChild(node('span', 'pi-replay__cursor', ' '));

    var footer = node('div', 'pi-replay__footer');
    footer.appendChild(node('span', null, this.data.cwd));
    footer.appendChild(node('span', null, this.data.model));

    root.appendChild(this.chat);
    root.appendChild(this.status);
    root.appendChild(editor);
    root.appendChild(footer);

    this.button = node('button', 'pi-replay__button', 'Skip');
    this.button.type = 'button';
    this.button.addEventListener('click', function() {
      if (self.playing) {
        self.showFinal();
      } else {
        self.play();
      }
    });

    this.chat.addEventListener('scroll', function() {
      var distance = self.chat.scrollHeight - self.chat.scrollTop - self.chat.clientHeight;
      self.followOutput = distance < 24;
    }, { passive: true });

    var fallback = this.figure.querySelector('.pi-replay__fallback');
    if (fallback) fallback.hidden = true;
    var caption = this.figure.querySelector('figcaption');
    this.figure.insertBefore(root, caption || null);
    (caption || this.figure).appendChild(this.button);
    this.figure.classList.add('is-ready');
  };

  PiReplay.prototype.scrollToEnd = function() {
    if (this.followOutput) this.chat.scrollTop = this.chat.scrollHeight;
  };

  PiReplay.prototype.setWorking = function(isWorking) {
    var self = this;
    this.status.classList.toggle('is-active', isWorking);
    clearInterval(this.spinnerTimer);
    this.spinnerTimer = null;
    if (!isWorking) return;
    var frame = 0;
    this.statusSpinner.textContent = SPINNER[0];
    this.spinnerTimer = setInterval(function() {
      if (!self.figure.isConnected) {
        self.run++;
        self.setWorking(false);
        return;
      }
      frame = (frame + 1) % SPINNER.length;
      self.statusSpinner.textContent = SPINNER[frame];
    }, 80);
  };

  // Waits unless a newer run (replay or skip) has started in the meantime.
  PiReplay.prototype.wait = function(run, ms) {
    var self = this;
    return new Promise(function(resolve, reject) {
      setTimeout(function() {
        if (run === self.run) resolve(); else reject(CANCELLED);
      }, ms);
    });
  };

  PiReplay.prototype.frame = function(run) {
    var self = this;
    return new Promise(function(resolve, reject) {
      window.requestAnimationFrame(function(now) {
        if (run === self.run) resolve(now); else reject(CANCELLED);
      });
    });
  };

  PiReplay.prototype.reset = function() {
    this.chat.textContent = '';
    this.editorText.textContent = '';
    this.followOutput = true;
    this.tool = null;
    this.setWorking(false);
  };

  PiReplay.prototype.addUser = function() {
    this.chat.appendChild(node('div', 'pi-replay__user', this.data.prompt));
  };

  PiReplay.prototype.addIntro = function() {
    var intro = node('div', 'pi-replay__assistant');
    this.chat.appendChild(intro);
    return intro;
  };

  PiReplay.prototype.addTool = function() {
    var box = node('div', 'pi-replay__tool is-pending');
    box.appendChild(node('div', 'pi-replay__tool-title', 'codemode'));
    var code = node('pre', 'pi-replay__code');
    var calls = node('div', 'pi-replay__calls');
    var output = node('pre', 'pi-replay__output');
    calls.hidden = true;
    output.hidden = true;
    box.appendChild(code);
    box.appendChild(calls);
    box.appendChild(output);
    this.chat.appendChild(box);
    this.tool = { box: box, code: code, calls: calls, output: output };
  };

  // Streams the highlighted script up to `count` characters.
  PiReplay.prototype.renderScript = function(count) {
    var code = this.tool.code;
    code.textContent = '';
    var remaining = count;
    for (var i = 0; i < this.data.script.length && remaining > 0; i++) {
      var token = this.data.script[i];
      var text = token[1].length > remaining ? token[1].slice(0, remaining) : token[1];
      remaining -= text.length;
      if (token[0]) {
        code.appendChild(node('span', 'pi-replay__syn-' + token[0], text));
      } else {
        code.appendChild(document.createTextNode(text));
      }
    }
  };

  // Mirrors the codemode renderer: the most recent nested calls with their
  // status, and a count of the earlier ones that scrolled out.
  PiReplay.prototype.renderCalls = function(simTime) {
    var calls = this.data.calls;
    var started = 0;
    while (started < calls.length && calls[started].t <= simTime) started++;
    var container = this.tool.calls;
    container.hidden = started === 0;
    container.textContent = '';
    var first = Math.max(0, started - CALL_PREVIEW_COUNT);
    if (first > 0) {
      container.appendChild(node('div', 'pi-replay__muted',
        '... (' + first + ' earlier calls, ctrl+o to expand)'));
    }
    for (var i = first; i < started; i++) {
      var call = calls[i];
      var done = simTime >= call.t + call.d;
      var line = node('div', 'pi-replay__call');
      line.appendChild(node('span', done ? 'pi-replay__ok' : 'pi-replay__running', done ? '✓' : '…'));
      line.appendChild(document.createTextNode(' ' + call.name + ' '));
      line.appendChild(node('span', 'pi-replay__muted', call.args));
      if (done) line.appendChild(node('span', 'pi-replay__dim', ' ' + formatDuration(call.d)));
      container.appendChild(line);
    }
  };

  PiReplay.prototype.finishTool = function() {
    this.tool.box.classList.remove('is-pending');
    this.tool.box.classList.add('is-success');
    this.tool.output.hidden = false;
    this.tool.output.textContent = this.data.output;
  };

  PiReplay.prototype.addAnswer = function() {
    var answer = node('div', 'pi-replay__assistant pi-replay__answer');
    this.chat.appendChild(answer);
    return answer;
  };

  // Answer blocks are authored markup from the replay JSON, not session text.
  PiReplay.prototype.answerBlock = function(block) {
    var element;
    if (block[0] === 'ul') {
      element = node('ul');
      block[1].forEach(function(item) {
        var li = node('li');
        li.innerHTML = item;
        element.appendChild(li);
      });
    } else {
      element = node('p');
      element.innerHTML = block[1];
    }
    return element;
  };

  PiReplay.prototype.showFinal = function() {
    this.run++;
    this.playing = false;
    this.reset();
    this.addUser();
    this.addIntro().textContent = this.data.intro;
    this.addTool();
    this.renderScript(this.scriptLength);
    this.renderCalls(Infinity);
    this.finishTool();
    var answer = this.addAnswer();
    var self = this;
    this.data.answer.forEach(function(block) {
      answer.appendChild(self.answerBlock(block));
    });
    this.button.textContent = 'Replay';
    this.chat.scrollTop = 0;
  };

  PiReplay.prototype.play = function() {
    var self = this;
    var run = ++this.run;
    this.playing = true;
    this.button.textContent = 'Skip';
    this.reset();
    this.sequence(run).then(function() {
      if (run !== self.run) return;
      self.playing = false;
      self.button.textContent = 'Replay';
    }, function(error) {
      if (error !== CANCELLED) throw error;
    });
  };

  PiReplay.prototype.sequence = async function(run) {
    var data = this.data;
    var i;

    await this.wait(run, 500);
    for (i = 1; i <= data.prompt.length; i++) {
      this.editorText.textContent = data.prompt.slice(0, i);
      await this.wait(run, 18 + (data.prompt[i - 1] === ' ' ? 30 : 0));
    }
    await this.wait(run, 450);
    this.editorText.textContent = '';
    this.addUser();
    this.setWorking(true);
    this.scrollToEnd();

    await this.wait(run, 900);
    var intro = this.addIntro();
    var words = data.intro.split(' ');
    for (i = 1; i <= words.length; i++) {
      intro.textContent = words.slice(0, i).join(' ');
      this.scrollToEnd();
      await this.wait(run, 35);
    }

    await this.wait(run, 400);
    this.addTool();
    var start = await this.frame(run);
    var shown = 0;
    while (shown < this.scriptLength) {
      var now = await this.frame(run);
      shown = Math.min(this.scriptLength, Math.round((now - start) * 0.9));
      this.renderScript(shown);
      this.scrollToEnd();
    }

    // Play the nested calls in simulated time: close to real time at first
    // so the individual calls are readable, then fast-forward.
    await this.wait(run, 300);
    var simTime = 0;
    var last = await this.frame(run);
    var elapsed = 0;
    while (simTime < data.wallMs) {
      var frameTime = await this.frame(run);
      var delta = Math.min(frameTime - last, 50);
      last = frameTime;
      elapsed += delta;
      simTime += delta * Math.min(24, 1 + elapsed / 160);
      this.renderCalls(Math.min(simTime, data.wallMs));
      this.scrollToEnd();
    }

    await this.wait(run, 250);
    this.finishTool();
    this.scrollToEnd();

    await this.wait(run, 900);
    var answer = this.addAnswer();
    for (i = 0; i < data.answer.length; i++) {
      answer.appendChild(this.answerBlock(data.answer[i]));
      this.scrollToEnd();
      await this.wait(run, 320);
    }
    this.setWorking(false);
  };

  function startReplay(figure) {
    var replay = figure.__piReplay;
    if (!replay || replay.started) return;
    replay.started = true;
    if (replayObserver) replayObserver.unobserve(figure);
    if (prefersReducedMotion()) {
      replay.showFinal();
    } else {
      replay.play();
    }
  }

  function getReplayObserver() {
    if (replayObserver || typeof IntersectionObserver !== 'function') return replayObserver;
    replayObserver = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) startReplay(entry.target);
      });
    }, { threshold: 0.45 });
    return replayObserver;
  }

  function initPiReplays() {
    document.querySelectorAll('[data-pi-replay]').forEach(function(figure) {
      if (figure.dataset.replayInitialized) return;
      figure.dataset.replayInitialized = 'true';
      fetch(figure.getAttribute('data-pi-replay'))
        .then(function(response) {
          if (!response.ok) throw new Error('HTTP ' + response.status);
          return response.json();
        })
        .then(function(data) {
          if (!figure.isConnected) return;
          figure.__piReplay = new PiReplay(figure, data);
          var observer = getReplayObserver();
          if (observer) observer.observe(figure); else startReplay(figure);
        })
        .catch(function() {
          // Keep the static transcript.
        });
    });
  }

  function boot() {
    initPiReplays();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
