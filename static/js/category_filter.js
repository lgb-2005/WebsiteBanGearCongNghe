document.addEventListener('DOMContentLoaded', function () {

    /*
    =========================
    CENTRALIZED FILTER STATE
    =========================
    */
    const filterState = {
        attributes: {},
        brand: [],
        q: '',
        sort: 'featured',
        price_min: null,
        price_max: null,
    };

    /*
    =========================
    OPEN/CLOSE POPUP
    =========================
    */
    document.getElementById('openFilterPopup')?.addEventListener('click', function () {
        document.getElementById('categoryFilterPopup').style.display = 'flex';
    });

    document.getElementById('closeFilterPopup')?.addEventListener('click', function () {
        document.getElementById('categoryFilterPopup').style.display = 'none';
    });

    /*
    =========================
    POPUP FILTER BUTTONS
    =========================
    */
    document.querySelectorAll('.filter-popup-value-btn')
    .forEach(button => {

        button.addEventListener('click', function () {

            const group = this.dataset.group;
            const value = this.dataset.value;

            if (!filterState.attributes[group]) {
                filterState.attributes[group] = [];
            }

            const values =
                filterState.attributes[group];

            const exists =
                values.includes(value);

            if (exists) {

                filterState.attributes[group] =
                    values.filter(v => v !== value);

            } else {

                filterState.attributes[group].push(value);
            }

            syncPopupUi();
        });
    });

    /*
    =========================
    PRICE DOM
    =========================
    */
    const priceMinSlider =
    document.getElementById('priceMinSlider');

    const priceMaxSlider =
        document.getElementById('priceMaxSlider');

    const priceMinInput =
        document.getElementById('priceMinInput');

    const priceMaxInput =
        document.getElementById('priceMaxInput');

    const priceMinDisplay =
        document.getElementById('priceMinDisplay');

    const priceMaxDisplay =
        document.getElementById('priceMaxDisplay');
    
        const popupPriceMinSlider =
    document.getElementById('popupPriceMinSlider');
    
    const popupPriceMaxSlider =
        document.getElementById('popupPriceMaxSlider');
    
    const popupPriceMinDisplay =
        document.getElementById('popupPriceMinDisplay');
    
    const popupPriceMaxDisplay =
        document.getElementById('popupPriceMaxDisplay');

    /*
    =========================
    URL -> STATE
    =========================
    */
    function hydrateStateFromUrl() {

        const params = new URLSearchParams(window.location.search);
    
        filterState.attributes = {};
        filterState.q = (params.get('q') || '').trim();
    
        filterState.sort =
            params.get('sort') || 'featured';
    
        filterState.price_min =
            params.get('price_min');
    
        filterState.price_max =
            params.get('price_max');

        filterState.brand = (params.get('brand') || '')
            .split(',')
            .map(v => v.trim())
            .filter(Boolean);
    
        params.forEach((value, key) => {
    
            if (
                key === 'q' ||
                key === 'sort' ||
                key === 'price_min' ||
                key === 'price_max' ||
                key === 'brand'
            ) {
                return;
            }
    
            filterState.attributes[key] = value
                .split(',')
                .map(v => v.trim())
                .filter(Boolean);
        });
    }

    function updateFilterToggleState() {

        document.querySelectorAll('.filterbar-dropdown')
        .forEach(dropdown => {
    
            const toggle =
                dropdown.querySelector('.filterbar-dropdown-toggle');
    
            if (!toggle) return;
    
            let isActive = false;
    
            const selectedItems =
                dropdown.querySelectorAll(
                    '.filterbar-dropdown-item.selected'
                );
    
            if (selectedItems.length > 0) {
                isActive = true;
            }
    
            // Dropdown giá
            if (
                dropdown.querySelector('#priceMinSlider')
            ) {
    
                const min =
                    Number(filterState.price_min);
    
                const max =
                    Number(filterState.price_max);
    
                if (
                    min > 0 ||
                    max < 10000000
                ) {
                    isActive = true;
                }
            }

            // Dropdown thương hiệu
            if (dropdown.querySelector('[data-brand]')) {
                const selectedBrandItems =
                    dropdown.querySelectorAll('.filterbar-dropdown-item[data-brand].selected');
    
                if (selectedBrandItems.length > 0) {
                    isActive = true;
                }
            }
    
            toggle.classList.toggle(
                'filter-active',
                isActive
            );
        });
    }

    function syncPopupUi() {

        document
        .querySelectorAll('.filter-popup-value-btn')
        .forEach(item => {
    
            const group = item.dataset.group;
            const value = item.dataset.value;
    
            const selectedValues =
                filterState.attributes[group] || [];
    
            item.classList.toggle(
                'active',
                selectedValues.includes(value)
            );
        });
    }

    function syncFilterBarUi() {

        document
        .querySelectorAll(
            '.filterbar-dropdown-item[data-group]'
        )
        .forEach(item => {
    
            const group = item.dataset.group;
            const value = item.dataset.value;
    
            const selectedValues =
                appliedFilterState.attributes[group] || [];
    
            item.classList.toggle(
                'selected',
                selectedValues.includes(value)
            );
        });

        document
        .querySelectorAll('.filterbar-dropdown-item[data-brand]')
        .forEach(item => {
            const value = item.dataset.value;
            const selectedValues = appliedFilterState.brand || [];
            item.classList.toggle('selected', selectedValues.includes(value));
        });
    
        updateFilterToggleState();
    }

    /*
    =========================
    STATE -> UI
    =========================
    */
    function syncUiFromState() {

        document.querySelectorAll('.filter-popup-value-btn')
        .forEach(item => {

            const group = item.dataset.group;
            const value = item.dataset.value;

            const selectedValues =
                filterState.attributes[group] || [];

            item.classList.toggle(
                'active',
                selectedValues.includes(value)
            );
        });

        document.querySelectorAll('.filterbar-dropdown-item[data-group]').forEach(item => {
            const group = item.dataset.group;
            const value = item.dataset.value;

            const selectedValues = filterState.attributes[group] || [];

            item.classList.toggle(
                'selected',
                selectedValues.includes(value)
            );
        });

        document.querySelectorAll('.filterbar-dropdown-item[data-brand]').forEach(item => {
            const value = item.dataset.value;
            item.classList.toggle('selected', filterState.brand.includes(value));
        });

        updateFilterToggleState();

        if (priceMinInput && filterState.price_min) {
            priceMinInput.value = filterState.price_min;
            priceMinSlider.value = filterState.price_min;
            if (priceMinDisplay) {
                priceMinDisplay.textContent =
                    `${parseInt(filterState.price_min).toLocaleString('vi-VN')}đ`;
            }
        }

        if (priceMaxInput && filterState.price_max) {
            priceMaxInput.value = filterState.price_max;
            priceMaxSlider.value = filterState.price_max;
            if (priceMaxDisplay) {
                priceMaxDisplay.textContent =
                    `${parseInt(filterState.price_max).toLocaleString('vi-VN')}đ`;
            }
        }
    }

    /*
    =========================
    STATE -> URL
    =========================
    */
    function buildUrlFromState() {

        const url = new URL(window.location.href);

        url.search = '';

        Object.entries(filterState.attributes).forEach(([group, values]) => {
            if (!Array.isArray(values) || !values.length) {
                return;
            }

            url.searchParams.set(group, values.join(','));
        });

        if (filterState.q) {
            url.searchParams.set('q', filterState.q);
        }

        if (filterState.sort) {
            url.searchParams.set('sort', filterState.sort);
        }

        if (filterState.price_min) {
            url.searchParams.set('price_min', filterState.price_min);
        }

        if (filterState.price_max) {
            url.searchParams.set('price_max', filterState.price_max);
        }

        if (filterState.brand.length) {
            url.searchParams.set('brand', filterState.brand.join(','));
        }

        return url.toString();
    }

    /*
    =========================
    SORT
    =========================
    */
    document.querySelectorAll('.filterbar-sort-menu .filterbar-dropdown-item')
        .forEach(item => {
            item.addEventListener('click', function () {
                filterState.sort = this.dataset.sort;
                window.location.href = buildUrlFromState();
            });
        });

    /*
    =========================
    ATTRIBUTE CLICK
    =========================
    */
    document.querySelectorAll('.filterbar-dropdown-item[data-group]')
        .forEach(item => {

            item.addEventListener('click', function (e) {

                e.preventDefault();
                e.stopPropagation();

                const group = this.dataset.group;
                if (!group) return;
                const value = this.dataset.value;

                if (!filterState.attributes[group]) {
                    filterState.attributes[group] = [];
                }

                const values = filterState.attributes[group];
                const exists = values.includes(value);

                if (exists) {
                    filterState.attributes[group] =
                        values.filter(v => v !== value);
                } else {
                    filterState.attributes[group].push(value);
                }

                syncUiFromState();
            });
        });

    document.querySelectorAll('.filterbar-dropdown-item[data-brand]')
        .forEach(item => {
            item.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();

                const value = this.dataset.value;
                const exists = filterState.brand.includes(value);

                if (exists) {
                    filterState.brand = filterState.brand.filter(v => v !== value);
                } else {
                    filterState.brand.push(value);
                }

                syncUiFromState();
            });
        });

    /*
    =========================
    PREVENT CLOSE DROPDOWN
    =========================
    */
    document.querySelectorAll('.filterbar-dropdown-menu').forEach(menu => {
        menu.addEventListener('click', function (e) {
            e.stopPropagation();
        });
    });

    /*
    =========================
    PRICE LOGIC
    =========================
    */
   
    function formatPrice(value) {
        return Number(value).toLocaleString('vi-VN');
    }
    
    function updatePriceUI() {
    
        let min = parseInt(priceMinSlider.value);
        let max = parseInt(priceMaxSlider.value);
    
        if (min > max) {
            [min, max] = [max, min];
        }
    
        priceMinSlider.value = min;
        priceMaxSlider.value = max;

        const track = document.querySelector('.slider-track');

        const minPercent =
            (min / parseInt(priceMinSlider.max)) * 100;

        const maxPercent =
            (max / parseInt(priceMaxSlider.max)) * 100;

        track.style.background = `
            linear-gradient(
                to right,
                #e5e7eb ${minPercent}%,
                #2563eb ${minPercent}%,
                #2563eb ${maxPercent}%,
                #e5e7eb ${maxPercent}%
            )
        `;
    
        filterState.price_min = min;
        filterState.price_max = max;
    
        priceMinInput.value = formatPrice(min);
        priceMaxInput.value = formatPrice(max);
    
        priceMinDisplay.textContent =
            `${formatPrice(min)}đ`;
    
        priceMaxDisplay.textContent =
            `${formatPrice(max)}đ`;
    }

    function updatePopupPriceUI() {

        if (!popupPriceMinSlider || !popupPriceMaxSlider) {
            return;
        }
    
        let min = parseInt(popupPriceMinSlider.value);
        let max = parseInt(popupPriceMaxSlider.value);
    
        if (min > max) {
            [min, max] = [max, min];
        }
    
        popupPriceMinSlider.value = min;
        popupPriceMaxSlider.value = max;
    
        const track =
            document.querySelector('.popup-slider-track');
    
        const minPercent =
            (min / parseInt(popupPriceMinSlider.max)) * 100;
    
        const maxPercent =
            (max / parseInt(popupPriceMaxSlider.max)) * 100;
    
        track.style.background = `
            linear-gradient(
                to right,
                #e5e7eb 0%,
                #e5e7eb ${minPercent}%,
                #2563eb ${minPercent}%,
                #2563eb ${maxPercent}%,
                #e5e7eb ${maxPercent}%,
                #e5e7eb 100%
            )
        `;
    
        filterState.price_min = min;
        filterState.price_max = max;
    
        popupPriceMinDisplay.textContent =
            `${formatPrice(min)}đ`;
    
        popupPriceMaxDisplay.textContent =
            `${formatPrice(max)}đ`;
    }
    
    if (priceMinSlider && priceMaxSlider) {
    
        if (popupPriceMinSlider && popupPriceMaxSlider) {

            popupPriceMinSlider.addEventListener(
                'input',
                updatePopupPriceUI
            );
        
            popupPriceMaxSlider.addEventListener(
                'input',
                updatePopupPriceUI
            );
        
            updatePopupPriceUI();
        }
        priceMinSlider.addEventListener(
            'input',
            updatePriceUI
        );
    
        priceMaxSlider.addEventListener(
            'input',
            updatePriceUI
        );
    
        updatePriceUI();
    }

    /*
    =========================
    APPLY
    =========================
    */
    document.querySelectorAll('.filterbar-action-apply[data-group]')
        .forEach(btn => {

            btn.addEventListener('click', function () {

                const group = this.dataset.group;
                if (!group) return;
                if (group === 'price') {
                    filterState.price_min =
                    parseInt(
                        priceMinInput.value.replace(/\./g, '')
                    ) || null;

                filterState.price_max =
                    parseInt(
                        priceMaxInput.value.replace(/\./g, '')
                    ) || null;
                }

                window.location.href = buildUrlFromState();
            });
        });

    /*
    =========================
    RESET
    =========================
    */
    document.querySelectorAll('.filterbar-action-reset')
        .forEach(btn => {

            btn.addEventListener('click', function () {

                const group = this.dataset.group;
                if (!group) return;
                if (group === 'price') {

                    filterState.price_min = null;
                    filterState.price_max = null;

                    if (priceMinInput) {
                        priceMinInput.value = formatPrice(0);
                    }
                    
                    if (priceMaxInput) {
                        priceMaxInput.value =
                            formatPrice(10000000);
                    }

                    if (priceMinSlider) priceMinSlider.value = 0;
                    if (priceMaxSlider) priceMaxSlider.value = 10000000;

                    if (priceMinDisplay) priceMinDisplay.textContent = '0đ';
                    if (priceMaxDisplay) priceMaxDisplay.textContent = '10,000,000đ';

                } else if (group === 'brand') {
                    filterState.brand = [];
                } else {
                    delete filterState.attributes[group];
                }

                syncUiFromState();
            });
        });

    /*
    =========================
    POPUP APPLY
    =========================
    */
    document
    .getElementById('applyFilters')
    .addEventListener('click', function () {

        appliedFilterState =
            structuredClone(filterState);

        syncFilterBarUi();

        window.location.href =
            buildUrlFromState();
    });

    /*
    =========================
    POPUP RESET
    =========================
    */
    document.getElementById('resetFilters')
    ?.addEventListener('click', function () {

        filterState.attributes = {};

        filterState.price_min = 0;
        filterState.price_max = 10000000;

        if (popupPriceMinSlider) {
            popupPriceMinSlider.value = 0;
        }

        if (popupPriceMaxSlider) {
            popupPriceMaxSlider.value = 10000000;
        }

        syncUiFromState();

        updatePopupPriceUI();
    });

    /*
    =========================
    INIT
    =========================
    */
    hydrateStateFromUrl();
    syncUiFromState();
});