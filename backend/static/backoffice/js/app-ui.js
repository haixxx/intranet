/* Z115 Backoffice UI helper layer. Requires Tabler 1.4.0, which bundles Bootstrap 5.3.x. */
(function () {
  function initTooltips(root) {
    if (!window.bootstrap || !window.bootstrap.Tooltip) return;
    root.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
      if (!window.bootstrap.Tooltip.getInstance(el)) {
        new window.bootstrap.Tooltip(el);
      }
    });
  }

  function initPopovers(root) {
    if (!window.bootstrap || !window.bootstrap.Popover) return;
    root.querySelectorAll('[data-bs-toggle="popover"]').forEach(function (el) {
      if (!window.bootstrap.Popover.getInstance(el)) {
        new window.bootstrap.Popover(el);
      }
    });
  }

  function initHelpToggles(root) {
    root.querySelectorAll('.js-help-toggle[data-help-target]').forEach(function (btn) {
      if (btn.dataset.boHelpBound === '1') return;
      btn.dataset.boHelpBound = '1';
      btn.addEventListener('click', function () {
        var targetId = btn.getAttribute('data-help-target');
        var target = document.getElementById(targetId);
        if (!target) return;
        var isShown = target.classList.toggle('show');
        btn.setAttribute('aria-expanded', isShown ? 'true' : 'false');
      });
    });
  }

  function normalizeDjangoFormControls(root) {
    root.querySelectorAll('.bo-form-card input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]):not([type="file"])').forEach(function (el) {
      if (!el.classList.contains('form-control')) {
        el.classList.add('form-control');
      }
      if (!el.classList.contains('form-control-sm')) {
        el.classList.add('form-control-sm');
      }
    });

    root.querySelectorAll('.bo-form-card input[type="file"]').forEach(function (el) {
      if (!el.classList.contains('form-control')) {
        el.classList.add('form-control');
      }
    });

    root.querySelectorAll('.bo-form-card select').forEach(function (el) {
      if (!el.classList.contains('form-select')) {
        el.classList.add('form-select');
      }
      if (!el.multiple && !el.classList.contains('form-select-sm')) {
        el.classList.add('form-select-sm');
      }
    });

    root.querySelectorAll('.bo-form-card textarea').forEach(function (el) {
      if (!el.classList.contains('form-control')) {
        el.classList.add('form-control');
      }
      if (!el.classList.contains('form-control-sm')) {
        el.classList.add('form-control-sm');
      }
    });

    root.querySelectorAll('.bo-form-card input[type="checkbox"], .bo-form-card input[type="radio"]').forEach(function (el) {
      if (!el.classList.contains('form-check-input')) {
        el.classList.add('form-check-input');
      }
    });
  }


  function initMobileSidebar(root) {
    var sidebar = document.getElementById('bo-mobile-sidebar');
    if (!sidebar || !window.bootstrap || !window.bootstrap.Offcanvas) return;

    sidebar.querySelectorAll('a.bo-nav-item').forEach(function (link) {
      if (link.dataset.boSidebarCloseBound === '1') return;
      link.dataset.boSidebarCloseBound = '1';
      link.addEventListener('click', function () {
        var offcanvas = window.bootstrap.Offcanvas.getOrCreateInstance(sidebar);
        if (offcanvas) offcanvas.hide();
      });
    });
  }


  function setNavTitles(root) {
    root.querySelectorAll('a.bo-nav-item').forEach(function (link) {
      if (!link.getAttribute('title')) {
        var label = (link.textContent || '').replace(/\s+/g, ' ').trim();
        if (label) link.setAttribute('title', label);
      }
    });
  }

  function initSidebarCollapse(root) {
    var body = document.body;
    var buttons = root.querySelectorAll('[data-bo-sidebar-toggle]');
    if (!buttons.length || !body) return;

    var storageKey = 'z115.backoffice.sidebarCollapsed';

    function readStoredState() {
      try {
        return window.localStorage && window.localStorage.getItem(storageKey) === '1';
      } catch (err) {
        return false;
      }
    }

    function writeStoredState(collapsed) {
      try {
        if (window.localStorage) {
          window.localStorage.setItem(storageKey, collapsed ? '1' : '0');
        }
      } catch (err) {
        // localStorage may be disabled; the visual toggle still works for this page load.
      }
    }

    function applyState(collapsed) {
      body.classList.toggle('bo-sidebar-collapsed', collapsed);
      buttons.forEach(function (btn) {
        btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        btn.setAttribute('aria-label', collapsed ? 'Mở rộng menu' : 'Thu gọn menu');
        btn.setAttribute('title', collapsed ? 'Mở rộng menu' : 'Thu gọn menu');
      });
    }

    applyState(readStoredState());

    buttons.forEach(function (btn) {
      if (btn.dataset.boSidebarToggleBound === '1') return;
      btn.dataset.boSidebarToggleBound = '1';
      btn.addEventListener('click', function () {
        var collapsed = !body.classList.contains('bo-sidebar-collapsed');
        applyState(collapsed);
        writeStoredState(collapsed);
      });
    });
  }

  function initBackofficeUI(root) {
    root = root || document;
    normalizeDjangoFormControls(root);
    initTooltips(root);
    initPopovers(root);
    initHelpToggles(root);
    setNavTitles(root);
    initSidebarCollapse(root);
    initMobileSidebar(root);
  }

  document.addEventListener('DOMContentLoaded', function () {
    initBackofficeUI(document);
  });

  window.BackofficeUI = {
    init: initBackofficeUI
  };
})();
