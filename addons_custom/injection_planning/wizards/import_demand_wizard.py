import base64
import csv
import io
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ImportDemandWizard(models.TransientModel):
    _name = "injection.import.demand.wizard"
    _description = "수요 데이터 파일 업로드"

    planning_run_id = fields.Many2one(
        "injection.planning.run", string="계획 실행", required=True,
    )
    file_data = fields.Binary(string="CSV 파일", required=True)
    file_name = fields.Char(string="파일명")
    replace_oracle = fields.Boolean(
        string="기존 Oracle 수요 교체",
        default=True,
        help="체크하면 기존 Oracle 소스 수요를 삭제 후 교체합니다.",
    )

    def action_import(self):
        """CSV 파일에서 수요 데이터 임포트"""
        self.ensure_one()
        if not self.file_data:
            raise UserError("파일을 선택해주세요.")

        # CSV 파일 파싱
        try:
            raw = base64.b64decode(self.file_data)
            # BOM(utf-8-sig) 처리
            if raw[:3] == b'\xef\xbb\xbf':
                raw = raw[3:]
            content = raw.decode("utf-8")
        except Exception as e:
            raise UserError(f"파일 읽기 실패: {e}")

        reader = csv.DictReader(io.StringIO(content))

        # 필수 컬럼 확인
        required = {"demand_date", "product_code", "quantity", "demand_type"}
        if not required.issubset(set(reader.fieldnames or [])):
            missing = required - set(reader.fieldnames or [])
            raise UserError(
                f"필수 컬럼이 없습니다: {', '.join(missing)}\n"
                f"필수: demand_date, product_code, quantity, demand_type"
            )

        # 기존 Oracle 수요 삭제
        if self.replace_oracle:
            self.planning_run_id.demand_ids.filtered(
                lambda d: d.source == "oracle"
            ).unlink()

        # CSV 행 파싱
        rows = []
        errors = []
        product_cache = {}  # code → product record
        for i, row in enumerate(reader, start=2):
            product_code = (row.get("product_code") or "").strip()
            if not product_code:
                continue

            # 제품 조회 (캐시)
            if product_code not in product_cache:
                product = self.env["product.product"].search(
                    ["|", ("default_code", "=", product_code),
                          ("barcode", "=", product_code)],
                    limit=1,
                )
                product_cache[product_code] = product

            product = product_cache[product_code]
            if not product:
                errors.append(f"행 {i}: 제품 코드 '{product_code}' 없음")
                continue

            try:
                qty = float(row.get("quantity", 0))
            except (ValueError, TypeError):
                errors.append(f"행 {i}: 수량 '{row.get('quantity')}' 변환 실패")
                continue

            if qty <= 0:
                continue

            demand_type = row.get("demand_type", "daily").strip()
            hour_val = row.get("hour", "")
            hour = int(hour_val) if hour_val and str(hour_val).strip() else 0

            rows.append({
                "demand_date": row["demand_date"].strip(),
                "product_id": product.id,
                "quantity": qty,
                "demand_type": demand_type,
                "hour": hour,
                "source": "oracle",  # 파일이지만 Oracle 원천 데이터
                "planning_run_id": self.planning_run_id.id,
            })

        if not rows and errors:
            raise UserError(
                "임포트할 데이터가 없습니다.\n\n" + "\n".join(errors[:20])
            )

        # 수요 레코드 생성
        if rows:
            self.env["injection.production.demand"].create(rows)

        # 결과 메시지
        msg = f"파일 임포트 완료: {len(rows)}건 수요 생성"
        if errors:
            msg += f"\n\n⚠ {len(errors)}건 오류:\n" + "\n".join(errors[:20])
            if len(errors) > 20:
                msg += f"\n... 외 {len(errors) - 20}건"

        self.planning_run_id.message_post(body=msg)

        return {"type": "ir.actions.act_window_close"}
