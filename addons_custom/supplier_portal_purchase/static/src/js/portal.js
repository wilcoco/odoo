/** 협력사 포탈 JavaScript */

document.addEventListener('DOMContentLoaded', function() {

    // 응답 유형 변경 시 폼 토글
    const responseTypeRadios = document.querySelectorAll('input[name="response_type"]');
    const lineInputs = document.getElementById('line_inputs');

    if (responseTypeRadios.length && lineInputs) {
        responseTypeRadios.forEach(function(radio) {
            radio.addEventListener('change', function() {
                if (this.value === 'partial_accept') {
                    lineInputs.style.display = 'block';
                } else {
                    lineInputs.style.display = 'none';
                }
            });
        });
    }

    // 알림 읽음 처리
    const notificationLinks = document.querySelectorAll('.notification-link');
    notificationLinks.forEach(function(link) {
        link.addEventListener('click', function() {
            const notificationId = this.dataset.notificationId;
            const token = this.dataset.token;

            if (notificationId && token) {
                fetch('/supplier/notification/read', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        method: 'call',
                        params: {
                            token: token,
                            notification_id: notificationId,
                        },
                    }),
                });
            }
        });
    });

    // 수량 입력 시 자동 계산
    const qtyInputs = document.querySelectorAll('input[name^="qty_"]');
    qtyInputs.forEach(function(input) {
        input.addEventListener('change', function() {
            // 음수 방지
            if (this.value < 0) {
                this.value = 0;
            }
            // 소수점 제거
            this.value = Math.floor(this.value);
        });
    });

    // 폼 제출 확인
    const responseForm = document.querySelector('form[action*="/respond"]');
    if (responseForm) {
        responseForm.addEventListener('submit', function(e) {
            const responseType = document.querySelector('input[name="response_type"]:checked');

            if (responseType && responseType.value === 'reject') {
                const note = document.querySelector('textarea[name="note"]');
                if (!note || !note.value.trim()) {
                    e.preventDefault();
                    alert('납품 불가 선택 시 사유를 입력해 주세요.');
                    note.focus();
                    return false;
                }
            }

            if (!confirm('응답을 제출하시겠습니까?')) {
                e.preventDefault();
                return false;
            }
        });
    }

});
