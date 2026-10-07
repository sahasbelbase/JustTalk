/**
 * Just Talk — Official Website Interactive Controller
 * Native ES Script: Pure vanilla, zero dependencies, OS auto-detection,
 * 3D mechanical keycap physics, live waveform visualizer, and realistic typing simulation.
 */

(() => {
  'use strict';

  // --- 1. Constants & Download URLs ---
  const MAC_DOWNLOAD_URL = 'https://github.com/sahasbelbase/JustTalk/releases/latest/download/JustTalk-macOS.dmg';
  const WIN_DOWNLOAD_URL = 'https://github.com/sahasbelbase/JustTalk/releases/latest/download/JustTalk-Windows.exe';
  const RELEASES_PAGE_URL = 'https://github.com/sahasbelbase/JustTalk/releases/latest';

  const appleSvgPath = `M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M15.97 6.37c.56-.73.96-1.74.85-2.77-.89.04-1.95.6-2.58 1.34-.54.63-.98 1.65-.85 2.66.98.08 1.98-.51 2.58-1.23z`;
  const winSvgPath = `M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.9-1.801`;

  // --- 2. OS Detection & UI Setup ---
  function detectPlatform() {
    const userAgent = navigator.userAgent || '';
    const platform = (navigator.userAgentData?.platform || navigator.platform || '').toLowerCase();

    // Check mobile first
    if (/android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini/i.test(userAgent)) {
      return 'mobile';
    }

    if (platform.includes('win') || userAgent.includes('Windows')) {
      return 'windows';
    } else if (platform.includes('mac') || userAgent.includes('Macintosh')) {
      return 'mac';
    } else {
      return 'desktop-other';
    }
  }

  const detectedOS = detectPlatform();
  const desktopDownloadBox = document.getElementById('desktop-download-box');
  const mobileNoticeBox = document.getElementById('mobile-notice-box');
  const smartBtn = document.getElementById('smart-download-btn');
  const smartLabel = document.getElementById('smart-btn-label');
  const smartSub = document.getElementById('smart-btn-sub');
  const smartIcon = document.getElementById('smart-btn-icon');
  const keycapLegend = document.getElementById('keycap-legend');

  if (detectedOS === 'mobile') {
    if (desktopDownloadBox) desktopDownloadBox.classList.add('hidden');
    if (mobileNoticeBox) mobileNoticeBox.classList.remove('hidden');

    const copyBtn = document.getElementById('mobile-copy-btn');
    const copyFeedback = document.getElementById('copy-feedback');
    if (copyBtn && copyFeedback) {
      copyBtn.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(window.location.origin + '/#download');
          copyFeedback.classList.remove('hidden');
          setTimeout(() => copyFeedback.classList.add('hidden'), 3000);
        } catch (_) {
          copyFeedback.textContent = 'Visit on desktop: ' + (window.location.host || 'sahasbelbase.github.io/JustTalk');
          copyFeedback.classList.remove('hidden');
        }
      });
    }
  } else if (smartBtn && smartLabel && smartSub && smartIcon) {
    if (detectedOS === 'windows') {
      smartBtn.href = WIN_DOWNLOAD_URL;
      smartLabel.textContent = 'Download for Windows (.exe)';
      smartSub.textContent = 'Windows 10 / 11 64-bit • Standalone Setup';
      smartIcon.innerHTML = `<path d="${winSvgPath}"/>`;
      if (keycapLegend) keycapLegend.textContent = 'alt';
    } else {
      // Default to macOS universal DMG
      smartBtn.href = MAC_DOWNLOAD_URL;
      smartLabel.textContent = 'Download for macOS (.dmg)';
      smartSub.textContent = 'Universal Installer • macOS 12.0+';
      smartIcon.innerHTML = `<path d="${appleSvgPath}"/>`;
      if (keycapLegend) keycapLegend.textContent = 'fn';
    }
  }

  // OS Dropdown Toggle
  const dropdownTrigger = document.getElementById('os-dropdown-trigger');
  const dropdownMenu = document.getElementById('os-dropdown-menu');

  if (dropdownTrigger && dropdownMenu) {
    dropdownTrigger.addEventListener('click', (e) => {
      e.stopPropagation();
      const isExpanded = dropdownTrigger.getAttribute('aria-expanded') === 'true';
      dropdownTrigger.setAttribute('aria-expanded', !isExpanded);
      dropdownMenu.classList.toggle('hidden');
    });

    document.addEventListener('click', (e) => {
      if (!dropdownMenu.contains(e.target) && !dropdownTrigger.contains(e.target)) {
        dropdownMenu.classList.add('hidden');
        dropdownTrigger.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // --- 3. Interactive 3D Keycap & Live HUD Simulation ---
  const keycapBtn = document.getElementById('sim-keycap');
  const playgroundCard = document.getElementById('playground-card');
  const hudPill = document.getElementById('sim-pill');
  const hudBadge = document.getElementById('sim-pill-badge');
  const hudStatus = document.getElementById('sim-pill-status');
  const waveformCanvas = document.getElementById('sim-waveform');
  const typedTextEl = document.getElementById('sim-typed-text');
  const presetButtons = document.querySelectorAll('.preset-btn');
  const behaviorSub = document.getElementById('sim-app-behavior');

  let isRecording = false;
  let isShiftActive = false;
  let isSpaceActive = false;
  let animationFrameId = null;
  let typingTimer = null;
  let currentPreset = 'english';

  const PRESETS = {
    english: {
      raw: 'async def handle_request(client_socket, timeout=5.0):',
      formatted: 'async def handle_request(client_socket: socket.socket, timeout: float = 5.0) -> None:',
      desc: 'Transcribed locally with Faster-Whisper int8. Formatted cleanly with proper Python typing.'
    },
    nepali: {
      raw: 'yo code ma error aayo bro fast check garera fix garnu paryo',
      formatted: 'यो कोडमा त्रुटि आयो, कृपया तुरुन्तै जाँच गरी समाधान गर्नुहोस्।',
      desc: 'Transcribed offline with Kriti, the open Nepali speech model by Naamche Labs.'
    },
    action: {
      raw: 'Action Mode: translate to english: mero laptop ko battery dherai xito sakinxa',
      formatted: 'Action Translation: "My laptop battery drains very quickly."',
      desc: 'Ignited by Shift key. Translates foreign speech directly into English or triggers AI actions.'
    }
  };

  // Preset Button Selection
  presetButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      presetButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentPreset = btn.dataset.preset || 'english';
      if (!isRecording && typedTextEl) {
        typedTextEl.textContent = `Preset selected: "${btn.textContent}". Hold the keycap (or hold Space) to test!`;
      }
    });
  });

  // Waveform Visualizer
  const canvasCtx = waveformCanvas ? waveformCanvas.getContext('2d') : null;
  let waveTick = 0;

  function drawWaveform(isAction) {
    if (!canvasCtx || !waveformCanvas) return;
    const width = waveformCanvas.width;
    const height = waveformCanvas.height;

    canvasCtx.clearRect(0, 0, width, height);

    const barCount = 12;
    const barWidth = 3;
    const spacing = 6;
    const totalWidth = barCount * (barWidth + spacing) - spacing;
    const startX = (width - totalWidth) / 2;

    const primaryColor = isAction ? '#FF9F0A' : '#6C8EEF';

    waveTick += 0.16;

    for (let i = 0; i < barCount; i++) {
      // Natural oscillating voice energy calculation
      const wave = Math.sin(waveTick + i * 0.5) * Math.cos(waveTick * 0.8 + i * 0.3);
      const minH = 3;
      const maxH = height - 2;
      const barH = Math.max(minH, Math.min(maxH, (Math.abs(wave) * 0.85 + 0.15) * height));

      const x = startX + i * (barWidth + spacing);
      const y = (height - barH) / 2;

      canvasCtx.fillStyle = primaryColor;
      canvasCtx.beginPath();
      canvasCtx.roundRect(x, y, barWidth, barH, 2);
      canvasCtx.fill();
    }

    if (isRecording) {
      animationFrameId = requestAnimationFrame(() => drawWaveform(isAction));
    }
  }

  function startRecording(withAction) {
    if (isRecording) return;
    isRecording = true;

    if (typingTimer) clearInterval(typingTimer);

    // Keycap Appearance
    if (keycapBtn) {
      keycapBtn.classList.add('pressed');
      if (withAction) keycapBtn.classList.add('action-mode');
      else keycapBtn.classList.remove('action-mode');
    }

    // HUD Appearance
    if (hudPill) {
      hudPill.classList.remove('pill-hidden');
      hudPill.classList.add('pill-visible');

      if (withAction) {
        hudPill.classList.add('action-active');
        if (hudBadge) hudBadge.innerHTML = `<span style="font-size: 11px; font-weight: 700;">A</span>`;
        if (hudStatus) hudStatus.textContent = 'ACTION MODE';
      } else {
        hudPill.classList.remove('action-active');
        if (hudBadge) hudBadge.innerHTML = `<span class="dot-listening"></span>`;
        if (hudStatus) hudStatus.textContent = 'LISTENING...';
      }
    }

    // Waveform Animation
    if (animationFrameId) cancelAnimationFrame(animationFrameId);
    drawWaveform(withAction);

    // Preview in Buffer
    if (typedTextEl) {
      typedTextEl.textContent = withAction ? '[Action Mode — listening...]' : '[Listening to local audio stream...]';
    }
  }

  function stopRecording() {
    if (!isRecording) return;
    isRecording = false;

    // Release Keycap
    if (keycapBtn) {
      keycapBtn.classList.remove('pressed');
      keycapBtn.classList.remove('action-mode');
    }

    // Stop Waveform
    if (animationFrameId) cancelAnimationFrame(animationFrameId);
    if (canvasCtx && waveformCanvas) {
      canvasCtx.clearRect(0, 0, waveformCanvas.width, waveformCanvas.height);
    }

    // Brief Formatting status before hiding HUD
    if (hudPill && hudStatus) {
      hudStatus.textContent = 'FORMATTING...';
      setTimeout(() => {
        hudPill.classList.remove('pill-visible');
        hudPill.classList.add('pill-hidden');
        hudPill.classList.remove('action-active');
      }, 300);
    }

    // Simulate final formatted text insertion directly into focused buffer
    simulateInsertionOutput();
  }

  function simulateInsertionOutput() {
    if (!typedTextEl) return;
    const targetData = PRESETS[currentPreset] || PRESETS.english;
    const textToType = targetData.formatted;
    typedTextEl.textContent = '';

    let charIdx = 0;
    typingTimer = setInterval(() => {
      if (charIdx < textToType.length) {
        typedTextEl.textContent += textToType.charAt(charIdx);
        charIdx++;
      } else {
        clearInterval(typingTimer);
        if (behaviorSub) {
          behaviorSub.textContent = `Typed into the active cursor: ${targetData.desc}`;
        }
      }
    }, 16); // High-speed typing matching realistic paste insertion
  }

  // Track mouse hover and focus on playground
  let isHoveringPlayground = false;
  if (playgroundCard) {
    playgroundCard.addEventListener('mouseenter', () => { isHoveringPlayground = true; });
    playgroundCard.addEventListener('mouseleave', () => { isHoveringPlayground = false; });
    playgroundCard.addEventListener('click', () => { playgroundCard.focus(); });
  }

  // Mouse & Touch on 3D Keycap
  if (keycapBtn) {
    const onPointerDown = (e) => {
      e.preventDefault();
      startRecording(isShiftActive || currentPreset === 'action');
    };

    const onPointerUp = (e) => {
      e.preventDefault();
      stopRecording();
    };

    keycapBtn.addEventListener('mousedown', onPointerDown);
    window.addEventListener('mouseup', onPointerUp);

    keycapBtn.addEventListener('touchstart', onPointerDown, { passive: false });
    window.addEventListener('touchend', onPointerUp, { passive: false });
  }

  // Keyboard Navigation: Space key triggers simulation without scrolling the page
  window.addEventListener('keydown', (e) => {
    // Detect Shift for Action Mode toggle
    if (e.key === 'Shift') {
      isShiftActive = true;
      if (isRecording) {
        if (keycapBtn) keycapBtn.classList.add('action-mode');
        if (hudPill) {
          hudPill.classList.add('action-active');
          if (hudBadge) hudBadge.innerHTML = `<span style="font-size: 11px; font-weight: 700;">A</span>`;
          if (hudStatus) hudStatus.textContent = 'ACTION MODE';
        }
      }
    }

    // Trigger push-to-talk simulation with Space
    if (e.code === 'Space' || e.key === ' ') {
      const targetTag = e.target ? e.target.tagName : '';
      const isInput = targetTag === 'INPUT' || targetTag === 'TEXTAREA' || (e.target && e.target.isContentEditable);
      if (isInput) return;

      const rect = playgroundCard ? playgroundCard.getBoundingClientRect() : null;
      // In view if the playground card is anywhere in the viewport
      const isPlaygroundInView = rect && (rect.top < window.innerHeight && rect.bottom > 0);
      const isFocused = document.activeElement === keycapBtn || 
                        (playgroundCard && (playgroundCard.contains(document.activeElement) || document.activeElement === playgroundCard));

      if (isHoveringPlayground || isFocused || isPlaygroundInView) {
        e.preventDefault(); // Prevents browser from scrolling down the page!
        if (!e.repeat && !isSpaceActive) {
          isSpaceActive = true;
          startRecording(isShiftActive || currentPreset === 'action');
        }
      }
    }
  });

  window.addEventListener('keyup', (e) => {
    if (e.key === 'Shift') {
      isShiftActive = false;
      if (isRecording && currentPreset !== 'action') {
        if (keycapBtn) keycapBtn.classList.remove('action-mode');
        if (hudPill) {
          hudPill.classList.remove('action-active');
          if (hudBadge) hudBadge.innerHTML = `<span class="dot-listening"></span>`;
          if (hudStatus) hudStatus.textContent = 'LISTENING...';
        }
      }
    }

    if (e.code === 'Space' || e.key === ' ') {
      if (isSpaceActive) {
        e.preventDefault();
        isSpaceActive = false;
        stopRecording();
      }
    }
  });

})();
