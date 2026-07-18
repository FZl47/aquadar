/**
 * Global Select2 init for all <select> fields + farm→plot helper.
 * Requires jQuery + Select2. RTL-aware (Persian UI).
 */
(function ($) {
    'use strict';

    var SELECT2_DEFAULTS = {
        dir: 'rtl',
        width: '100%',
        allowClear: true,
        placeholder: '—',
        language: {
            noResults: function () { return 'موردی یافت نشد'; },
            searching: function () { return 'در حال جستجو…'; },
            inputTooShort: function () { return 'بیشتر تایپ کنید'; }
        }
    };

    function initSelect2(context) {
        var $root = context ? $(context) : $(document);
        $root.find('select').each(function () {
            var $el = $(this);
            if ($el.hasClass('no-select2') || $el.data('select2')) {
                return;
            }
            // Skip empty / hidden selects that are not visible form fields
            if ($el.attr('type') === 'hidden') {
                return;
            }
            var opts = $.extend({}, SELECT2_DEFAULTS);
            // Don't allow clear on required selects without empty option
            if ($el.prop('required') && !$el.find('option[value=""]').length) {
                opts.allowClear = false;
            }
            // Dropdown parent for modals so list is not clipped
            var $modal = $el.closest('.modal');
            if ($modal.length) {
                opts.dropdownParent = $modal;
            }
            $el.select2(opts);
        });
    }

    function reinitSelect2($el) {
        if ($el.data('select2')) {
            $el.select2('destroy');
        }
        initSelect2($el.parent());
    }

    /**
     * Wire farm select → filter plot options.
     * plotsByFarm: { "1": [{id, label}, ...], ... }
     */
    function bindFarmPlotFilter(farmSelector, plotSelector, plotsByFarm) {
        var $farm = $(farmSelector);
        var $plot = $(plotSelector);
        if (!$farm.length || !$plot.length || !plotsByFarm) {
            return;
        }

        function rebuildPlots(farmId, keepValue) {
            var current = keepValue != null ? String(keepValue) : String($plot.val() || '');
            var options = farmId ? (plotsByFarm[String(farmId)] || []) : [];
            // If no farm chosen, flatten all plots
            if (!farmId) {
                options = [];
                Object.keys(plotsByFarm).forEach(function (k) {
                    options = options.concat(plotsByFarm[k]);
                });
            }
            var html = '<option value="">---------</option>';
            options.forEach(function (p) {
                var sel = String(p.id) === current ? ' selected' : '';
                html += '<option value="' + p.id + '"' + sel + '>' + $('<div>').text(p.label).html() + '</option>';
            });
            if ($plot.data('select2')) {
                $plot.select2('destroy');
            }
            $plot.html(html);
            initSelect2($plot.parent());
        }

        $farm.on('change', function () {
            rebuildPlots($(this).val(), null);
        });

        // Initial filter if farm already has a value
        if ($farm.val()) {
            rebuildPlots($farm.val(), $plot.val());
        }
    }

    // Expose helpers
    window.aqInitSelect2 = initSelect2;
    window.aqBindFarmPlotFilter = bindFarmPlotFilter;

    $(function () {
        initSelect2(document);

        // Re-init selects inside Bootstrap modals when opened
        $(document).on('shown.bs.modal', '.modal', function () {
            initSelect2(this);
        });
    });
})(jQuery);
