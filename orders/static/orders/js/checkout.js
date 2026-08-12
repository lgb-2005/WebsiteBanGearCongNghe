function getCookie(name) {

    let cookieValue = null;

    if (document.cookie && document.cookie !== '') {

        const cookies =
            document.cookie.split(';');

        for (let i = 0; i < cookies.length; i++) {

            const cookie =
                cookies[i].trim();

            if (
                cookie.substring(
                    0,
                    name.length + 1
                ) === (name + '=')
            ) {

                cookieValue =
                    decodeURIComponent(
                        cookie.substring(
                            name.length + 1
                        )
                    );

                break;
            }
        }
    }

    return cookieValue;
}

let provinces = [];

const provinceCode =
    document.getElementById(
        "provinceCode"
    );

const provinceName =
    document.getElementById(
        "provinceName"
    );

const wardCode =
    document.getElementById(
        "wardCode"
    );

const wardName =
    document.getElementById(
        "wardName"
    );

    fetch(
        '/static/orders/data/vietnam_administrative.json'
    )
    .then(response => response.json())
    .then(data => {
    
        provinces = data;
    
        loadProvinces();
    
        restoreSelectedAddress();
    });

function restoreSelectedAddress() {

    const provinceSelect =
        document.getElementById(
            "provinceSelect"
        );

    const wardSelect =
        document.getElementById(
            "wardSelect"
        );

    const selectedProvince =
        provinceSelect.dataset.selected;

    const selectedWard =
        wardSelect.dataset.selected;

    if (!selectedProvince) {
        return;
    }

    provinceSelect.value =
        selectedProvince;

    const province =
        provinces.find(
            p =>
                String(
                    p.province_code
                ) === String(
                    selectedProvince
                )
        );

    loadWards(province);

    if (selectedWard) {

        wardSelect.value =
            selectedWard;
    }

    updateHiddenFields();
}

function loadProvinces() {

    const provinceSelect =
        document.getElementById('provinceSelect');

    const sortedProvinces =
        [...provinces].sort((a, b) =>
            a.name.localeCompare(
                b.name,
                'vi'
            )
        );

    sortedProvinces.forEach(province => {

        const option =
            document.createElement('option');

        option.value =
            province.province_code;

        option.textContent =
            province.name;

        provinceSelect.appendChild(option);
    });
}

document
.getElementById('provinceSelect')
.addEventListener(
    'change',
    function () {

        const province =
            provinces.find(
                p =>
                    String(
                        p.province_code
                    ) === String(
                        this.value
                    )
            );

        loadWards(province);

        document.getElementById(
            "wardSelect"
        ).value = "";

        updateHiddenFields();
    }
);

document
.getElementById('wardSelect')
.addEventListener(
    'change',
    function () {

        updateHiddenFields();
    }
);

function loadWards(province){

    const wardSelect =
        document.getElementById('wardSelect');

    wardSelect.innerHTML =
        '<option value="">Chọn phường/xã</option>';

    if(!province){
        return;
    }

    const sortedWards =
        [...province.wards].sort((a, b) =>
            a.name.localeCompare(
                b.name,
                'vi'
            )
        );

    sortedWards.forEach(ward => {

        const option =
            document.createElement('option');

        option.value =
            ward.ward_code;

        option.textContent =
            ward.name;

        wardSelect.appendChild(option);
    });
}


function updateHiddenFields() {

    const provinceSelect =
        document.getElementById(
            "provinceSelect"
        );

    const wardSelect =
        document.getElementById(
            "wardSelect"
        );

    provinceCode.value =
        provinceSelect.value;

    provinceName.value =
        provinceSelect.selectedIndex > 0
            ? provinceSelect.options[
                provinceSelect.selectedIndex
              ].text
            : "";

    wardCode.value =
        wardSelect.value;

    wardName.value =
        wardSelect.selectedIndex > 0
            ? wardSelect.options[
                wardSelect.selectedIndex
              ].text
            : "";
}

function buildShippingAddress() {

    const provinceSelect =
        document.getElementById('provinceSelect');

    const wardSelect =
        document.getElementById('wardSelect');

    const streetInput =
        document.getElementById('streetAddress');

    if (!provinceSelect.value) {
        alert('Vui lòng chọn tỉnh/thành');
        return null;
    }

    if (!wardSelect.value) {
        alert('Vui lòng chọn phường/xã');
        return null;
    }

    if (!streetInput.value.trim()) {
        alert('Vui lòng nhập địa chỉ chi tiết');
        return null;
    }

    const provinceName =
        provinceSelect.options[
            provinceSelect.selectedIndex
        ].text;

    const wardName =
        wardSelect.options[
            wardSelect.selectedIndex
        ].text;

    return `${streetInput.value.trim()}, ${wardName}, ${provinceName}`;
}

const placeOrderBtn =
document.getElementById(
    "placeOrderBtn"
);

placeOrderBtn.addEventListener(
    "click",
    async function () {

        const formData =
            new FormData();

        formData.append(
            "full_name",
            document.getElementById(
                "fullName"
            ).value
        );

        formData.append(
            "phone",
            document.getElementById(
                "phone"
            ).value
        );

        formData.append(
            "email",
            document.getElementById(
                "email"
            ).value
        );

        formData.append(
            "province_code",
            provinceCode.value
        );

        formData.append(
            "province_name",
            provinceName.value
        );

        formData.append(
            "ward_code",
            wardCode.value
        );

        formData.append(
            "ward_name",
            wardName.value
        );

        formData.append(
            "street_address",
            document.getElementById(
                "streetAddress"
            ).value
        );

        const selectedPayment =
            document.querySelector(
                'input[name="payment_method"]:checked'
            );

        const paymentMethodValue = selectedPayment ? selectedPayment.value : "cod";

        formData.append(
            "payment_method",
            paymentMethodValue
        );

        console.log('[checkout] payment_method selected:', paymentMethodValue);

        const response =
            await fetch(
                "/orders/place-order/",
                {
                    method: "POST",

                    headers: {
                        "X-CSRFToken":
                            getCookie(
                                "csrftoken"
                            )
                    },

                    body: formData
                }
            );

        const data =
            await response.json();

        console.log('[checkout] server response:', data);

        if (data.success) {

            if (data.redirect_url) {
                window.location.href = data.redirect_url;
            } else {
                alert("Đặt hàng thành công!");
                window.location.href = "/";
            }
        }
        else {

            alert(
                data.message
            );
        }
    }
);